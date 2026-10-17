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
  editsOf,
  editsProblems,
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
  assert.ok(colors.some((c) => c.token === "text.primary" && c.hex === "#0E1110"));
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
