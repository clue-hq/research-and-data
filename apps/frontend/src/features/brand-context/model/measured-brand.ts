import type { z } from "zod";
import {
  STATES,
  brandData,
  colorOf,
  contrast,
  durationOf,
  easingOf,
  hexOf,
  inkRole,
  isComponentToken,
  isMeasured,
  kindOf,
  measuredComponents,
  motionEntries,
  motionNotes,
  otherSurfaceRoles,
  partsFromSlots,
  pxOf,
  styleOf,
  surfaceLabels,
  tokenEntry,
  tokenGroups,
  trim,
  typographyOf,
  type BrandData,
  type MeasuredRecipe,
  type Part,
  type Parts,
} from "@clue/site-kit/brand-view";
import type { BrandColorGroupSchema } from "./brand-context";
import type { BrandKitDetail } from "./brand-kit";
import type {
  MeasuredBrandView,
  MeasuredGroup,
  MeasuredIcon,
  MeasuredSample,
  MeasuredStyleView,
  MeasuredValue,
  SampleState,
  SpacingStep,
} from "./measured-view";

/**
 * Wave 2 A9, Task X6 (founder Q-A9-3 (c), 2026-10-12): what the brand-kit extraction measured on
 * the seller's site, as the Brand page shows it — each measured button, card and link style in
 * every state it was measured in, the colours minted from them, the section backgrounds with their
 * text colour, the brand's spacing and its motion.
 *
 * Every value is read through site-kit's own functions (`@clue/site-kit/brand-view`), the ones
 * that draw a published site, so this page and a site can never describe a style differently.
 * Pure: no transport, no React. The mapping's two rules hold (`brand-context-mapping.ts`):
 *  1. Honest empties — a kit made before measurement has no view (`null`), and the page is
 *     exactly as before.
 *  2. One bad row never blanks the page — a token that does not resolve drops its own value.
 * Nothing here is a fallback: a part the kit did not measure is not shown.
 */

type BrandColorGroup = z.infer<typeof BrandColorGroupSchema>;
type Drawn = ReturnType<typeof partsFromSlots>;

// --- the page's words (T-A9-8) ----------------------------------------------------------

const STATE_NAMES: Record<SampleState, string> = {
  rest: "Rest", hover: "Hover", pressed: "Pressed", focus: "Focus", disabled: "Disabled",
};
const GROUPS: readonly { id: string; title: string; components: readonly string[] }[] = [
  { id: "buttons", title: "Buttons", components: ["button"] },
  { id: "cards", title: "Cards", components: ["card"] },
  { id: "links", title: "Links", components: ["link", "nav_link"] },
  { id: "chips", title: "Chips", components: ["chip"] },
  { id: "fields", title: "Fields", components: ["input"] },
  { id: "images", title: "Images", components: ["image"] },
];
const COMPONENT_NAMES: Record<string, string> = {
  button: "Button", card: "Card", link: "Link", nav_link: "Navigation link", chip: "Chip", input: "Field", image: "Image",
};
const SAMPLE_WORDS: Record<string, string> = {
  button: "Button", card: "Card", link: "Link", nav_link: "Link", chip: "Chip", input: "Field", image: "Image",
};
const KIND_NAMES = { outline: "Outline", ghost: "Text only", solid: "Filled" } as const;
const VALUE_NAMES: Partial<Record<Part | "font", string>> = {
  fill: "Fill", label: "Text", border: "Border", borderWidth: "Border width", borderStyle: "Border style",
  radius: "Corners", padding: "Padding", height: "Height", gap: "Gap", font: "Font", case: "Letter case",
  decoration: "Underline", decorationThickness: "Underline thickness", underlineOffset: "Underline offset",
  shadow: "Shadow", opacity: "Opacity", transform: "Transform", filter: "Filter", cursor: "Pointer",
  outlineColor: "Focus ring", outlineWidth: "Focus ring width", outlineStyle: "Focus ring style",
  outlineOffset: "Focus ring offset", iconColor: "Icon color", iconTransform: "Icon transform", iconOpacity: "Icon opacity",
};
const COLOR_NAMES: readonly [Part, string][] = [
  ["fill", "Fill"], ["label", "Text"], ["border", "Border"], ["outlineColor", "Focus ring"], ["iconColor", "Icon"],
];
const SCRIPTED_NAMES: Record<string, string> = {
  scripted: "Scripted animation", canvas: "Canvas animation", video: "Video",
};
const SIZE_NAMES: Record<string, string> = {
  xs: "Extra small", sm: "Small", md: "Medium", lg: "Large", xl: "Extra large",
};
const BROWSER_RING = "The browser's own focus ring";
const NEEDS_A_SCRIPT = "Needs a script, so pages made here don't copy it.";

// --- reading ----------------------------------------------------------------------------

