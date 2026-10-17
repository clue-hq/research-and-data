// Button and card looks, text links and motion (Wave 2 A9). A look is one of the brief's recipes
// (what the model judged: which styles are page buttons, notes, confidence) joined by (component,
// variant) to the kit's measured recipe (what the capture measured, as token names). Each part is
// drawn from the measured token first, the recipe's token second, the standard part third, a named
// fallback last — and `Drawn.source` says which, for brand.md.
import type { BrandData } from "./brand";
import {
  FALLBACKS, alphaOf, colorOf, contrast, durationOf, easingOf, fluid, fontStack, keywordOf, numberOf, pxOf,
  ratioOf, shadowOf, styleOf, tokenEntry, transformOf, trim, typographyOf, typeSteps,
} from "./brand-values";
import { inkRole, readableInk } from "./surfaces";

export type State = "hover" | "pressed" | "focus" | "disabled";
export const STATES: State[] = ["hover", "pressed", "focus", "disabled"];

export type MeasuredRecipe = {
  component: string; variant: string; count: number; probed: string; source: string;
  rest: Record<string, string>;
  states: Partial<Record<State, Record<string, string>>>;
  motion: { target: "self" | "label" | "icon"; property: string; duration: string; easing: string; delay?: string | null }[];
  icon: { token: string; position: "start" | "end" } | null;
  browser_focus_ring?: boolean;
};
export type Recipe = {
  component: string; variant: string; radius?: string | null; padding?: string | null; border?: string | null;
  shadow?: string | null; background?: string | null; text?: string | null; unmapped?: string[]; confidence?: string;
};
export type Look = { name: string; kind: "outline" | "ghost" | "solid" | "other"; label: string; index: number; recipe: Recipe; measured: MeasuredRecipe | null };
type Motion = { animations?: string[]; reveals?: string[]; scripted?: { kind: string; where: string }[] };
type Section = { schema_version?: number; styles?: MeasuredRecipe[]; motion?: Motion };

export function measuredComponents(brand: BrandData): Section | null {
  const section = (brand.kit as { measured_components?: Section }).measured_components;
  return section && section.schema_version === 1 ? section : null;
}

export function recipes(brand: BrandData): Recipe[] {
  const list = (brand.kit as { brief?: { component_recipes?: unknown[] } }).brief?.component_recipes ?? [];
  return list.filter((r): r is Recipe => !!r && typeof (r as Recipe).component === "string" && typeof (r as Recipe).variant === "string");
}

const KIND_ORDER = ["outline", "ghost", "solid", "other"] as const;
const KIND_LABEL = { outline: "Outline", ghost: "Text only", solid: "Filled" } as const;
export const kindOf = (variant: string): Look["kind"] => {
  const head = variant.split(".")[0];
  return head === "outline" || head === "ghost" || head === "solid" ? head : "other";
};
/** An old kit's frequency rank (`solid.2` → 2). A look-keyed name (`solid.047464`, founder Q-A9-6)
 * has none: its hex part is six or eight characters, never a one-to-three-digit rank. */
