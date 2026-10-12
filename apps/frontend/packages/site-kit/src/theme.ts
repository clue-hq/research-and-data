// Brand kit -> one theme stylesheet (Wave 2 A9).
//
// Per-brand values are emitted as `--brand-*` custom properties on `.brand-root`; tailwindThemeCss()
// maps them into Tailwind v4 theme variables (`@theme inline`), so sections use fixed class names
// (`text-headline`, `bg-surface-brand`, `py-section`) and the brand decides the values. Buttons,
// cards, links and motion are drawn from the kit's measured recipes (looks.ts). Every value is the
// kit's (brand-values.ts) or one of FALLBACKS; clones keep their own captured CSS.
import type { BrandData } from "./brand";
import {
  FALLBACKS, alphaOf, colorOf, contrast, fluid, fontStack, hexOf, isComponentToken, isMeasured, numberOf,
  pxOf, ratioOf, tokenEntry, tokenGroups, trim, typographyOf,
} from "./brand-values";
import {
  STATES, buttonLooks, cardLooks, drawnButton, drawnCard, drawnLink, elementStyle, motionEntries,
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

/** CSS declarations for a set of parts: the box's and its icon's. A colour that a dark surface swaps
 * reads that surface's value first (`--bs-<id>-<part>`), so the NEAREST surface decides. Outlines are
 * drawn on :focus-visible only, so a look with no focus style leaves the browser's ring alone. */
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

/** Where a button would not stand out on a surface (text 4.5:1, WCAG 1.4.3; a filled shape 3:1,
 * WCAG 1.4.11). Outline and text-only styles take the surface's text colour on ANY surface, light or
 * dark, where their own label would fail (a white ghost measured on a dark hero, used on a white
 * page); their border too when it is the label's colour. Filled styles take the light version (the
 * kit's page colour with its text colour) on dark surfaces only. */
function buttonSwaps(brand: BrandData, drawn: Drawn, surfaces: string[], dark: string[]): Swaps {
  const swaps: Swaps = { parts: new Set(), bySurface: new Map() };
  const fill = drawn.parts.fill;
  const clear = !fill || fill === "transparent" || (fill.startsWith("#") && alphaOf(fill) === 0);
  for (const surface of surfaces) {
    const bg = hexOf(brand, surface);
    if (!bg) continue;
    const on = `var(--brand-on-${colorVar(surface)})`;
    let swap: Swap | null = null;
    const label = drawn.parts.label;
    if (clear && label?.startsWith("#") && contrast(label.slice(0, 7), bg) < 4.5) {
      swap = { label: on, ...(drawn.parts.border === label ? { border: on } : {}) };
    } else if (!clear && dark.includes(surface) && fill?.startsWith("#") && contrast(fill.slice(0, 7), bg) < 3) {
      swap = {
        fill: "var(--brand-button-light-fill)", label: "var(--brand-button-light-label)",
        ...(drawn.parts.border ? { border: "var(--brand-button-light-fill)" } : {}),
      };
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
    lines.push(`@font-face{font-family:"${face.family}";src:url("${face.file}");font-weight:${face.weight ?? 400};font-style:${face.style};font-display:swap}`);
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
  root["--brand-button-light-fill"] = "var(--brand-surface-page)";
  root["--brand-button-light-label"] = "var(--brand-on-surface-page)";

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
  const swaps = new Map(buttons.map((b) => [b.id, buttonSwaps(brand, b.drawn, surfaces, dark)]));
  // A text link whose colour fails 4.5:1 on a surface, light or dark, takes that surface's text colour.
  const link = drawnLink(brand, "link");
  const linkSwap = new Map<string, string>();
  for (const surface of surfaces) {
    const bg = hexOf(brand, surface);
    const color = link.parts.label;
    if (bg && color?.startsWith("#") && contrast(color.slice(0, 7), bg) < 4.5) linkSwap.set(surface, `var(--brand-on-${colorVar(surface)})`);
  }
  for (const surface of surfaces) {
    const vars = local.get(surface)!;
    for (const [id, s] of swaps) for (const part of s.parts) vars[`--bs-${id}-${part}`] = s.bySurface.get(surface)?.[part as keyof Swap] ?? "initial";
    if (linkSwap.size) vars["--bs-link-color"] = linkSwap.get(surface) ?? "initial";
  }

  lines.push(rule(".brand-root", { ...root, ...(local.get("surface.page") ?? {}) }));
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
  for (const look of cardLooks(brand)) {
    const selector = `.brand-card.brand-card-look-${look.index}`;
    components.push(rule(selector, { ...declarations(drawnCard(brand, look).parts).box, transition: transitionsOf(brand, look.measured, "box") }));
    for (const state of ["hover", "pressed", "focus"] as State[]) {
      const parts = partsFromSlots(brand, look.measured?.states?.[state]).parts;
      components.push(rule(`a${selector}${STATE_SELECTOR[state]}`, declarations(parts, { outline: state === "focus" }).box));
    }
  }
  const linkParts: Parts = { ...link.parts };
  const linkDecl = declarations(linkParts).box;
  if (linkParts.label) linkDecl.color = linkSwap.size ? `var(--bs-link-color,${linkParts.label})` : linkParts.label;
  components.push(rule(".brand-link", { ...linkDecl, transition: transitionsOf(brand, link.style, "box") }));
  const nav = drawnLink(brand, "nav_link");
  components.push(rule(".brand-navlink", { ...declarations(nav.parts).box, transition: transitionsOf(brand, nav.style, "box") }));
  for (const [selector, style] of [[".brand-link", elementStyle(brand, "link")], [".brand-navlink", elementStyle(brand, "nav_link")]] as const) {
    for (const state of ["hover", "pressed", "focus"] as State[]) {
      const parts = partsFromSlots(brand, style?.states?.[state]).parts;
      const decl = declarations(parts, { outline: state === "focus" }).box;
      if (selector === ".brand-link" && parts.label && linkSwap.size) decl.color = `var(--bs-link-color,${parts.label})`;
      components.push(rule(`${selector}${STATE_SELECTOR[state]}`, decl));
    }
  }
  lines.push(`@layer components{${components.filter(Boolean).join("")}}`);

  for (const entry of motionEntries(brand)) lines.push(entry.css);
  lines.push(
    '@media (prefers-reduced-motion:reduce),print{.brand-btn,.brand-btn-icon,.brand-link,.brand-navlink,.brand-card{transition:none!important}[class*="brand-motion-"]{animation:none!important}}',
  );
  return lines.filter(Boolean).join("\n");
}

/** The Tailwind v4 mapping of the `--brand-*` variables this theme emits, as one `@theme inline`
 * block (per brand: the kit's extra surfaces and spacing add utilities). The design API's server CSS
 * compile prepends `@import "tailwindcss";` and compiles it over a site's rendered HTML (Task 17). */
export function tailwindThemeCss(brand: BrandData): string {
  const lines: string[] = [];
  for (const surface of surfaceRoles(brand)) lines.push(`--color-on-${colorVar(surface)}: var(--brand-on-${colorVar(surface)});`);
  for (const role of [...COLOR_ROLES, ...extraSurfaceRoles(brand)]) lines.push(`--color-${colorVar(role)}: var(--brand-${colorVar(role)});`);
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
  for (const role of SPACING_ROLES) {
    if (numberOf(brand, `space.${role}`)) lines.push(`--spacing-${spacingVar(role)}: var(--brand-space-${spacingVar(role)});`);
  }
  return `@theme inline {\n${lines.map((line) => `  ${line}`).join("\n")}\n}\n`;
}