/** A section background minted from the seller's site, and a text colour minted with one. */
const BAND_SURFACE = /^surface\.band\.[0-9a-f]{6}$/;
const BAND_INK = /^text\.band\.[0-9a-f]{6}$/;
/** Below this contrast with the page colour a style would not show on it (a white button). */
const MIN_SHOWING_CONTRAST = 1.5;
const KIND_ORDER = ["outline", "ghost", "solid", "other"] as const;
const VALUE_ORDER: readonly (Part | "font")[] = [
  "fill", "label", "border", "borderWidth", "borderStyle", "radius", "padding", "height", "gap", "font", "case",
  "decoration", "decorationThickness", "underlineOffset", "shadow", "opacity", "transform", "filter", "cursor",
  "outlineColor", "outlineWidth", "outlineStyle", "outlineOffset", "iconColor", "iconTransform", "iconOpacity",
];
/** What the sample draws; `cursor` is listed, never drawn (a static sample has no pointer). */
const CSS_PROPERTY: Partial<Record<Part, string>> = {
  fill: "backgroundColor", label: "color", border: "borderColor", borderWidth: "borderWidth",
  borderStyle: "borderStyle", radius: "borderRadius", padding: "padding", height: "minHeight", gap: "gap",
  fontFamily: "fontFamily", fontSize: "fontSize", fontWeight: "fontWeight", lineHeight: "lineHeight",
  tracking: "letterSpacing", case: "textTransform", decoration: "textDecorationLine",
  decorationThickness: "textDecorationThickness", underlineOffset: "textUnderlineOffset", shadow: "boxShadow",
  opacity: "opacity", transform: "transform", filter: "filter", outlineColor: "outlineColor",
  outlineWidth: "outlineWidth", outlineStyle: "outlineStyle", outlineOffset: "outlineOffset",
};
/** Layout only, so a label and its icon sit in one line; every visual value is measured. */
const BOX: Record<string, string> = { display: "inline-flex", alignItems: "center", boxSizing: "border-box" };
const TEXT_ONLY = new Set(["link", "nav_link"]);
const SVG_NAMESPACE = 'xmlns="http://www.w3.org/2000/svg"';

const capital = (text: string) => (text ? text[0].toUpperCase() + text.slice(1) : text);
const humanize = (text: string) => capital(text.replace(/[._-]+/g, " ").trim());

/** A measured colour token, moved out of "Semantic roles" when this page shows it elsewhere. */
export function isMeasuredColor(path: string): boolean {
  return isComponentToken(path) || BAND_SURFACE.test(path) || BAND_INK.test(path);
}

export function toMeasuredBrand(kit: BrandKitDetail): MeasuredBrandView | null {
  const brand = brandData({
    slug: kit.brand_kit.id,
    kit: kit.brand_kit_json as unknown as Record<string, unknown>,
    fonts: [],
    kitAssets: {},
    clones: [],
  });
  const section = measuredComponents(brand);
  const bands = otherSurfaceRoles(brand).filter((role) => BAND_SURFACE.test(role));
  if (!section && !bands.length) return null;

  const shown = new Set<string>();
  const groups = section ? styleGroups(brand, section.styles ?? []) : [];
  const colorGroups = [
    ...bandGroup(brand, bands, shown),
    ...groups.flatMap((group) => group.styles).flatMap((style) => styleColorGroup(style, shown)),
  ];
  return {
    colorGroups,
    movedColors: [...shown].filter(isMeasuredColor).sort(),
    groups,
    spacing: section ? spacingSteps(brand) : [],
    ...motionCards(brand),
  };
}

function styleGroups(brand: BrandData, styles: readonly MeasuredRecipe[]): MeasuredGroup[] {
  return GROUPS.flatMap(({ id, title, components }) => {
    const views = components.flatMap((component) =>
      named(styles.filter((style) => style.component === component), component).map(([style, name]) =>
        styleView(brand, style, name),
      ),
    );
    return views.length ? [{ id, title, styles: views }] : [];
  });
}

/** Dock order and dock names (T-A9-7): outline, text only, filled; the most used first; a number
 * only when a kind repeats. Other components are named by what they are ("Card", "Card 2"). */
function named(styles: readonly MeasuredRecipe[], component: string): [MeasuredRecipe, string][] {
  const sorted = [...styles].sort((a, b) =>
    KIND_ORDER.indexOf(kindOf(a.variant)) - KIND_ORDER.indexOf(kindOf(b.variant))
    || b.count - a.count
    || a.variant.localeCompare(b.variant));
  if (component !== "button") {
    const noun = COMPONENT_NAMES[component] ?? humanize(component);
    return sorted.map((style, index) => [style, sorted.length > 1 ? `${noun} ${index + 1}` : noun]);
  }
  const totals = new Map<string, number>();
  for (const style of sorted) totals.set(kindOf(style.variant), (totals.get(kindOf(style.variant)) ?? 0) + 1);
  const seen = new Map<string, number>();
  return sorted.map((style) => {
    const kind = kindOf(style.variant);
    const n = (seen.get(kind) ?? 0) + 1;
    seen.set(kind, n);
    if (kind === "other") return [style, humanize(style.variant)];
    return [style, (totals.get(kind) ?? 0) > 1 ? `${KIND_NAMES[kind]} ${n}` : KIND_NAMES[kind]];
  });
}

