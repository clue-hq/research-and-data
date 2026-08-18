// W4.8a: MIRROR of the design subsystem's in-iframe rich-text runtime,
// `subsystems/clue-design/apps/editor/src/iframe/webRichTextRuntime.ts` —
// copied VERBATIM (this header is the only edit; the `../engine/*` imports
// already resolve here, since the engine modules are byte-identical copies).
// Keep it a mirror: fix bugs upstream and re-copy, never diverge in place.
//
// Why this app hosts it: the design API injects only a lazy LOADER into the
// rendered srcdoc — `lumen_api/web_bridge.py:424-444` appends
// `<script src="/vendor/web-rich-text-runtime.js?v=structured-blocks-v2">` and
// then reads `window.LumenRichTextRuntime`. The sandboxed srcdoc has no
// same-origin, so that root-relative URL resolves against the PARENT origin:
// the API never serves the bundle, the host app does. `scripts/copy-design-
// vendor.mjs` bundles THIS file (esbuild, iife, minified) to
// `public/vendor/web-rich-text-runtime.js` at `predev`/`prebuild`, beside the
// W1.4 Tailwind copy. The `?v=` query is a cache-buster static serving
// ignores. The global is assigned by this file itself (bottom of the file), so
// no bundler-level global name matters.
//
// Nothing in the Next client bundle imports this module or Lexical: the parent
// app only exchanges postMessages with the frame.

import {
  $createLineBreakNode,
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  $getSelection,
  $getState,
  $isElementNode,
  $isLineBreakNode,
  $isParagraphNode,
  $isRangeSelection,
  $isTextNode,
  $setSelection,
  $setState,
  createEditor,
  createState,
  INDENT_CONTENT_COMMAND,
  INSERT_LINE_BREAK_COMMAND,
  INSERT_PARAGRAPH_COMMAND,
  OUTDENT_CONTENT_COMMAND,
  type ElementNode,
  type LexicalEditor,
  type LexicalNode,
  type RangeSelection,
  type TextFormatType
} from "lexical";
import { createEmptyHistoryState, registerHistory } from "@lexical/history";
import {
  $createLinkNode,
  $isLinkNode,
  $toggleLink,
  LinkNode
} from "@lexical/link";
import {
  $createListItemNode,
  $createListNode,
  $isListItemNode,
  $isListNode,
  INSERT_ORDERED_LIST_COMMAND,
  INSERT_UNORDERED_LIST_COMMAND,
  ListItemNode,
  ListNode,
  REMOVE_LIST_COMMAND,
  registerList,
  registerListStrictIndentTransform
} from "@lexical/list";
import { registerRichText } from "@lexical/rich-text";

import type {
  RichTextBlock,
  RichTextDocument,
  RichTextInline,
  RichTextLink,
  RichTextMarks
} from "../engine/webDocuments";
import {
  richTextHrefIsAllowed,
  webBindingKeyIsAllowed
} from "../engine/webRichText";
import type {
  RichTextCommand,
  RichTextFormat,
  RichTextFormatState,
  RichTextFormatValue,
  RichTextSelectionState,
  WebNodeRect
} from "../engine/webBridge";

interface InlineMetadata {
  classes: string | null;
  variableKey: string | null;
}

const EMPTY_METADATA: InlineMetadata = { classes: null, variableKey: null };
const inlineMetadataState = createState("lumenRichInline", {
  parse(value): InlineMetadata {
    if (!value || typeof value !== "object") {
      return EMPTY_METADATA;
    }
    const record = value as Record<string, unknown>;
    return {
      classes: typeof record.classes === "string" && record.classes ? record.classes : null,
      variableKey:
        typeof record.variableKey === "string" && record.variableKey
          ? record.variableKey
          : null
    };
  }
});

interface ImportContext {
  marks: RichTextMarks;
  classes: string[];
  variableKey: string | null;
}

export interface RichTextSession {
  format: (format: RichTextFormat) => void;
  command: (command: RichTextCommand) => void;
  setInteractionActive: (active: boolean) => void;
  getDocument: () => RichTextDocument;
  getHtml: () => string;
  getFormatState: () => RichTextFormatState;
  getSelectionState: () => RichTextSelectionState;
  refreshSelection: () => void;
  focus: () => void;
  destroy: () => void;
}

export interface RichTextMountOptions {
  initialHtml: string;
  textVariant: string;
  onFormatStateChange?: (state: RichTextFormatState) => void;
  onSelectionStateChange?: (state: RichTextSelectionState) => void;
  onCommitRequest?: () => void;
  onCancelRequest?: () => void;
}

const FORMATS: RichTextFormat[] = ["bold", "italic", "underline", "strikethrough"];
const MAX_LIST_DEPTH = 6;

function variantAllowsStructure(variant: string): boolean {
  return variant === "body" || variant === "small";
}