const legacyRank = (variant: string) => {
  const part = variant.split(".")[1] ?? "";
  return /^\d{1,3}$/.test(part) ? Number(part) : Number.POSITIVE_INFINITY;
};
const words = (variant: string) => {
  const text = variant.replace(/[._-]+/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : variant;
};

/** The brand's looks for a component, in dock order: outline, text only, filled; within a kind the
 * style the site uses most first (its measured count), then an old kit's rank (`solid.1` before
 * `solid.2`, so a kit made before measurement keeps today's order), then the name. Names never
 * change with the order; only the "Filled 1" / "Filled 2" labels follow it. */
export function looks(brand: BrandData, component: "button" | "card"): Look[] {
  const measured = measuredComponents(brand)?.styles ?? [];
  const seen = new Set<string>();
  const list = recipes(brand).filter((r) => r.component === component && !seen.has(r.variant) && !!seen.add(r.variant));
  const used = (variant: string) => measured.find((s) => s.component === component && s.variant === variant)?.count ?? 0;
  list.sort((a, b) =>
    KIND_ORDER.indexOf(kindOf(a.variant)) - KIND_ORDER.indexOf(kindOf(b.variant))
    || used(b.variant) - used(a.variant)
    || legacyRank(a.variant) - legacyRank(b.variant)
    || a.variant.localeCompare(b.variant));
  const totals = new Map<string, number>();
  for (const r of list) totals.set(kindOf(r.variant), (totals.get(kindOf(r.variant)) ?? 0) + 1);
  const counters = new Map<string, number>();
  return list.map((recipe, index) => {
    const kind = kindOf(recipe.variant);
    const n = (counters.get(kind) ?? 0) + 1;
    counters.set(kind, n);
    const label = kind === "other" ? words(recipe.variant) : (totals.get(kind) ?? 0) > 1 ? `${KIND_LABEL[kind]} ${n}` : KIND_LABEL[kind];
    return { name: recipe.variant, kind, label, index, recipe, measured: measured.find((s) => s.component === component && s.variant === recipe.variant) ?? null };
  });
}

export const buttonLooks = (brand: BrandData) => looks(brand, "button");
export const cardLooks = (brand: BrandData) => looks(brand, "card");
export const lookNamed = (brand: BrandData, component: "button" | "card", name?: string | null) =>
  (name ? looks(brand, component).find((look) => look.name === name) : undefined) ?? null;

/** The dock's "Button style" options (T-A9-7). */
export function buttonLookOptions(brand: BrandData): { label: string; value: string }[] {
  return [{ label: "Standard", value: "" }, ...buttonLooks(brand).map((look) => ({ label: look.label, value: look.name }))];
}

/** The dock's "Card style" options for an agent section's `cardLook` (S2a-2). */
export function cardLookOptions(brand: BrandData): { label: string; value: string }[] {
  return [{ label: "Standard", value: "" }, ...cardLooks(brand).map((look) => ({ label: look.label, value: look.name }))];
}

/** The site's most measured style of an element the kit draws without a choice (styles are stored
 * most frequent first). */
export function elementStyle(brand: BrandData, component: "link" | "nav_link"): MeasuredRecipe | null {
  return measuredComponents(brand)?.styles?.find((style) => style.component === component) ?? null;
}

export type Part =
  | "fill" | "label" | "border" | "borderWidth" | "borderStyle" | "radius" | "padding" | "height" | "gap"
  | "fontFamily" | "fontSize" | "fontWeight" | "lineHeight" | "tracking" | "case" | "decoration"
  | "decorationThickness" | "underlineOffset" | "shadow" | "opacity" | "transform" | "filter" | "cursor"
  | "outlineColor" | "outlineWidth" | "outlineStyle" | "outlineOffset" | "iconColor" | "iconTransform" | "iconOpacity";
/** CSS values; four-sided parts list top right bottom left (corners: tl tr br bl). */
export type Parts = Partial<Record<Part, string>>;
/** Where a drawn part came from; `readable`: put in place of one that does not read (readableLabel). */
export type Source = "measured" | "kit" | "standard" | "fallback" | "none" | "inherit" | "readable";
/** `replaced`: a `readable` part's own value before it was replaced, named as brand.md names it. */
export type Drawn = {
  parts: Parts; tokens: Partial<Record<Part, string>>; source: Partial<Record<Part, Source>>; replaced?: Partial<Record<Part, string>>;
};

const SIDES = ["top", "right", "bottom", "left"] as const;
const CORNERS = ["tl", "tr", "br", "bl"] as const;
const four = (value: string) => `${value} ${value} ${value} ${value}`;
const distinct = (names: (string | undefined)[]) => [...new Set(names.filter((n): n is string => !!n))].join(" / ");

/** The parts a set of measured slots names, resolved through the kit. */
export function partsFromSlots(brand: BrandData, slots: Record<string, string> | undefined): { parts: Parts; tokens: Partial<Record<Part, string>> } {
  const parts: Parts = {};
  const tokens: Partial<Record<Part, string>> = {};
  if (!slots) return { parts, tokens };
  const set = (part: Part, value: string | undefined, token: string) => {
    if (value !== undefined) {
      parts[part] = value;
      tokens[part] = token;
    }
  };
  const padding = SIDES.map((side) => pxOf(brand, slots[`padding-${side}`]));
  const borders = SIDES.map((side) => pxOf(brand, slots[`border-width-${side}`]));
  const corners = CORNERS.map((corner) => pxOf(brand, slots[`radius-${corner}`]));
  if (padding.some(Boolean)) {
    parts.padding = padding.map((v) => v ?? "0").join(" ");
    tokens.padding = distinct(SIDES.map((side) => slots[`padding-${side}`]));
  }
  if (borders.some(Boolean)) {
    parts.borderWidth = borders.map((v) => v ?? "0").join(" ");
    tokens.borderWidth = distinct(SIDES.map((side) => slots[`border-width-${side}`]));
  }
  if (corners.some(Boolean)) {
    parts.radius = corners.map((v) => v ?? "0").join(" ");
    tokens.radius = distinct(CORNERS.map((corner) => slots[`radius-${corner}`]));
  }
  const shadows = Object.keys(slots).filter((slot) => /^shadow-\d+$/.test(slot)).sort((a, b) => Number(a.slice(7)) - Number(b.slice(7)));
  const layers = shadows.map((slot) => shadowOf(brand, slots[slot])).filter((s): s is string => !!s);
  if (layers.length) {
    parts.shadow = layers.join(", ");
    tokens.shadow = distinct(shadows.map((slot) => slots[slot]));
  }
  for (const [slot, token] of Object.entries(slots)) {
    switch (slot) {
      case "fill": set("fill", colorOf(brand, token), token); break;
      case "label": set("label", colorOf(brand, token), token); break;
      case "border": set("border", colorOf(brand, token), token); break;
      case "border-width": { const w = pxOf(brand, token); set("borderWidth", w && four(w), token); break; }
      case "border-style": set("borderStyle", keywordOf(brand, token), token); break;
      case "radius": { const r = pxOf(brand, token); set("radius", r && four(r), token); break; }
      case "height": set("height", pxOf(brand, token), token); break;
      case "gap": set("gap", pxOf(brand, token), token); break;
      case "font": {
        const style = typographyOf(brand, token);
        if (!style) break;
        set("fontFamily", fontStack(brand, style), token);
        set("fontSize", typeSize(brand, token, style.size), token);
        set("fontWeight", String(style.weight), token);
        if (style.lineHeight !== null) set("lineHeight", trim(style.lineHeight), token);
        if (style.letterSpacing !== null) set("tracking", `${trim(style.letterSpacing)}em`, token);
        break;
      }
      case "case": set("case", keywordOf(brand, token), token); break;
      case "decoration": set("decoration", keywordOf(brand, token), token); break;
      case "decoration-thickness": set("decorationThickness", pxOf(brand, token) ?? keywordOf(brand, token), token); break;
      case "underline-offset": set("underlineOffset", pxOf(brand, token) ?? keywordOf(brand, token), token); break;
      case "shadow": set("shadow", keywordOf(brand, token), token); break; // "none": a state that removes the rest shadow
      case "opacity": set("opacity", ratioOf(brand, token), token); break;
      case "transform": set("transform", transformOf(brand, token), token); break;
      case "filter": set("filter", keywordOf(brand, token), token); break;
      case "cursor": set("cursor", keywordOf(brand, token), token); break;
      case "outline": set("outlineColor", colorOf(brand, token), token); break;
      case "outline-width": set("outlineWidth", pxOf(brand, token), token); break;
      case "outline-style": set("outlineStyle", keywordOf(brand, token), token); break;
      case "outline-offset": set("outlineOffset", pxOf(brand, token), token); break;
      case "icon-color": set("iconColor", colorOf(brand, token), token); break;
      case "icon-transform": set("iconTransform", transformOf(brand, token), token); break;
      case "icon-opacity": set("iconOpacity", ratioOf(brand, token), token); break;
      default: break;
    }
  }
  return { parts, tokens };
}

/** The parts a brief recipe names (token names the model chose; measured values outrank them). */
export function partsFromRecipe(brand: BrandData, recipe: Recipe): { parts: Parts; tokens: Partial<Record<Part, string>> } {
  const parts: Parts = {};
  const tokens: Partial<Record<Part, string>> = {};
  const set = (part: Part, value: string | undefined, token: string | null | undefined) => {
    if (value !== undefined && token) {
      parts[part] = value;
      tokens[part] = token;
    }
  };
  set("fill", colorOf(brand, recipe.background), recipe.background);
  set("label", colorOf(brand, recipe.text), recipe.text);
  const width = pxOf(brand, recipe.border);
  set("borderWidth", width && four(width), recipe.border);
  if (width) parts.borderStyle = "solid";
  const radius = pxOf(brand, recipe.radius);
  set("radius", radius && four(radius), recipe.radius);
  const padding = pxOf(brand, recipe.padding);
  set("padding", padding && four(padding), recipe.padding);
  set("shadow", shadowOf(brand, recipe.shadow), recipe.shadow);
  return { parts, tokens };
}

function put(drawn: Drawn, part: Part, value: string | undefined, token: string | undefined, source: Source) {
  if (value === undefined) return;
  drawn.parts[part] = value;
  drawn.source[part] = source;
  if (token) drawn.tokens[part] = token;
  else delete drawn.tokens[part];
}

function apply(drawn: Drawn, from: { parts: Parts; tokens: Partial<Record<Part, string>> }, source: Source, skip: readonly Part[] = []) {
  for (const [part, value] of Object.entries(from.parts) as [Part, string][]) {
    if (!skip.includes(part)) put(drawn, part, value, from.tokens[part], source);
  }
}

/** A type token's size as CSS: a role the kit measured across window widths is its variable (so it
 * follows the seller's steps, responsive brand type); anything else its size in px. */
function typeSize(brand: BrandData, token: string, size: number): string {
  const role = token.startsWith("type.") ? token.slice("type.".length) : null;
  // The variable's name is theme.ts's typeVar (dots become dashes); theme imports this file.
  return role && typeSteps(brand)?.has(role) ? `var(--brand-text-${role.replace(/\./g, "-")})` : `${trim(size)}px`;
}

function putType(drawn: Drawn, brand: BrandData, role: string, source: Source) {
  const style = typographyOf(brand, role);
  if (!style) return;
  put(drawn, "fontFamily", fontStack(brand, style), role, source);
  put(drawn, "fontSize", typeSize(brand, role, style.size), role, source);
  put(drawn, "fontWeight", String(style.weight), role, source);
  if (style.lineHeight !== null) put(drawn, "lineHeight", trim(style.lineHeight), role, source);
  if (style.letterSpacing !== null) put(drawn, "tracking", `${trim(style.letterSpacing)}em`, role, source);
}

/** The filled style the seller's site uses most, when the kit measured its button styles (looks()
 * orders each kind by use): the standard button is drawn from it. */
export function standardLook(brand: BrandData): Look | null {
  return buttonLooks(brand).find((look) => look.kind === "solid" && look.measured !== null) ?? null;
}

/** The parts the standard button takes from the most used filled style. */
const STANDARD_PARTS: readonly Part[] = [
  "fill", "label", "border", "borderWidth", "borderStyle", "radius", "padding", "height", "gap",
  "fontFamily", "fontSize", "fontWeight", "lineHeight", "tracking",
];

/** The kit's standard button: its brand surface with its pair, its button corners, its cta type;
 * the padding is site-kit's one fallback (no kit token holds it). When the kit measured the seller's
 * button styles, the most used filled one (standardLook) gives its fill, label, border, corners,
 * padding, height, font and icon gap instead. */
export function standardButton(brand: BrandData): Drawn {
  const drawn: Drawn = { parts: {}, tokens: {}, source: {} };
  const ink = inkRole(brand, "surface.brand");
  put(drawn, "fill", colorOf(brand, "surface.brand"), "surface.brand", "kit");
  put(drawn, "label", colorOf(brand, ink), ink, "kit");
  const radius = pxOf(brand, "radius.button");
  put(drawn, "radius", radius && four(radius), "radius.button", "kit");
  const [block, inline] = FALLBACKS.buttonPadding;
  put(drawn, "padding", `${block} ${inline} ${block} ${inline}`, undefined, "fallback");
  put(drawn, "decoration", FALLBACKS.controlDecoration, undefined, "fallback");
  putType(drawn, brand, "type.cta", "kit");
  const look = standardLook(brand);
  if (look) {
    const measured = partsFromSlots(brand, look.measured?.rest);
    const skip = (Object.keys(measured.parts) as Part[]).filter((part) => !STANDARD_PARTS.includes(part));
    apply(drawn, measured, "measured", skip);
  }
  const disabled = ratioOf(brand, "opacity.disabled");
  if (disabled) drawn.tokens.opacity = "opacity.disabled";
  return drawn;
}

/** A fill a label is read through rather than on: none, transparent, or less than half opaque (a
 * "glass" button, Tailwind's `bg-white/10`). Its label has to read on the surface behind it. */
export const isClearFill = (fill: string | undefined) =>
  !fill || fill === "transparent" || (fill.startsWith("#") && alphaOf(fill) < 0.5);

/** A fill and a label that were never seen together — one the standard button's, the other the
 * kit's or measured — and do not read together (4.5:1): the label becomes the text colour that reads
 * on that fill, the standard button's own label on the standard's fill, else the better of
 * text.primary and text.inverse, with source `readable` and the label it replaced kept in `replaced`
 * (brand.md says both). A pair from one source is never changed. */
function readableLabel(brand: BrandData, drawn: Drawn) {
  const { fill, label } = drawn.parts;
  const sources = [drawn.source.fill, drawn.source.label];
  const mixed = sources.includes("standard") && (sources.includes("kit") || sources.includes("measured"));
  if (!mixed || isClearFill(fill) || !fill?.startsWith("#") || !label?.startsWith("#")) return;
  if (contrast(fill.slice(0, 7), label.slice(0, 7)) >= 4.5) return;
  const std = standardButton(brand);
  const ink = readableInk(brand, fill.slice(0, 7));
  const [value, token] = drawn.source.fill === "standard" ? [std.parts.label, std.tokens.label] : [colorOf(brand, ink), ink];
  if (!value) return;
  drawn.replaced = { ...drawn.replaced, label: drawn.tokens.label ? `${label} (${drawn.tokens.label})` : label };
  put(drawn, "label", value, token, "readable");
}

/** How a look is drawn at rest. */
export function drawnButton(brand: BrandData, look: Look | null): Drawn {
  const drawn = standardButton(brand);
  if (!look) return drawn;
  for (const part of Object.keys(drawn.source) as Part[]) if (drawn.source[part] !== "fallback") drawn.source[part] = "standard";
  delete drawn.tokens.opacity;
  if (look.kind === "outline" || look.kind === "ghost") {
    put(drawn, "fill", "transparent", undefined, "none");
    put(drawn, "label", "inherit", undefined, "inherit");
  }
  if (look.kind === "outline") {
    put(drawn, "borderWidth", four(FALLBACKS.outlineWidth), undefined, "fallback");
    put(drawn, "borderStyle", "solid", undefined, "fallback");
    put(drawn, "border", "currentColor", undefined, "inherit");
  }
  apply(drawn, partsFromRecipe(brand, look.recipe), "kit");
  apply(drawn, partsFromSlots(brand, look.measured?.rest), "measured");
  readableLabel(brand, drawn);
  return drawn;
}

/** The kit's standard card. */
export function standardCard(brand: BrandData): Drawn {
  const drawn: Drawn = { parts: {}, tokens: {}, source: {} };
  const ink = inkRole(brand, "surface.card");
  put(drawn, "fill", colorOf(brand, "surface.card"), "surface.card", "kit");
  put(drawn, "label", colorOf(brand, ink), ink, "kit");
  const radius = pxOf(brand, "radius.card");
  put(drawn, "radius", radius && four(radius), "radius.card", "kit");
  const padding = numberOf(brand, "space.card.padding");
  put(drawn, "padding", padding && padding.unit === "px" ? fluid(padding.value) : undefined, "space.card.padding", "kit");
  put(drawn, "decoration", FALLBACKS.controlDecoration, undefined, "fallback");
  return drawn;
}

const CARD_SKIP: readonly Part[] = ["height", "gap", "fontFamily", "fontSize", "fontWeight", "lineHeight", "tracking", "case"];

export function drawnCard(brand: BrandData, look: Look | null): Drawn {
  const drawn = standardCard(brand);
  if (!look) return drawn;
  for (const part of Object.keys(drawn.source) as Part[]) if (drawn.source[part] !== "fallback") drawn.source[part] = "standard";
  if (look.kind === "ghost" || look.kind === "outline") {
    put(drawn, "fill", "transparent", undefined, "none");
    put(drawn, "label", "inherit", undefined, "inherit");
  }
  if (look.kind === "outline") {
    put(drawn, "borderWidth", four(FALLBACKS.outlineWidth), undefined, "fallback");
    put(drawn, "borderStyle", "solid", undefined, "fallback");
    put(drawn, "border", "currentColor", undefined, "inherit");
  }
  apply(drawn, partsFromRecipe(brand, look.recipe), "kit", CARD_SKIP);
  apply(drawn, partsFromSlots(brand, look.measured?.rest), "measured", CARD_SKIP);
  return drawn;
}

/** A text link takes its paragraph's font and box; a nav item keeps the measured font. */
const LINK_SKIP: readonly Part[] = ["fill", "border", "borderWidth", "borderStyle", "radius", "padding", "height", "gap", "fontFamily", "fontSize", "lineHeight"];
const NAV_SKIP: readonly Part[] = ["fill", "border", "borderWidth", "borderStyle", "radius", "padding", "height", "gap"];

export function drawnLink(brand: BrandData, component: "link" | "nav_link"): Drawn & { style: MeasuredRecipe | null } {
  const style = elementStyle(brand, component);
  const drawn: Drawn = { parts: {}, tokens: {}, source: {} };
  if (component === "link") put(drawn, "decoration", FALLBACKS.linkDecoration, undefined, "fallback");
  else putType(drawn, brand, "type.body", "kit");
  apply(drawn, partsFromSlots(brand, style?.rest), "measured", component === "link" ? LINK_SKIP : NAV_SKIP);
  return { ...drawn, style };
}

/** A recipe's measured transitions as one CSS `transition` value, for the box or for its icon. */
export function transitionsOf(brand: BrandData, recipe: MeasuredRecipe | null | undefined, target: "box" | "icon"): string | undefined {
  const steps = (recipe?.motion ?? [])
    .filter((m) => (target === "icon" ? m.target === "icon" : m.target !== "icon"))
    .flatMap((m) => {
      const duration = durationOf(brand, m.duration);
      const easing = easingOf(brand, m.easing);
      const delay = m.delay ? durationOf(brand, m.delay) : "0ms";
      return duration && easing && delay && /^(all|[a-z-]{1,60})$/.test(m.property) ? [`${m.property} ${duration} ${easing} ${delay}`] : [];
    });
  return steps.length ? steps.join(", ") : undefined;
}

export type DrawnIcon = { position: "start" | "end"; glyph?: string; svg?: string };

/** The icon's root `<svg>` at the size it was measured at on the seller's site. The seller's CSS often
 * sizes it (Tailwind's w-4 h-4, Font Awesome), so its captured markup has no size, or one the CSS
 * overrode, and it drew at 0x0 on our sites while the Brand page showed it (review S6-2). The
 * measured size replaces whatever width and height the root tag carried. */
function sizedSvg(markup: string, width: number, height: number): string {
  return markup.replace(/^<svg\b([^>]*)>/, (_tag, attributes: string) => {
    const rest = attributes.replace(/\s(?:width|height)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/g, "");
    return `<svg width="${width}" height="${height}"${rest}>`;
  });
}

/** The icon the seller's site draws in this button style, if the kit kept one. */
export function lookIcon(brand: BrandData, look: Look | null): DrawnIcon | null {
  const icon = look?.measured?.icon;
  if (!icon) return null;
  const value = styleOf(brand, icon.token);
  if (value?.kind === "glyph") return { position: icon.position, glyph: value.text };
  if (value?.kind === "svg") {
    // A kit written before icons were measured may carry no size: its markup is drawn as captured.
    const measured = [value.width, value.height].every((n) => typeof n === "number" && Number.isFinite(n) && n > 0);
    return { position: icon.position, svg: measured ? sizedSvg(value.markup, value.width, value.height) : value.markup };
  }
  return null;
}

export type MotionEntry = { className: string; token: string; kind: "animation" | "reveal"; css: string; describe: string; timing: string; where: string };
const KEYFRAME_PROPERTIES = new Set(["opacity", "transform", "translate", "scale", "rotate", "filter", "color", "background-color", "border-color", "box-shadow", "background-position"]);
const SAFE_VALUE = /^[A-Za-z0-9 ,.()%#+\-/]{1,200}$/;
const seconds = (ms: string) => (Number.parseFloat(ms) >= 1000 ? `${trim(Number.parseFloat(ms) / 1000)}s` : ms);

function describeMove(transform: string | null): string {
  const m = transform?.match(/^matrix\(([^)]+)\)$/);
  if (!m) return "";
  const [a, , , d, tx, ty] = m[1].split(",").map((n) => Number.parseFloat(n));
  const moves: string[] = [];
  if (ty) moves.push(`from ${trim(Math.abs(ty))}px ${ty > 0 ? "below" : "above"}`);
  if (tx) moves.push(`from ${trim(Math.abs(tx))}px to the ${tx > 0 ? "right" : "left"}`);
  const parts = moves.length ? [`moves into place ${moves.join(" and ")}`] : [];
  if (a === d && a && a !== 1) parts.push(`grows from ${trim(a * 100)}%`);
  return parts.join(" and ");
}

/** The kit's measured motion as classes an agent section may add (Wave 2 A9). Script-free CSS
 * only: keyframe animations as measured; a reveal as a scroll-driven animation from its measured
 * starting look (a published page cannot run the seller's script that started it). */
export function motionEntries(brand: BrandData): MotionEntry[] {
  const motion = measuredComponents(brand)?.motion;
  const entries: MotionEntry[] = [];
  for (const token of motion?.animations ?? []) {
    const value = styleOf(brand, token);
    const keyframes = value?.kind === "animation" ? styleOf(brand, value.keyframes) : undefined;
    if (value?.kind !== "animation" || keyframes?.kind !== "keyframes") continue;
    const slug = token.replace(/^motion\.animation\./, "");
    const duration = durationOf(brand, value.duration);
    const easing = easingOf(brand, value.easing);
    const delay = value.delay ? durationOf(brand, value.delay) : "0ms";
    if (!duration || !easing || !delay || !/^[a-z0-9-]+$/.test(slug)) continue;
    const frames = keyframes.frames.map((frame) => {
      const decls = Object.entries(frame.declarations).filter(([p, v]) => KEYFRAME_PROPERTIES.has(p) && SAFE_VALUE.test(v) && !/url\(|var\(/i.test(v));
      return `${trim(frame.offset)}%{${decls.map(([p, v]) => `${p}:${v}`).join(";")}}`;
    });
    const first = keyframes.frames[0]?.declarations ?? {};
    const last = keyframes.frames[keyframes.frames.length - 1]?.declarations ?? {};
    const changes = [...new Set([...Object.keys(first), ...Object.keys(last)])]
      .filter((p) => first[p] !== undefined && last[p] !== undefined && first[p] !== last[p])
      .map((p) => `${p} ${first[p]} → ${last[p]}`);
    const repeat = value.iterations === "infinite" ? "repeats forever" : Number(value.iterations) > 1 ? `plays ${value.iterations} times` : "plays once";
    const direction = value.direction.startsWith("alternate") ? ", alternating" : "";
    entries.push({
      className: `brand-motion-${slug}`, token, kind: "animation",
      css: `@keyframes brand-kf-${slug}{${frames.join("")}}`
        + `@media (prefers-reduced-motion:no-preference){.brand-motion-${slug}{animation:brand-kf-${slug} ${duration} ${easing} ${delay} ${value.iterations} ${value.direction} ${value.fill_mode}}}`,
      describe: `${changes.join(", ")}; ${repeat}${direction}`,
      timing: `${seconds(duration)} ${easing}`,
      where: tokenEntry(brand, "styles", token)?.description ?? "",
    });
  }
  for (const token of motion?.reveals ?? []) {
    const value = styleOf(brand, token);
    if (value?.kind !== "reveal") continue;
    const slug = token.replace(/^motion\.reveal\./, "");
    const easing = easingOf(brand, value.easing);
    const opacity = value.from_opacity ? ratioOf(brand, value.from_opacity) : undefined;
    const transform = value.from_transform ? transformOf(brand, value.from_transform) : undefined;
    if (!easing || !/^[0-9a-f]{8}$/.test(slug) || (opacity === undefined && !transform)) continue;
    const from = [opacity !== undefined ? `opacity:${opacity}` : "", transform ? `transform:${transform}` : ""].filter(Boolean).join(";");
    const said = [opacity !== undefined ? `fades in from opacity ${opacity}` : "", describeMove(transform ?? null)].filter(Boolean).join(" and ");
    entries.push({
      className: `brand-motion-reveal-${slug}`, token, kind: "reveal",
      css: `@keyframes brand-kf-reveal-${slug}{from{${from}}}`
        + `@supports (animation-timeline:view()){@media (prefers-reduced-motion:no-preference){.brand-motion-reveal-${slug}{animation:brand-kf-reveal-${slug} ${easing} both;animation-timeline:view();animation-range:entry 0% entry 100%}}}`,
      describe: `${said} as it scrolls into view`,
      timing: easing,
      where: tokenEntry(brand, "styles", token)?.description ?? "",
    });
  }
  return entries;
}

export const motionClassNames = (brand: BrandData) => motionEntries(brand).map((entry) => entry.className);

/** Motion the seller's site has that a script-free page cannot carry: named, never reproduced. */
export const motionNotes = (brand: BrandData) => measuredComponents(brand)?.motion?.scripted ?? [];
