// Fill a stored clone's slots the way the engine does (crates/lumen-web/src/fragment.rs,
// substitute_fragment_slots), then apply exact text replacements for text that has no slot
// (the engine's apply_fragment_text_overrides plays this role for human overrides).
//
// Slot kinds: text replaces the element's content with plain text; href sets the element's
// href; image sets the element's src; visibility removes the element when false. Captured links
// the page does not change are made absolute against the clone's source page.
// Runs on the server (published pages) and in the browser (editor), so it uses an isomorphic
// parser rather than the DOM.
//
// Every text element is keyed for the site inspector (data-clue-el, edits.ts ELEMENT_KEY_ATTR) by its
// place in the CAPTURED markup, before any slot is applied, so hiding or filling a slot never moves
// another element's key and a section's `_edits` keep pointing at the same text.
import { parse, TextNode, type HTMLElement } from "node-html-parser";
import { ELEMENT_KEY_ATTR } from "./edits";
import { richHtml } from "./rich";

export type SlotKind = "text" | "href" | "image" | "visibility";
export type CloneSlot = { kind: SlotKind; fallback: unknown };
export type Clone = {
  id: string;
  role: string;
  label: string;
  page_url: string;
  section_index: number | null;
  wrapper_class: string;
  html: string;
  css: string;
  slots: Record<string, CloneSlot>;
  /** The registry's sentence when this captured section is marked broken (degraded); absent otherwise. */
  degraded_note?: string | null;
  /** false: a section the page already uses that the catalog no longer offers (superseded by a
   * repair, or retired). It still draws, validates and publishes; the agent is not offered it anew. */
  in_catalog?: boolean;
  /** What the capture made for this section's videos, by the video's digest: a poster (JPEG) and a
   * smaller rendition (MP4), each a digest; either may be null. Kept beside the fragment. */
  videos?: Record<string, { poster?: string | null; rendition?: string | null }>;
};

const STORE_FILE = /^\/asset-store\/([0-9a-f]{64})$/;

export type SlotValues = Record<string, string | boolean | undefined>;
export type TextReplacement = { find: string; replace: string };
export type LinkReplacement = { find: string; replace: string };

/** What a section adds beside its slots and replacements: the links that open in a new tab, by element
 * key (plan 2). `id` is the section's (CloneHtml passes it; the filler itself does not need it). */
export type CloneExtras = {
  id?: string;
  newTab?: readonly string[];
  /** Plan 4: the order of a box's children, by the box's key (the section's `_edits` orders). */
  order?: Readonly<Record<string, readonly string[]>>;
  /** Plan 5: alt texts of the section's images, by element key. */
  alts?: Readonly<Record<string, string>>;
};

