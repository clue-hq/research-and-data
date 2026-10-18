// The _edits contract: one strict style override per element key, validated with the page and the
// shell, and checked against the brand (its colour tokens, its font families and their weights).
import assert from "node:assert/strict";
import { test } from "node:test";
import { z } from "zod";
import {
  EDITS_PROP,
  ELEMENT_KEY_ATTR,
  ElementKeySchema,
  SECTION_SCOPE_ATTR,
  SHELL_SCOPE,
  StyleOverrideSchema,
  brandColorChoices,
  brandFontFamilies,
  editsCss,
  editsOf,
  editsProblems,
  orderOf,
  withStyleOverride,
  withoutEdits,
} from "../src/edits";
import { PageSchema, ShellSchema, pageSchemaWith } from "../src/schemas";
import { validateSite } from "../src/validate";
import { garner, site as readSite } from "./fixtures/garner";
import { kitBrand } from "./fixtures/kits";

const brand = garner();

test("the names every later step shares", () => {
  assert.equal(EDITS_PROP, "_edits");
  assert.equal(ELEMENT_KEY_ATTR, "data-clue-el");
  assert.equal(SECTION_SCOPE_ATTR, "data-clue-section");
  assert.deepEqual(SHELL_SCOPE, { header: "shell-header", footer: "shell-footer" });
});

test("a valid override parses and an unknown property is refused", () => {
  assert.ok(StyleOverrideSchema.safeParse({ color: { token: "text.heading" }, fontSize: 48, fontWeight: 600, italic: true, textAlign: "center" }).success);
  assert.ok(StyleOverrideSchema.safeParse({ color: { hex: "#0F59B0", opacity: 80 }, underline: false }).success);
  assert.equal(StyleOverrideSchema.safeParse({ fontSize: 48, letterSpacing: 2 }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ color: { hex: "#0F59B0" } }).success, false); // opacity required
  assert.equal(StyleOverrideSchema.safeParse({ color: { token: "text.primary", hex: "#0F59B0", opacity: 50 } }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ color: { hex: "#0F59", opacity: 50 } }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ color: { hex: "#0F59B0", opacity: 101 } }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ fontWeight: 650 }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ fontSize: 7 }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ textAlign: "start" }).success, false);
});

test("element keys refuse anything that could break out of a selector", () => {
  for (const bad of ['"]{}body{', "", "-x", "a b", "x".repeat(101)]) assert.equal(ElementKeySchema.safeParse(bad).success, false, bad);
  for (const good of ["heading", "stats.2.value", "0.2.1", "nav.0", "my_title-2"]) assert.ok(ElementKeySchema.safeParse(good).success, good);
});

test("a styled span of highlighted words is its element's key plus ~<number>, and is drawn by data-s", () => {
  for (const good of ["heading~1", "0.2.1~12"]) assert.ok(ElementKeySchema.safeParse(good).success, good);
  for (const bad of ["heading~", "~1", "heading~x", "heading~1~2", "heading~12345"]) assert.equal(ElementKeySchema.safeParse(bad).success, false, bad);
  assert.equal(
    editsCss("hero", { "heading~1": { fontWeight: 700 } }, brand),
    '[data-clue-section="hero"] [data-s="heading~1"]{font-weight:700 !important}',
  );
});

test("editsOf reads a valid _edits and gives {} for none or an invalid one; withoutEdits drops it", () => {
  assert.deepEqual(editsOf({ heading: "Hi", _edits: { heading: { italic: true } } }), { heading: { italic: true } });
  assert.deepEqual(editsOf({ heading: "Hi" }), {});
  assert.deepEqual(editsOf({ _edits: { heading: { fontSize: 1 } } }), {});
  assert.deepEqual(withoutEdits({ id: "hero", _edits: { heading: { italic: true } } }), { id: "hero" });
});

test("withStyleOverride removes cleared properties and empty entries", () => {
  const a = withStyleOverride({}, "heading", { fontSize: 48, italic: true });
  assert.deepEqual(a, { heading: { fontSize: 48, italic: true } });
  assert.deepEqual(withStyleOverride(a, "heading", { fontSize: 48, italic: undefined }), { heading: { fontSize: 48 } });
  assert.deepEqual(withStyleOverride(a, "heading", {}), {});
  assert.deepEqual(withStyleOverride(a, "lead", { underline: true }), { heading: { fontSize: 48, italic: true }, lead: { underline: true } });
  assert.deepEqual(a, { heading: { fontSize: 48, italic: true } }, "the edits it was given are not changed");
});

