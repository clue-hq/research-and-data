import { ELEMENT_KEY_ATTR, ElementKeySchema, ROOT_INNER_KEY, ROOT_KEY, sizeScaleFrom } from "@clue/site-kit/edits";
import type { Arrange, ComputedBox, ComputedContainer, ComputedTypography, EditorMode, ElementSelection, ElementSummary, SiteGeometry } from "@clue/site-kit/editor-protocol";
import type { BrandData } from "@clue/site-kit";

export type ClickAction =
  | { kind: "navigate"; href: string }
  | { kind: "shell"; part: "header" | "footer"; element: Element }
  | { kind: "component"; componentId: string; element: Element }
  | { kind: "none" };

function asElement(target: EventTarget | null): Element | null {
  const node = target as (Partial<Element> & { parentElement?: Element | null }) | null;
  if (!node) return null;
  if (typeof node.closest === "function") return node as Element;
  return node.parentElement ?? null; // a text node
}

/**
 * What one click on the canvas means. Preview: a link switches page (the frame never navigates
 * itself — `preventDefault` — except to an in-page "#anchor"). Edit: a click on the header/footer
 * selects the shell, a click on a section reports it for the comment box, and no link is followed.
 */
export function clickIntent(target: EventTarget | null, mode: EditorMode): { action: ClickAction; preventDefault: boolean } {
  const element = asElement(target);
  if (!element) return { action: { kind: "none" }, preventDefault: false };
  const anchor = element.closest("a[href]");
  const href = anchor?.getAttribute("href") ?? null;
  const inPage = href !== null && href.startsWith("#");
  const preventDefault = anchor !== null && (mode === "edit" || !inPage);
  if (mode !== "edit") {
    return { action: href !== null && !inPage ? { href, kind: "navigate" } : { kind: "none" }, preventDefault };
  }
  const shell = element.closest(".brand-root > header, .brand-root > footer");
  if (shell) {
    return {
      action: { element: shell, kind: "shell", part: shell.tagName.toLowerCase() === "header" ? "header" : "footer" },
      preventDefault,
    };
  }
  const component = element.closest("[data-puck-component]");
  if (component) {
    return {
      action: { componentId: component.getAttribute("data-puck-component") ?? "", element: component, kind: "component" },
      preventDefault,
    };
  }
  return { action: { kind: "none" }, preventDefault };
}

/** The web bridge's geometry shape: the element's box in viewport and in document coordinates. */
export function rectOf(element: Element, scroll: { x: number; y: number }): SiteGeometry {
  const box = element.getBoundingClientRect();
  const viewport = {
    bottom: box.bottom,
    height: box.height,
    left: box.left,
    right: box.right,
    top: box.top,
    width: box.width,
    x: box.x,
    y: box.y,
  };
  return {
    document: {
      ...viewport,
      bottom: box.bottom + scroll.y,
      left: box.left + scroll.x,
      right: box.right + scroll.x,
      top: box.top + scroll.y,
      x: box.x + scroll.x,
      y: box.y + scroll.y,
    },
    viewport,
  };
}

// Site element inspector (plan 1). A styleable element carries data-clue-el (stamped by site-kit, or
// written by the agent in its own sections). Plan 1 selects TEXT elements: a keyed element that is not
// an image, video or button and holds no other keyed element. A key the schema refuses (it could not
// be addressed safely) is never selectable.

const KEYED = `[${ELEMENT_KEY_ATTR}]`;
const NOT_TEXT_TAGS = new Set(["img", "video", "picture", "svg", "button", "input", "select", "textarea"]);

function validKey(element: Element): string | null {
  const key = element.getAttribute(ELEMENT_KEY_ATTR);
  return key !== null && ElementKeySchema.safeParse(key).success ? key : null;
}