function applyMarks(node: ReturnType<typeof $createTextNode>, marks: RichTextMarks): void {
  for (const format of FORMATS) {
    if (marks[format]) {
      node.toggleFormat(format);
    }
  }
}

const DROPPED_RICH_TEXT_TAGS = new Set([
  "script",
  "style",
  "iframe",
  "object",
  "embed"
]);

function appendDomChildren(
  lexicalParent: ElementNode,
  domParent: Node,
  context: ImportContext,
  preserveMetadata: boolean
): void {
  for (const child of Array.from(domParent.childNodes)) {
    if (child.nodeType === Node.TEXT_NODE) {
      const text = child.textContent ?? "";
      if (!text) {
        continue;
      }
      const node = $createTextNode(text);
      applyMarks(node, context.marks);
      const classes = context.classes
        .flatMap((value) => value.split(/\s+/))
        .filter(Boolean)
        .join(" ");
      if (classes || context.variableKey) {
        $setState(node, inlineMetadataState, {
          classes: classes || null,
          variableKey: context.variableKey
        });
      }
      lexicalParent.append(node);
      continue;
    }
    if (!(child instanceof HTMLElement)) {
      continue;
    }
    const tag = child.tagName.toLowerCase();
    if (DROPPED_RICH_TEXT_TAGS.has(tag)) {
      continue;
    }
    if (tag === "br") {
      lexicalParent.append($createLineBreakNode());
      continue;
    }
    if (tag === "ul" || tag === "ol") {
      continue;
    }

    const next: ImportContext = {
      marks: { ...context.marks },
      classes: [...context.classes],
      variableKey: context.variableKey
    };
    if (tag === "strong" || tag === "b") next.marks.bold = true;
    if (tag === "em" || tag === "i") next.marks.italic = true;
    if (tag === "u") next.marks.underline = true;
    if (tag === "s" || tag === "strike") next.marks.strikethrough = true;
    if (tag === "span" && preserveMetadata) {
      const classes = child.getAttribute("class");
      if (classes) next.classes.push(classes);
      const variableKey = child.getAttribute("data-var");
      next.variableKey =
        variableKey && webBindingKeyIsAllowed(variableKey)
          ? variableKey
          : next.variableKey;
    }

    if (tag === "a") {
      const href = child.getAttribute("href") ?? "";
      if (!richTextHrefIsAllowed(href)) {
        appendDomChildren(lexicalParent, child, next, preserveMetadata);
        continue;
      }
      const link = $createLinkNode(href, {
        target: child.getAttribute("target") === "_blank" ? "_blank" : null,
        rel:
          child.getAttribute("target") === "_blank"
            ? "noopener noreferrer"
            : null
      });
      lexicalParent.append(link);
      appendDomChildren(link, child, next, preserveMetadata);
    } else {
      appendDomChildren(lexicalParent, child, next, preserveMetadata);
    }
  }
}

function listNodeFromDom(
  element: HTMLElement,
  preserveMetadata: boolean,
  depth: number
): ListNode {
  const list = $createListNode(
    element.tagName.toLowerCase() === "ol" ? "number" : "bullet"
  );
  for (const child of Array.from(element.children)) {
    if (child.tagName.toLowerCase() !== "li") {
      continue;
    }
    const item = $createListItemNode();
    appendDomChildren(
      item,
      child,
      { marks: {}, classes: [], variableKey: null },
      preserveMetadata
    );
    list.append(item);
    for (const nested of Array.from(child.children)) {
      const tag = nested.tagName.toLowerCase();
      if (tag !== "ul" && tag !== "ol") {
        continue;
      }
      if (depth < MAX_LIST_DEPTH) {
        const wrapper = $createListItemNode();
        wrapper.append(listNodeFromDom(nested as HTMLElement, preserveMetadata, depth + 1));
        list.append(wrapper);
      } else {
        item.append($createLineBreakNode());
        appendDomChildren(
          item,
          nested,
          { marks: {}, classes: [], variableKey: null },
          preserveMetadata
        );
      }
    }
  }
  if (list.getChildrenSize() === 0) {
    list.append($createListItemNode());
  }
  return list;
}