const agent = { Hero: z.object({ id: z.string(), surface: z.string(), headline: z.string() }).strict() };
const heroPage = (edits: unknown) => ({
  root: { props: {} },
  content: [{ type: "Hero", props: { id: "hero", surface: "page", headline: "Hi", _edits: edits } }],
});

test("the page schema validates _edits beside any section's own props, including a strict agent schema", () => {
  assert.ok(pageSchemaWith(agent).safeParse(heroPage({ headline: { fontSize: 40 } })).success);
  const bad = pageSchemaWith(agent).safeParse(heroPage({ headline: { fontSize: 1 } }));
  assert.equal(bad.success, false);
  assert.deepEqual(bad.error!.issues[0].path.slice(0, 5), ["content", 0, "props", "_edits", "headline"]);
  const badKey = pageSchemaWith(agent).safeParse(heroPage({ '"]{}body{': { italic: true } }));
  assert.equal(badKey.success, false);
  assert.deepEqual(badKey.error!.issues[0].path.slice(0, 4), ["content", 0, "props", "_edits"]);
});

test("our own strict sections accept _edits too", () => {
  const home = structuredClone(readSite("garner-syracuse").pages["/"]);
  const ours = home.content.findIndex((item: { type: string }) => item.type !== "ClonedSection");
  assert.ok(ours >= 0, "the fixture has one of our sections");
  home.content[ours].props._edits = { heading: { fontWeight: 700 } };
  const result = PageSchema.safeParse(home);
  assert.ok(result.success, result.success ? "" : JSON.stringify(result.error.issues));
});

test("the shell's header and footer accept _edits", () => {
  const shell = structuredClone(readSite("garner-syracuse").shell);
  shell.header._edits = { preparedFor: { italic: true } };
  shell.footer._edits = { legal: { fontSize: 12, color: { hex: "#000000", opacity: 60 } } };
  assert.ok(ShellSchema.safeParse(shell).success);
  shell.footer._edits = { legal: { fontSize: 2 } };
  assert.equal(ShellSchema.safeParse(shell).success, false);
});

test("an entry for a key no element has is valid (the agent may have rewritten the section)", () => {
  assert.ok(pageSchemaWith(agent).safeParse(heroPage({ gone: { italic: true } })).success);
});

test("brand colours and font families, in kit order, weights ascending", () => {
  const colors = brandColorChoices(brand);
  assert.ok(colors.length > 0);
  assert.equal(colors[0].token, "focus.ring");
  assert.ok(colors.some((c) => c.token === "text.primary" && c.value === "#0E1110"));
  const measured = brandColorChoices(kitBrand("garner.v3")).map((c) => c.token);
  assert.equal(measured.length, new Set(measured).size);
  assert.ok(measured.includes("surface.band.014036"));
  assert.deepEqual(brandFontFamilies(brand), [
    { family: "Open Sans", weights: [400, 500, 600, 700] },
    { family: "Stix Two Text", weights: [400, 500, 600, 700] },
  ]);
  const nullWeight = { ...brand, fonts: [{ family: "Plain", weight: null, style: "normal", file: "plain.woff2" }] };
  assert.deepEqual(brandFontFamilies(nullWeight), [{ family: "Plain", weights: [400] }]);
});

test("brand checks: unknown token, non-brand family, missing weight", () => {
  const problems = editsProblems(
    {
      heading: { color: { token: "no.such" } },
      body: { fontFamily: "Comic Sans" },
      lead: { fontFamily: "Stix Two Text", fontWeight: 100 },
      fine: { color: { token: "text.primary" }, fontFamily: "Open Sans", fontWeight: 700, italic: true },
      hex: { color: { hex: "#123456", opacity: 40 }, fontWeight: 100 },
    },
    brand,
  );
  assert.equal(problems.length, 3, problems.join("\n"));
  assert.match(problems[0], /^heading: .*"no\.such"/);
  assert.match(problems[1], /^body: .*"Comic Sans"/);
  assert.match(problems[2], /^lead: .*100.*400, 500, 600, 700/);
});

test("validateSite reports _edits brand problems with their place", () => {
  const s = readSite("garner-syracuse");
  const home = structuredClone(s.pages["/"]);
  const id = home.content[0].props.id;
  home.content[0].props._edits = { heading: { color: { token: "no.such" } } };
  const shell = structuredClone(s.shell);
  shell.header._edits = { preparedFor: { fontFamily: "Comic Sans" } };
  const result = validateSite({ pages: { "/": home, "/analysis": s.pages["/analysis"] }, shell }, brand, {});
  assert.equal(result.valid, false);
  assert.equal(result.errors.length, 2, result.errors.join("\n"));
  assert.ok(result.errors[0].startsWith(`page.content.0(${id})._edits.heading: `), result.errors[0]);
  assert.ok(result.errors[1].startsWith("shell.header._edits.preparedFor: "), result.errors[1]);
});

