import type { WebNode } from "../engine/webDocuments";

/** Registry facts about one pinned fragment, as `GET /documents/{id}` serves them under
 * `fragment_meta` (design API `public_document`, Task 2). Absent → "unreleased or unknown". */
export interface FragmentMeta {
  label: string | null;
  section_role: string | null;
}
export type FragmentMetaMap = Record<string, FragmentMeta>;

const NAME_CAP = 40;

function plainText(html: string): string {
  return html.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
}

function capitalise(word: string): string {
  return word.length === 0 ? word : word[0].toUpperCase() + word.slice(1);
}

function fragmentName(node: WebNode, fragmentMeta?: FragmentMetaMap): string {
  const meta = node.fragment_id ? fragmentMeta?.[node.fragment_id] : undefined;
  if (!meta) return "Cloned section";
  const role = meta.section_role ? capitalise(meta.section_role) : null;
  const label = meta.label?.trim() || null;
  if (role && label) return `${role} — ${label}`;
  return role ?? label ?? "Cloned section";
}

/**
 * Ruling R-A5 (founder, 2026-09-04): every label the shell shows for a web node is a human
 * name, never a raw id. ONE order of precedence, shared by the layers panel, the hover chip,
 * the comment chip, and (mirrored in Python, `_web_node_label`) the agent's TURN TARGET line:
 *   1. the node's own `name` (pin tools stamp it; a human rename writes it);
 *   2. by kind — text: its plain words; button: its label; image: its alt; fragment: the
 *      registry's role and label; a section wrapping exactly one fragment: that fragment's name;
 *   3. the kind, capitalised.
 */
export function displayNameForNode(
  node: WebNode,
  nodes: Record<string, WebNode>,
  fragmentMeta?: FragmentMetaMap,
): string {
  if (typeof node.name === "string" && node.name.trim().length > 0) return node.name.trim();
  switch (node.kind) {
    case "text": {
      const text = plainText(typeof node.content === "string" ? node.content : "");
      return text.length > 0 ? text.slice(0, NAME_CAP).trim() : "Text";
    }
    case "button":
      return node.label?.trim() || "Button";
    case "image":
      return node.alt?.trim() || "Image";
    case "fragment":
      return fragmentName(node, fragmentMeta);
    case "section": {
      const children = node.children ?? [];
      const only = children.length === 1 ? nodes[children[0]] : undefined;
      if (only && only.kind === "fragment") return fragmentName(only, fragmentMeta);
      return "Section";
    }
    default:
      return capitalise(node.kind);
  }
}

/** Ruling R-A4: an element INSIDE a clone reads as its tag plus the slot it carries. */
export function innerElementLabel(tag: string, slot?: string | null): string {
  const lower = tag.toLowerCase();
  return slot ? `${lower} · ${slot}` : lower;
}