const BLOCK_SET = new Set(["div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "section", "article", "header", "footer", "figure", "blockquote", "table", "form", "nav", "aside", "main"]);

/** Words of its own: a non-blank text child (a copied section's text test, clone.ts). */
const ownWords = (element: Element) => [...element.childNodes].some((child) => child.nodeType === 3 && (child.nodeValue ?? "").trim() !== "");

function isTextElement(element: Element): boolean {
  if (validKey(element) === null) return false;
  if (NOT_TEXT_TAGS.has(element.tagName.toLowerCase()) || element.classList.contains("brand-btn")) return false;
  // A card is a box (plan 4 review I4), and so is a named element of unnamed blocks (an agent's
  // kit.Card around its own heading and paragraph); words of its own keep an element text.
  if (element.classList.contains("brand-card")) return false;
  if (element.querySelector(KEYED) !== null) return false;
  // Words being edited in place: Puck's editor puts its own blocks inside the text element.
  if (element.querySelector(IN_PLACE_EDITOR) !== null) return true;
  return ownWords(element) || ![...element.children].some((child) => BLOCK_SET.has(child.tagName.toLowerCase()));
}

/** Puck's in-place editors (its overlay portal, rich text's ProseMirror, a plain editable field). */
const IN_PLACE_EDITOR = "[data-puck-overlay-portal], .ProseMirror, [contenteditable]";

/** The scope's text elements in document order; a key repeated later in the scope is skipped (the
 * first element with a key owns it, as a section's `_edits` rule would style both). */
export function keyedElementsIn(scope: Element): Element[] {
  const seen = new Set<string>();
  return [...scope.querySelectorAll(KEYED)].filter((element) => {
    if (!isTextElement(element)) return false;
    const key = validKey(element)!;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** The element with this key inside the scope (plan 4: any keyed element, text, button, box or
 * image), or null: the first element carrying a valid key, as a section's `_edits` rule would style it. */
export function findKeyedElement(scope: Element, key: string): Element | null {
  return [...scope.querySelectorAll(KEYED)].find((element) => validKey(element) === key) ?? null;
}

/** The key of the element a click meant: the target's own text element or button when the click
 * reached it (an in-place field takes pointer events), else the smallest one whose box contains the
 * point (Puck turns pointer events off inside sections, so the target is the section itself). With a
 * `view`, buttons count too (plan 3), and a click on a button's words means the button. */
export function elementKeyAt(
  scope: Element,
  target: EventTarget | null,
  point: { x: number; y: number },
  view?: Pick<Window, "getComputedStyle">,
): string | null {
  // With a view (plan 4), boxes and images too; the section's own box never (ruling R1).
  const candidates = view ? inspectableElementsIn(scope, view).filter(({ hidden }) => !hidden).map(({ element }) => element) : keyedElementsIn(scope);
  const hit = asElement(target);
  const button = view && hit ? buttonAround(hit, view) : null;
  if (button && candidates.includes(button)) return validKey(button);
  // The innermost listed element holding the target.
  const holding = hit ? candidates.filter((element) => element.contains(hit)) : [];
  const direct = holding.find((element) => !holding.some((other) => other !== element && element.contains(other)));
  if (direct) return validKey(direct);
  let best: { element: Element; area: number } | null = null;
  for (const element of candidates) {
    const box = element.getBoundingClientRect();
    if (point.x < box.left || point.x > box.right || point.y < box.top || point.y > box.bottom) continue;
    const area = (box.right - box.left) * (box.bottom - box.top);
    // A tie goes to the later element: inner elements come after the box around them.
    if (!best || area <= best.area) best = { area, element };
  }
  return best ? validKey(best.element) : null;
}

/** What Layers shows for an element: its words, whitespace collapsed, cut at 60 characters. */
export function elementSummary(element: Element, kind: ElementSummary["kind"] = "text"): ElementSummary {
  const key = validKey(element) ?? "";
  const words = (element.textContent ?? "").replace(/\s+/g, " ").trim();
  const label = words.length > 60 ? `${words.slice(0, 59)}…` : words;
  return { key, kind, label: label || key };
}

/** "rgb(15, 89, 176)", "rgba(…)" or "#abc"/"#aabbcc" as #RRGGBB; null for anything else (an oklch
 * colour: the frame converts those through a canvas, see editor-app). */
export function cssColorToHex(value: string): string | null {
  const text = value.trim();
  const rgb = /^rgba?\(\s*(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)/i.exec(text);
  const channel = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, "0");
  if (rgb) return `#${channel(Number(rgb[1]))}${channel(Number(rgb[2]))}${channel(Number(rgb[3]))}`.toUpperCase();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text);
  if (!hex) return null;
  const digits = hex[1].length === 3 ? [...hex[1]].map((d) => d + d).join("") : hex[1];
  return `#${digits}`.toUpperCase();
}

const ALIGN: Record<string, ComputedTypography["textAlign"]> = {
  left: "left", start: "left", center: "center", "-webkit-center": "center", right: "right", end: "right", justify: "justify",
};

/** How the browser draws the element now. `toHex` turns any computed colour into #RRGGBB. */
export function computedTypography(
  element: Element,
  view: Pick<Window, "getComputedStyle">,
  toHex: (color: string) => string | null,
): ComputedTypography {
  const style = view.getComputedStyle(element);
  // Cut to the message's limit, so an odd family name can never get the whole selection dropped.
  const family = (style.fontFamily.split(",")[0] ?? "").trim().replace(/^["']|["']$/g, "").slice(0, 200);
  return {
    color: toHex(style.color) ?? "#000000",
    fontFamily: family,
    fontSize: Number.parseFloat(style.fontSize) || 0,
    fontWeight: Math.min(1000, Math.max(1, Number.parseInt(style.fontWeight, 10) || 400)),
    italic: style.fontStyle === "italic" || style.fontStyle.startsWith("oblique"),
    underline: style.textDecorationLine.includes("underline"),
    textAlign: ALIGN[style.textAlign] ?? "left",
  };
}

/** The element as the `selected` message carries it. */
export function elementSelection(
  element: Element,
  view: Pick<Window, "getComputedStyle">,
  toHex: (color: string) => string | null,
): ElementSelection {
  return { ...elementSummary(element), computed: computedTypography(element, view, toHex) };
}

// Plan 2: highlighted words. Offsets count characters as the browser's textContent does (a line break
// is none), which is how site-kit's rich.ts counts the stored text, so the app can find the same words.

/** The range's offsets and words inside the element, or null when the range is not inside it. */
export function selectionOffsets(element: Element, range: Range): { start: number; end: number; text: string } | null {
  if (!element.contains(range.startContainer) || !element.contains(range.endContainer)) return null;
  const doc = element.ownerDocument;
  const before = doc.createRange();
  before.selectNodeContents(element);
  before.setEnd(range.startContainer, range.startOffset);
  const start = before.toString().length;
  const text = range.toString();
  return { start, end: start + text.length, text };
}

/** A range over the element's characters [start, end), or null when they are not all there. */
export function rangeAt(element: Element, start: number, end: number): Range | null {
  const doc = element.ownerDocument;
  const walker = doc.createTreeWalker(element, 4 /* NodeFilter.SHOW_TEXT */);
  const range = doc.createRange();
  let at = 0;
  let started = false;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const length = node.nodeValue?.length ?? 0;
    if (!started && start <= at + length) {
      range.setStart(node, start - at);
      started = true;
    }
    if (started && end <= at + length) {
      range.setEnd(node, end - at);
      return range;
    }
    at += length;
  }
  return null;
}

/** How many words a reader sees in the text. */
export const wordCount = (text: string) => text.split(/\s+/).filter(Boolean).length;

/** The text element (data-clue-el, as keyedElementsIn counts them) a node sits in, or null. */
export function textElementAround(node: Node | null): Element | null {
  for (let element = asElement(node as EventTarget | null); element; element = element.parentElement) {
    if (isTextElement(element)) return element;
  }
  return null;
}

// Plan 3: buttons. Our own buttons (brand-btn) always are. In a copied section, a keyed link or
// button whose content is inline only (words and icons; no blocks, no images, at most one text) and,
// for a link, that the browser draws as a visible box: a background or a border. A text link inside
// a sentence stays text; a link holding a block is a card.

const PUCK_EDITOR = "[data-puck-overlay-portal]";
const COPIED_SECTION = "[data-lumen-fragment]";
const MEDIA_TAGS = "img,picture,video";
const BLOCK_TAGS = "div,p,h1,h2,h3,h4,h5,h6,ul,ol,li,section,article,header,footer,figure,blockquote,table,form,nav,aside,main";

const transparent = (color: string) => color === "" || color === "transparent" || /rgba\([^)]*,\s*0\s*\)$/.test(color);

export function isButtonElement(element: Element, view: Pick<Window, "getComputedStyle">): boolean {
  if (validKey(element) === null) return false;
  const tag = element.tagName.toLowerCase();
  if (tag !== "a" && tag !== "button" && !element.classList.contains("brand-btn")) return false;
  // Puck's in-place editor (its overlay portal) sits inside words being edited; it is not the page's.
  const own = (found: Element[]) => found.filter((inner) => !inner.closest(PUCK_EDITOR));
  if (own([...element.querySelectorAll(BLOCK_TAGS)]).length) return false;
  if (element.classList.contains("brand-btn")) return true;
  // Outside a copied section only our own buttons (brand-btn) are buttons: a menu, footer or card
  // link keeps its Link and Text rows whatever it looks like (review finding 2).
  if (!element.closest(COPIED_SECTION)) return false;
  // A copied link holding an image is a card; one holding two texts is two texts (ruling R2).
  if (own([...element.querySelectorAll(MEDIA_TAGS)]).length) return false;
  if (own([...element.querySelectorAll(KEYED)]).filter((inner) => isTextElement(inner)).length > 1) return false;
  if (tag === "button") return true;
  const style = view.getComputedStyle(element);
  // A box the visitor can see: a fill or a stroke. A link only laid out as a block (a menu link)
  // still reads as a link.
  return !transparent(style.backgroundColor) || Number.parseFloat(style.borderTopWidth) > 0;
}

/** The button a node sits in (or is), or null. */
export function buttonAround(node: Node | null, view: Pick<Window, "getComputedStyle">): Element | null {
  for (let element = asElement(node as EventTarget | null); element; element = element.parentElement) {
    if (isButtonElement(element, view)) return element;
  }
  return null;
}

/** A button's words: our `<key>.label`, else the first keyed text inside it, else the button itself. */
export function buttonLabelOf(button: Element): Element | null {
  const key = validKey(button);
  const named = key ? [...button.querySelectorAll(KEYED)].find((element) => validKey(element) === `${key}.label`) : undefined;
  if (named) return named;
  return [...button.querySelectorAll(KEYED)].find((element) => isTextElement(element)) ?? button;
}

export type InspectableElement = { element: Element; kind: ElementSummary["kind"]; parent: string | null; hidden?: true };

/** How many elements Layers lists for one section (the message's limit). */
export const MAX_LISTED = 500;

/** The scope's elements the inspector selects, in document order, each with its nearest listed
 * ancestor's key (Layers' tree, plan 4): buttons, text that is not a button's words, images and boxes.
 * The section's own box is left out (it is the section, ruling R1), and so are pass-through wrappers
 * (R10). A repeated key is skipped (the first owns it). `hiddenKeys`: the header's or footer's parts
 * hidden by hand, listed (hidden) though they have no box. */
export function inspectableElementsIn(
  scope: Element,
  view: Pick<Window, "getComputedStyle">,
  hiddenKeys: ReadonlySet<string> = new Set(),
): InspectableElement[] {
  const seen = new Set<string>();
  const found: { element: Element; kind: ElementSummary["kind"]; hidden?: true }[] = [];
  const buttons: Element[] = [];
  const box = sectionBoxOf(scope, view);
  const own = box ? new Set([box.outer, box.inner]) : new Set<Element>();
  const all = [...(scope.matches(KEYED) ? [scope] : []), ...scope.querySelectorAll(KEYED)];
  for (const element of all) {
    if (found.length >= MAX_LISTED) break;
    const key = validKey(element);
    if (key === null || seen.has(key) || own.has(element)) continue;
    if (buttons.some((button) => button.contains(element))) continue;
    if (hiddenKeys.has(key)) {
      seen.add(key);
      found.push({ element, hidden: true, kind: isImageElement(element) ? "image" : isTextElement(element) && visibleWords(element) ? "text" : "container" });
    } else if (isButtonElement(element, view)) {
      seen.add(key);
      buttons.push(element);
      found.push({ element, kind: "button" });
    } else if (isImageElement(element)) {
      if (!hasBox(element)) continue;
      seen.add(key);
      found.push({ element, kind: "image" });
    } else if (isTextElement(element) && visibleWords(element)) {
      // An empty element (a copied button's overlay link) has nothing to show or style.
      seen.add(key);
      found.push({ element, kind: "text" });
    } else if (isContainerElement(element, view)) {
      seen.add(key);
      found.push({ element, kind: "container" });
    }
  }
  const listed = new Map(found.map((item) => [item.element, validKey(item.element)!]));
  return found.map((item) => {
    let parent: string | null = null;
    for (let up = item.element.parentElement; up && scope.contains(up); up = up.parentElement) {
      const key = listed.get(up);
      if (key !== undefined) {
        parent = key;
        break;
      }
      if (up === scope) break;
    }
    return { ...item, parent };
  });
}

/** One listed element as Layers shows it (plan 4): a box by its name (ruling R7), an image by its alt
 * text or its key in words ("accountLogo" → "Account logo"), text and buttons by their words; with its
 * parent and, for a hidden part, hidden. */
export function listedSummary(item: InspectableElement, view: Pick<Window, "getComputedStyle">): ElementSummary {
  const base = elementSummary(item.element, item.kind);
  const key = base.key;
  let label = base.label;
  if (item.kind === "container") label = containerName(item.element, view);
  if (item.kind === "image") {
    const alt = (item.element.getAttribute("alt") ?? "").trim();
    const words = /^[A-Za-z]+$/.test(key) ? key.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase() : "";
    label = (alt || (words ? words[0].toUpperCase() + words.slice(1) : "Image")).slice(0, 80);
  }
  return { ...base, label, parent: item.parent, ...(item.hidden ? { hidden: true as const } : {}) };
}

// Plan 4: boxes and images. A box is any keyed element drawn with a box of its own that is not text,
// a button or an image; the section's own box is `root` / `root.inner` (ours, the agent's kit.Shell,
// the shell) or a copied section's one top element.

const IMAGE_TAGS = new Set(["img", "picture", "video", "svg"]);
const NO_WORDS = new Set(["script", "style", "noscript", "template"]);

/** A keyed image or icon. */
export function isImageElement(element: Element): boolean {
  return validKey(element) !== null && IMAGE_TAGS.has(element.tagName.toLowerCase());
}

function hasBox(element: Element): boolean {
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

/** Whether the element holds words a visitor reads (not a script's or a style's). */
function visibleWords(element: Element): boolean {
  const walk = (node: Element): boolean =>
    [...node.childNodes].some((child) =>
      child.nodeType === 3
        ? (child.nodeValue ?? "").trim() !== ""
        : child.nodeType === 1 && !NO_WORDS.has((child as Element).tagName.toLowerCase()) && walk(child as Element),
    );
  return walk(element);
}

const visible = (style: CSSStyleDeclaration) => !transparent(style.backgroundColor) || (Number.parseFloat(style.borderTopWidth) || 0) > 0;

/** A copied wrapper that adds nothing (ruling R10): one element child, no words of its own, no fill
 * or stroke, and the same drawn box as its child (within 1px). */
function isPassThrough(element: Element, view: Pick<Window, "getComputedStyle">): boolean {
  const children = [...element.children].filter((child) => !NO_WORDS.has(child.tagName.toLowerCase()));
  if (children.length !== 1) return false;
  if ([...element.childNodes].some((child) => child.nodeType === 3 && (child.nodeValue ?? "").trim() !== "")) return false;
  if (visible(view.getComputedStyle(element))) return false;
  const a = element.getBoundingClientRect();
  const b = children[0].getBoundingClientRect();
  return Math.abs(a.left - b.left) <= 1 && Math.abs(a.top - b.top) <= 1 && Math.abs(a.right - b.right) <= 1 && Math.abs(a.bottom - b.bottom) <= 1;
}

/** A box the inspector selects (plan 4). */
export function isContainerElement(element: Element, view: Pick<Window, "getComputedStyle">): boolean {
  if (validKey(element) === null || isImageElement(element) || isButtonElement(element, view)) return false;
  if (isTextElement(element) && visibleWords(element)) return false;
  const style = view.getComputedStyle(element);
  if (style.display === "inline" || style.display === "contents" || style.display === "none") return false;
  // An empty overlay or decoration (a copied button's overlay link, a background layer) draws nothing
  // a marketer could style unless it has a fill or a stroke (review I3).
  const empty = ![...element.children].some((child) => !NO_WORDS.has(child.tagName.toLowerCase())) && !visibleWords(element);
  if (empty && !visible(style)) return false;
  return hasBox(element) && !isPassThrough(element, view);
}

/** How the box lays out its contents (ruling R3): a row, a stack, a grid, or flowing text. */
function layoutOf(style: CSSStyleDeclaration): ComputedContainer["layout"] {
  if (style.display === "flex" || style.display === "inline-flex") return style.flexDirection.startsWith("column") ? "stack" : "row";
  if (style.display === "grid" || style.display === "inline-grid") return "grid";
  return "text";
}

const LINE_UP: Record<string, ComputedContainer["contentAlign"]> = {
  center: "center", "flex-end": "end", end: "end", right: "end", "-webkit-right": "end", "-webkit-center": "center",
};

/** What the panel calls the box (ruling R7). */
export function containerName(element: Element, view: Pick<Window, "getComputedStyle">): string {
  const tag = element.tagName.toLowerCase();
  if (tag === "nav") return "Menu";
  if (tag === "li") return "List item";
  if (tag === "ul" || tag === "ol") return "List";
  if (element.classList.contains("brand-card") || /^stats\.\d+$/.test(validKey(element) ?? "")) return "Card";
  const style = view.getComputedStyle(element);
  if (visible(style) && cornersOf(style).some((corner) => (Number.parseFloat(corner) || 0) > 0)) return "Card";
  const layout = layoutOf(style);
  return layout === "row" ? "Row" : layout === "stack" ? "Column" : layout === "grid" ? "Grid" : "Box";
}

/** A box as the browser draws it: plan 3's box, its gap, layout, how its contents line up, its name. */
export function computedContainer(element: Element, view: Pick<Window, "getComputedStyle">, toHex: (color: string) => string | null): ComputedContainer {
  const style = view.getComputedStyle(element);
  const layout = layoutOf(style);
  const lineUp = layout === "row" ? style.justifyContent : layout === "stack" ? style.alignItems : layout === "grid" ? style.justifyItems : style.textAlign;
  const gap = Number.parseFloat(style.columnGap || style.getPropertyValue("gap")) || 0;
  return {
    ...computedBox(element, view, toHex),
    gap: Math.min(10_000, Math.max(0, gap)),
    layout,
    contentAlign: LINE_UP[lineUp] ?? "start",
    name: containerName(element, view),
    alignRoom: alignRoomOf(element, style, layout, gap),
  };
}

/** Whether the box has room to line its contents up across it (review I5): a row whose children and
 * gaps fill it has none, nor a stack whose children are all as wide as it, nor a box drawn as wide as
 * its contents. A grid's cells are not read, so a grid counts as having room. */
function alignRoomOf(element: Element, style: CSSStyleDeclaration, layout: ComputedContainer["layout"], gap: number): boolean {
  if (layout === "grid") return true;
  if (layout === "text") return !style.display.startsWith("inline");
  const rect = element.getBoundingClientRect();
  const inner = rect.width - (Number.parseFloat(style.paddingLeft) || 0) - (Number.parseFloat(style.paddingRight) || 0);
  const children = [...element.children].map((child) => child.getBoundingClientRect().width).filter((width) => width > 0);
  if (!children.length) return false;
  if (layout === "stack") return children.some((width) => width < inner - 1);
  return inner - (children.reduce((sum, width) => sum + width, 0) + gap * (children.length - 1)) > 1;
}

/** The section's own box (ruling R2): `root` and its `root.inner` (ours, an agent's kit.Shell, the
 * header and footer, whose scope element is the box itself), or a copied section's one top element.
 * Null when the section has none (an agent section that draws no kit.Shell, a copied section with
 * several top elements). */
export function sectionBoxOf(scope: Element, view?: Pick<Window, "getComputedStyle">): { outer: Element; inner: Element } | null {
  const outer = validKey(scope) === ROOT_KEY ? scope : [...scope.querySelectorAll(KEYED)].find((element) => validKey(element) === ROOT_KEY);
  if (outer) {
    const inner = [...outer.querySelectorAll(KEYED)].find((element) => validKey(element) === ROOT_INNER_KEY) ?? outer;
    return { inner, outer };
  }
  const fragment = scope.querySelector(COPIED_SECTION);
  const tops = fragment ? [...fragment.children].filter((child) => validKey(child) !== null) : [];
  if (tops.length !== 1) return null;
  // Captured sections sit in display:contents wrappers (ingestion's ls-h / ls-b, review C1): the box is
  // the first element under them that draws one.
  let top = tops[0];
  while (view && view.getComputedStyle(top).display === "contents") {
    const inside = [...top.children].filter((child) => validKey(child) !== null);
    if (inside.length !== 1) return null;
    top = inside[0];
  }
  return { inner: top, outer: top };
}

/** Where the element moves among its neighbours (spec §4.8): the element (or a wrapper that only
 * holds it: unkeyed, or keyed and drawn as the same box, such as the header's button area) among its
 * keyed parent's keyed children, in their order. Null when that is no keyed element with a neighbour
 * inside the section, or when it is the section's own box. */
export function arrangeOf(element: Element, scope: Element): Arrange | null {
  let item = element;
  for (;;) {
    const parent = item.parentElement;
    if (!parent || item === scope || !scope.contains(parent)) return null;
    const parentKey = validKey(parent);
    if (parentKey === null && parent !== scope) {
      item = parent;
      continue;
    }
    const siblings = [...parent.children].flatMap((child) => {
      const key = validKey(child);
      return key !== null && !key.includes("~") ? [key] : [];
    });
    const itemKey = validKey(item);
    if (siblings.length >= 2) {
      if (itemKey === null || parentKey === null || itemKey === ROOT_KEY || itemKey === ROOT_INNER_KEY || siblings.length > 200) return null;
      return { item: itemKey, parent: parentKey, siblings };
    }
    if (parent === scope || parentKey === ROOT_KEY || parentKey === ROOT_INNER_KEY || !sameBox(parent, item)) return null;
    item = parent;
  }
}

function sameBox(a: Element, b: Element): boolean {
  const x = a.getBoundingClientRect();
  const y = b.getBoundingClientRect();
  return Math.abs(x.left - y.left) <= 1 && Math.abs(x.top - y.top) <= 1 && Math.abs(x.right - y.right) <= 1 && Math.abs(x.bottom - y.bottom) <= 1;
}

/** The four corner radii; from the shorthand when the browser gives no longhands. */
function cornersOf(style: CSSStyleDeclaration): string[] {
  const longhands = [style.borderTopLeftRadius, style.borderTopRightRadius, style.borderBottomRightRadius, style.borderBottomLeftRadius];
  const zero = (value: string) => !value || Number.parseFloat(value) === 0;
  if (!longhands.every(zero) || zero(style.borderRadius)) return longhands;
  const values = (style.borderRadius || "0").split("/")[0].trim().split(/\s+/);
  const [a, b = a, c = a, d = b] = values;
  return [a, b, c, d];
}

/** A button's box as the browser draws it. */
export function computedBox(element: Element, view: Pick<Window, "getComputedStyle">, toHex: (color: string) => string | null): ComputedBox {
  const style = view.getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  const round = (value: number) => Math.round(value * 10) / 10;
  // Every number held within the message's limits, so a seller's odd value (9999em corners) never
  // makes the whole selection invalid (review finding 6).
  const px = (value: string, max = 10_000) => Math.min(max, Math.max(0, Number.parseFloat(value) || 0));
  // A percentage corner is a share of the box (of its shorter side, which is what draws a pill).
  const corner = (value: string) =>
    value.trim().endsWith("%") ? round((Math.min(rect.width, rect.height) * px(value, 100)) / 100) : px(value, 100_000);
  const colour = (value: string) => (transparent(value) ? "" : (toHex(value) ?? ""));
  return {
    fill: colour(style.backgroundColor),
    fillOpacity: transparent(style.backgroundColor) ? 0 : Math.round(alphaOf(style.backgroundColor) * 100),
    borderColor: px(style.borderTopWidth) > 0 ? colour(style.borderTopColor) : "",
    borderWidth: px(style.borderTopWidth),
    radius: cornersOf(style).map(corner),
    paddingY: px(style.paddingTop),
    paddingX: px(style.paddingLeft),
    width: Math.min(100_000, round(rect.width)),
    height: Math.min(100_000, round(rect.height)),
  };
}

/** A CSS colour's alpha, 0 to 1 ("rgba(…, 0.5)", "rgb(… / 50%)"); 1 when it has none. */
function alphaOf(color: string): number {
  const match = /^rgba?\((.*)\)$/.exec(color.trim());
  if (!match) return 1;
  const parts = match[1].split(/[\s,/]+/).filter(Boolean);
  if (parts.length < 4) return 1;
  const alpha = parts[3].endsWith("%") ? Number.parseFloat(parts[3]) / 100 : Number.parseFloat(parts[3]);
  return Number.isFinite(alpha) ? Math.min(1, Math.max(0, alpha)) : 1;
}

/** Responsive brand type (review finding 3): the brand's size scale where `element` is drawn now,
 * read from its inherited `--brand-text-*` (site-kit's sizeScaleFrom decides the rest). */
export function sizeScaleAt(element: Element, brand: BrandData, view: Pick<Window, "getComputedStyle">): ComputedTypography["sizeScale"] | null {
  const style = view.getComputedStyle(element);
  return sizeScaleFrom(brand, (role) => Number.parseFloat(style.getPropertyValue(`--brand-text-${role}`)));
}