function lexicalBlocksFromDom(
  domParent: HTMLElement,
  structured: boolean,
  preserveMetadata: boolean
): LexicalNode[] {
  if (!structured) {
    const paragraph = $createParagraphNode();
    appendDomChildren(
      paragraph,
      domParent,
      { marks: {}, classes: [], variableKey: null },
      preserveMetadata
    );
    return [paragraph];
  }

  const blocks: LexicalNode[] = [];
  let looseParagraph: ReturnType<typeof $createParagraphNode> | null = null;
  const flushLooseParagraph = () => {
    if (looseParagraph) {
      blocks.push(looseParagraph);
      looseParagraph = null;
    }
  };
  for (const child of Array.from(domParent.childNodes)) {
    if (child instanceof HTMLElement) {
      const tag = child.tagName.toLowerCase();
      if (DROPPED_RICH_TEXT_TAGS.has(tag)) {
        continue;
      }
      if (tag === "ul" || tag === "ol") {
        flushLooseParagraph();
        blocks.push(listNodeFromDom(child, preserveMetadata, 1));
        continue;
      }
      if (
        tag === "p" ||
        tag === "div" ||
        /^h[1-6]$/.test(tag)
      ) {
        flushLooseParagraph();
        const paragraph = $createParagraphNode();
        appendDomChildren(
          paragraph,
          child,
          { marks: {}, classes: [], variableKey: null },
          preserveMetadata
        );
        blocks.push(paragraph);
        continue;
      }
    }
    looseParagraph ??= $createParagraphNode();
    const holder = document.createElement("div");
    holder.appendChild(child.cloneNode(true));
    appendDomChildren(
      looseParagraph,
      holder,
      { marks: {}, classes: [], variableKey: null },
      preserveMetadata
    );
  }
  flushLooseParagraph();
  return blocks.length > 0 ? blocks : [$createParagraphNode()];
}

function importHtml(
  editor: LexicalEditor,
  html: string,
  structured: boolean
): void {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  editor.update(
    () => {
      const root = $getRoot();
      root.clear();
      root.append(...lexicalBlocksFromDom(parsed.body, structured, true));
    },
    { discrete: true }
  );
}

function lexicalBlocksFromPlainText(
  text: string,
  structured: boolean
): LexicalNode[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  if (!structured) {
    const paragraph = $createParagraphNode();
    lines.forEach((line, index) => {
      if (index > 0) {
        paragraph.append($createLineBreakNode());
      }
      if (line) {
        paragraph.append($createTextNode(line));
      }
    });
    return [paragraph];
  }
  return lines.map((line) => {
    const paragraph = $createParagraphNode();
    if (line) {
      paragraph.append($createTextNode(line));
    }
    return paragraph;
  });
}

function marksFor(node: ReturnType<typeof $createTextNode>): RichTextMarks {
  const marks: RichTextMarks = {};
  if (node.hasFormat("bold")) marks.bold = true;
  if (node.hasFormat("italic")) marks.italic = true;
  if (node.hasFormat("underline")) marks.underline = true;
  if (node.hasFormat("strikethrough")) marks.strikethrough = true;
  return marks;
}

function appendCanonicalInline(
  inlines: RichTextInline[],
  next: RichTextInline
): void {
  const previous = inlines[inlines.length - 1];
  if (
    previous?.type === "text" &&
    next.type === "text" &&
    JSON.stringify(previous.marks ?? {}) === JSON.stringify(next.marks ?? {}) &&
    previous.classes === next.classes &&
    JSON.stringify(previous.link ?? null) === JSON.stringify(next.link ?? null)
  ) {
    previous.text += next.text;
    return;
  }
  if (
    previous?.type === "variable" &&
    next.type === "variable" &&
    previous.key === next.key &&
    JSON.stringify(previous.marks ?? {}) === JSON.stringify(next.marks ?? {}) &&
    previous.classes === next.classes &&
    JSON.stringify(previous.link ?? null) === JSON.stringify(next.link ?? null)
  ) {
    previous.fallback += next.fallback;
    return;
  }
  inlines.push(next);
}

function exportChildren(
  children: LexicalNode[],
  inlines: RichTextInline[],
  activeLink: RichTextLink | undefined
): void {
  for (const child of children) {
    if ($isLinkNode(child)) {
      exportChildren(child.getChildren(), inlines, {
        href: child.getURL(),
        ...(child.getTarget() === "_blank" ? { new_tab: true } : {})
      });
      continue;
    }
    if ($isTextNode(child)) {
      const metadata = $getState(child, inlineMetadataState);
      const common = {
        ...(Object.keys(marksFor(child)).length > 0 ? { marks: marksFor(child) } : {}),
        ...(metadata.classes ? { classes: metadata.classes } : {}),
        ...(activeLink ? { link: activeLink } : {})
      };
      appendCanonicalInline(
        inlines,
        metadata.variableKey
          ? {
              type: "variable",
              key: metadata.variableKey,
              fallback: child.getTextContent(),
              ...common
            }
          : { type: "text", text: child.getTextContent(), ...common }
      );
      continue;
    }
    if ($isLineBreakNode(child)) {
      inlines.push({ type: "line_break", ...(activeLink ? { link: activeLink } : {}) });
      continue;
    }
    if ($isElementNode(child)) {
      exportChildren(child.getChildren(), inlines, activeLink);
    }
  }
}