function styleView(brand: BrandData, style: MeasuredRecipe, name: string): MeasuredStyleView {
  const rest = partsFromSlots(brand, style.rest);
  const backdrop = backdropFor(brand, style, rest);
  const samples = [drawSample(brand, style, "rest", rest, rest, backdrop)];
  for (const state of STATES) {
    const slots = style.states?.[state];
    const browserRing = state === "focus" && !!style.browser_focus_ring;
    if (!slots && !browserRing) continue;
    samples.push(drawSample(brand, style, state, rest, partsFromSlots(brand, slots), backdrop));
  }
  return {
    id: `${style.component}:${style.variant}`,
    component: style.component,
    variant: style.variant,
    name,
    word: SAMPLE_WORDS[style.component] ?? humanize(style.component),
    family: typographyOf(brand, style.rest.font)?.family ?? null,
    samples,
    transitions: transitions(brand, style),
  };
}

function drawSample(
  brand: BrandData,
  style: MeasuredRecipe,
  state: SampleState,
  rest: Drawn,
  own: Drawn,
  backdrop: string | null,
): MeasuredSample {
  const parts: Parts = state === "rest" ? rest.parts : { ...rest.parts, ...own.parts };
  const css: Record<string, string> = TEXT_ONLY.has(style.component) ? {} : { ...BOX };
  for (const [part, property] of Object.entries(CSS_PROPERTY) as [Part, string][]) {
    const value = parts[part];
    if (value !== undefined) css[property] = value;
  }
  const ringIsTheBrowsers = state === "focus" && !!style.browser_focus_ring && own.parts.outlineColor === undefined;
  return {
    state,
    name: STATE_NAMES[state],
    style: css,
    backdrop,
    icon: iconOf(brand, style, parts),
    values: valuesOf(brand, own),
    note: ringIsTheBrowsers ? BROWSER_RING : null,
  };
}

function valuesOf(brand: BrandData, drawn: Drawn): MeasuredValue[] {
  const values: MeasuredValue[] = [];
  for (const part of VALUE_ORDER) {
    if (part === "font") {
      const token = drawn.tokens.fontFamily;
      const font = typographyOf(brand, token);
      if (!font || !token) continue;
      const spacing = font.letterSpacing ? `${trim(font.letterSpacing)}em letter spacing` : "";
      const value = [font.family, `${trim(font.size)}px`, String(font.weight), spacing].filter(Boolean).join(" · ");
      values.push({ part, label: VALUE_NAMES.font ?? "Font", value, token });
      continue;
    }
    const value = drawn.parts[part];
    const token = drawn.tokens[part];
    if (value !== undefined && token) values.push({ part, label: VALUE_NAMES[part] ?? humanize(part), value, token });
  }
  return values;
}

function backdropFor(brand: BrandData, style: MeasuredRecipe, rest: Drawn): string | null {
  const page = hexOf(brand, "surface.page");
  if (!page) return null;
  const kind = kindOf(style.variant);
  const token = kind === "solid" ? rest.tokens.fill : kind === "outline" ? rest.tokens.border ?? rest.tokens.label : rest.tokens.label;
  const showing = hexOf(brand, token);
  const inverse = hexOf(brand, "surface.inverse");
  return showing && inverse && contrast(showing, page) < MIN_SHOWING_CONTRAST ? inverse : page;
}

