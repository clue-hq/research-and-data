// The editor's rich text fields (site element inspector, plan 2): Puck's `richtext` field (TipTap)
// narrowed to the stored grammar (rich.ts) — one paragraph, line breaks, bold / italic / underline /
// strike, links and styled spans — so whatever the marketer types or pastes is text the save check
// accepts, and a stored styled span or link survives every keystroke (both are marks in the editor's
// schema; an element the schema does not know would be dropped on the first edit). Editor-only: the
// published page draws rich text with rich.ts and never loads TipTap.
import { Extension, Mark, mergeAttributes } from "@tiptap/core";
import { ElementKeySchema, SPAN_KEY_ATTR } from "../edits";
import { isRichLink } from "../rich";

/** Enter makes a line break: the grammar is inline only (plan 2 ruling R1). Text pasted as several
 * paragraphs keeps every word: its paragraphs become line breaks when it is saved (normalizeRich). */
export const ClueEnter = Extension.create({
  name: "clueEnter",
  addKeyboardShortcuts() {
    return { Enter: () => this.editor.commands.setHardBreak() };
  },
});

/** A link of the grammar: `<a href="…">`, with `data-new-tab` for one that opens in a new tab. An
 * address outside the grammar (javascript:, a bare word) is not a link: its words are kept. */
export const ClueLink = Mark.create({
  name: "clueLink",
  priority: 1100,
  inclusive: false,
  addAttributes() {
    return {
      href: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("href"),
        renderHTML: (attributes: { href?: string | null }) => (attributes.href ? { href: attributes.href } : {}),
      },
      newTab: {
        default: false,
        parseHTML: (element: HTMLElement) => element.hasAttribute("data-new-tab"),
        renderHTML: (attributes: { newTab?: boolean }) => (attributes.newTab ? { "data-new-tab": "" } : {}),
      },
    };
  },
  parseHTML() {
    return [
      {
        tag: "a[href]",
        getAttrs: (element: HTMLElement) => (isRichLink(element.getAttribute("href") ?? "") ? null : false),
      },
    ];
  },
  renderHTML({ HTMLAttributes }) {
    return ["a", mergeAttributes(HTMLAttributes), 0];
  },
});

/** A styled span of highlighted words: `<span data-s="<key>">`, its look an `_edits` entry. */
export const ClueStyle = Mark.create({
  name: "clueStyle",
  priority: 1050,
  addAttributes() {
    return {
      key: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute(SPAN_KEY_ATTR),
        renderHTML: (attributes: { key?: string | null }) => (attributes.key ? { [SPAN_KEY_ATTR]: attributes.key } : {}),
      },
    };
  },
  parseHTML() {
    return [
      {
        tag: `span[${SPAN_KEY_ATTR}]`,
        getAttrs: (element: HTMLElement) => (ElementKeySchema.safeParse(element.getAttribute(SPAN_KEY_ATTR)).success ? null : false),
      },
    ];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes), 0];
  },
});

/** Puck's built-in rich text pieces this grammar has no room for (ours replaces its link). Puck always
 * registers text alignment; what it writes is dropped when the text is saved. */
export const RICH_TEXT_OPTIONS = {
  blockquote: false,
  bulletList: false,
  code: false,
  codeBlock: false,
  heading: false,
  horizontalRule: false,
  link: false,
  listItem: false,
  listKeymap: false,
  orderedList: false,
} as const;

export const RICH_TEXT_EXTENSIONS = [ClueEnter, ClueLink, ClueStyle];

/** One rich text field, edited in place on the canvas. Puck draws no menu of its own for it: the
 * styling controls are the inspector's (they act on the stored text, not through TipTap). */
export function richTextField(label: string, options: { links?: boolean } = {}) {
  return {
    type: "richtext" as const,
    label,
    contentEditable: true,
    options: RICH_TEXT_OPTIONS,
    // A button's words (plan 3) have no link mark: a pasted link keeps its words, never its link.
    tiptap: { extensions: options.links === false ? RICH_TEXT_EXTENSIONS.filter((extension) => extension !== ClueLink) : RICH_TEXT_EXTENSIONS },
    renderInlineMenu: () => null,
  };
}

/** The rich text of an element the marketer typed in directly (a clone's text slot), as the grammar's
 * markup: bold / italic / underline / strike from their tags (the browser's own ⌘B writes <b>), links
 * and styled spans kept, line breaks and block boundaries as <br>, everything else unwrapped to its
 * words. The browser half of rich.ts's normalizeRich, which then gives the canonical form. */
export function richFromDom(element: Element): string {
  const escape = (text: string) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const attr = (text: string) => escape(text).replace(/"/g, "&quot;");
  const MARKS: Record<string, string> = { b: "strong", strong: "strong", i: "em", em: "em", u: "u", s: "s", strike: "s" };
  const BLOCK = /^(p|div|li|h[1-6]|blockquote|section|article|header|footer|ul|ol|tr)$/;
  const walk = (node: globalThis.Node, top: boolean): string => {
    if (node.nodeType === 3) return escape(node.nodeValue ?? "");
    if (node.nodeType !== 1) return "";
    const el = node as Element;
    const tag = el.tagName.toLowerCase();
    if (tag === "br") return el.classList.contains("ProseMirror-trailingBreak") ? "" : "<br>";
    if (/^(script|style|template|noscript|svg)$/.test(tag)) return "";
    const inner = [...el.childNodes].map((child) => walk(child, false)).join("");
    if (top) return inner;
    if (MARKS[tag]) return `<${MARKS[tag]}>${inner}</${MARKS[tag]}>`;
    if (tag === "a" && isRichLink(el.getAttribute("href") ?? "")) {
      return `<a href="${attr(el.getAttribute("href") ?? "")}"${el.hasAttribute("data-new-tab") ? ' data-new-tab=""' : ""}>${inner}</a>`;
    }
    const key = tag === "span" ? el.getAttribute(SPAN_KEY_ATTR) : null;
    if (key && ElementKeySchema.safeParse(key).success) return `<span ${SPAN_KEY_ATTR}="${attr(key)}">${inner}</span>`;
    // A block inside the text (the browser's contentEditable makes <div>s on Enter) starts a new line.
    if (BLOCK.test(tag)) return el.previousSibling ? `<br>${inner}` : inner;
    return inner;
  };
  return walk(element, true);
}
