// Brand kit -> one theme stylesheet (Wave 2 A9).
//
// Per-brand values are emitted as `--brand-*` custom properties on `.brand-root`; tailwindThemeCss()
// maps them into Tailwind v4 theme variables (`@theme inline`), so sections use fixed class names
// (`text-headline`, `bg-surface-brand`, `py-section`) and the brand decides the values. Buttons,
// cards, links and motion are drawn from the kit's measured recipes (looks.ts). Every value is the
// kit's (brand-values.ts) or one of FALLBACKS; clones keep their own captured CSS.
import type { BrandData } from "./brand";
import {
  FALLBACKS, colorOf, contrast, cssString, fluid, fontStack, hexOf, isComponentToken, isMeasured, numberOf,
  pxOf, ratioOf, tokenEntry, tokenGroups, trim, typographyOf,
} from "./brand-values";
import {
  STATES, buttonLooks, cardLooks, drawnButton, drawnCard, drawnLink, isClearFill, motionEntries,
  partsFromSlots, transitionsOf, type Drawn, type Look, type Part, type Parts, type State,
} from "./looks";
import { COLOR_ROLES, SURFACES, colorVar, extraSurfaceRoles, inkRole, isDarkSurface, surfaceRoles } from "./surfaces";

export { COLOR_ROLES, SURFACES, colorVar, extraSurfaceRoles, surfaceRoles };

export const TYPE_ROLES = [
  "display", "headline", "title", "subtitle", "body", "body.small",
  "eyebrow", "cta", "stat", "label", "caption", "legal",
] as const;
export const RADIUS_ROLES = ["none", "xs", "sm", "md", "lg", "xl", "card", "button", "badge", "full"] as const;
/** The kit's named spacing, as Tailwind utilities (`py-section`, `mt-stack-tight`, `p-card-padding`). */
export const SPACING_ROLES = ["section", "page.margin", "stack.tight", "stack.default", "stack.loose", "card.padding"] as const;
export const typeVar = (role: string) => role.replace(/\./g, "-");
export const spacingVar = typeVar;

const STATE_SELECTOR: Record<State, string> = { hover: ":hover", pressed: ":active", focus: ":focus-visible", disabled: '[aria-disabled="true"]' };
const CSS_OF: Record<Part, string> = {
  fill: "background-color", label: "color", border: "border-color", borderWidth: "border-width", borderStyle: "border-style",
  radius: "border-radius", padding: "padding", height: "min-height", gap: "gap", fontFamily: "font-family",
  fontSize: "font-size", fontWeight: "font-weight", lineHeight: "line-height", tracking: "letter-spacing",
  case: "text-transform", decoration: "text-decoration-line", decorationThickness: "text-decoration-thickness",
  underlineOffset: "text-underline-offset", shadow: "box-shadow", opacity: "opacity", transform: "transform",
  filter: "filter", cursor: "cursor", outlineColor: "outline-color", outlineWidth: "outline-width",
  outlineStyle: "outline-style", outlineOffset: "outline-offset", iconColor: "color", iconTransform: "transform",
  iconOpacity: "opacity",
};
const ICON_PARTS = new Set<Part>(["iconColor", "iconTransform", "iconOpacity"]);
/** A relative asset path: the only font file a face's url("…") may hold. */
const ASSET_PATH = /^[A-Za-z0-9._~/-]+$/;
/** The only values a face's font-style and font-weight are written with. */
const FONT_STYLES = new Set(["normal", "italic", "oblique"]);
const fontWeightOk = (weight: unknown) =>
  weight === null || weight === undefined || (typeof weight === "number" && Number.isFinite(weight) && weight >= 1 && weight <= 1000);
const OUTLINE_PARTS = new Set<Part>(["outlineColor", "outlineWidth", "outlineStyle", "outlineOffset"]);
type Swap = Partial<Record<"fill" | "label" | "border", string>>;
type Swaps = { parts: Set<Part>; bySurface: Map<string, Swap> };

function body(props: Record<string, string | undefined>): string {
  return Object.entries(props).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => `${k}:${v}`).join(";");
}
function rule(selector: string, props: Record<string, string | undefined>): string {
  const text = body(props);
  return text ? `${selector}{${text}}` : "";
}

