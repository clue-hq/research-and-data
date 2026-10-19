// No unreadable text or invisible button on any surface (Wave 2 A9, Task FX-A): what a visitor sees
// is computed from the generated stylesheet itself — each rule's colours, with every `var()` resolved
// through the surface's own rule and `.brand-root`, the way the cascade resolves them.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "../src/brand";
import { alphaOf, contrast, hexOf } from "../src/brand-values";
import { buildCatalog } from "../src/catalog";
import { buttonLooks, cardLooks, drawnButton, elementStyle, lookNamed } from "../src/looks";
import { inkRole, isDarkSurface, readableInk } from "../src/surfaces";
import { colorVar, surfaceRoles, themeCss } from "../src/theme";
import { kitBrand, type KitName } from "./fixtures/kits";

const ruleOf = (css: string, selector: string) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return css.match(new RegExp(`(?:^|[}\\n])${escaped}\\{[^}]*\\}`))?.[0] ?? "";
};
const declarationsOf = (rule: string): Record<string, string> => {
  const out: Record<string, string> = {};
  for (const declaration of rule.slice(rule.indexOf("{") + 1, rule.lastIndexOf("}")).split(";")) {
    const colon = declaration.indexOf(":");
    if (colon > 0) out[declaration.slice(0, colon)] = declaration.slice(colon + 1);
  }
  return out;
};

/** A copy of a fixture brand with colour tokens set to hex values (the fixture file is never touched). */
const withColors = (brand: BrandData, colours: Record<string, string>): BrandData => {
  const copy = structuredClone(brand);
  const tokens = (copy.kit as { tokens: { colors: Record<string, { value: Record<string, unknown> }> } }).tokens.colors;
  for (const [token, hex] of Object.entries(colours)) {
    assert.ok(tokens[token], `no colour token ${token}`);
    tokens[token] = { ...tokens[token], value: { ...tokens[token].value, default: { kind: "hex", value: hex } } };
  }
  return copy;
};
const measuredRest = (brand: BrandData, component: string, variant: string) =>
  (brand.kit as { measured_components: { styles: { component: string; variant: string; rest: Record<string, string> }[] } })
    .measured_components.styles.find((s) => s.component === component && s.variant === variant)!.rest;

/** The stylesheet as a visitor's browser reads it, inside a section on one surface. */
function cascade(brand: BrandData) {
  const css = themeCss(brand);
  const root = declarationsOf(ruleOf(css, ".brand-root"));
  const resolve = (value: string | undefined, scopes: Record<string, string>[], depth = 0): string | undefined => {
    if (value === undefined || depth > 20) return undefined;
    const call = /^var\((--[A-Za-z0-9-]+)(?:,(.*))?\)$/s.exec(value.trim());
    if (!call) return value.trim();
    const found = scopes.map((scope) => scope[call[1]]).find((v) => v !== undefined);
    if (found !== undefined && found.trim() !== "initial") return resolve(found, scopes, depth + 1);
    return call[2] === undefined ? undefined : resolve(call[2], scopes, depth + 1);
  };
  const on = (surface: string) => {
    const scopes = [declarationsOf(ruleOf(css, `.bg-${colorVar(surface)}`)), root];
    return {
      bg: resolve(`var(--brand-${colorVar(surface)})`, scopes)!,
      ink: resolve(`var(--brand-on-${colorVar(surface)})`, scopes)!,
      value: (v: string | undefined) => resolve(v, scopes),
    };
  };
  /** What an element of `selector` (more specific rules first) shows on `surface`. */
  const seen = (selectors: string[], surface: string) => {
    const s = on(surface);
    const rules = selectors.map((selector) => declarationsOf(ruleOf(css, selector)));
    const pick = (property: string) => rules.map((r) => r[property]).find((v) => v !== undefined);
    const fill = s.value(pick("background-color"));
    const colour = s.value(pick("color"));
    const clear = !fill || fill === "transparent" || (fill.startsWith("#") && alphaOf(fill) < 0.5);
    const label = !colour || colour === "inherit" ? s.ink : colour;
    return { fill, label, clear, inherits: !colour || colour === "inherit", backdrop: clear ? s.bg : fill!.slice(0, 7), surfaceBg: s.bg };
  };
  return { css, on, seen };
}
const ratio = (a: string, b: string) => contrast(a.slice(0, 7), b.slice(0, 7));