export function fillClone(
  clone: Clone,
  values: SlotValues = {},
  replacements: TextReplacement[] = [],
  links: LinkReplacement[] = [],
  extras: CloneExtras = {},
): string {
  const root = parse(clone.html, { comment: false });
  keyElements(root, clone.slots);
  // Keyed first, then moved: a moved element keeps the key of its captured place (spec §4.8).
  applyOrder(root, extras.order ?? {});
  const linksWeSet = new Set<HTMLElement>();

  for (const [key, slot] of Object.entries(clone.slots)) {
    const value = values[key];
    if (value === undefined || value === "") continue;
    // An unchanged slot keeps the captured markup exactly (its fallback is plain text, so
    // re-applying it would drop line breaks and inline markup).
    if (slot.kind !== "visibility" && String(value) === String(slot.fallback ?? "")) continue;
    if (slot.kind === "visibility" && (value === true || value === "true")) continue;
    const elements = root.querySelectorAll(`[data-lumen-slot="${key}"]`);
    for (const element of elements) {
      applySlot(element, slot.kind, value);
      if (slot.kind === "href") linksWeSet.add(element);
      // Links written in a text slot's rich text are this site's links, not the seller's.
      if (slot.kind === "text") for (const anchor of element.querySelectorAll("a[href]")) linksWeSet.add(anchor);
    }
  }

  // Videos load only their metadata until they play. A video without its own poster shows the one
  // the capture made, and plays the smaller rendition when there is one (the original stays stored).
  for (const video of root.querySelectorAll("video")) {
    video.setAttribute("preload", "metadata");
    if (video.getAttribute("poster")) continue;
    const named = video.getAttribute("src") ? video : video.querySelector("source[src]");
    const digest = STORE_FILE.exec(named?.getAttribute("src") ?? "")?.[1];
    const made = digest ? clone.videos?.[digest] : undefined;
    if (made?.poster) video.setAttribute("poster", `/asset-store/${made.poster}`);
    if (named && made?.rendition) {
      named.setAttribute("src", `/asset-store/${made.rendition}`);
      if (named !== video && named.getAttribute("type")) named.setAttribute("type", "video/mp4");
    }
  }

  const wanted = replacements.filter((r) => r.find && r.find !== r.replace);
  if (wanted.length) replaceText(root, wanted, clone.slots);

  // Links with no href slot (for example audience cards that point at the seller's own pages):
  // an exact href match is pointed somewhere else; "*" re-points every link in the section.
  for (const link of links.filter((l) => l.find && l.replace)) {
    for (const anchor of root.querySelectorAll("a[href]")) {
      if (link.find === "*" || anchor.getAttribute("href") === link.find) {
        anchor.setAttribute("href", link.replace);
        linksWeSet.add(anchor);
      }
    }
  }

  // Plan 5: alt texts by element key, on images only. The parser escapes only quotes in an attribute,
  // so &, < and > are escaped here: alt text is text, never markup.
  for (const [key, alt] of Object.entries(extras.alts ?? {})) {
    const image = byKey(root, key);
    // A raw backslash is dropped by the parser (review M1), so it is written as its reference too.
    if (image?.tagName === "IMG") {
      image.setAttribute("alt", alt.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\\/g, "&#92;"));
    }
  }

  // Links that open in a new tab, named by element key: the key is on the link, or on the text inside it.
  for (const key of extras.newTab ?? []) {
    const element = root.querySelector(`[${ELEMENT_KEY_ATTR}="${key.replace(/["\\]/g, "")}"]`);
    const anchor = element?.tagName === "A" ? element : (element?.closest("a") as HTMLElement | null);
    if (!anchor) continue;
    anchor.setAttribute("target", "_blank");
    anchor.setAttribute("rel", "noopener");
  }

  // Every other link keeps going where it went on the seller's site: a captured "/book-a-demo"
  // is the seller's page, not a page of this site.
  for (const anchor of root.querySelectorAll("a[href]")) {
    const href = anchor.getAttribute("href") ?? "";
    if (linksWeSet.has(anchor) || !href.startsWith("/") || href.startsWith("//")) continue;
    if (href.startsWith("/asset-store/") || href.startsWith("/brands/")) continue;
    try {
      anchor.setAttribute("href", new URL(href, clone.page_url).toString());
    } catch {
      /* a page_url that is not a URL leaves the link as captured */
    }
  }

  return root.toString();
}

/** Elements whose text is never the page's words. */
const NOT_TEXT = new Set(["script", "style", "svg", "noscript", "template"]);
/** Elements that are never keyed (plan 4): not part of what a visitor sees. */
const NEVER_KEYED = new Set(["script", "style", "noscript", "template"]);
/** Elements keyed as a whole and never walked into (plan 4): images and icons. A <picture> is walked
 * into (plan 5, ruling R4): its <img> is the image. */
const WHOLE = new Set(["svg", "img", "video"]);

/** Tags that make an element a block (a link holding one is a card, not a button). */
const BLOCKS = new Set([
  "div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "section", "article", "header",
  "footer", "figure", "blockquote", "table", "form", "nav", "aside", "main",
]);

/** Whether an element is a text element: a text slot, or an element with words of its own. */
const textTest = (slots: Record<string, CloneSlot>) => (element: HTMLElement) => {
  const slot = element.getAttribute("data-lumen-slot");
  if (slot && slots[slot]?.kind === "text") return true;
  return element.childNodes.some((child) => child instanceof TextNode && child.rawText.trim() !== "");
};

/** Media that make a link a card, not a button (ruling R2). */
const MEDIA = new Set(["img", "picture", "video"]);

/** A link or button whose content is inline only (words and icons: no blocks, no images) with at most
 * one text inside: a button candidate (plan 3; the frame calls it a button when the browser draws it
 * as a box). A control with two texts is not one button: each text stays its own element. */
function isInlineControl(element: HTMLElement, isText: (element: HTMLElement) => boolean): boolean {
  const tag = element.tagName.toLowerCase();
  if (tag !== "a" && tag !== "button") return false;
  const inside = element.querySelectorAll("*");
  if (inside.some((child) => BLOCKS.has(child.tagName.toLowerCase()) || MEDIA.has(child.tagName.toLowerCase()))) return false;
  const texts = inside.filter((child) => isText(child) && !child.closest("svg"));
  // Count only the outermost texts: a text's inline children are part of it.
  return texts.filter((text) => !texts.some((other) => other !== text && other.querySelectorAll("*").includes(text))).length <= 1;
}

