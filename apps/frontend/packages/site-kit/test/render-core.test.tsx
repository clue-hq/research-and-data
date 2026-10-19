// The server render's React half (Wave 2 Lane A): plain renderToStaticMarkup of each route with
// Puck's <Render>, testable in Node. The browser entry runs exactly this inside the hardened page.
import assert from "node:assert/strict";
import { test } from "node:test";
import { z } from "zod";
import { RenderRefusal, renderSitePages, sectionPropsSchema, siteRoutes } from "../src/render-core";
import { garner, site as readSite } from "./fixtures/garner";
import { render as quoteRender, schema as quoteSchema } from "./fixtures/section-example";

const brand = garner();
const stored = readSite("garner-syracuse");
const site = { title: "Garner for Syracuse", pages: stored.pages, shell: stored.shell };

test("routes render home first, then the others in order", () => {
  assert.deepEqual(siteRoutes({ ...site, pages: { "/zeta": {}, "/": {}, "/alpha": {} } }), ["/", "/alpha", "/zeta"]);
});

test("a stored site renders every route as a document, with its links under the base path", () => {
  const result = renderSitePages({ site, brand, basePath: "/acme-site", agentSections: {}, maxOutputBytes: 10_000_000 });
  assert.deepEqual(result.pages.map((page) => page.route), ["/", "/analysis"]);
  const home = result.pages[0].html;
  assert.ok(home.startsWith('<!doctype html><html lang="en"><head><title>Garner Health for Syracuse City School District</title><style data-clue-page="">html{background-color:#'), home.slice(0, 260));
  assert.ok(home.includes('</style></head><body>'), home.slice(0, 400));
  assert.ok(home.includes('class="brand-root"'));
  assert.ok(home.includes('href="/acme-site/analysis"'), "the closing clone's /analysis link is rebased");
  assert.ok(result.tailwindTheme.startsWith("@theme inline {"));
  assert.equal(result.size, result.pages.reduce((total, page) => total + page.html.length, 0));
});

test("an agent section renders inside its data-agent-section wrapper, with the kit", () => {
  const home = structuredClone(stored.pages["/"]);
  home.content.push({ type: "QuoteBand", props: { id: "quote", surface: "brand", quote: "Fewer surprises.", attribution: "A buyer" } });
  const result = renderSitePages({
    site: { ...site, pages: { "/": home } },
    brand,
    basePath: "",
    agentSections: { QuoteBand: { schema: quoteSchema, render: quoteRender as never } },
    maxOutputBytes: 10_000_000,
  });
  const html = result.pages[0].html;
  assert.ok(html.includes('<div data-agent-section="QuoteBand"><section class="bg-surface-brand text-on-surface-brand" data-clue-el="root">'), html);
  assert.ok(html.includes("Fewer surprises."));
});

// Live publishing, phase 1: each agent section draws inside its own error boundary, which works only
// in the browser. On the server a section that throws still fails the whole render, as before — the
// boundary adds no element, so the static HTML is unchanged (the wrapper test above), and it does not
// hide a broken section from the render.
test("a section that throws while drawing on the server still fails the render, in both modes", () => {
  const home = structuredClone(stored.pages["/"]);
  home.content.push({ type: "Broken", props: { id: "broken", surface: "page" } });
  const Broken = { schema: quoteSchema, render: (() => { throw new Error("broken section"); }) as never };
  for (const live of [false, true]) {
    assert.throws(
      () => renderSitePages({ site: { ...site, pages: { "/": home } }, brand, basePath: "", agentSections: { Broken }, maxOutputBytes: 10_000_000, live }),
      /broken section/,
    );
  }
});

test("the output cap is a typed refusal", () => {
  assert.throws(
    () => renderSitePages({ site, brand, basePath: "", agentSections: {}, maxOutputBytes: 1000 }),
    (error) => error instanceof RenderRefusal && error.code === "render.output_too_large",
  );
  assert.throws(
    () => renderSitePages({ site, brand, basePath: "", routes: ["/nope"], agentSections: {}, maxOutputBytes: 10_000_000 }),
    (error) => error instanceof RenderRefusal && error.code === "render.failed",
  );
});

test("sectionPropsSchema reads the props schema and refuses the shapes the check used to", () => {
  const ok = sectionPropsSchema({ schema: quoteSchema, render: quoteRender });
  assert.ok("props" in ok);
  assert.deepEqual(Object.keys((ok.props as { properties: Record<string, unknown> }).properties).sort(), ["attribution", "id", "quote", "surface"]);
  assert.deepEqual(sectionPropsSchema({ schema: z.object({ id: z.string() }).strict(), render: quoteRender }), {
    errors: ['the props need "surface" (every section has an id and a surface)'],
  });
  assert.deepEqual(sectionPropsSchema({ schema: z.object({ id: z.string(), surface: z.string(), style: z.string() }), render: quoteRender }), {
    errors: ['the props may not include "style"'],
  });
  assert.deepEqual(sectionPropsSchema({ schema: {}, render: 1 }), {
    errors: ["`schema` must be a zod object (z.object({...}).strict())", "`render` must be a function (props, kit) => JSX"],
  });
});