// A seller whose site is dark: the page is near black, the inverse surface white.
const darkSeller = () => withColors(kitBrand("probe.minted"), {
  "surface.page": "#0B0B0B", "text.primary": "#F5F5F5", "text.inverse": "#0B0B0B", "surface.inverse": "#FFFFFF",
});
// The same seller as ingestion writes its kit: a contrast pair names the text colour the site showed on
// that background, so the pairs probe.minted carries for its light site (surface.brand and the
// #014036 band → text.inverse, white there) name the light text here, text.primary. Without this the
// edit above leaves the kit claiming #0B0B0B is the text on its own #047464 brand surface.
const darkSellerAsIngested = () => {
  const brand = darkSeller();
  const pairs = (brand.kit as { constraints: { contrast_pairs: { background: string; foreground: string }[] } }).constraints.contrast_pairs;
  for (const pair of pairs) {
    const bg = hexOf(brand, pair.background)!;
    if (ratio(hexOf(brand, pair.foreground)!, bg) < 4.5) pair.foreground = readableInk(brand, bg)!;
  }
  return brand;
};
// A seller whose header is dark, with white nav items.
const whiteNav = () => {
  const probe = kitBrand("probe.minted");
  return withColors(probe, { [elementStyle(probe, "nav_link")!.rest.label]: "#FFFFFF" });
};
// A "glass" button measured on a dark hero: white at 10% (Tailwind `bg-white/10`), white label.
const glass = () => {
  const probe = kitBrand("probe.minted");
  const rest = measuredRest(probe, "button", "solid.7c4cff");
  return withColors(probe, { [rest.fill]: "#FFFFFF1A", [rest.label]: "#FFFFFF" });
};

test("A1: on a dark-themed brand a filled look's light version stands out from the dark page", () => {
  const brand = darkSeller();
  const { css, on } = cascade(brand);
  const page = on("surface.page");
  assert.equal(page.bg, "#0B0B0B");
  const swapped = Object.entries(declarationsOf(ruleOf(css, ".bg-surface-page"))).filter(([name, v]) => /^--bs-[a-z0-9]+-fill$/.test(name) && v !== "initial");
  assert.ok(swapped.length >= 2, `filled looks that vanish on the dark page swap there: ${swapped.join(" ")}`);
  for (const [name] of swapped) {
    assert.equal(page.value(`var(${name})`), "#FFFFFF", `${name} resolves to the inverse colour, never the page colour`);
    const label = page.value(`var(${name.replace(/-fill$/, "-label")})`)!;
    assert.ok(ratio(label, "#FFFFFF") >= 4.5, `${name}'s label ${label} reads on it`);
  }
  assert.doesNotMatch(css, /--brand-button-light-/);
});

