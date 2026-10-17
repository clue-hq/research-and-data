// Where a section's rich text is (plan 2, spec §4.4; ruling R4): our sections' RICH_PROPS, the props
// an agent section marked for editing in place, and a clone's text slots. One reading for the save
// check (validate.ts) and for the frame, which saves rich text in the grammar's canonical form.
import { richPropPaths, richValuesAt } from "./agent-props";
import type { BrandData } from "./brand";
import { setAtPath } from "./editor-site";
import { normalizeRich } from "./rich";
import { RICH_PROPS } from "./schemas";

/** An agent section's stored props JSON Schema, by section name (undefined when unknown). */
export type PropsSchemaOf = (type: string) => unknown;

/** The section's rich values, each with its prop path (`heading`, `cards.1.title`, `slots.headline`). */
export function richValuesOfItem(
  item: { type: string; props: Record<string, unknown> },
  brand: BrandData,
  propsSchemaOf: PropsSchemaOf,
): { path: string; value: string }[] {
  const props = item.props ?? {};
  const ours = (RICH_PROPS as Record<string, readonly string[]>)[item.type];
  if (ours) return richValuesAt(props, ours);
  if (item.type === "ClonedSection") {
    const clone = brand.clones[String(props.fragmentId ?? "")];
    const slots = (props.slots as Record<string, unknown> | undefined) ?? {};
    return Object.entries(slots).flatMap(([key, value]) =>
      clone?.slots[key]?.kind === "text" && typeof value === "string" ? [{ path: `slots.${key}`, value }] : [],
    );
  }
  const schema = propsSchemaOf(item.type);
  return schema ? richValuesAt(props, richPropPaths(schema as Parameters<typeof richPropPaths>[0])) : [];
}

/** The page with every rich value in the grammar's canonical form (what the editor's TipTap or a
 * paste wrote, cleaned: a pasted alignment, a stray attribute, paragraphs as line breaks). The same
 * page object when nothing changes. */
export function normalizeRichIn<P extends { content?: { type: string; props: Record<string, unknown> }[] }>(
  page: P,
  brand: BrandData,
  propsSchemaOf: PropsSchemaOf,
): P {
  let changed = false;
  const content = (page.content ?? []).map((item) => {
    let props = item.props;
    for (const { path, value } of richValuesOfItem(item, brand, propsSchemaOf)) {
      const clean = normalizeRich(value);
      if (clean !== value) props = setAtPath(props, path, clean);
    }
    if (props === item.props) return item;
    changed = true;
    return { ...item, props };
  });
  return changed ? { ...page, content } : page;
}

/** Where our section's or the shell's own link for an element is written (plan 2, ruling R5): the
 * address prop and the new-tab prop beside it. Null for an element that is not one of those links. */
export function ownLinkSource(type: string, key: string): { kind: "prop"; href: string; newTab: string } | null {
  if (type === "ProofCard" && key === "linkLabel") return { kind: "prop", href: "linkHref", newTab: "linkNewTab" };
  const nav = type === "SiteHeader" ? /^nav\.(\d+)$/.exec(key) : null;
  if (nav) return { kind: "prop", href: `nav.${nav[1]}.href`, newTab: `nav.${nav[1]}.newTab` };
  if (type === "SiteFooter" && (key === "privacy" || key === "terms")) return { kind: "prop", href: `${key}Href`, newTab: `${key}NewTab` };
  return null;
}

/** Where an element's words are stored when they are rich text (ruling R4): our section's rich prop
 * the element draws (its key is the prop's name), or an agent's inline prop the element is named after
 * (`cards.*.body` names `cards.1.body`). A clone's slot is read from the canvas (its slot attribute);
 * the header's and footer's words are not rich until plan 6. */
export function richSourceOf(
  item: { type: string; props: Record<string, unknown> },
  key: string,
  _brand: BrandData,
  propsSchemaOf: PropsSchemaOf,
): { prop: string } | null {
  const ours = (RICH_PROPS as Record<string, readonly string[]>)[item.type];
  if (ours) return ours.includes(key) ? { prop: key } : null;
  if (item.type === "ClonedSection") return null;
  const schema = propsSchemaOf(item.type);
  if (!schema) return null;
  const matches = richPropPaths(schema as Parameters<typeof richPropPaths>[0]).some((path) =>
    new RegExp(`^${path.replace(/\./g, "\\.").replace(/\*/g, "\\d+")}$`).test(key),
  );
  return matches ? { prop: key } : null;
}