function iconOf(brand: BrandData, style: MeasuredRecipe, parts: Parts): MeasuredIcon | null {
  const icon = style.icon;
  const value = icon ? styleOf(brand, icon.token) : undefined;
  if (!icon || !value || (value.kind !== "glyph" && value.kind !== "svg")) return null;
  const color = parts.iconColor ?? parts.label;
  const css: Record<string, string> = {};
  if (color) css.color = color;
  if (parts.iconTransform) css.transform = parts.iconTransform;
  if (parts.iconOpacity) css.opacity = parts.iconOpacity;
  if (value.kind === "glyph") {
    return { position: icon.position, glyph: value.text, src: null, width: null, height: null, style: css };
  }
  // An image has no surrounding text colour, so `currentColor` becomes the measured icon colour,
  // and a standalone SVG needs its namespace (inline SVG in HTML does not).
  let markup = color ? value.markup.replaceAll("currentColor", color) : value.markup;
  if (!markup.includes("xmlns=")) markup = markup.replace(/^<svg\b/, `<svg ${SVG_NAMESPACE}`);
  return {
    position: icon.position,
    glyph: null,
    src: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`,
    width: value.width,
    height: value.height,
    style: css,
  };
}

function transitions(brand: BrandData, style: MeasuredRecipe): MeasuredValue[] {
  return (style.motion ?? []).flatMap((step) => {
    const duration = durationOf(brand, step.duration);
    const easing = easingOf(brand, step.easing);
    const delay = step.delay ? durationOf(brand, step.delay) : undefined;
    if (!duration || !easing) return [];
    return [{
      part: "transition",
      label: step.target === "icon" ? "Icon transition" : "Transition",
      value: `${step.property} ${duration} ${easing}${delay ? ` after ${delay}` : ""}`,
      token: step.duration,
    }];
  });
}

function bandGroup(brand: BrandData, roles: readonly string[], shown: Set<string>): BrandColorGroup[] {
  if (!roles.length) return [];
  const labels = surfaceLabels(brand);
  const swatches = roles.flatMap((role) => {
    const value = colorOf(brand, role);
    if (!value) return [];
    shown.add(role);
    const ink = inkRole(brand, role);
    const inkValue = colorOf(brand, ink);
    if (ink && inkValue) shown.add(ink);
    const name = labels.get(role) ?? role;
    // Minted surfaces carry no dark colourway (the emitter writes none), so dark shows the same value.
    return [{ id: role, label: inkValue ? `${name} · text ${inkValue}` : name, lightValue: value, darkValue: value }];
  });
  return swatches.length ? [{ id: "measured-section-backgrounds", label: "Section backgrounds", swatches }] : [];
}

function styleColorGroup(style: MeasuredStyleView, shown: Set<string>): BrandColorGroup[] {
  const swatches = style.samples.flatMap((sample) =>
    sample.values.flatMap((value) => {
      const name = COLOR_NAMES.find(([part]) => part === value.part)?.[1];
      if (!name) return [];
      shown.add(value.token);
      const label = sample.state === "rest" || (sample.state === "focus" && value.part === "outlineColor")
        ? name
        : `${sample.name} ${name.toLocaleLowerCase()}`;
      return [{ id: `${style.id}:${sample.state}:${value.part}`, label, lightValue: value.value, darkValue: value.value }];
    }),
  );
  if (!swatches.length) return [];
  return [{ id: `measured-${style.id}`, label: style.component === "button" ? `${style.name} button` : style.name, swatches }];
}

function spacingSteps(brand: BrandData): SpacingStep[] {
  const spacing = tokenGroups(brand).spacing ?? {};
  return Object.keys(spacing)
    .filter((name) => !isComponentToken(name))
    .flatMap((name) => {
      const value = pxOf(brand, name);
      if (!value) return [];
      return [{
        id: name,
        name: spacingName(name),
        value,
        token: name,
        measured: isMeasured(tokenEntry(brand, "spacing", name)),
      }];
    })
    .sort((a, b) => Number.parseFloat(a.value) - Number.parseFloat(b.value) || a.token.localeCompare(b.token));
}

/** A spacing step in plain words: `space.stack.tight` → "Stack tight", `space.sm` → "Small",
 * `space.4` → "Step 4". */
function spacingName(name: string): string {
  const key = name.replace(/^space\./, "");
  if (/^\d+$/.test(key)) return `Step ${key}`;
  return SIZE_NAMES[key] ?? humanize(key);
}

function motionCards(brand: BrandData): Pick<MeasuredBrandView, "animations" | "reveals" | "scripted"> {
  const entries = motionEntries(brand);
  const animations = entries
    .filter((entry) => entry.kind === "animation")
    .map((entry) => ({
      id: entry.token,
      name: humanize(entry.className.replace(/^brand-motion-/, "")),
      headline: entry.timing,
      lines: [capital(entry.describe), entry.where].filter(Boolean),
    }));
  const revealEntries = entries.filter((entry) => entry.kind === "reveal");
  const reveals = revealEntries.map((entry, index) => {
    const value = styleOf(brand, entry.token);
    const duration = value?.kind === "reveal" ? durationOf(brand, value.duration) : undefined;
    return {
      id: entry.token,
      name: revealEntries.length > 1 ? `Scroll reveal ${index + 1}` : "Scroll reveal",
      headline: [duration, entry.timing].filter(Boolean).join(" "),
      lines: [capital(entry.describe), entry.where].filter(Boolean),
    };
  });
  const scripted = motionNotes(brand).map((note, index) => ({
    id: `scripted-${index}`,
    name: SCRIPTED_NAMES[note.kind] ?? humanize(note.kind),
    headline: note.where,
    lines: [NEEDS_A_SCRIPT],
  }));
  return { animations, reveals, scripted };
}
