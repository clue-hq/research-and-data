// Our sections take the brand's surfaces and button styles by name (founder rulings 4, 6; Q4 = (b)).
import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { lookNamed } from "../src/looks";
import { fillClone } from "../src/clone";
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
  const config = makeConfig(kitBrand("garner"), { cloneHtml: fillClone }) as unknown as { components: { SiteHeader: { fields: Record<string, Field> } } };
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

// Plan 5 (ruling R2): alt texts drawn on our image and the shell's logos.
test("FeatureSplit draws its image alt; the header and footer draw their logo alts", async () => {
  const brand = garner();
  const sections = makeSections(brand, (v) => v);
  const html = renderToStaticMarkup(<>{sections.FeatureSplit.render({ id: "f", surface: "page", eyebrow: "", heading: "H", headingRole: "title", body: "B", image: "/brands/x.png", imageAlt: 'A "quiet" room', imageSide: "left", buttonLabel: "", buttonHref: "", buttonLook: "" } as never)}</>);
  assert.match(html, /<img src="\/brands\/x.png" alt="A &quot;quiet&quot; room"/);
  const { SiteHeader, SiteFooter } = await import("../src/shell");
  const header = renderToStaticMarkup(<SiteHeader brand={brand} header={{ accountLine: "For C", accountLogo: "/brands/c.png", accountLogoAlt: "Carmel Clay", logoAlt: "Garner", ctaLabel: "Go", ctaHref: "/" }} href={(v) => v} />);
  assert.match(header, /alt="Garner"[^>]*data-clue-el="logo"/);
  assert.match(header, /alt="Carmel Clay"[^>]*data-clue-el="accountLogo"/);
  const footer = renderToStaticMarkup(<SiteFooter brand={brand} footer={{ legal: "©", privacyHref: "", termsHref: "", logoAlt: "Garner Health" }} href={(v) => v} />);
  assert.match(footer, /alt="Garner Health"[^>]*data-clue-el="logo"/);
});

// Plan 6 (ruling R10): the header's own placement marks its section box.
test("sticky and overlay set the section box's attributes", () => {
  const config = makeConfig(garner(), { cloneHtml: fillClone }) as unknown as { components: Record<string, { render: (props: object) => React.ReactNode }> };
  const header = { id: "header", accountLine: "For C", accountLogo: "", ctaLabel: "Go", ctaHref: "/" };
  const plain = renderToStaticMarkup(<>{config.components.SiteHeader.render(header)}</>);
  assert.match(plain, /<div data-clue-section="header" class="clue-section"><header/);
  const placed = renderToStaticMarkup(<>{config.components.SiteHeader.render({ ...header, _edits: { root: { sticky: true, overlay: true } } })}</>);
  assert.match(placed, /<div data-clue-section="header" class="clue-section" data-clue-sticky="" data-clue-overlay=""><header/);
});