function exportListBlock(list: ListNode): RichTextBlock {
  const items: Extract<RichTextBlock, { type: "list" }>["items"] = [];
  for (const child of list.getChildren()) {
    if (!$isListItemNode(child)) {
      continue;
    }
    const directNested = child.getChildren().filter($isListNode);
    const contentNodes = child.getChildren().filter((node) => !$isListNode(node));
    if (directNested.length > 0 && contentNodes.length === 0 && items.length > 0) {
      const previous = items[items.length - 1];
      previous.nested = [
        ...(previous.nested ?? []),
        ...directNested.map(exportListBlock)
      ];
      continue;
    }
    const inlines: RichTextInline[] = [];
    exportChildren(contentNodes, inlines, undefined);
    const nested = directNested.map(exportListBlock);
    items.push({
      children: inlines,
      ...(nested.length > 0 ? { nested } : {})
    });
  }
  return {
    type: "list",
    list_type: list.getListType() === "number" ? "ordered" : "unordered",
    items
  };
}

export function exportRichTextDocument(): RichTextDocument {
  const blocks: RichTextBlock[] = [];
  for (const blockNode of $getRoot().getChildren()) {
    if ($isListNode(blockNode)) {
      blocks.push(exportListBlock(blockNode));
      continue;
    }
    const children: RichTextInline[] = [];
    if ($isElementNode(blockNode)) {
      exportChildren(blockNode.getChildren(), children, undefined);
    } else {
      exportChildren([blockNode], children, undefined);
    }
    blocks.push({ type: "paragraph", children });
  }
  return {
    schema_version: 1,
    blocks: blocks.length > 0 ? blocks : [{ type: "paragraph", children: [] }]
  };
}