test("A2: a nav link whose colour would vanish on a surface takes that surface's text colour, like a text link", () => {
  const { css, on } = cascade(whiteNav());
  assert.match(ruleOf(css, ".bg-surface-page"), /--bs-nav-color:var\(--brand-on-surface-page\)/);
  assert.match(ruleOf(css, ".brand-navlink"), /color:var\(--bs-nav-color,#FFFFFF\)/);
  assert.ok(ratio(on("surface.page").value(declarationsOf(ruleOf(css, ".brand-navlink")).color)!, on("surface.page").bg) >= 4.5);
});

test("A3: a text-only card takes the surface's text colour where its own would vanish; brand.md says what the card's text is", () => {
  const brand = kitBrand("conduit");
  const index = lookNamed(brand, "card", "ghost.1")!.index;
  const { css } = cascade(brand);
  assert.match(ruleOf(css, ".bg-surface-inverse"), new RegExp(`--bs-card-${index}-label:var\\(--brand-on-surface-inverse\\)`));
  assert.match(ruleOf(css, `.brand-card.brand-card-look-${index}`), new RegExp(`color:var\\(--bs-card-${index}-label,#29251E\\)`));
  const md = buildCatalog(brand, "Conduit")["brand/brand.md"];
  assert.ok(md.includes("| look | kind | fill | text | border | corners | padding | confidence | notes from the brand kit |"), md);
  assert.ok(md.includes("| ghost.1 | text only | none | #29251E (text.primary) | none | 0px (radius.none) |"), md);
});

test("A4: a fill and a label from different sources that do not read together: the label is the one that reads on the fill", () => {
  // conduit's "Primary demo CTA": the recipe's white label, drawn on the standard button's light cyan.
  const conduit = kitBrand("conduit");
  const demo = drawnButton(conduit, lookNamed(conduit, "button", "solid.2"));
  const std = drawnButton(conduit, null);
  assert.equal(demo.parts.fill, "#7CE4FC");
  assert.deepEqual([demo.parts.label, demo.tokens.label, demo.source.label], [std.parts.label, std.tokens.label, "readable"]);
  assert.equal(demo.replaced?.label, "#FFFFFF (text.inverse)");
  assert.ok(ratio(demo.parts.label!, "#7CE4FC") >= 4.5);
  // A measured light fill with no measured label: the better of the kit's two text colours.
  const probe = kitBrand("probe.minted");
  const lightFill = withColors(probe, { [measuredRest(probe, "button", "solid.7c4cff").fill]: "#F5F5F5" });
  delete measuredRest(lightFill, "button", "solid.7c4cff").label;
  const light = drawnButton(lightFill, lookNamed(lightFill, "button", "solid.7c4cff"));
  assert.deepEqual([light.parts.label, light.tokens.label, light.source.label], ["#0E1110", "text.primary", "readable"]);
  assert.equal(light.replaced?.label, "#FFFFFF (text.inverse)", "the standard button's label it replaced");
  // A pair the seller drew (fill and label both measured) is drawn as measured, readable or not.
  const drawnPair = withColors(probe, { [measuredRest(probe, "button", "solid.7c4cff").fill]: "#F5F5F5" });
  const pair = drawnButton(drawnPair, lookNamed(drawnPair, "button", "solid.7c4cff"));
  assert.deepEqual([pair.parts.label, pair.source.label], ["#FFFFFF", "measured"]);
});

test("A5: a translucent fill is a clear fill: its label takes the surface's text colour where it would vanish", () => {
  const brand = glass();
  const index = lookNamed(brand, "button", "solid.7c4cff")!.index;
  const { css } = cascade(brand);
  const lookRule = ruleOf(css, `.brand-btn.brand-look-${index}`);
  assert.match(lookRule, /[{;]background-color:#FFFFFF1A[;}]/, "the fill itself is drawn as measured");
  assert.match(lookRule, new RegExp(`[{;]color:var\\(--bs-${index}-label,#FFFFFF\\)`), lookRule);
  assert.match(ruleOf(css, ".bg-surface-page"), new RegExp(`--bs-${index}-label:var\\(--brand-on-surface-page\\)`));
});

// The audit. On every surface of every kit, after the swaps:
//   (1) every clear button look's and clear card look's text, (2) the text link's and the nav link's
//   colour, and (3) every filled button's label on its fill all read at 4.5:1 or better; and (4) every
//   light version a swap draws stands out from its surface at 3:1 (a filled button's shape).
// (3) checks every filled button whose pair is not the seller's own (so every mixed-source pair the
// standard button completes, every kit-token pair and every light version), and excludes only pairs
// the seller drew themselves — fill and label both measured, drawn as measured by ruling: in the
// fixtures conduit.minted solid.28241e (#28241E/#FFFFFF), garner.minted solid.ffffff (#FFFFFF/#0D2B25)
// and probe.minted solid.047464, solid.0a4a8a, solid.28241e and solid.7c4cff (each with #FFFFFF), and
// those same probe pairs in the three variants below. A seller's pair that a dark surface swaps for its
// light version is no longer the seller's, and is checked.
const KITS: [string, () => BrandData][] = [
  ...(["garner", "conduit", "altcarbon", "garner.minted", "conduit.minted", "probe.minted"] as KitName[]).map((name) => [name, () => kitBrand(name)] as [string, () => BrandData]),
  ["probe.minted, dark-themed", darkSellerAsIngested], ["probe.minted, white nav", whiteNav], ["probe.minted, glass button", glass],
];

test("audit: no unreadable text or invisible button label on any surface of any kit", () => {
  const failures: string[] = [];
  const checked = { clearButton: 0, clearCard: 0, link: 0, nav: 0, filled: 0, lightVersion: 0, sellerPairs: 0 };
  for (const [name, make] of KITS) {
    const brand = make();
    const { seen } = cascade(brand);
    const buttons = [{ name: "(standard)", selectors: [".brand-btn"], drawn: drawnButton(brand, null) }, ...buttonLooks(brand).map((look) => ({
      name: look.name, selectors: [`.brand-btn.brand-look-${look.index}`, ".brand-btn"], drawn: drawnButton(brand, look),
    }))];
    for (const surface of surfaceRoles(brand)) {
      const where = `${name} on ${surface}`;
      for (const b of buttons) {
        const v = seen(b.selectors, surface);
        if (v.clear) {
          checked.clearButton += 1;
          if (ratio(v.label, v.backdrop) < 4.5) failures.push(`${where}: clear button ${b.name} text ${v.label} on ${v.backdrop} ${ratio(v.label, v.backdrop).toFixed(2)}`);
          continue;
        }
        const sellers = b.drawn.source.fill === "measured" && b.drawn.source.label === "measured" && v.fill === b.drawn.parts.fill && v.label === b.drawn.parts.label;
        if (sellers) { checked.sellerPairs += 1; continue; }
        checked.filled += 1;
        if (ratio(v.label, v.backdrop) < 4.5) failures.push(`${where}: filled button ${b.name} label ${v.label} on its fill ${v.backdrop} ${ratio(v.label, v.backdrop).toFixed(2)}`);
        if (v.fill === b.drawn.parts.fill) continue;
        checked.lightVersion += 1;
        if (ratio(v.fill!, v.surfaceBg) < 3) failures.push(`${where}: filled button ${b.name}'s light version ${v.fill} on ${v.surfaceBg} ${ratio(v.fill!, v.surfaceBg).toFixed(2)}`);
      }
      for (const look of cardLooks(brand)) {
        const v = seen([`.brand-card.brand-card-look-${look.index}`, ".brand-card"], surface);
        if (!v.clear) continue;
        checked.clearCard += 1;
        if (ratio(v.label, v.backdrop) < 4.5) failures.push(`${where}: clear card ${look.name} text ${v.label} on ${v.backdrop} ${ratio(v.label, v.backdrop).toFixed(2)}`);
      }
      for (const [selector, key] of [[".brand-link", "link"], [".brand-navlink", "nav"]] as const) {
        const v = seen([selector], surface);
        if (v.inherits) continue;
        checked[key] += 1;
        if (ratio(v.label, v.surfaceBg) < 4.5) failures.push(`${where}: ${selector} ${v.label} on ${v.surfaceBg} ${ratio(v.label, v.surfaceBg).toFixed(2)}`);
      }
    }
  }
  assert.deepEqual(failures, [], failures.join("\n"));
  for (const [key, n] of Object.entries(checked)) assert.ok(n > 0, `the audit checked no ${key}`);
});

test("S6-1: a band whose stored text colour does not read takes the readable one, everywhere inkRole is read", () => {
  // probe.minted pairs text.band.ffffff (#111111) with surface.band.ffffff; make the stored text the
  // orange eyebrow the capture used to take (#F5A623 on white is 2.0:1).
  const brand = withColors(kitBrand("probe.minted"), { "text.band.ffffff": "#F5A623" });
  assert.equal(inkRole(brand, "surface.band.ffffff"), "text.primary");
  const band = cascade(brand).on("surface.band.ffffff");
  assert.ok(ratio(band.ink, band.bg) >= 4.5, `${band.ink} on ${band.bg}`);
});

test("S6-1: a dark band whose stored text is a card's dark grey takes the light text, and is dark", () => {
  const brand = withColors(kitBrand("probe.minted"), { "surface.band.ffffff": "#0B2545", "text.band.ffffff": "#222222" });
  assert.equal(inkRole(brand, "surface.band.ffffff"), "text.inverse");
  assert.equal(isDarkSurface(brand, "surface.band.ffffff"), true);
});

test("S6-1: a stored text colour that reads is kept", () => {
  assert.equal(inkRole(kitBrand("probe.minted"), "surface.band.ffffff"), "text.band.ffffff");
});

test("S6-1: an oklch pair is left to the existing choice (no hex, no contrast maths)", () => {
  const brand = structuredClone(kitBrand("probe.minted"));
  const colors = (brand.kit as { tokens: { colors: Record<string, { value: Record<string, unknown> }> } }).tokens.colors;
  colors["text.band.ffffff"] = { ...colors["text.band.ffffff"], value: { ...colors["text.band.ffffff"].value, default: { kind: "oklch", l: 0.2, c: 0, h: 0 } } };
  assert.doesNotThrow(() => inkRole(brand, "surface.band.ffffff"));
});