// Review finding K1-2: the editor opens a site only when every section has a text id, so a section
// whose schema lets its id be left out, a number or a default is refused when it is added.
test("K1-2: a section schema must make its id required text", () => {
  const render = () => null;
  for (const id of [z.string().optional(), z.number(), z.string().default("hero")]) {
    const result = sectionPropsSchema({ schema: z.object({ id, surface: z.string() }).strict(), render });
    assert.ok("errors" in result && result.errors.some((e) => e.includes('"id" must be required text')), JSON.stringify(result));
  }
  assert.ok("props" in sectionPropsSchema({ schema: z.object({ id: z.string(), surface: z.string() }).strict(), render }));
});

// S2a-2 (option B): the marker `.meta({ edit: "inline" })` makes a prop edit in place on the canvas.
// It belongs on prose only; on a brand choice, a link, an image, `alt` or a prop that is not text the
// section is refused when it is written, with what to do instead.
test("S2a-2: the edit-in-place marker is refused on a choice, link, image, alt or non-text prop", () => {
  const render = () => null;
  const refused: [string, z.ZodType, string][] = [
    ["surface", z.string(), "it is a brand choice, picked from a list in the editor"],
    ["ctaLook", z.string(), "it is a brand choice, picked from a list in the editor"],
    ["cardLook", z.string(), "it is a brand choice, picked from a list in the editor"],
    ["buttonHref", z.string(), "it is a link, edited in the editor's side panel"],
    ["heroImage", z.string(), "it is an image, chosen from the brand's assets in the editor"],
    ["alt", z.string(), "it is an image's description, edited in the editor's side panel"],
    ["count", z.number(), "it is not text; only z.string() props edit in place"],
  ];
  for (const [name, type, why] of refused) {
    const shape: Record<string, z.ZodType> = { id: z.string(), surface: z.string(), [name]: type.meta({ edit: "inline" }) };
    const result = sectionPropsSchema({ schema: z.object(shape).strict(), render });
    assert.deepEqual(result, { errors: [`"${name}" cannot be edited in place: ${why}. Remove .meta({ edit: "inline" }) from it`] }, name);
  }
  const nested = sectionPropsSchema({
    schema: z.object({ id: z.string(), surface: z.string(), cards: z.array(z.object({ title: z.string(), linkHref: z.string().meta({ edit: "inline" }) })) }).strict(),
    render,
  });
  assert.deepEqual(nested, { errors: ['"cards.linkHref" cannot be edited in place: it is a link, edited in the editor\'s side panel. Remove .meta({ edit: "inline" }) from it'] });
});

test("S2a-2: marked prose passes and the stored props schema carries the marker, inside lists too", () => {
  const result = sectionPropsSchema({
    schema: z.object({
      id: z.string(),
      surface: z.string(),
      quote: z.string().min(1).meta({ edit: "inline" }),
      note: z.string().optional().meta({ edit: "inline" }),
      caption: z.string(),
      steps: z.array(z.object({ title: z.string().meta({ edit: "inline" }) })),
    }).strict(),
    render: () => null,
  });
  assert.ok("props" in result, JSON.stringify(result));
  const properties = (result.props as { properties: Record<string, { edit?: string; items?: { properties: Record<string, { edit?: string }> } }> }).properties;
  assert.equal(properties.quote.edit, "inline");
  assert.equal(properties.note.edit, "inline");
  assert.equal(properties.caption.edit, undefined);
  assert.equal(properties.steps.items?.properties.title.edit, "inline");
});

// Manual styling (site element inspector, spec §4.5): a section's `_edits` is drawn as a scoped
// stylesheet beside it — the same in the static render, the live render and the editor — and never
// reaches the section's own render.
const styleOf = (html: string, scope: string) =>
  html.match(new RegExp(`<div data-clue-section="${scope}" class="clue-section"><style data-clue-edits="">([^<]*)</style>`))?.[1];

