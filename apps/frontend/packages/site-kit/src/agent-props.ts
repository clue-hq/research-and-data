// How an agent section's props are edited (S2a-2, option B; founder 2026-10-16). The agent marks a
// prop a marketer reads as words on the page with `.meta({ edit: "inline" })`; the editor makes
// exactly those editable in place on the canvas. Brand choices, links, images and `alt` are named
// by these rules (the same names the save check's agent walk uses, ./validate) and are never edited
// in place: the editor offers the choices from the brand's lists and the rest in the side panel.
// Read by the editor's field mapping and by the marker rule in render-core's sectionPropsSchema.

/** The value of the marker in a stored props JSON Schema: `"edit": "inline"`. */
export const EDIT_INLINE = "inline";

export const SURFACE_PROP = /^surface$|Surface$/;
export const CARD_LOOK_PROP = /^cardLook$|CardLook$/;
export const LOOK_PROP = /^look$|Look$/;
export const LINK_PROP = /(href|link|url)$/i;
export const IMAGE_PROP = /(image|logo|photo|picture|src)$/i;
export const ALT_PROP = /^alt$|Alt$/;

export type BrandChoice = "surface" | "cardLook" | "look";

/** The brand list a prop is chosen from, by its name; null for any other prop. */
export function brandChoice(name: string): BrandChoice | null {
  if (SURFACE_PROP.test(name)) return "surface";
  if (CARD_LOOK_PROP.test(name)) return "cardLook";
  if (LOOK_PROP.test(name)) return "look";
  return null;
}

/** Why a prop with this name can never be edited in place, or null when it can (when marked). */
export function notInlineReason(name: string): string | null {
  if (brandChoice(name)) return "it is a brand choice, picked from a list in the editor";
  if (IMAGE_PROP.test(name)) return "it is an image, chosen from the brand's assets in the editor";
  if (LINK_PROP.test(name)) return "it is a link, edited in the editor's side panel";
  if (ALT_PROP.test(name)) return "it is an image's description, edited in the editor's side panel";
  return null;
}

type PropsJsonSchema = { type?: unknown; edit?: unknown; properties?: Record<string, PropsJsonSchema>; items?: PropsJsonSchema };

/** Where a section's props JSON Schema puts the marker on a prop that cannot edit in place, as
 * write-time refusals (render-core's sectionPropsSchema). Nested props are named by their path
 * (`cards.linkHref`). */
export function inlineMarkerErrors(schema: PropsJsonSchema, prefix = ""): string[] {
  return Object.entries(schema.properties ?? {}).flatMap(([name, property]) => {
    const path = `${prefix}${name}`;
    const errors: string[] = [];
    if (property.edit === EDIT_INLINE) {
      const why = notInlineReason(name) ?? (property.type === "string" ? null : "it is not text; only z.string() props edit in place");
      if (why) errors.push(`"${path}" cannot be edited in place: ${why}. Remove .meta({ edit: "inline" }) from it`);
    }
    const child = property.items ?? property;
    if (child.properties) errors.push(...inlineMarkerErrors(child, `${path}.`));
    return errors;
  });
}

/** The props an agent section marked for editing in place (and that may be): its RICH text (plan 2,
 * spec §4.4). Nested props are paths with "*" for an array's items (`cards.*.title`). */
export function richPropPaths(schema: PropsJsonSchema, prefix = ""): string[] {
  return Object.entries(schema.properties ?? {}).flatMap(([name, property]) => {
    const path = `${prefix}${name}`;
    if (property.edit === EDIT_INLINE && property.type === "string" && notInlineReason(name) === null) return [path];
    if (property.items?.properties) return richPropPaths(property.items, `${path}.*.`);
    if (property.properties) return richPropPaths(property, `${path}.`);
    return [];
  });
}

/** The string values at those paths in a section's props, each with its real path (`cards.1.title`). */
export function richValuesAt(props: Record<string, unknown>, paths: readonly string[]): { path: string; value: string }[] {
  const found: { path: string; value: string }[] = [];
  const visit = (value: unknown, parts: string[], at: string) => {
    if (!parts.length) {
      if (typeof value === "string") found.push({ path: at, value });
      return;
    }
    const [head, ...rest] = parts;
    if (head === "*") {
      if (Array.isArray(value)) value.forEach((item, i) => visit(item, rest, `${at}.${i}`));
    } else if (value && typeof value === "object") {
      visit((value as Record<string, unknown>)[head], rest, at ? `${at}.${head}` : head);
    }
  };
  for (const path of paths) visit(props, path.split("."), "");
  return found;
}
