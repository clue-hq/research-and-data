import type { Config, Field, Fields } from "@puckeditor/core";
import {
  EDIT_INLINE,
  IMAGE_PROP as IMAGE_NAME,
  LINK_PROP as LINK_NAME,
  brandChoice,
  buttonLookOptions,
  cardLookOptions,
  notInlineReason,
  surfaceChoices,
  type BrandChoice,
  type BrandData,
} from "@clue/site-kit";
import type { FieldDescription, FieldKind, FieldOption } from "@clue/site-kit/editor-protocol";

/**
 * Contract 6's FieldDescription, derived in the frame (where the Puck config lives) and drawn in
 * the app's dock. Built-in sections describe their site-kit Puck fields; a cloned section shows its
 * slots (never the clone id, text replacements or link replacements — the marketer never sees
 * "clones"); an agent section's fields come from its props JSON Schema (the D2 spike's `fieldsFrom`,
 * `trials/puck-spike/app/edit-runtime/[site]/client.tsx:41-69`).
 */
const LONG_TEXT = /(body|intro|statement|description|quote|summary)$/i;
const SLOT_KINDS: Record<string, FieldKind> = { href: "link", image: "image", text: "textarea", visibility: "boolean" };
const HIDDEN: Record<string, readonly string[]> = { ClonedSection: ["fragmentId", "slots", "replacements", "links", "newTab"] };

type JsonSchema = {
  type?: string | string[];
  enum?: unknown[];
  edit?: unknown;
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
};

export function humanize(name: string): string {
  const words = name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim()
    .toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const isOptionValue = (value: unknown): value is FieldOption["value"] =>
  typeof value === "string" || typeof value === "number" || typeof value === "boolean";

function describeField(name: string, field: Field): FieldDescription[] {
  const label = field.label ?? humanize(name);
  switch (field.type) {
    case "text":
      return [{ kind: IMAGE_NAME.test(name) ? "image" : LINK_NAME.test(name) ? "link" : "text", label, name }];
    case "textarea":
      return [{ kind: "textarea", label, name }];
    case "number":
      return [{ kind: "number", label, name }];
    case "select":
    case "radio": {
      const options = field.options
        .filter((option) => isOptionValue(option.value))
        .map((option) => ({ label: String(option.label), value: option.value as FieldOption["value"] }));
      const boolean = options.length === 2 && options.every((option) => typeof option.value === "boolean");
      return [boolean ? { kind: "boolean", label, name } : { kind: "select", label, name, options }];
    }
    case "custom":
      return [{ kind: "image", label, name }];
    case "array":
      return [{ item: describeFields(field.arrayFields as Fields), kind: "list", label, name }];
    case "object":
      return describeFields(field.objectFields as Fields).map((child) => ({ ...child, name: `${name}.${child.name}` }));
    default:
      return [];
  }
}

export function describeFields(fields: Fields, hidden: readonly string[] = []): FieldDescription[] {
  return Object.entries(fields).flatMap(([name, field]) => (hidden.includes(name) ? [] : describeField(name, field as Field)));
}

export function clonedSectionFields(brand: BrandData, props: Record<string, unknown>): FieldDescription[] {
  const clone = brand.clones[String(props.fragmentId ?? "")];
  if (!clone) return [];
  return Object.entries(clone.slots).flatMap(([key, slot]) => {
    const kind = SLOT_KINDS[slot.kind];
    return kind ? [{ kind, label: humanize(key), name: `slots.${key}` }] : [];
  });
}

export function fieldsForComponent(
  config: Config,
  brand: BrandData,
  type: string,
  props: Record<string, unknown>,
): FieldDescription[] {
  if (type === "ClonedSection") return clonedSectionFields(brand, props);
  const component = (config.components as Record<string, { fields?: Fields } | undefined>)[type];
  return describeFields(component?.fields ?? {}, HIDDEN[type] ?? []);
}

/** The options of a brand choice, as built-in sections show them. */
function choiceOptions(choice: BrandChoice, brand: BrandData): { label: string; value: string }[] {
  if (choice === "surface") return surfaceChoices(brand).map(({ label, value }) => ({ label, value }));
  return choice === "cardLook" ? cardLookOptions(brand) : buttonLookOptions(brand);
}

/** Puck fields for an agent section, from its props JSON Schema (S2a-2). Text the agent marked
 * `.meta({ edit: "inline" })` edits in place on the canvas; any other text is edited in the side
 * panel and reaches the section as a plain string. Surfaces and styles are pick-lists from this
 * brand; links, images and `alt` are never edited in place, marked or not. */
export function puckFieldsFromJsonSchema(schema: Record<string, unknown>, brand: BrandData): Fields {
  const fields: Record<string, Field> = {};
  const properties = (schema as JsonSchema).properties ?? {};
  for (const [key, property] of Object.entries(properties)) {
    if (key === "id") continue;
    const type = Array.isArray(property.type) ? property.type.find((entry) => entry !== "null") : property.type;
    const label = humanize(key);
    const choice = brandChoice(key);
    if (property.enum) {
      fields[key] = {
        label,
        options: property.enum.filter(isOptionValue).map((value) => ({ label: String(value), value })),
        type: "select",
      };
    } else if (type === "string" && choice) {
      fields[key] = { label, options: choiceOptions(choice, brand), type: "select" };
    } else if (type === "string" && IMAGE_NAME.test(key)) {
      fields[key] = { label, render: () => null, type: "custom" } as unknown as Field;
    } else if (type === "string") {
      fields[key] = {
        contentEditable: property.edit === EDIT_INLINE && notInlineReason(key) === null,
        label,
        type: LONG_TEXT.test(key) ? "textarea" : "text",
      };
    } else if (type === "boolean") {
      fields[key] = { label, options: [{ label: "Yes", value: true }, { label: "No", value: false }], type: "radio" };
    } else if (type === "number" || type === "integer") {
      fields[key] = { label, type: "number" };
    } else if (type === "array" && property.items?.type === "object") {
      fields[key] = { arrayFields: puckFieldsFromJsonSchema(property.items as Record<string, unknown>, brand), label, type: "array" } as Field;
    } else if (type === "object") {
      fields[key] = { label, objectFields: puckFieldsFromJsonSchema(property as Record<string, unknown>, brand), type: "object" } as Field;
    }
  }
  return fields as Fields;
}
