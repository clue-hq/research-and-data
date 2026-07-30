import {
  $createLineBreakNode,
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  $getSelection,
  $getState,
  $isElementNode,
  $isLineBreakNode,
  $isRangeSelection,
  $isTextNode,
  $setSelection,
  $setState,
  createEditor,
  createState,
  INSERT_LINE_BREAK_COMMAND,
  type ElementNode,
  type LexicalEditor,
  type LexicalNode,
  type RangeSelection,
  type TextFormatType
} from "lexical";
import { createEmptyHistoryState, registerHistory } from "@lexical/history";
import { $createLinkNode, $isLinkNode, LinkNode } from "@lexical/link";
import { registerRichText } from "@lexical/rich-text";

import type {
  RichTextBlock,
  RichTextDocument,
  RichTextInline,
  RichTextLink,
  RichTextMarks
} from "../engine/webDocuments";

export type RichTextFormat = "bold" | "italic" | "underline" | "strikethrough";
export type RichTextFormatValue = "on" | "off" | "mixed";
export type RichTextFormatState = Record<RichTextFormat, RichTextFormatValue>;

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
  getDocument: () => RichTextDocument;
  getHtml: () => string;
  getFormatState: () => RichTextFormatState;
  focus: () => void;
  destroy: () => void;
}

export interface RichTextMountOptions {
  initialHtml: string;
  onFormatStateChange?: (state: RichTextFormatState) => void;
  onCommitRequest?: () => void;
  onCancelRequest?: () => void;
}

const FORMATS: RichTextFormat[] = ["bold", "italic", "underline", "strikethrough"];

function applyMarks(node: ReturnType<typeof $createTextNode>, marks: RichTextMarks): void {
  for (const format of FORMATS) {
    if (marks[format]) {
      node.toggleFormat(format);
    }
  }
}

function appendDomChildren(
  lexicalParent: ElementNode,
  domParent: Node,
  context: ImportContext
): void {
  for (const child of Array.from(domParent.childNodes)) {
    if (child.nodeType === Node.TEXT_NODE) {
      const text = child.textContent ?? "";
      if (!text) {
        continue;
      }
      const node = $createTextNode(text);
      applyMarks(node, context.marks);
      const classes = context.classes.flatMap((value) => value.split(/\s+/)).filter(Boolean).join(" ");
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
    if (tag === "br") {
      lexicalParent.append($createLineBreakNode());
      continue;
    }

    const next: ImportContext = {
      marks: { ...context.marks },
      classes: [...context.classes],
      variableKey: context.variableKey
    };
    if (tag === "strong") next.marks.bold = true;
    if (tag === "em") next.marks.italic = true;
    if (tag === "u") next.marks.underline = true;
    if (tag === "s") next.marks.strikethrough = true;
    if (tag === "span") {
      const classes = child.getAttribute("class");
      if (classes) next.classes.push(classes);
      next.variableKey = child.getAttribute("data-var") || next.variableKey;
    }

    if (tag === "a") {
      const link = $createLinkNode(child.getAttribute("href") ?? "", {
        target: child.getAttribute("target")
      });
      lexicalParent.append(link);
      appendDomChildren(link, child, next);
    } else {
      appendDomChildren(lexicalParent, child, next);
    }
  }
}

function importInlineHtml(editor: LexicalEditor, html: string): void {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  editor.update(
    () => {
      const root = $getRoot();
      root.clear();
      const paragraph = $createParagraphNode();
      root.append(paragraph);
      appendDomChildren(
        paragraph,
        parsed.body,
        { marks: {}, classes: [], variableKey: null }
      );
    },
    { discrete: true }
  );
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

export function exportRichTextDocument(): RichTextDocument {
  const blocks: RichTextBlock[] = [];
  for (const blockNode of $getRoot().getChildren()) {
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
      link.new_tab ? ' target="_blank"' : ""
    }>${html}</a>`;
  }
  return html;
}

function renderBlock(block: RichTextBlock): string {
  if (block.type === "paragraph") {
    return block.children.map(renderInline).join("");
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
  return document.blocks.map(renderBlock).join("<br />");
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

function readFormatState(): RichTextFormatState {
  const selection = $getSelection();
  if (!$isRangeSelection(selection)) {
    return { bold: "off", italic: "off", underline: "off", strikethrough: "off" };
  }
  return {
    bold: formatValue(selection, "bold"),
    italic: formatValue(selection, "italic"),
    underline: formatValue(selection, "underline"),
    strikethrough: formatValue(selection, "strikethrough")
  };
}

export function mountRichTextEditor(
  rootElement: HTMLElement,
  options: RichTextMountOptions
): RichTextSession {
  const editor = createEditor({
    namespace: `lumen-web-rich-text-${Math.random().toString(36).slice(2)}`,
    nodes: [LinkNode],
    onError(error) {
      throw error;
    }
  });
  const unregisterRichText = registerRichText(editor);
  const unregisterHistory = registerHistory(editor, createEmptyHistoryState(), 300);
  let lastSelection: RangeSelection | null = null;

  editor.setRootElement(rootElement);
  rootElement.setAttribute("contenteditable", "true");
  rootElement.setAttribute("spellcheck", "true");
  rootElement.setAttribute("role", "textbox");
  rootElement.setAttribute("aria-multiline", "true");
  rootElement.setAttribute("aria-label", "Edit text");
  importInlineHtml(editor, options.initialHtml);

  const emitFormatState = (): RichTextFormatState => {
    let state: RichTextFormatState = {
      bold: "off",
      italic: "off",
      underline: "off",
      strikethrough: "off"
    };
    editor.getEditorState().read(() => {
      const selection = $getSelection();
      if ($isRangeSelection(selection)) {
        lastSelection = selection.clone();
      }
      state = readFormatState();
    });
    options.onFormatStateChange?.(state);
    return state;
  };

  const unregisterUpdate = editor.registerUpdateListener(() => {
    emitFormatState();
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
      editor.dispatchCommand(INSERT_LINE_BREAK_COMMAND, false);
    }
  };
  rootElement.addEventListener("keydown", onKeyDown, true);

  const format = (value: RichTextFormat): void => {
    editor.update(
      () => {
        let selection = $getSelection();
        if (!$isRangeSelection(selection) && lastSelection) {
          $setSelection(lastSelection.clone());
          selection = $getSelection();
        }
        if ($isRangeSelection(selection)) {
          selection.formatText(value);
          lastSelection = selection.clone();
        }
      },
      { discrete: true }
    );
    editor.focus();
    emitFormatState();
  };

  const session: RichTextSession = {
    format,
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
      return renderRichTextDocument(session.getDocument());
    },
    getFormatState: emitFormatState,
    focus() {
      editor.focus();
    },
    destroy() {
      rootElement.removeEventListener("keydown", onKeyDown, true);
      unregisterUpdate();
      unregisterHistory();
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
  emitFormatState();
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