/** Key every element by its child-index path from the fragment root ("0.2.1", element children
 * only). A text element holds words of its own (a non-blank text child), or is a text slot (whose
 * words may sit in inline tags, and which the slot's fill replaces whole): inside it nothing more is
 * keyed, its inline children are part of its one text box. A link or button with inline-only content
 * is keyed and walked into, so its words keep their own key (plan 3). Every other element is a box
 * (plan 4), keyed and walked into; images and icons are keyed whole; scripts, styles, noscripts and
 * templates never. The paths count every element child, so keying more elements never moves a key. */
function keyElements(root: HTMLElement, slots: Record<string, CloneSlot>): void {
  const isText = textTest(slots);
  const walk = (node: HTMLElement, path: string) => {
    let index = 0;
    for (const child of node.childNodes) {
      if (child instanceof TextNode || !(child as HTMLElement).tagName) continue;
      const element = child as HTMLElement;
      const place = path ? `${path}.${index}` : String(index);
      index += 1;
      const tag = element.tagName.toLowerCase();
      if (NEVER_KEYED.has(tag)) continue;
      element.setAttribute(ELEMENT_KEY_ATTR, place);
      if (WHOLE.has(tag) || isText(element)) continue;
      walk(element, place);
    }
  };
  walk(root, "");
}

/** An element's keyed element children, in their order. */
const keyedChildren = (element: HTMLElement): HTMLElement[] =>
  element.childNodes.filter((child): child is HTMLElement => !(child instanceof TextNode) && Boolean((child as HTMLElement).getAttribute?.(ELEMENT_KEY_ATTR)));

const byKey = (root: HTMLElement, key: string): HTMLElement | undefined =>
  root.querySelectorAll(`[${ELEMENT_KEY_ATTR}]`).find((element) => element.getAttribute(ELEMENT_KEY_ATTR) === key);

/** Each box's children in its order: the children it names go into the places those children hold,
 * in its order; a key that is not a child is ignored, and children it does not name keep their places. */
function applyOrder(root: HTMLElement, order: Readonly<Record<string, readonly string[]>>): void {
  for (const [parentKey, keys] of Object.entries(order)) {
    const parent = byKey(root, parentKey);
    if (!parent) continue;
    const children = keyedChildren(parent);
    const listed = children
      .filter((child) => keys.includes(child.getAttribute(ELEMENT_KEY_ATTR)!))
      .sort((a, b) => keys.indexOf(a.getAttribute(ELEMENT_KEY_ATTR)!) - keys.indexOf(b.getAttribute(ELEMENT_KEY_ATTR)!));
    if (listed.length < 2) continue;
    // Placeholders keep each listed child's place while the children are swapped.
    const spots = children.filter((child) => listed.includes(child)).map((child) => {
      const spot = parse("<i></i>").firstChild as HTMLElement;
      child.replaceWith(spot);
      return spot;
    });
    spots.forEach((spot, index) => spot.replaceWith(listed[index]));
  }
}

/** A copied image found by its element key in the captured markup (plan 5): the image slot that fills
 * it (on the <img> or its <picture>), how many images that slot fills, and its captured alt text.
 * Null when the key is no <img> or <video>. */
export function cloneImageAt(clone: Clone, key: string): { slot: string | null; uses: number; alt: string } | null {
  const root = parse(clone.html, { comment: false });
  keyElements(root, clone.slots);
  const image = byKey(root, key);
  const tag = image?.tagName.toLowerCase();
  if (!image || (tag !== "img" && tag !== "video")) return null;
  const parent = image.parentNode as HTMLElement | null;
  const named = [image.getAttribute("data-lumen-slot"), parent?.tagName === "PICTURE" ? parent.getAttribute("data-lumen-slot") : undefined].find(
    (slot): slot is string => Boolean(slot) && clone.slots[slot as string]?.kind === "image",
  );
  const uses = named ? root.querySelectorAll(`[data-lumen-slot="${named.replace(/["\\]/g, "")}"]`).length : 1;
  return { alt: image.getAttribute("alt") ?? "", slot: named ?? null, uses };
}

/** A box's keyed children in their captured order, or null when the key is no element (plan 4). */
export function cloneOrderOf(clone: Clone, parentKey: string): string[] | null {
  const root = parse(clone.html, { comment: false });
  keyElements(root, clone.slots);
  const parent = byKey(root, parentKey);
  return parent ? keyedChildren(parent).map((child) => child.getAttribute(ELEMENT_KEY_ATTR)!) : null;
}