test("a static render carries the section's edits next to it and never passes _edits to an agent section", () => {
  const analysis = structuredClone(stored.pages["/analysis"]);
  const cta = analysis.content.find((item: { type: string }) => item.type === "CtaBand");
  cta.props._edits = { heading: { italic: true } };
  analysis.content.push({ type: "Picky", props: { id: "picky", surface: "page", quote: "Hi", attribution: "A buyer", _edits: { quote: { fontSize: 40 } } } });
  const Picky = {
    schema: quoteSchema,
    render: ((props: Record<string, unknown>, kit: never) => {
      if ("_edits" in props) throw new Error("the section was given _edits");
      return quoteRender(props as never, kit);
    }) as never,
  };
  const html = renderSitePages({ site: { ...site, pages: { "/analysis": analysis } }, brand, basePath: "", agentSections: { Picky }, maxOutputBytes: 10_000_000 }).pages[0].html;
  assert.equal(styleOf(html, "cta"), '[data-clue-section="cta"] [data-clue-el="heading"]{font-style:italic !important}');
  assert.equal(styleOf(html, "picky"), '[data-clue-section="picky"] [data-clue-el="quote"]{font-size:40px !important}');
  assert.ok(html.includes('<div data-clue-section="picky" class="clue-section"><style data-clue-edits="">'), html);
  assert.ok(html.includes('</style><div data-agent-section="Picky">'), "the agent section's own wrapper follows the stylesheet");
});

test("a live render carries the same stylesheet the browser will draw", () => {
  const analysis = structuredClone(stored.pages["/analysis"]);
  analysis.content.find((item: { type: string }) => item.type === "CtaBand").props._edits = { heading: { color: { hex: "#0F59B0", opacity: 80 } } };
  const render = (live: boolean) =>
    renderSitePages({ site: { ...site, pages: { "/analysis": analysis } }, brand, basePath: "", agentSections: {}, maxOutputBytes: 10_000_000, live }).pages[0];
  const staticCss = styleOf(render(false).html, "cta");
  const livePage = render(true);
  assert.ok(staticCss, "the static render has the stylesheet");
  assert.equal(styleOf(livePage.html, "cta"), staticCss);
  assert.deepEqual(
    (livePage.data!.page.content as { props: Record<string, unknown> }[]).find((item) => item.props.id === "cta")!.props._edits,
    { heading: { color: { hex: "#0F59B0", opacity: 80 } } },
    "the browser builds the same stylesheet from the page data",
  );
});

test("the header's edits are scoped to the header", () => {
  const shell = structuredClone(stored.shell);
  shell.header.props._edits = { accountLine: { fontWeight: 700 } };
  shell.footer.props._edits = { legal: { underline: true } };
  const html = renderSitePages({ site: { ...site, shell }, brand, basePath: "", routes: ["/"], agentSections: {}, maxOutputBytes: 10_000_000 }).pages[0].html;
  assert.match(html, /<div data-clue-section="header" class="clue-section"><style data-clue-edits="">\[data-clue-section="header"\] \[data-clue-el="accountLine"\]\{font-weight:700 !important\}<\/style><header data-clue-el="root"/);
  assert.match(html, /<div data-clue-section="footer" class="clue-section"><style data-clue-edits="">\[data-clue-section="footer"\] \[data-clue-el="legal"\]\{text-decoration-line:underline !important\}<\/style><footer data-clue-el="root"/);
});

// Plan 6 (ruling R2): one drawing path for the header and footer.
const TEMPLATE = "frag_00000000000000aa";
const withTemplate = () => {
  const b = garner();
  b.clones[TEMPLATE] = {
    id: TEMPLATE, role: "site_header", label: "Header template", page_url: "https://garnerhealth.com/", section_index: 0,
    wrapper_class: `lumen-frag-${TEMPLATE}`, html: '<header><span data-lumen-slot="account_line">Prepared for you</span></header>',
    css: `.lumen-frag-${TEMPLATE} header{color:#123456}`, slots: { account_line: { kind: "text", fallback: "Prepared for you" } },
  } as never;
  return b;
};
const templateShell = () => ({
  header: { type: "ClonedSection", props: { id: "header" as const, fragmentId: TEMPLATE, slots: { account_line: "Built for Syracuse" }, replacements: [], links: [] } },
  footer: stored.shell.footer,
});