/** CSS declarations for a set of parts: the box's and its icon's. A colour that a surface swaps reads
 * that surface's value first (`--bs-<id>-<part>`), so the NEAREST surface decides. Outlines are drawn
 * on :focus-visible only, so a look with no focus style leaves the browser's ring alone. */
function declarations(parts: Parts, opts: { swaps?: Swaps; id?: string; outline?: boolean } = {}) {
  const box: Record<string, string> = {};
  const icon: Record<string, string> = {};
  for (const [part, value] of Object.entries(parts) as [Part, string][]) {
    if (OUTLINE_PARTS.has(part) && !opts.outline) continue;
    const css = opts.swaps?.parts.has(part) ? `var(--bs-${opts.id}-${part},${value})` : value;
    (ICON_PARTS.has(part) ? icon : box)[CSS_OF[part]] = css;
  }
  return { box, icon };
}

const inkOn = (surface: string) => `var(--brand-on-${colorVar(surface)})`;

/** Where a text colour would not stand out on a surface, light or dark (4.5:1, WCAG 1.4.3): that
 * surface's text colour, by surface. Text links, nav links and the labels of clear looks. */
function textSwaps(brand: BrandData, color: string | undefined, surfaces: string[]): Map<string, string> {
  const swaps = new Map<string, string>();
  for (const surface of surfaces) {
    const bg = hexOf(brand, surface);
    if (bg && color?.startsWith("#") && contrast(color.slice(0, 7), bg) < 4.5) swaps.set(surface, inkOn(surface));
  }
  return swaps;
}

/** A filled button's light version on a dark surface: of the kit's page and inverse surfaces, the one
 * that stands out more from this surface (a dark-themed seller's page is itself dark). */
function lightVersion(brand: BrandData, bg: string): string | undefined {
  return ["surface.page", "surface.inverse"]
    .filter((role) => hexOf(brand, role) && colorOf(brand, inkRole(brand, role)))
    .sort((a, b) => contrast(hexOf(brand, b)!, bg) - contrast(hexOf(brand, a)!, bg))[0];
}

/** Where a button or a card would not stand out on a surface (text 4.5:1, WCAG 1.4.3; a filled shape
 * 3:1, WCAG 1.4.11). A clear look (isClearFill: no fill, transparent, or under half opaque) takes the
 * surface's text colour on ANY surface, light or dark, where its own label would fail (a white ghost
 * measured on a dark hero, used on a white page); its border too when it is the label's colour. A
 * filled button (`filled`) takes its light version on dark surfaces only; a filled card is drawn as
 * the kit draws it. */
function lookSwaps(brand: BrandData, drawn: Drawn, surfaces: string[], dark: string[], filled: boolean): Swaps {
  const swaps: Swaps = { parts: new Set(), bySurface: new Map() };
  const { fill, label, border } = drawn.parts;
  const clear = isClearFill(fill);
  const labels = clear ? textSwaps(brand, label, surfaces) : new Map<string, string>();
  for (const surface of surfaces) {
    const bg = hexOf(brand, surface);
    if (!bg) continue;
    let swap: Swap | null = null;
    const on = labels.get(surface);
    if (on) {
      swap = { label: on, ...(border === label ? { border: on } : {}) };
    } else if (!clear && filled && dark.includes(surface) && fill?.startsWith("#") && contrast(fill.slice(0, 7), bg) < 3) {
      const light = lightVersion(brand, bg);
      if (light) swap = { fill: `var(--brand-${colorVar(light)})`, label: inkOn(light), ...(border ? { border: `var(--brand-${colorVar(light)})` } : {}) };
    }
    if (!swap) continue;
    swaps.bySurface.set(surface, swap);
    for (const part of Object.keys(swap) as Part[]) swaps.parts.add(part);
  }
  return swaps;
}

