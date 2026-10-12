// Our sections take the brand's surfaces and button styles by name (founder rulings 4, 6; Q4 = (b)).
import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { lookNamed } from "../src/looks";
import { makeConfig } from "../src/config";
import { makeSections } from "../src/sections";
import { validateSite } from "../src/validate";
import { garner, site } from "./fixtures/garner";
import { kitBrand } from "./fixtures/kits";

const href = (v: string) => v;
type Field = { label: string; options?: { label: string; value: string }[] };
const fields = (brand: ReturnType<typeof kitBrand>) => makeSections(brand, href).FeatureSplit.fields as unknown as Record<string, Field>;

test("the Button style field lists Standard and then this brand's styles, by kind", () => {
  assert.deepEqual(fields(kitBrand("garner")).buttonLook.options!.map((o) => o.label), ["Standard", "Outline", "Text only", "Filled 1", "Filled 2", "Filled 3", "Filled 4"]);
  assert.equal(fields(kitBrand("garner")).buttonLook.label, "Button style");
  const bare = kitBrand("garner");
  (bare.kit as { brief: { component_recipes: unknown[] } }).brief.component_recipes = [];
  assert.equal(fields(bare).buttonLook, undefined, "nothing to choose: no field");
  assert.ok((makeSections(kitBrand("garner"), href).CtaBand.fields as unknown as Record<string, Field>).buttonLook);
});

test("the Surface field lists the six and then this brand's other surfaces", () => {
  const options = fields(kitBrand("garner.minted")).surface.options!;
  assert.deepEqual(options.slice(0, 6).map((o) => o.label), ["Page", "Card", "Muted", "Brand, subtle", "Brand", "Inverse"]);
  assert.ok(options.some((o) => o.value === "band-014036" && o.label === "Dark band"));
});

test("a FeatureSplit draws the look it names", () => {
  const brand = kitBrand("conduit.minted");
  const index = lookNamed(brand, "button", "solid.28241e")!.index;
  const split = makeSections(brand, href).FeatureSplit;
  const markup = renderToStaticMarkup(
    <>{split.render({ id: "f", surface: "page", eyebrow: "", heading: "H", headingRole: "title", body: "B", image: "", imageSide: "left", buttonLabel: "Book a demo", buttonHref: "/", buttonLook: "solid.28241e" } as never)}</>,
  );
  assert.ok(markup.includes(`class="brand-btn brand-look-${index}"`), markup);
});

test("the shell header's button takes a look too", () => {
  const config = makeConfig(kitBrand("garner"), { mode: "shell" }) as unknown as { components: { SiteHeader: { fields: Record<string, Field> } } };
  assert.equal(config.components.SiteHeader.fields.ctaLook.label, "Button style");
});

test("the validator holds surfaces and looks to this brand's", () => {
  const brand = garner();
  const pages = structuredClone(site("garner-syracuse").pages) as Record<string, { content: { type: string; props: Record<string, unknown> }[] }>;
  const split = { type: "CtaBand", props: { id: "cta-check", surface: "canvas", heading: "H", body: "", buttonLabel: "Go", buttonHref: "/", buttonLook: "outline.1" } };
  pages["/"].content.push(split);
  const shell = site("garner-syracuse").shell;
  assert.equal(validateSite({ pages, shell }, brand, {}).valid, true, validateSite({ pages, shell }, brand, {}).errors.join("\n"));
  split.props.buttonLook = "solid.9";
  split.props.surface = "green";
  const errors = validateSite({ pages, shell }, brand, {}).errors;
  assert.ok(errors.some((e) => e.endsWith(`.buttonLook: "solid.9" is not one of this brand's button styles; its styles are outline.1, ghost.1, solid.1, solid.2, solid.3, solid.4, or leave it empty for the standard button (brand/brand.md, Buttons)`)), errors.join("\n"));
  assert.ok(errors.some((e) => e.includes('.surface: "green" is not one of this brand\'s surfaces; its surfaces are page, card, muted, brandSubtle, brand, inverse, canvas,')), errors.join("\n"));
});