test("the header and footer are the page's first and last sections", () => {
  for (const live of [false, true]) {
    for (const page of renderSitePages({ site, brand, basePath: "", agentSections: {}, maxOutputBytes: 10_000_000, live }).pages) {
      const sections = [...page.html.matchAll(/data-clue-section="([^"]+)"/g)].map((m) => m[1]);
      assert.equal(sections[0], "header", `${page.route} live=${live}`);
      assert.equal(sections.at(-1), "footer", `${page.route} live=${live}`);
    }
  }
  const live = renderSitePages({ site: { ...site, shell: templateShell() }, brand: withTemplate(), basePath: "", routes: ["/analysis"], agentSections: {}, maxOutputBytes: 10_000_000, live: true }).pages[0].html;
  assert.match(live, /<style data-clue-clones="">[^<]*#123456/, "a template header's CSS is drawn with the clones'");
  assert.ok(live.includes("Built for Syracuse"));
});

test("an old-shape shell draws neither header nor footer", () => {
  const old = { header: { preparedFor: "SCSD", ctaLabel: "Go", ctaHref: "/" }, footer: { legal: "©" } };
  const html = renderSitePages({ site: { ...site, shell: old as never }, brand, basePath: "", routes: ["/"], agentSections: {}, maxOutputBytes: 10_000_000 }).pages[0].html;
  assert.ok(!html.includes('data-clue-section="header"') && !html.includes('data-clue-section="footer"'));
  assert.ok(!html.includes("<header") || !html.includes("SCSD"));
});

test("a section with no _edits has no style element", () => {
  for (const live of [false, true]) {
    const html = renderSitePages({ site, brand, basePath: "", agentSections: {}, maxOutputBytes: 10_000_000, live }).pages[0].html;
    assert.ok(!html.includes("data-clue-edits"), "no stylesheet without edits");
    assert.ok(html.includes('<div data-clue-section="hero" class="clue-section">'), "every section still has its scope");
    assert.ok(html.includes('<div data-clue-section="header" class="clue-section"><header data-clue-el="root"'), "the header still has its scope");
  }
});

test("an agent section's props may not be named _edits (it is reserved for manual styling)", () => {
  assert.deepEqual(sectionPropsSchema({ schema: z.object({ id: z.string(), surface: z.string(), _edits: z.string() }).strict(), render: quoteRender }), {
    errors: ['the props may not include "_edits"'],
  });
});

// Puck's in-place text transform matches props by key name at any depth, so in the editor a
// section's `_edits.heading` reaches its render as Puck's inline-edit element, not the override.
// The scoping box reads `_edits` from the section as stored (the editor's useRawProps) instead.
test("in the editor the section's styling comes from its stored props, whatever Puck put in the drawn ones", async () => {
  const { makeConfig: make } = await import("../src/config");
  const { fillClone: fill } = await import("../src/clone");
  const { garner: brandOf } = await import("./fixtures/garner");
  const { renderToStaticMarkup: draw } = await import("react-dom/server");
  const stored = { id: "cta", surface: "brand", heading: "H", body: "", buttonLabel: "Go", buttonHref: "/", buttonLook: "", _edits: { heading: { fontSize: 48 } } };
  const config = make(brandOf(), {
    cloneHtml: fill,
    editor: { AssetPicker: () => null, CloneEditor: () => null, useRawProps: () => (id: string) => (id === "cta" ? stored : undefined) },
  }) as unknown as { components: { CtaBand: { render: (props: Record<string, unknown>) => React.ReactNode } } };
  const drawn = { ...stored, puck: { isEditing: true }, _edits: { heading: { type: "span", props: { propPath: "_edits.heading", value: { fontSize: 48 } } } } };
  const html = draw(<>{config.components.CtaBand.render(drawn)}</>);
  assert.match(html, /\[data-clue-el="heading"\]\{font-size:48px !important\}/);
});

// Plan 6 (ruling R8): the menu lists the site's pages on every page, in both render modes.
test("the header's menu lists the site's pages, static and live", () => {
  for (const live of [false, true]) {
    for (const page of renderSitePages({ site, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000, live }).pages) {
      assert.match(page.html, /<a href="\/acme" class="brand-navlink" data-clue-el="menu\._home"[^>]*>Overview<\/a>/, `${page.route} live=${live}`);
      assert.match(page.html, /<a href="\/acme\/analysis" class="brand-navlink" data-clue-el="menu\.analysis"[^>]*>Analysis<\/a>/, `${page.route} live=${live}`);
    }
  }
});

// Plan 6: the header's and footer's own `order` reaches them through their section box (review of the
// published render: the box strips `_edits` before a section draws, and passes them as the edits).
test("the header's and footer's order applies on the published page", () => {
  const shell = structuredClone(stored.shell);
  shell.header.props._edits = { actions: { order: ["ctaArea", "menu"] }, menu: { order: ["menu.analysis", "menu._home"] } };
  shell.footer.props._edits = { links: { order: ["terms", "privacy"] } };
  const html = renderSitePages({ site: { ...site, shell }, brand, basePath: "", routes: ["/"], agentSections: {}, maxOutputBytes: 10_000_000 }).pages[0].html;
  const at = (needle: string) => html.indexOf(needle);
  assert.ok(at('data-clue-el="ctaArea"') < at('data-clue-el="menu"'), "the button before the menu");
  assert.ok(at('data-clue-el="menu.analysis"') < at('data-clue-el="menu._home"'), "the menu in its order");
  assert.ok(at('data-clue-el="terms"') < at('data-clue-el="privacy"'), "the footer's links in their order");
});
