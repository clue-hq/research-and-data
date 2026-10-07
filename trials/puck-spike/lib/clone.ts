// Fill a stored clone's slots the way the engine does (crates/lumen-web/src/fragment.rs,
// substitute_fragment_slots), then apply exact text replacements for text that has no slot
// (the engine's apply_fragment_text_overrides plays this role for human overrides).
//
// Slot kinds: text replaces the element's content with plain text; href sets the element's
// href; image sets the element's src; visibility removes the element when false.
// Runs on the server (published pages) and in the browser (editor), so it uses an isomorphic
// parser rather than the DOM.
import { parse, TextNode, type HTMLElement } from "node-html-parser";

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
};

export type SlotValues = Record<string, string | boolean | undefined>;
export type TextReplacement = { find: string; replace: string };
export type LinkReplacement = { find: string; replace: string };

export function fillClone(
  clone: Clone,
  values: SlotValues = {},
  replacements: TextReplacement[] = [],
  links: LinkReplacement[] = [],
): string {
  const root = parse(clone.html, { comment: false });

  for (const [key, slot] of Object.entries(clone.slots)) {
    const value = values[key];
    if (value === undefined || value === "") continue;
    // An unchanged slot keeps the captured markup exactly (its fallback is plain text, so
    // re-applying it would drop line breaks and inline markup).
    if (slot.kind !== "visibility" && String(value) === String(slot.fallback ?? "")) continue;
    if (slot.kind === "visibility" && (value === true || value === "true")) continue;
    const elements = root.querySelectorAll(`[data-lumen-slot="${key}"]`);
    for (const element of elements) applySlot(element, slot.kind, value);
  }

  const wanted = replacements.filter((r) => r.find && r.find !== r.replace);
  if (wanted.length) replaceText(root, wanted);

  // Links with no href slot (for example audience cards that point at the seller's own pages):
  // an exact href match is pointed somewhere else; "*" re-points every link in the section.
  for (const link of links.filter((l) => l.find && l.replace)) {
    for (const anchor of root.querySelectorAll("a[href]")) {
      if (link.find === "*" || anchor.getAttribute("href") === link.find) {
        anchor.setAttribute("href", link.replace);
      }
    }
  }

  return root.toString();
}

function applySlot(element: HTMLElement, kind: SlotKind, value: string | boolean): void {
  if (kind === "text") {
    element.set_content(new TextNode(escapeText(String(value)), element));
  } else if (kind === "href") {
    element.setAttribute("href", String(value));
  } else if (kind === "image") {
    element.setAttribute("src", String(value));
    element.removeAttribute("srcset");
  } else if (kind === "visibility" && (value === false || value === "false")) {
    element.remove();
  }
}

function replaceText(root: HTMLElement, replacements: TextReplacement[]): void {
  const walk = (node: HTMLElement) => {
    for (const child of node.childNodes) {
      if (child instanceof TextNode) {
        const original = child.rawText;
        const trimmed = original.trim();
        const match = replacements.find((r) => r.find.trim() === trimmed);
        if (match) child.rawText = original.replace(trimmed, escapeText(match.replace));
      } else {
        walk(child as HTMLElement);
      }
    }
  };
  walk(root);
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