test("validateSite reports a malformed _edits once, at its place", () => {
  const s = readSite("garner-syracuse");
  const home = structuredClone(s.pages["/"]);
  const id = home.content[0].props.id;
  home.content[0].props._edits = { heading: { fontSize: 1 } };
  const result = validateSite({ pages: { "/": home, "/analysis": s.pages["/analysis"] }, shell: s.shell }, brand, {});
  assert.equal(result.errors.length, 1, result.errors.join("\n"));
  assert.ok(result.errors[0].startsWith(`page.content.0(${id})._edits.heading.fontSize: `), result.errors[0]);
});

// Applying the edits (spec §4.5): one scoped stylesheet per section, beside it. Every declaration is
// !important because the clones' own CSS is unlayered and would beat a layered rule.
// The brief's "text.heading" is not a token of the Garner fixture kit; text.primary is, and has a
// root variable (--brand-ink-primary), which is what this test is about.
test("editsCss: tokens through the theme's variables, hex with opacity, important declarations", () => {
  const css = editsCss("hero", { heading: { color: { token: "text.primary" }, fontSize: 48, fontWeight: 600, italic: true, textAlign: "center" }, lead: { color: { hex: "#0F59B0", opacity: 80 } } }, brand);
  assert.match(css, /\[data-clue-section="hero"\] \[data-clue-el="heading"\]\{[^}]*color:var\(--brand-[^)]+\) !important/);
  assert.match(css, /font-size:48px !important/);
  assert.match(css, /\[data-clue-el="lead"\]\{color:#0F59B0CC !important\}/);
  assert.equal(
    css,
    '[data-clue-section="hero"] [data-clue-el="heading"]{color:var(--brand-ink-primary) !important;font-size:48px !important;font-weight:600 !important;font-style:italic !important;text-align:center !important}' +
      '[data-clue-section="hero"] [data-clue-el="lead"]{color:#0F59B0CC !important}',
  );
});

test("editsCss skips an unknown token and every invalid key or value, and returns '' for nothing", () => {
  assert.equal(editsCss("s", { heading: { color: { token: "gone" } } }, brand), "");
  assert.equal(editsCss("s", { '"]{}body{': { italic: true } } as never, brand), "");
  assert.equal(editsCss("s", {}, brand), "");
  assert.equal(editsCss("s", { heading: { fontSize: 1 } } as never, brand), "");
  assert.equal(editsCss("s", { heading: { color: { hex: "red", opacity: 50 } } } as never, brand), "");
  // A scope that is not a section id (or a shell scope) styles nothing either.
  assert.equal(editsCss('x"]{}body{', { heading: { italic: true } }, brand), "");
  assert.equal(editsCss("", { heading: { italic: true } }, brand), "");
});

test("editsCss: a component colour has no root variable, so it is written as the kit's colour", () => {
  const measured = kitBrand("garner.v3");
  assert.equal(editsCss("s", { label: { color: { token: "button.ghost-2d62ff.label" } } }, measured), '[data-clue-section="s"] [data-clue-el="label"]{color:#2D62FF !important}');
});

test("editsCss: a font family is quoted, with the kit's generic fallback or sans-serif; underline; opacity 0 and 100", () => {
  const css = editsCss("s", { a: { fontFamily: "Stix Two Text", underline: true }, b: { fontFamily: 'Odd"; } body {' } }, brand);
  assert.equal(
    css,
    '[data-clue-section="s"] [data-clue-el="a"]{font-family:"Stix Two Text", sans-serif !important;text-decoration-line:underline !important}' +
      '[data-clue-section="s"] [data-clue-el="b"]{font-family:"Odd body", sans-serif !important}',
  );
  const serifKit = structuredClone(brand);
  const fonts = (serifKit.kit as { assets: { fonts: Record<string, { fallback_stack?: string[] }> } }).assets.fonts;
  fonts.brand.fallback_stack = ["Georgia", "serif"];
  assert.match(editsCss("s", { a: { fontFamily: "Stix Two Text" } }, serifKit), /font-family:"Stix Two Text", serif !important/);
  assert.match(editsCss("s", { a: { color: { hex: "#0f59b0", opacity: 0 } }, b: { color: { hex: "#0F59B0", opacity: 100 } } }, brand), /color:#0F59B000 !important.*color:#0F59B0FF !important/);
});

test("editsCss: turning italic or underline off overrides text that has it by default", () => {
  const css = editsCss("hero", { quote: { italic: false, underline: false } }, brand);
  assert.match(css, /font-style:normal !important/);
  assert.match(css, /text-decoration-line:none !important/);
});

// Plan 2: the font library (the ad editor's ~27 families) after the brand's own fonts.
import { libraryFontFamilies } from "../src/edits";

const libraryBrand = {
  ...brand,
  libraryFonts: [
    { family: "Inter", category: "sans", faces: [{ weight: 400, style: "normal", file: "/asset-store/aa" }, { weight: 700, style: "normal", file: "/asset-store/bb" }] },
    { family: "Lora", category: "serif", faces: [{ weight: 400, style: "normal", file: "/asset-store/cc" }] },
    { family: "Open Sans", category: "sans", faces: [{ weight: 400, style: "normal", file: "/asset-store/dd" }] },
  ],
};

test("library families follow the brand's, each with its own weights; a family the brand has is the brand's", () => {
  assert.deepEqual(libraryFontFamilies(libraryBrand), [
    { family: "Inter", weights: [400, 700] },
    { family: "Lora", weights: [400] },
  ]);
  assert.deepEqual(libraryFontFamilies(brand), []);
});

test("a library family is accepted with its own weights; anything else is refused naming both lists", () => {
  const problems = editsProblems(
    { a: { fontFamily: "Inter", fontWeight: 700 }, b: { fontFamily: "Lora", fontWeight: 700 }, c: { fontFamily: "Comic Sans" } },
    libraryBrand,
  );
  assert.equal(problems.length, 2, problems.join("\n"));
  assert.match(problems[0], /^b: Lora has no weight 700; use one of its weights \(400\)/);
  assert.match(problems[1], /^c: "Comic Sans" is not one of this brand's font families or the font library's/);
});

test("a section that uses a library family carries that family's faces; one that does not carries none", () => {
  const css = editsCss("hero", { heading: { fontFamily: "Lora" }, lead: { fontFamily: "Lora", fontWeight: 400 } }, libraryBrand);
  assert.ok(css.startsWith('@font-face{font-family:"Lora";src:url("/asset-store/cc");font-weight:400;font-style:normal;font-display:swap}['), css);
  assert.equal(css.split("@font-face").length - 1, 1, "each family's faces once");
  assert.ok(css.includes('font-family:"Lora", serif !important'));
  assert.ok(!editsCss("hero", { heading: { fontFamily: "Open Sans" } }, libraryBrand).includes("@font-face"), "the brand's own family is loaded by the theme");
});

// Site element inspector, plan 3 (buttons): the box properties.
test("box properties parse within their ranges and shapes, and refuse anything else", () => {
  const ok = [
    { fill: { token: "text.primary" } }, { fill: { hex: "#0F59B0", opacity: 50 } }, { borderColor: { hex: "#000000", opacity: 100 } },
    { borderWidth: 0 }, { borderWidth: 200 }, { radius: 12 }, { radius: "pill" }, { radius: [0, 4, 8, 200] },
    { padding: 16 }, { padding: { y: 12, x: 22 } }, { width: "fit" }, { width: "fill" }, { width: 320 },
  ];
  for (const value of ok) assert.ok(StyleOverrideSchema.safeParse(value).success, JSON.stringify(value));
  const bad = [
    { borderWidth: -1 }, { borderWidth: 201 }, { radius: 300 }, { radius: "round" }, { radius: [1, 2, 3] }, { radius: [1, 2, 3, 400] },
    { padding: 201 }, { padding: { y: 1 } }, { padding: { y: 1, x: 2, z: 3 } }, { width: 0 }, { width: 2001 }, { width: "half" },
    { fill: "red" }, { background: { token: "x" } },
  ];
  for (const value of bad) assert.equal(StyleOverrideSchema.safeParse(value).success, false, JSON.stringify(value));
});

test("box properties are drawn as important CSS; a fill clears a gradient; a border width is solid", () => {
  assert.equal(
    editsCss("cta", { button: { fill: { hex: "#0F59B0", opacity: 100 }, borderColor: { hex: "#000000", opacity: 50 }, borderWidth: 2, radius: "pill", padding: { y: 12, x: 22 }, width: "fill" } }, brand),
    '[data-clue-section="cta"] [data-clue-el="button"]{background-color:#0F59B0FF !important;background-image:none !important;border-color:#00000080 !important;border-width:2px !important;border-style:solid !important;border-radius:9999px !important;padding:12px 22px !important;width:100% !important}',
  );
  assert.match(editsCss("cta", { button: { radius: [0, 4, 8, 16], padding: 10, width: "fit" } }, brand), /border-radius:0px 4px 8px 16px !important;padding:10px !important;width:fit-content !important/);
  assert.match(editsCss("cta", { button: { radius: 6, width: 240 } }, brand), /border-radius:6px !important;width:240px !important/);
  assert.match(editsCss("cta", { button: { fill: { token: "text.primary" } } }, brand), /background-color:var\(--brand-ink-primary\) !important/);
});

test("an unknown fill or stroke token is reported at its key", () => {
  const problems = editsProblems({ button: { fill: { token: "no.fill" }, borderColor: { token: "no.border" } } }, brand);
  assert.equal(problems.length, 2, problems.join("\n"));
  assert.match(problems[0], /^button: fill token "no\.fill" is not one of this brand's colours/);
  assert.match(problems[1], /^button: stroke colour token "no\.border" is not one of this brand's colours/);
});

// Plan 4: boxes. Gap, content alignment (stored with the CSS it set, ruling R3), the order of a box's
// children (applied to the markup, not drawn as CSS) and hidden (the header's and footer's parts only).
test("gap, contentAlign, order and hidden parse; out-of-range and wrong shapes are refused", () => {
  assert.ok(StyleOverrideSchema.safeParse({ gap: 12, contentAlign: { along: "row", to: "center" }, order: ["0.1", "0.0"], hidden: true }).success);
  assert.ok(StyleOverrideSchema.safeParse({ gap: 0 }).success);
  assert.equal(StyleOverrideSchema.safeParse({ gap: 201 }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ contentAlign: { along: "column", to: "center" } }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ contentAlign: { along: "row", to: "middle" } }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ contentAlign: { along: "row", to: "center", extra: 1 } }).success, false);
  const twice = StyleOverrideSchema.safeParse({ order: ["a", "a"] });
  assert.equal(twice.success, false);
  assert.match(JSON.stringify(twice.error?.issues), /each key once in an order/);
  assert.equal(StyleOverrideSchema.safeParse({ order: ["a~1"] }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ order: [] }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ order: Array.from({ length: 201 }, (_, i) => `k${i}`) }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ hidden: false }).success, false);
});

