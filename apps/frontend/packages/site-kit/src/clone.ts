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
export type CloneExtras = { id?: string; newTab?: readonly string[] };

export function fillClone(
  clone: Clone,
  values: SlotValues = {},
  replacements: TextReplacement[] = [],
  links: LinkReplacement[] = [],
  extras: CloneExtras = {},
): string {
  const root = parse(clone.html, { comment: false });
  keyTextElements(root, clone.slots);
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
  if (wanted.length) replaceText(root, wanted);

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

/** Key every text element by its child-index path from the fragment root ("0.2.1", element children
 * only). A text element holds words of its own (a non-blank text child), or is a text slot (whose
 * words may sit in inline tags, and which the slot's fill replaces whole). Inside a text element
 * nothing more is keyed: its inline children are part of its one text box. */
function keyTextElements(root: HTMLElement, slots: Record<string, CloneSlot>): void {
  const isText = (element: HTMLElement) => {
    const slot = element.getAttribute("data-lumen-slot");
    if (slot && slots[slot]?.kind === "text") return true;
    return element.childNodes.some((child) => child instanceof TextNode && child.rawText.trim() !== "");
  };
  const walk = (node: HTMLElement, path: string) => {
    let index = 0;
    for (const child of node.childNodes) {
      if (child instanceof TextNode || !(child as HTMLElement).tagName) continue;
      const element = child as HTMLElement;
      const place = path ? `${path}.${index}` : String(index);
      index += 1;
      if (NOT_TEXT.has(element.tagName.toLowerCase())) continue;
      if (isText(element)) element.setAttribute(ELEMENT_KEY_ATTR, place);
      else walk(element, place);
    }
  };
  walk(root, "");
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
function replaceText(root: HTMLElement, replacements: TextReplacement[]): void {
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
        walk(child as HTMLElement);
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
