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
  assert.ok(home.startsWith('<!doctype html><html lang="en"><head><title>Garner Health for Syracuse City School District</title></head><body>'), home.slice(0, 200));
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
