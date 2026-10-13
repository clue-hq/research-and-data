// The theme is drawn from the kit (Wave 2 A9): measured recipes first, tokens second, named
// fallbacks last; states, dark surfaces, links, cards and motion included.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "../src/brand";
import { colorOf } from "../src/brand-values";
import { buildCatalog } from "../src/catalog";
import { lintOptionsFor } from "../src/check-section";
import { buttonLooks, elementStyle, lookNamed } from "../src/looks";
import { surfaceChoices } from "../src/surfaces";
import { tailwindThemeCss, themeCss } from "../src/theme";
import { kitBrand } from "./fixtures/kits";

const ruleOf = (css: string, selector: string) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return css.match(new RegExp(`(?:^|[}\\n])${escaped}\\{[^}]*\\}`))?.[0] ?? "";
};

/** A copy of a fixture brand with one colour token set to a hex value (the fixture file is never touched). */
const withColor = (brand: BrandData, token: string, hex: string): BrandData => {
  const copy = structuredClone(brand);
  const colors = (copy.kit as { tokens: { colors: Record<string, { value: Record<string, unknown> }> } }).tokens.colors;
  assert.ok(colors[token], `no colour token ${token}`);
  colors[token] = { ...colors[token], value: { ...colors[token].value, default: { kind: "hex", value: hex } } };
  return copy;
};

test("Conduit's demo button: the kit's own fill when measured, surface.brand only in the old kit", () => {
  for (const [name, fill, look] of [["conduit.minted", "#28241E", "solid.28241e"], ["conduit", "#7CE4FC", "solid.2"]] as const) {
    const brand = kitBrand(name);
    const index = lookNamed(brand, "button", look)!.index;
    const css = themeCss(brand);
    const lookRule = ruleOf(css, `.brand-btn.brand-look-${index}`);
    assert.match(lookRule, new RegExp(`background-color:(var\\(--bs-${index}-fill,)?${fill}`), lookRule);
    if (name === "conduit.minted") assert.doesNotMatch(lookRule, /7CE4FC/);
  }
});

test("a filled look that would vanish on a dark surface takes the light version there, and only there", () => {
  const brand = kitBrand("conduit.minted");
  const index = lookNamed(brand, "button", "solid.28241e")!.index;
  const css = themeCss(brand);
  // Of the page (#FFFFFF) and the inverse surface (#121212), the page stands out from the #28241E band.
  const band = ruleOf(css, ".bg-surface-band-28241e");
  assert.match(band, new RegExp(`--bs-${index}-fill:var\\(--brand-surface-page\\)`));
  assert.match(band, new RegExp(`--bs-${index}-label:var\\(--brand-on-surface-page\\)`));
  assert.match(ruleOf(css, ".bg-surface-page"), new RegExp(`--bs-${index}-fill:initial`));
});

test("an outline look on a dark band takes the band's text colour", () => {
  const brand = kitBrand("garner.minted");
  const index = lookNamed(brand, "button", "outline.1")!.index;
  assert.match(ruleOf(themeCss(brand), ".bg-surface-band-014036"), new RegExp(`--bs-${index}-label:var\\(--brand-on-surface-band-014036\\)`));
});

test("a text-only look whose label would vanish on a light surface takes that surface's text colour", () => {
  const brand = kitBrand("conduit");
  const index = lookNamed(brand, "button", "ghost.1")!.index;
  assert.match(ruleOf(themeCss(brand), ".bg-surface-page"), new RegExp(`--bs-${index}-label:var\\(--brand-on-surface-page\\)`));
});

test("a text link whose colour would vanish on a light surface takes that surface's text colour", () => {
  const probe = kitBrand("probe.minted");
  const brand = withColor(probe, elementStyle(probe, "link")!.rest.label, "#FFFFFF");
  assert.match(ruleOf(themeCss(brand), ".bg-surface-page"), /--bs-link-color:var\(--brand-on-surface-page\)/);
});

test("a state that clears the fill draws a transparent fill", () => {
  const probe = kitBrand("probe.minted");
  const brand = withColor(probe, lookNamed(probe, "button", "solid.047464")!.measured!.states.hover!.fill, "#00000000");
  const index = lookNamed(brand, "button", "solid.047464")!.index;
  assert.match(ruleOf(themeCss(brand), `.brand-btn.brand-look-${index}:hover`), new RegExp(`background-color:(var\\(--bs-${index}-fill,)?#00000000`));
});

