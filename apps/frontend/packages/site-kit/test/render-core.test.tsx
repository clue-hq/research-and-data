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
  assert.ok(html.includes('<div data-agent-section="QuoteBand"><section class="bg-surface-brand text-on-surface-brand">'), html);
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