function escapeText(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttribute(value: string): string {
  return escapeText(value).replaceAll('"', "&quot;");
}

function renderInline(inline: RichTextInline): string {
  if (inline.type === "line_break") {
    return "<br />";
  }
  const marks = inline.marks ?? {};
  const link = inline.link;
  const classes = inline.classes;
  const variableKey = inline.type === "variable" ? inline.key : null;
  let html = escapeText(inline.type === "variable" ? inline.fallback : inline.text);
  if (marks.strikethrough) html = `<s>${html}</s>`;
  if (marks.underline) html = `<u>${html}</u>`;
  if (marks.italic) html = `<em>${html}</em>`;
  if (marks.bold) html = `<strong>${html}</strong>`;
  if (variableKey || classes) {
    html = `<span${variableKey ? ` data-var="${escapeAttribute(variableKey)}"` : ""}${
      classes ? ` class="${escapeAttribute(classes)}"` : ""
    }>${html}</span>`;
  }
  if (link) {
    html = `<a href="${escapeAttribute(link.href)}"${
      link.new_tab ? ' target="_blank" rel="noopener noreferrer"' : ""
    }>${html}</a>`;
  }
  return html;
}

function renderBlock(block: RichTextBlock): string {
  if (block.type === "paragraph") {
    return `<p>${block.children.map(renderInline).join("")}</p>`;
  }
  const tag = block.list_type === "ordered" ? "ol" : "ul";
  const items = block.items
    .map(
      (item) =>
        `<li>${item.children.map(renderInline).join("")}${(item.nested ?? [])
          .map(renderBlock)
          .join("")}</li>`
    )
    .join("");
  return `<${tag}>${items}</${tag}>`;
}

export function renderRichTextDocument(document: RichTextDocument): string {
  return document.blocks.map(renderBlock).join("");
}

function renderInlineRichTextDocument(document: RichTextDocument): string {
  const first = document.blocks[0];
  if (!first || first.type !== "paragraph") {
    return "";
  }
  return first.children.map(renderInline).join("");
}

function formatValue(selection: RangeSelection, format: TextFormatType): RichTextFormatValue {
  if (selection.isCollapsed()) {
    return selection.hasFormat(format) ? "on" : "off";
  }
  const textNodes = selection.getNodes().filter($isTextNode);
  if (textNodes.length === 0) {
    return selection.hasFormat(format) ? "on" : "off";
  }
  const matching = textNodes.filter((node) => node.hasFormat(format)).length;
  if (matching === 0) return "off";
  if (matching === textNodes.length) return "on";
  return "mixed";
}

function textNodesForSelection(selection: RangeSelection): ReturnType<typeof $createTextNode>[] {
  return selection.getNodes().filter($isTextNode);
}

function classSelectionState(selection: RangeSelection): {
  commonClasses: string[];
  mixedClasses: string[];
} {
  const nodes = textNodesForSelection(selection);
  if (nodes.length === 0) {
    return { commonClasses: [], mixedClasses: [] };
  }
  const sets = nodes.map(
    (node) =>
      new Set(
        ($getState(node, inlineMetadataState).classes ?? "")
          .split(/\s+/)
          .filter(Boolean)
      )
  );
  const union = new Set(sets.flatMap((set) => Array.from(set)));
  const commonClasses = Array.from(union).filter((name) =>
    sets.every((set) => set.has(name))
  );
  return {
    commonClasses,
    mixedClasses: Array.from(union).filter((name) => !commonClasses.includes(name))
  };
}

function parentLinkFor(node: LexicalNode): LinkNode | null {
  let current = node.getParent();
  while (current) {
    if ($isLinkNode(current)) {
      return current;
    }
    current = current.getParent();
  }
  return null;
}

function enclosingLinkFor(node: LexicalNode): LinkNode | null {
  return $isLinkNode(node) ? node : parentLinkFor(node);
}

function enclosingListItem(node: LexicalNode): ListItemNode | null {
  let current: LexicalNode | null = node;
  while (current) {
    if ($isListItemNode(current)) {
      return current;
    }
    current = current.getParent();
  }
  return null;
}

function blockTypeForNode(
  node: LexicalNode
): Exclude<RichTextSelectionState["blockType"], "mixed"> {
  let current: LexicalNode | null = node;
  while (current) {
    if ($isListNode(current)) {
      return current.getListType() === "number"
        ? "ordered_list"
        : "unordered_list";
    }
    if ($isParagraphNode(current)) {
      return "paragraph";
    }
    current = current.getParent();
  }
  return "paragraph";
}

function blockSelectionState(
  selection: RangeSelection,
  structured: boolean
): Pick<
  RichTextSelectionState,
  "blockType" | "structured" | "canIndent" | "canOutdent"
> {
  const nodes = selection.getNodes();
  const candidates = nodes.length > 0 ? nodes : [selection.anchor.getNode()];
  const blockTypes = new Set(candidates.map(blockTypeForNode));
  const listItems = Array.from(
    new Map(
      candidates
        .map(enclosingListItem)
        .filter((item): item is ListItemNode => item !== null)
        .map((item) => [item.getKey(), item])
    ).values()
  );
  return {
    blockType:
      blockTypes.size === 1
        ? Array.from(blockTypes)[0]
        : "mixed",
    structured,
    canIndent:
      structured &&
      listItems.length > 0 &&
      listItems.every(
        (item) =>
          item.getIndent() < MAX_LIST_DEPTH - 1 &&
          item.getPreviousSibling() !== null
      ),
    canOutdent:
      structured &&
      listItems.length > 0 &&
      listItems.some((item) => item.getIndent() > 0)
  };
}

function selectionHasToolbarContext(
  selection: RangeSelection,
  structured: boolean
): boolean {
  return (
    structured ||
    !selection.isCollapsed() ||
    enclosingLinkFor(selection.anchor.getNode()) !== null
  );
}

function unwrapLink(link: LinkNode): void {
  const parent = link.getParentOrThrow();
  parent.splice(link.getIndexWithinParent(), 0, link.getChildren());
  link.remove();
}

function linkSelectionState(selection: RangeSelection): RichTextSelectionState["link"] {
  const nodes = textNodesForSelection(selection);
  const candidates =
    nodes.length > 0
      ? nodes
      : $isTextNode(selection.anchor.getNode())
        ? [selection.anchor.getNode()]
        : [];
  if (candidates.length === 0) {
    return { state: "off", href: null, newTab: null };
  }
  const links = candidates.map(parentLinkFor);
  if (links.every((link) => link === null)) {
    return { state: "off", href: null, newTab: null };
  }
  const first = links[0];
  if (
    first &&
    links.every(
      (link) =>
        link?.getURL() === first.getURL() &&
        link?.getTarget() === first.getTarget()
    )
  ) {
    return {
      state: "on",
      href: first.getURL(),
      newTab: first.getTarget() === "_blank"
    };
  }
  return { state: "mixed", href: null, newTab: null };
}

function domSelectionRect(rootElement: HTMLElement): WebNodeRect | null {
  const domSelection = window.getSelection();
  if (!domSelection || domSelection.rangeCount === 0) {
    return null;
  }
  const anchor = domSelection.anchorNode;
  const focus = domSelection.focusNode;
  if (
    !anchor ||
    !focus ||
    (!rootElement.contains(anchor) && anchor !== rootElement) ||
    (!rootElement.contains(focus) && focus !== rootElement)
  ) {
    return null;
  }
  const range = domSelection.getRangeAt(0);
  const rect =
    typeof range.getBoundingClientRect === "function"
      ? range.getBoundingClientRect()
      : null;
  const firstClientRect =
    (!rect || (rect.width === 0 && rect.height === 0)) &&
    typeof range.getClientRects === "function"
      ? range.getClientRects()[0]
      : null;
  const measured = firstClientRect ?? rect;
  if (!measured) {
    return null;
  }
  return {
    x: measured.x,
    y: measured.y,
    top: measured.top,
    right: measured.right,
    bottom: measured.bottom,
    left: measured.left,
    width: measured.width,
    height: measured.height
  };
}

function emptySelectionState(structured = false): RichTextSelectionState {
  return {
    collapsed: true,
    selectedText: "",
    rect: null,
    formats: {
      bold: "off",
      italic: "off",
      underline: "off",
      strikethrough: "off"
    },
    commonClasses: [],
    mixedClasses: [],
    link: { state: "off", href: null, newTab: null },
    blockType: "paragraph",
    structured,
    canIndent: false,
    canOutdent: false
  };
}

/** Personalization variables are semantic atoms. Expanding a partial endpoint
 * to the whole variable prevents formatting from splitting one variable into
 * multiple same-key spans (which would duplicate its derived value). */
function expandVariableEndpoints(selection: RangeSelection): void {
  if (selection.isCollapsed()) {
    return;
  }
  const backward = selection.isBackward();
  const start = backward ? selection.focus : selection.anchor;
  const end = backward ? selection.anchor : selection.focus;
  const startNode = start.getNode();
  const endNode = end.getNode();
  if (
    $isTextNode(startNode) &&
    $getState(startNode, inlineMetadataState).variableKey
  ) {
    start.set(startNode.getKey(), 0, "text");
  }
  if (
    $isTextNode(endNode) &&
    $getState(endNode, inlineMetadataState).variableKey
  ) {
    end.set(endNode.getKey(), endNode.getTextContentSize(), "text");
  }
}

function updateMetadataClasses(
  node: ReturnType<typeof $createTextNode>,
  transform: (classes: string[]) => string[]
): void {
  const metadata = $getState(node, inlineMetadataState);
  const classes = transform(
    (metadata.classes ?? "").split(/\s+/).filter(Boolean)
  );
  $setState(node, inlineMetadataState, {
    classes: classes.length > 0 ? Array.from(new Set(classes)).join(" ") : null,
    variableKey: metadata.variableKey
  });
}

export function mountRichTextEditor(
  rootElement: HTMLElement,
  options: RichTextMountOptions
): RichTextSession {
  const structured = variantAllowsStructure(options.textVariant);
  const editor = createEditor({
    namespace: `lumen-web-rich-text-${Math.random().toString(36).slice(2)}`,
    nodes: [LinkNode, ListNode, ListItemNode],
    onError(error) {
      throw error;
    }
  });
  const unregisterRichText = registerRichText(editor);
  const unregisterList = registerList(editor);
  const unregisterStrictIndent = registerListStrictIndentTransform(editor);
  const unregisterHistory = registerHistory(editor, createEmptyHistoryState(), 300);
  let lastSelection: RangeSelection | null = null;
  let interactionActive = false;

  editor.setRootElement(rootElement);
  rootElement.setAttribute("contenteditable", "true");
  rootElement.setAttribute("spellcheck", "true");
  rootElement.setAttribute("role", "textbox");
  rootElement.setAttribute("aria-multiline", structured ? "true" : "false");
  rootElement.setAttribute("aria-label", "Edit text");
  importHtml(editor, options.initialHtml, structured);

  let lastRect: WebNodeRect | null = null;
  let selectionFrame: number | null = null;

  const readSelectionState = (): RichTextSelectionState => {
    let state = emptySelectionState(structured);
    editor.getEditorState().read(() => {
      const current = $getSelection();
      const selection =
        interactionActive && lastSelection
          ? lastSelection
          : $isRangeSelection(current)
            ? current
            : lastSelection;
      if (!selection) {
        return;
      }
      if ($isRangeSelection(current) && !interactionActive) {
        lastSelection = current.clone();
      }
      const classes = classSelectionState(selection);
      const measured = domSelectionRect(rootElement);
      if (measured) {
        lastRect = measured;
      }
      state = {
        collapsed: selection.isCollapsed(),
        selectedText: selection.getTextContent(),
        rect: measured ?? lastRect,
        formats: {
          bold: formatValue(selection, "bold"),
          italic: formatValue(selection, "italic"),
          underline: formatValue(selection, "underline"),
          strikethrough: formatValue(selection, "strikethrough")
        },
        ...classes,
        link: linkSelectionState(selection),
        ...blockSelectionState(selection, structured)
      };
    });
    return state;
  };

  const emitSelectionState = (): RichTextSelectionState => {
    const state = readSelectionState();
    options.onFormatStateChange?.(state.formats);
    options.onSelectionStateChange?.(state);
    return state;
  };

  const scheduleSelectionState = () => {
    if (selectionFrame !== null) {
      return;
    }
    selectionFrame = window.requestAnimationFrame(() => {
      selectionFrame = null;
      emitSelectionState();
    });
  };

  const unregisterUpdate = editor.registerUpdateListener(() => {
    scheduleSelectionState();
  });
  const onKeyDown = (event: KeyboardEvent) => {
    const modifier = event.metaKey || event.ctrlKey;
    const key = event.key.toLowerCase();
    const shortcut: RichTextFormat | null =
      modifier && !event.shiftKey && ["b", "i", "u"].includes(key)
        ? ({ b: "bold", i: "italic", u: "underline" } as const)[
            key as "b" | "i" | "u"
          ]
        : modifier && event.shiftKey && (key === "x" || key === "s")
          ? "strikethrough"
          : null;
    if (shortcut) {
      event.preventDefault();
      event.stopImmediatePropagation();
      format(shortcut);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();
      options.onCancelRequest?.();
    } else if (event.key === "Enter" && modifier) {
      event.preventDefault();
      event.stopImmediatePropagation();
      options.onCommitRequest?.();
    } else if (event.key === "Enter" && !modifier) {
      event.preventDefault();
      event.stopImmediatePropagation();
      runWithSelection(() => {
        if (structured && !event.shiftKey) {
          editor.dispatchCommand(INSERT_PARAGRAPH_COMMAND, undefined);
        } else {
          editor.dispatchCommand(INSERT_LINE_BREAK_COMMAND, false);
        }
      });
    } else if (event.key === "Tab" && structured) {
      let handled = false;
      runWithSelection((selection) => {
        const block = blockSelectionState(selection, structured);
        if (
          block.blockType !== "ordered_list" &&
          block.blockType !== "unordered_list"
        ) {
          return;
        }
        handled = true;
        if (event.shiftKey) {
          if (block.canOutdent) {
            editor.dispatchCommand(OUTDENT_CONTENT_COMMAND, undefined);
          }
        } else if (block.canIndent) {
          editor.dispatchCommand(INDENT_CONTENT_COMMAND, undefined);
        }
      });
      if (handled) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }
  };
  rootElement.addEventListener("keydown", onKeyDown, true);

  const onPaste = (event: ClipboardEvent) => {
    const clipboard = event.clipboardData;
    if (!clipboard) {
      return;
    }
    const html = clipboard.getData("text/html");
    const plain = clipboard.getData("text/plain");
    if (!html && !plain) {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    editor.update(
      () => {
        const selection = $getSelection();
        if (!$isRangeSelection(selection)) {
          return;
        }
        const nodes = html
          ? lexicalBlocksFromDom(
              new DOMParser().parseFromString(html, "text/html").body,
              structured,
              false
            )
          : lexicalBlocksFromPlainText(plain, structured);
        selection.insertNodes(nodes);
      },
      { discrete: true }
    );
  };
  rootElement.addEventListener("paste", onPaste, true);

  const runWithSelection = (
    mutate: (selection: RangeSelection) => void
  ): void => {
    editor.update(
      () => {
        let selection = $getSelection();
        if (
          lastSelection &&
          (!$isRangeSelection(selection) ||
            interactionActive ||
            (!selectionHasToolbarContext(selection, structured) &&
              selectionHasToolbarContext(lastSelection, structured)))
        ) {
          $setSelection(lastSelection.clone());
          selection = $getSelection();
        }
        if ($isRangeSelection(selection)) {
          expandVariableEndpoints(selection);
          mutate(selection);
          const settled = $getSelection();
          if ($isRangeSelection(settled)) {
            lastSelection = settled.clone();
          }
        }
      },
      { discrete: true }
    );
    editor.focus();
    scheduleSelectionState();
  };

  const format = (value: RichTextFormat): void => {
    runWithSelection((selection) => selection.formatText(value));
  };

  const command = (value: RichTextCommand): void => {
    if (value.type === "refresh_selection") {
      scheduleSelectionState();
      return;
    }
    if (value.type === "format") {
      format(value.format);
      return;
    }
    runWithSelection((selection) => {
      if (value.type === "set_block") {
        if (!structured) {
          return;
        }
        const current = blockSelectionState(selection, structured).blockType;
        if (value.block === "paragraph" || current === value.block) {
          editor.dispatchCommand(REMOVE_LIST_COMMAND, undefined);
        } else {
          editor.dispatchCommand(
            value.block === "ordered_list"
              ? INSERT_ORDERED_LIST_COMMAND
              : INSERT_UNORDERED_LIST_COMMAND,
            undefined
          );
        }
        return;
      }
      if (value.type === "indent_list" || value.type === "outdent_list") {
        if (!structured) {
          return;
        }
        const block = blockSelectionState(selection, structured);
        if (value.type === "indent_list" && block.canIndent) {
          editor.dispatchCommand(INDENT_CONTENT_COMMAND, undefined);
        } else if (value.type === "outdent_list" && block.canOutdent) {
          editor.dispatchCommand(OUTDENT_CONTENT_COMMAND, undefined);
        }
        return;
      }
      if (value.type === "set_class_facet") {
        const safeTokens = new Set(
          value.knownTokens.filter((token) => /^[a-z0-9_-]+$/.test(token))
        );
        if (value.token !== null && !safeTokens.has(value.token)) {
          return;
        }
        const prefix = value.facet === "text_color" ? "text-" : "bg-";
        const removable = new Set(
          Array.from(safeTokens, (token) => `${prefix}${token}`)
        );
        for (const node of selection.extract().filter($isTextNode)) {
          updateMetadataClasses(node, (classes) => [
            ...classes.filter((name) => !removable.has(name)),
            ...(value.token ? [`${prefix}${value.token}`] : [])
          ]);
        }
        return;
      }
      if (value.type === "set_link") {
        const href = value.href.trim();
        if (richTextHrefIsAllowed(href)) {
          $toggleLink(href, {
            target: value.newTab ? "_blank" : null,
            rel: value.newTab ? "noopener noreferrer" : null
          });
        }
        return;
      }
      if (value.type === "remove_link") {
        if (selection.isCollapsed()) {
          const link = enclosingLinkFor(selection.anchor.getNode());
          if (link) {
            // Lexical's generic collapsed unlink path depends on getNodes(),
            // which may be empty for a caret-only selection. Resolve the
            // enclosing semantic link directly so toolbar unlink is reliable.
            unwrapLink(link);
            return;
          }
        }
        $toggleLink(null);
        return;
      }
      if (value.type === "insert_variable") {
        const key = value.key.trim();
        const fallback = value.fallback.trim();
        if (!webBindingKeyIsAllowed(key) || !fallback) {
          return;
        }
        const variable = $createTextNode(fallback);
        applyMarks(
          variable,
          Object.fromEntries(
            FORMATS.filter((mark) => selection.hasFormat(mark)).map((mark) => [
              mark,
              true
            ])
          )
        );
        $setState(variable, inlineMetadataState, {
          classes: null,
          variableKey: key
        });
        selection.insertNodes([variable]);
        variable.select();
        return;
      }
      if (value.type === "clear_formatting") {
        for (const node of selection.extract().filter($isTextNode)) {
          for (const mark of FORMATS) {
            if (node.hasFormat(mark)) {
              node.toggleFormat(mark);
            }
          }
          updateMetadataClasses(node, () => []);
        }
        return;
      }
    });
  };

  const onSelectionChange = () => scheduleSelectionState();
  const onViewportChange = () => scheduleSelectionState();
  document.addEventListener("selectionchange", onSelectionChange);
  window.addEventListener("scroll", onViewportChange, { passive: true });
  window.addEventListener("resize", onViewportChange, { passive: true });

  const session: RichTextSession = {
    format,
    command,
    setInteractionActive(active) {
      if (active && !interactionActive) {
        // Parent/iframe postMessage delivery is asynchronous: by the time the
        // pointer-down handshake arrives, the toolbar may already own browser
        // focus. Freeze first so readSelectionState prefers the last
        // selection captured inside the iframe instead of overwriting it with
        // a focus-transfer side effect.
        interactionActive = true;
        emitSelectionState();
        scheduleSelectionState();
        return;
      }
      interactionActive = active;
      scheduleSelectionState();
    },
    getDocument() {
      let document: RichTextDocument = {
        schema_version: 1,
        blocks: [{ type: "paragraph", children: [] }]
      };
      editor.getEditorState().read(() => {
        document = exportRichTextDocument();
      });
      return document;
    },
    getHtml() {
      const content = session.getDocument();
      return structured
        ? renderRichTextDocument(content)
        : renderInlineRichTextDocument(content);
    },
    getFormatState() {
      return emitSelectionState().formats;
    },
    getSelectionState: emitSelectionState,
    refreshSelection: scheduleSelectionState,
    focus() {
      editor.focus();
      scheduleSelectionState();
    },
    destroy() {
      interactionActive = false;
      if (selectionFrame !== null) {
        window.cancelAnimationFrame(selectionFrame);
        selectionFrame = null;
      }
      rootElement.removeEventListener("keydown", onKeyDown, true);
      rootElement.removeEventListener("paste", onPaste, true);
      document.removeEventListener("selectionchange", onSelectionChange);
      window.removeEventListener("scroll", onViewportChange);
      window.removeEventListener("resize", onViewportChange);
      unregisterUpdate();
      unregisterHistory();
      unregisterStrictIndent();
      unregisterList();
      unregisterRichText();
      editor.setRootElement(null);
      rootElement.removeAttribute("contenteditable");
      rootElement.removeAttribute("spellcheck");
      rootElement.removeAttribute("role");
      rootElement.removeAttribute("aria-multiline");
      rootElement.removeAttribute("aria-label");
    }
  };

  editor.focus();
  emitSelectionState();
  return session;
}

export const LumenRichTextRuntime = {
  mount: mountRichTextEditor
};

declare global {
  interface Window {
    LumenRichTextRuntime?: typeof LumenRichTextRuntime;
  }
}

window.LumenRichTextRuntime = LumenRichTextRuntime;