export function themeCss(brand: BrandData): string {
  const lines: string[] = [];
  for (const face of brand.fonts) {
    // A face is written only with a relative asset path for its file, a plain style and a numeric weight;
    // otherwise the whole face is skipped.
    const family = cssString(face.family);
    if (!family || !ASSET_PATH.test(face.file) || !FONT_STYLES.has(face.style) || !fontWeightOk(face.weight)) continue;
    lines.push(`@font-face{font-family:"${family}";src:url("${face.file}");font-weight:${face.weight ?? 400};font-style:${face.style};font-display:swap}`);
  }

  const root: Record<string, string> = {};
  // Every colour of the kit, except the minted component colours (drawn inline below).
  for (const role of Object.keys(tokenGroups(brand).colors ?? {})) {
    const value = isComponentToken(role) ? undefined : colorOf(brand, role);
    if (value) root[`--brand-${colorVar(role)}`] = value;
  }
  for (const role of TYPE_ROLES) {
    const style = typographyOf(brand, `type.${role}`);
    if (!style) continue;
    const name = typeVar(role);
    root[`--brand-font-${name}`] = fontStack(brand, style);
    root[`--brand-text-${name}`] = fluid(style.size);
    if (style.lineHeight !== null) root[`--brand-text-${name}-lh`] = trim(style.lineHeight);
    root[`--brand-text-${name}-weight`] = String(style.weight);
    if (style.letterSpacing !== null) root[`--brand-text-${name}-tracking`] = `${trim(style.letterSpacing)}em`;
  }
  for (const role of RADIUS_ROLES) {
    const value = pxOf(brand, `radius.${role}`);
    if (value) root[`--brand-radius-${role}`] = value;
  }
  for (const role of SPACING_ROLES) {
    const value = numberOf(brand, `space.${role}`);
    if (value && value.unit === "px") root[`--brand-space-${spacingVar(role)}`] = fluid(value.value);
  }
  const surfaces = surfaceRoles(brand);
  for (const surface of surfaces) {
    const ink = inkRole(brand, surface);
    if (ink && colorOf(brand, ink)) root[`--brand-on-${colorVar(surface)}`] = `var(--brand-${colorVar(ink)})`;
  }
  root["--brand-content-width"] = FALLBACKS.contentWidth;
  root["--brand-rule-width"] = pxOf(brand, "stroke.width.divider") ?? FALLBACKS.ruleWidth;

  // Per surface: type colours, the rule colour, and every swap the surface needs.
  const dark = surfaces.filter((surface) => isDarkSurface(brand, surface));
  const local = new Map<string, Record<string, string>>(surfaces.map((surface) => [surface, {}]));
  const mutedShare = ratioOf(brand, "opacity.muted");
  for (const surface of surfaces) {
    const vars = local.get(surface)!;
    const isDark = dark.includes(surface);
    for (const role of TYPE_ROLES) {
      const colorRole = typographyOf(brand, `type.${role}`)?.color;
      const usable = !isDark && !!colorRole && !!colorOf(brand, colorRole) && isMeasured(tokenEntry(brand, "colors", colorRole));
      vars[`--brand-ink-role-${typeVar(role)}`] = usable ? `var(--brand-${colorVar(colorRole!)})` : "initial";
    }
    vars["--brand-rule-color"] = isDark
      ? mutedShare ? `color-mix(in srgb, currentColor ${trim(Number(mutedShare) * 100)}%, transparent)` : "currentColor"
      : colorOf(brand, "border.subtle") ? "var(--brand-line-subtle)" : "currentColor";
  }
  const buttons: { id: string; selector: string; drawn: Drawn; look: Look | null }[] = [
    { id: "std", selector: ".brand-btn", drawn: drawnButton(brand, null), look: null },
    ...buttonLooks(brand).map((look) => ({ id: String(look.index), selector: `.brand-btn.brand-look-${look.index}`, drawn: drawnButton(brand, look), look })),
  ];
  const cards = cardLooks(brand).map((look) => ({ id: `card-${look.index}`, drawn: drawnCard(brand, look), look }));
  const swaps = new Map([
    ...buttons.map((b) => [b.id, lookSwaps(brand, b.drawn, surfaces, dark, true)] as const),
    ...cards.map((c) => [c.id, lookSwaps(brand, c.drawn, surfaces, dark, false)] as const),
  ]);
  // A text link or a nav link whose colour fails 4.5:1 on a surface takes that surface's text colour.
  const links = ([[".brand-link", "link", "--bs-link-color"], [".brand-navlink", "nav_link", "--bs-nav-color"]] as const).map(([selector, component, variable]) => {
    const drawn = drawnLink(brand, component);
    const swap = textSwaps(brand, drawn.parts.label, surfaces);
    return { selector, variable, drawn, swap, color: (value: string) => (swap.size ? `var(${variable},${value})` : value) };
  });
  for (const surface of surfaces) {
    const vars = local.get(surface)!;
    for (const [id, s] of swaps) for (const part of s.parts) vars[`--bs-${id}-${part}`] = s.bySurface.get(surface)?.[part as keyof Swap] ?? "initial";
    for (const l of links) if (l.swap.size) vars[l.variable] = l.swap.get(surface) ?? "initial";
  }

  // The root paints the page itself (walk defect 4): a gap between sections, or a section that sets no
  // surface, shows the brand's page colour and text, never the browser's default canvas.
  // Painting a background made the root cover a clone's background layers drawn at a negative
  // z-index (Garner's hero video sits at z-index:-4; the hero showed as a grey box, 2026-10-16):
  // isolation makes the root their stacking context, so they paint above its background and
  // below the section's content, as they do on the seller's own page.
  const paintsPage = colorOf(brand, "surface.page") !== undefined;
  lines.push(rule(".brand-root", {
    ...root, ...(local.get("surface.page") ?? {}),
    "background-color": paintsPage ? `var(--brand-${colorVar("surface.page")})` : undefined,
    color: paintsPage ? inkOn("surface.page") : undefined,
    isolation: "isolate",
  }));
  for (const surface of surfaces) lines.push(rule(`.bg-${colorVar(surface)}`, local.get(surface)!));
  for (const role of TYPE_ROLES) lines.push(`.brand-ink-${typeVar(role)}{color:var(--brand-ink-role-${typeVar(role)},currentColor)}`);
  lines.push(
    ".brand-heading{color:var(--brand-ink-role-headline,currentColor)}",
    ".brand-rule-t{border-top:var(--brand-rule-width) solid var(--brand-rule-color)}",
    ".brand-rule-b{border-bottom:var(--brand-rule-width) solid var(--brand-rule-color)}",
    ".brand-rule-v{align-self:stretch;width:var(--brand-rule-width);background-color:var(--brand-rule-color)}",
    ".brand-content{max-width:var(--brand-content-width);margin-inline:auto}",
    `.brand-logo-header{height:${FALLBACKS.headerLogoHeight}}`,
    `.brand-logo-footer{height:${FALLBACKS.footerLogoHeight}}`,
  );

  // Components live in the components layer so Tailwind utilities (hidden, sm:inline-flex…) can
  // still override them, as they would any component class.
  const components: string[] = [".brand-btn-icon{display:inline-flex}"];
  for (const b of buttons) {
    const s = swaps.get(b.id)!;
    const rest = declarations(b.drawn.parts, { swaps: s, id: b.id });
    const layout = b.look ? {} : { display: "inline-flex", "align-items": "center", "justify-content": "center", "white-space": "nowrap" };
    components.push(rule(b.selector, { ...layout, ...rest.box, transition: transitionsOf(brand, b.look?.measured, "box") }));
    components.push(rule(`${b.selector} .brand-btn-icon`, { ...rest.icon, transition: transitionsOf(brand, b.look?.measured, "icon") }));
    if (!b.look) {
      const disabled = ratioOf(brand, "opacity.disabled");
      if (disabled) components.push(rule(`${b.selector}[aria-disabled="true"]`, { opacity: disabled }));
      continue;
    }
    for (const state of STATES) {
      const parts = partsFromSlots(brand, b.look.measured?.states?.[state]).parts;
      const drawn = declarations(parts, { swaps: s, id: b.id, outline: state === "focus" });
      components.push(rule(`${b.selector}${STATE_SELECTOR[state]}`, drawn.box), rule(`${b.selector}${STATE_SELECTOR[state]} .brand-btn-icon`, drawn.icon));
    }
  }
  components.push(rule(".brand-card", { display: "block", ...declarations(drawnCard(brand, null).parts).box }));
  for (const c of cards) {
    const s = swaps.get(c.id)!;
    const selector = `.brand-card.brand-card-look-${c.look.index}`;
    components.push(rule(selector, { ...declarations(c.drawn.parts, { swaps: s, id: c.id }).box, transition: transitionsOf(brand, c.look.measured, "box") }));
    for (const state of ["hover", "pressed", "focus"] as State[]) {
      const parts = partsFromSlots(brand, c.look.measured?.states?.[state]).parts;
      components.push(rule(`a${selector}${STATE_SELECTOR[state]}`, declarations(parts, { swaps: s, id: c.id, outline: state === "focus" }).box));
    }
  }
  for (const l of links) {
    const decl = declarations(l.drawn.parts).box;
    if (l.drawn.parts.label) decl.color = l.color(l.drawn.parts.label);
    components.push(rule(l.selector, { ...decl, transition: transitionsOf(brand, l.drawn.style, "box") }));
  }
  for (const l of links) {
    for (const state of ["hover", "pressed", "focus"] as State[]) {
      const parts = partsFromSlots(brand, l.drawn.style?.states?.[state]).parts;
      const decl = declarations(parts, { outline: state === "focus" }).box;
      if (parts.label) decl.color = l.color(parts.label);
      components.push(rule(`${l.selector}${STATE_SELECTOR[state]}`, decl));
    }
  }
  lines.push(`@layer components{${components.filter(Boolean).join("")}}`);

  for (const entry of motionEntries(brand)) lines.push(entry.css);
  lines.push(
    '@media (prefers-reduced-motion:reduce),print{.brand-btn,.brand-btn-icon,.brand-link,.brand-navlink,.brand-card{transition:none!important}[class*="brand-motion-"]{animation:none!important}}',
  );
  return lines.filter(Boolean).join("\n");
}