function applySlot(element: HTMLElement, kind: SlotKind, value: string | boolean): void {
  if (kind === "text") {
    // Rich text (plan 2): the grammar's markup, drawn as the published page draws it. A slot's links
    // were resolved under the site's base path by the caller (config's mapRichLinks).
    element.set_content(richHtml(String(value), (href) => href));
  } else if (kind === "href") {
    element.setAttribute("href", String(value));
  } else if (kind === "image") {
    element.setAttribute("src", String(value));
    element.removeAttribute("srcset");
    // A <picture>'s sources would be chosen over the new image (plan 5, review focus 1).
    const picture = element.parentNode as HTMLElement | null;
    if (picture?.tagName === "PICTURE") for (const source of picture.querySelectorAll("source")) source.remove();
  } else if (kind === "visibility" && (value === false || value === "false")) {
    element.remove();
  }
}

/** A text node's words as a visitor reads them: entities decoded, whitespace collapsed, trimmed. */
const shownText = (node: TextNode) => node.text.replace(/\s+/g, " ").trim();
const collapse = (text: string) => text.replace(/\s+/g, " ").trim();

/** Exact text replacements: a text node whose words (decoded, collapsed) equal `find` (collapsed) gets
 * `replace` as text, keeping the node's own leading and trailing whitespace. Review finding S1-3: this
 * reading is `replaceableTexts`', so whatever the catalog lists and the check accepts is applied. */
function replaceText(root: HTMLElement, replacements: TextReplacement[], slots: Record<string, CloneSlot>): void {
  const walk = (node: HTMLElement) => {
    for (const child of node.childNodes) {
      if (child instanceof TextNode) {
        const words = shownText(child);
        const match = words ? replacements.find((r) => collapse(r.find) === words) : undefined;
        if (match) {
          const raw = child.rawText;
          const lead = /^\s*/.exec(raw)?.[0] ?? "";
          const trail = /\s*$/.exec(raw)?.[0] ?? "";
          child.rawText = `${lead}${escapeText(match.replace)}${trail}`;
        }
      } else {
        // Only the text replaceableTexts offers: never inside a text slot, a script, a style or an svg.
        const element = child as HTMLElement;
        if (!element.tagName || NOT_TEXT.has(element.tagName.toLowerCase())) continue;
        const slot = element.getAttribute("data-lumen-slot");
        if (slot && slots[slot]?.kind === "text") continue;
        walk(element);
      }
    }
  };
  walk(root);
}