test("box CSS for containers: gap, each content alignment's own property, hidden; an order draws nothing", () => {
  assert.equal(
    editsCss("s1", { card: { gap: 12, contentAlign: { along: "stack", to: "center" }, hidden: true } }, brand),
    '[data-clue-section="s1"] [data-clue-el="card"]{gap:12px !important;align-items:center !important;display:none !important}',
  );
  const along = (value: "row" | "stack" | "grid" | "text", to: "start" | "center" | "end") =>
    editsCss("s1", { box: { contentAlign: { along: value, to } } }, brand);
  assert.match(along("row", "start"), /\{justify-content:flex-start !important\}/);
  assert.match(along("row", "end"), /\{justify-content:flex-end !important\}/);
  assert.match(along("stack", "end"), /\{align-items:flex-end !important\}/);
  assert.match(along("grid", "center"), /\{justify-items:center !important\}/);
  assert.match(along("grid", "start"), /\{justify-items:start !important\}/);
  assert.match(along("text", "end"), /\{text-align:right !important\}/);
  assert.match(along("text", "start"), /\{text-align:left !important\}/);
  assert.equal(editsCss("s1", { box: { order: ["box.1", "box.0"] } }, brand), "");
});

test("orderOf lists the order of every key that has one", () => {
  assert.deepEqual(orderOf({ a: { order: ["a.1", "a.0"] }, b: { gap: 4 }, c: { order: ["c.2"] } }), { a: ["a.1", "a.0"], c: ["c.2"] });
  assert.deepEqual(orderOf({}), {});
});

test("hidden is refused on a page section and accepted on the shell", () => {
  const s = readSite("garner-syracuse");
  const home = structuredClone(s.pages["/"]);
  const id = home.content[0].props.id;
  home.content[0].props._edits = { logo: { hidden: true } };
  const shell = structuredClone(s.shell);
  shell.header._edits = { logo: { hidden: true } };
  shell.footer._edits = { privacy: { hidden: true } };
  const result = validateSite({ pages: { "/": home, "/analysis": s.pages["/analysis"] }, shell }, brand, {});
  assert.equal(result.errors.length, 1, result.errors.join("\n"));
  assert.equal(
    result.errors[0],
    `page.content.0(${id})._edits.logo: hidden is for the header and footer; to drop a part of a section, rewrite the section`,
  );
});