/** The document's own canvas (walk defect 4): the brand page colour and its text on `html`, so
 * overscroll and the space under a short page never show the browser's default — near black in a
 * dark-mode browser — and `color-scheme` tells the browser which way to draw its own controls.
 * Literal values: the `--brand-*` variables are declared on `.brand-root`, which `html` cannot see.
 * Empty for a kit with no page colour. */
export function pageCanvasCss(brand: BrandData): string {
  const page = colorOf(brand, "surface.page");
  if (!page) return "";
  return rule("html", {
    "background-color": page,
    color: colorOf(brand, inkRole(brand, "surface.page")),
    "color-scheme": isDarkSurface(brand, "surface.page") ? "dark" : "light",
  });
}

/** One `@theme inline` block mapping Tailwind's names onto the `--brand-*` variables. The published
 * page and the editor canvas both build theirs here, so a brand setting can never be named on one and
 * forgotten on the other (review finding K5-2: the canvas had none of the brand's spacing). */
function themeBlock(onSurfaces: readonly string[], colorRoles: readonly string[], spacingRoles: readonly string[]): string {
  const lines: string[] = [];
  for (const surface of onSurfaces) lines.push(`--color-on-${colorVar(surface)}: var(--brand-on-${colorVar(surface)});`);
  for (const role of colorRoles) lines.push(`--color-${colorVar(role)}: var(--brand-${colorVar(role)});`);
  for (const role of TYPE_ROLES) {
    const name = typeVar(role);
    lines.push(
      `--font-${name}: var(--brand-font-${name});`,
      `--text-${name}: var(--brand-text-${name});`,
      `--text-${name}--line-height: var(--brand-text-${name}-lh);`,
      `--text-${name}--font-weight: var(--brand-text-${name}-weight);`,
      `--text-${name}--letter-spacing: var(--brand-text-${name}-tracking);`,
    );
  }
  for (const role of RADIUS_ROLES) lines.push(`--radius-${role}: var(--brand-radius-${role});`);
  for (const role of spacingRoles) lines.push(`--spacing-${spacingVar(role)}: var(--brand-space-${spacingVar(role)});`);
  return `@theme inline {\n${lines.map((line) => `  ${line}`).join("\n")}\n}\n`;
}

/** The Tailwind v4 mapping of the `--brand-*` variables this theme emits, as one `@theme inline`
 * block (per brand: the kit's extra surfaces and spacing add utilities). The design API's server CSS
 * compile prepends `@import "tailwindcss";` and compiles it over a site's rendered HTML (Task 17). */
export function tailwindThemeCss(brand: BrandData): string {
  return themeBlock(
    surfaceRoles(brand),
    [...COLOR_ROLES, ...extraSurfaceRoles(brand)],
    SPACING_ROLES.filter((role) => numberOf(brand, `space.${role}`)),
  );
}

/** The editor canvas's mapping: compiled once, when the editor is built, for every brand, so it
 * declares every role (a brand without a value leaves its variable unset, which draws as the
 * published page does without the utility). A kit's extra surfaces are painted at runtime instead
 * (site-editor's surfaceUtilityCss). */
export function editorThemeCss(): string {
  return themeBlock(SURFACES, COLOR_ROLES, SPACING_ROLES);
}