/** Webflow's unrendered "{{wf …}}" placeholders are not words a visitor sees. */
const SKIP_TEXT = /^\{\{wf/;

/** The clone's text a `replacements` entry can change: each text node outside a text slot (a slot is
 * changed through `slots`) and outside script, style and svg, as a visitor reads it (decoded,
 * collapsed), once each, in document order. The one reading the catalog lists, the check accepts and
 * the renderer applies (review finding S1-3): a phrase that wraps a line break, spans bold text or is
 * part of a sentence is not one text node, so it is not offered and not accepted. */
/** How many texts in the markup read exactly `words`. */
function textsReading(root: HTMLElement, words: string): number {
  let count = 0;
  const walk = (node: HTMLElement) => {
    for (const child of node.childNodes) {
      if (child instanceof TextNode) {
        if (shownText(child) === words) count += 1;
      } else if ((child as HTMLElement).tagName && !NOT_TEXT.has((child as HTMLElement).tagName.toLowerCase())) {
        walk(child as HTMLElement);
      }
    }
  };
  walk(root);
  return count;
}

export function replaceableTexts(clone: Clone): string[] {
  const root = parse(clone.html, { comment: false });
  const found: string[] = [];
  const walk = (node: HTMLElement) => {
    for (const child of node.childNodes) {
      if (child instanceof TextNode) {
        const words = shownText(child);
        if (words && !SKIP_TEXT.test(words) && !found.includes(words)) found.push(words);
        continue;
      }
      const element = child as HTMLElement;
      if (!element.tagName || NOT_TEXT.has(element.tagName.toLowerCase())) continue;
      const slot = element.getAttribute("data-lumen-slot");
      if (slot && clone.slots[slot]?.kind === "text") continue;
      walk(element);
    }
  };
  walk(root);
  return found;
}

function escapeText(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** The clone's original wording for each slot, used to pre-fill the editor's fields. */
export function slotDefaults(clone: Clone): SlotValues {
  return Object.fromEntries(
    Object.entries(clone.slots).map(([key, slot]) => [
      key,
      slot.kind === "visibility" ? slot.fallback !== false : String(slot.fallback ?? ""),
    ]),
  );
}

/** The link a clone's element is or sits in, found by its element key in the captured markup: its
 * captured address, its href slot (if it has one), and whether another link in the section has the
 * same address (a link replacement then changes both). Null when the element is no link (plan 2). */
export function cloneLinkAt(clone: Clone, key: string): { href: string; slot: string | null; shared: boolean } | null {
  const root = parse(clone.html, { comment: false });
  keyElements(root, clone.slots);
  const element = root.querySelectorAll(`[${ELEMENT_KEY_ATTR}]`).find((candidate) => candidate.getAttribute(ELEMENT_KEY_ATTR) === key);
  if (!element) return null;
  const anchor = element.tagName === "A" ? element : (element.closest("a") as HTMLElement | null);
  const href = anchor?.getAttribute("href");
  if (!anchor || !href) return null;
  const slot = anchor.getAttribute("data-lumen-slot");
  return {
    href,
    slot: slot && clone.slots[slot]?.kind === "href" ? slot : null,
    shared: root.querySelectorAll("a[href]").filter((other) => other.getAttribute("href") === href).length > 1,
  };
}

/** The clone's text slots whose words sit inside a link or button (or are one): their rich text may
 * not hold a link (plan 3). */
export function slotsInsideLinks(clone: Clone): Set<string> {
  const root = parse(clone.html, { comment: false });
  const inside = new Set<string>();
  for (const element of root.querySelectorAll("[data-lumen-slot]")) {
    const slot = element.getAttribute("data-lumen-slot") ?? "";
    if (clone.slots[slot]?.kind !== "text") continue;
    const tag = element.tagName.toLowerCase();
    if (tag === "a" || tag === "button" || element.closest("a, button")) inside.add(slot);
  }
  return inside;
}

/** A clone's button, found by its element key in the captured markup (plan 3): the key of its words
 * (the button itself when the words are its own), the text slot that holds them, the words as one
 * replaceable text (null when they are not one text node), and its link as cloneLinkAt reads it.
 * Null when the key is not a link or button with inline-only content. */
export function cloneButtonAt(
  clone: Clone,
  key: string,
): { labelKey: string; labelSlot: string | null; labelText: string | null; labelShared: boolean; href: string | null; hrefSlot: string | null; shared: boolean } | null {
  const root = parse(clone.html, { comment: false });
  keyElements(root, clone.slots);
  const keyed = root.querySelectorAll(`[${ELEMENT_KEY_ATTR}]`);
  const button = keyed.find((element) => element.getAttribute(ELEMENT_KEY_ATTR) === key);
  const isText = textTest(clone.slots);
  if (!button || !isInlineControl(button, isText)) return null;
  const ownWords = button.childNodes.some((child) => child instanceof TextNode && child.rawText.trim() !== "");
  // Its words, not its icon (an icon is keyed too since plan 4).
  const label = ownWords ? button : (button.querySelectorAll(`[${ELEMENT_KEY_ATTR}]`).find((element) => isText(element)) ?? button);
  const slotOf = (element: HTMLElement) => {
    const slot = element.getAttribute("data-lumen-slot");
    return slot && clone.slots[slot]?.kind === "text" ? slot : null;
  };
  const textNodes = label.childNodes.filter((child): child is TextNode => child instanceof TextNode && child.rawText.trim() !== "");
  const onlyText = textNodes.length === 1 && label.childNodes.every((child) => child instanceof TextNode);
  const words = onlyText ? textNodes[0].text.replace(/\s+/g, " ").trim() : null;
  const href = button.tagName === "A" ? (button.getAttribute("href") ?? null) : null;
  const hrefSlot = button.getAttribute("data-lumen-slot");
  return {
    labelKey: label.getAttribute(ELEMENT_KEY_ATTR) ?? key,
    labelSlot: slotOf(label) ?? slotOf(button),
    labelText: words && replaceableTexts(clone).includes(words) ? words : null,
    // Replacing the words changes every text that reads the same in the section (review finding 9).
    labelShared: words !== null && textsReading(root, words) > 1,
    href,
    hrefSlot: hrefSlot && clone.slots[hrefSlot]?.kind === "href" ? hrefSlot : null,
    shared: href !== null && root.querySelectorAll("a[href]").filter((other) => other.getAttribute("href") === href).length > 1,
  };
}