test("every measured state is drawn: hover, press, focus, disabled, transitions and the icon", () => {
  const brand = kitBrand("probe.minted");
  const look = buttonLooks(brand).find((l) => colorOf(brand, l.measured?.rest.fill) === "#047464")!;
  const sel = `.brand-btn.brand-look-${look.index}`;
  const css = themeCss(brand);
  assert.match(ruleOf(css, `${sel}:hover`), /background-color:(var\(--bs-\d+-fill,)?#035A4E/);
  assert.match(ruleOf(css, `${sel}:hover`), /box-shadow:0px 4px 12px 0px #00000033/);
  assert.match(ruleOf(css, `${sel}:active`), /transform:matrix\(0\.98, 0, 0, 0\.98, 0, 0\)/);
  const focus = ruleOf(css, `${sel}:focus-visible`);
  for (const part of ["outline-color:#F5A623", "outline-width:3px", "outline-style:solid", "outline-offset:2px"]) assert.ok(focus.includes(part), focus);
  const disabled = ruleOf(css, `${sel}[aria-disabled="true"]`);
  assert.ok(disabled.includes("opacity:0.45") && disabled.includes("cursor:not-allowed"), disabled);
  assert.ok(ruleOf(css, sel).includes("transition:background-color 200ms ease-out 0ms, transform 150ms ease 0ms, box-shadow 300ms ease 50ms"));
  assert.ok(ruleOf(css, `${sel} .brand-btn-icon`).includes("transition:transform 200ms ease 0ms"));
  assert.ok(ruleOf(css, `${sel}:hover .brand-btn-icon`).includes("transform:matrix(1, 0, 0, 1, 4, 0)"));
  assert.ok(ruleOf(css, sel).includes("text-transform:uppercase"));
});

test("a look with no focus style of its own leaves the browser's focus ring alone", () => {
  const brand = kitBrand("probe.minted");
  const js = buttonLooks(brand).find((l) => colorOf(brand, l.measured?.rest.fill) === "#7C4CFF")!;
  assert.equal(ruleOf(themeCss(brand), `.brand-btn.brand-look-${js.index}:focus-visible`), "");
});

test("the standard button draws the kit's tokens and names its one fallback", () => {
  const std = ruleOf(themeCss(kitBrand("conduit")), ".brand-btn");
  assert.ok(std.includes("background-color:var(--bs-std-fill,#7CE4FC)") || std.includes("background-color:#7CE4FC"), std);
  assert.ok(std.includes("border-radius:8px 8px 8px 8px"), std);
  assert.ok(std.includes("padding:0.75em 1.5em 0.75em 1.5em"), std);
});

test("text links, cards, type colours and rules come from the kit", () => {
  const probe = themeCss(kitBrand("probe.minted"));
  assert.match(ruleOf(probe, ".brand-link"), /text-decoration-line:none/);
  const hover = ruleOf(probe, ".brand-link:hover");
  assert.match(hover, /color:(var\(--bs-link-color,)?#047464/);
  assert.ok(hover.includes("text-decoration-line:underline") && hover.includes("text-decoration-thickness:2px"), hover);
  const garner = themeCss(kitBrand("garner"));
  assert.match(ruleOf(garner, ".brand-link"), /text-decoration-line:underline/);
  assert.match(ruleOf(garner, ".bg-surface-page"), /--brand-ink-role-headline:var\(--brand-ink-primary\)/);
  assert.match(ruleOf(garner, ".bg-surface-page"), /--brand-ink-role-eyebrow:initial/, "text.brand is derived, not measured");
  assert.match(ruleOf(garner, ".bg-surface-inverse"), /--brand-ink-role-headline:initial/);
  assert.match(ruleOf(garner, ".brand-card"), /background-color:#F9FAF8/);
  assert.match(garner, /\.brand-rule-t\{border-top:var\(--brand-rule-width\) solid var\(--brand-rule-color\)\}/);
});

test("measured motion becomes classes, and nothing moves for visitors who ask for less", () => {
  const css = themeCss(kitBrand("probe.minted"));
  assert.ok(css.includes("@keyframes brand-kf-pulse{0%{opacity:1;transform:scale(1)}50%{opacity:.7}100%{opacity:.4;transform:scale(1.2)}}"), css);
  assert.match(css, /@media \(prefers-reduced-motion:no-preference\)\{\.brand-motion-pulse\{animation:brand-kf-pulse 1600ms ease-in-out 0ms infinite alternate none\}\}/);
  assert.match(css, /@supports \(animation-timeline:view\(\)\)\{@media \(prefers-reduced-motion:no-preference\)\{\.brand-motion-reveal-[0-9a-f]{8}\{animation:brand-kf-reveal-[0-9a-f]{8} ease-out both;animation-timeline:view\(\);animation-range:entry 0% entry 100%\}\}\}/);
  assert.match(css, /@media \(prefers-reduced-motion:reduce\),print\{[^}]*\{transition:none!important\}\[class\*="brand-motion-"\]\{animation:none!important\}\}/);
});

test("the Tailwind mapping covers every surface the kit has, the kit's spacing and nothing twice", () => {
  const css = tailwindThemeCss(kitBrand("garner.minted"));
  for (const line of [
    "--color-surface-band-014036: var(--brand-surface-band-014036);",
    "--color-on-surface-band-014036: var(--brand-on-surface-band-014036);",
    "--color-ink-secondary: var(--brand-ink-secondary);",
    "--text-body-small--line-height: var(--brand-text-body-small-lh);",
    "--radius-card: var(--brand-radius-card);",
    "--spacing-section: var(--brand-space-section);",
    "--spacing-stack-tight: var(--brand-space-stack-tight);",
    "--spacing-card-padding: var(--brand-space-card-padding);",
  ]) assert.ok(css.includes(line), line);
  assert.equal(css.split("--color-surface-page:").length, 2);
});

// E1: kit strings reach a <style> element; none may close it or leave its CSS string or rule.
const HOSTILE_FAMILY = 'A"; } </style><script>alert(1)</script>';
type FontKit = {
  tokens: { typography: Record<string, { value: { default: { font_family: string } } }>; colors: Record<string, unknown> };
  assets: { fonts: Record<string, { fallback_stack: string[] }> };
};

test("E1: a font family cannot close the stylesheet, in @font-face or in a font stack", () => {
  const brand = structuredClone(kitBrand("probe.minted"));
  const kit = brand.kit as FontKit;
  kit.tokens.typography["type.headline"].value.default.font_family = HOSTILE_FAMILY;
  kit.assets.fonts.brand.fallback_stack = ["Arial", "x</style><img src=x onerror=alert(1)>", "sans-serif"];
  brand.fonts = [{ family: HOSTILE_FAMILY, weight: 400, style: "normal", file: "/asset-store/abc123" }];
  const css = themeCss(brand);
  assert.doesNotMatch(css, /<\/style/i);
  assert.doesNotMatch(css, /<script/i);
  const face = /@font-face\{font-family:"([^"]*)";src:url\("\/asset-store\/abc123"\);/.exec(css);
  assert.ok(face, css.split("\n")[0]);
  assert.doesNotMatch(face[1], /[";}]/);
  assert.equal(face[1], "A /stylescriptalert(1)/script");
  assert.ok(css.includes('--brand-font-headline:"A /stylescriptalert(1)/script", "Arial", "x/styleimg src=x onerror=alert(1)", sans-serif;'), css);
});

test("E1: a font family that is empty once cleaned is skipped", () => {
  const brand = structuredClone(kitBrand("probe.minted"));
  (brand.kit as FontKit).tokens.typography["type.headline"].value.default.font_family = '"<;>"';
  brand.fonts = [{ family: "<{}>", weight: 400, style: "normal", file: "/asset-store/abc123" }];
  const css = themeCss(brand);
  assert.ok(!css.includes("@font-face"), css.split("\n")[0]);
  assert.ok(css.includes('--brand-font-headline:"Arial", sans-serif;'), css);
});

test("E1: a font face whose file is not a relative asset path is skipped whole", () => {
  const brand = structuredClone(kitBrand("probe.minted"));
  brand.fonts = [
    { family: "Probe Sans", weight: 400, style: "normal", file: 'x") ; } </style>' },
    { family: "Probe Sans", weight: 700, style: "normal", file: "/asset-store/abc123" },
  ];
  const css = themeCss(brand);
  assert.doesNotMatch(css, /<\/style/i);
  const faces = css.split("\n").filter((line) => line.startsWith("@font-face"));
  assert.deepEqual(faces, ['@font-face{font-family:"Probe Sans";src:url("/asset-store/abc123");font-weight:700;font-style:normal;font-display:swap}']);
});

test("E1: a token key outside the engine's token-path charset reaches no selector, variable or class", () => {
  const brand = structuredClone(kitBrand("probe.minted"));
  (brand.kit as FontKit).tokens.colors["surface.x</style>{"] = { value: { default: { kind: "hex", value: "#123456" } } };
  const files = buildCatalog(brand, "Seller");
  const emitted: [string, string][] = [
    ["themeCss", themeCss(brand)],
    ["tailwindThemeCss", tailwindThemeCss(brand)],
    ["surface choices", JSON.stringify(surfaceChoices(brand))],
    ["lint options", JSON.stringify(lintOptionsFor(brand))],
    ["brand.md", files["brand/brand.md"]],
    ["sections.md", files["catalog/sections.md"]],
  ];
  for (const [where, text] of emitted) {
    assert.ok(!text.includes("</style>") && !text.includes("x</style>{"), `${where} carries the hostile key`);
  }
  // The kit's real extra surface is still drawn.
  assert.ok(themeCss(brand).includes(".bg-surface-band-014036{"));
});
