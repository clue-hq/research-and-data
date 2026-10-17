import { ELEMENT_KEY_ATTR, ElementKeySchema } from "@clue/site-kit/edits";
import type { ComputedTypography, EditorMode, ElementSelection, ElementSummary, SiteGeometry } from "@clue/site-kit/editor-protocol";

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

function isTextElement(element: Element): boolean {
  if (validKey(element) === null) return false;
  if (NOT_TEXT_TAGS.has(element.tagName.toLowerCase()) || element.classList.contains("brand-btn")) return false;
  return element.querySelector(KEYED) === null;
}

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

/** The text element with this key inside the scope, or null. */
export function findKeyedElement(scope: Element, key: string): Element | null {
  return keyedElementsIn(scope).find((element) => validKey(element) === key) ?? null;
}

/** The key of the text element a click meant: the target's own text element when the click reached
 * it (an in-place field takes pointer events), else the smallest text element whose box contains the
 * point (Puck turns pointer events off inside sections, so the target is the section itself). */
export function elementKeyAt(scope: Element, target: EventTarget | null, point: { x: number; y: number }): string | null {
  const texts = keyedElementsIn(scope);
  const hit = asElement(target);
  const direct = hit ? texts.find((element) => element.contains(hit)) : undefined;
  if (direct) return validKey(direct);
  let best: { element: Element; area: number } | null = null;
  for (const element of texts) {
    const box = element.getBoundingClientRect();
    if (point.x < box.left || point.x > box.right || point.y < box.top || point.y > box.bottom) continue;
    const area = (box.right - box.left) * (box.bottom - box.top);
    if (!best || area < best.area) best = { area, element };
  }
  return best ? validKey(best.element) : null;
}

/** What Layers shows for an element: its words, whitespace collapsed, cut at 60 characters. */
export function elementSummary(element: Element): ElementSummary {
  const key = validKey(element) ?? "";
  const words = (element.textContent ?? "").replace(/\s+/g, " ").trim();
  const label = words.length > 60 ? `${words.slice(0, 59)}…` : words;
  return { key, kind: "text", label: label || key };
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
