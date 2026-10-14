// The live page (publishing live sites, phase 1 Task 3): the server draws each route into #clue-site
// with the same tree the browser hydrates, hands back the page's data, and an agent section that
// fails only in the browser is taken down alone and reported by name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { brandForPage, hydrateSite, type LivePageData } from "../src/live-page";
import { renderSitePages } from "../src/render-core";
import { garner, site as readSite } from "./fixtures/garner";
import { render as quoteRender, schema as quoteSchema } from "./fixtures/section-example";

const brand = garner();
const stored = readSite("garner-syracuse");
const site = { title: "Garner for Syracuse", pages: stored.pages, shell: stored.shell };

function jsdom() {
  const dom = new JSDOM("<!doctype html><html><body></body></html>");
  Object.assign(globalThis, { window: dom.window, document: dom.window.document });
  // Node 21+ ships a getter-only global `navigator`, so it is redefined rather than assigned.
  Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true, writable: true });
  return dom;
}

const bodyOf = (html: string) => html.slice(html.indexOf('<div id="clue-site">') + '<div id="clue-site">'.length, html.lastIndexOf("</div></body>"));

test("a page's data carries only the clones that page uses", () => {
  const page = stored.pages["/"];
  const used = new Set(page.content.filter((c: { type: string }) => c.type === "ClonedSection").map((c: { props: { fragmentId: string } }) => c.props.fragmentId));
  const trimmed = brandForPage(brand, page, stored.shell);
  assert.deepEqual(new Set(Object.keys(trimmed.clones)), used);
  assert.deepEqual(trimmed.kit, brand.kit);
});

test("live mode draws each route into #clue-site and returns its page data; static mode is unchanged", () => {
  const live = renderSitePages({ site, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000, live: true });
  const home = live.pages[0];
  assert.ok(home.html.includes('<body><div id="clue-site">') && home.html.endsWith("</div></body></html>"));
  assert.equal(home.data?.route, "/");
  assert.equal(home.data?.basePath, "/acme");
  assert.deepEqual(home.data?.sections, {});
  const still = renderSitePages({ site, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000 });
  assert.equal(still.pages[0].data, undefined);
  assert.ok(!still.pages[0].html.includes('id="clue-site"'));
});

test("the browser takes the live HTML over with no mismatch", async () => {
  const dom = jsdom();
  const agentSections = { QuoteBand: { schema: quoteSchema, render: quoteRender as never } };
  const live = renderSitePages({ site, brand, basePath: "/acme", agentSections, maxOutputBytes: 10_000_000, live: true });
  for (const page of live.pages) {
    const container = dom.window.document.createElement("div");
    container.innerHTML = bodyOf(page.html);
    dom.window.document.body.appendChild(container);
    const reports: string[] = [];
    const run = hydrateSite({ container, data: page.data as LivePageData, agentSections, report: (m) => reports.push(m) });
    await run.ready;
    assert.deepEqual(reports, [], page.route);
    run.unmount();
  }
});

test("Review focus 1: a section that throws only in the browser is lost alone, and reported", async () => {
  const dom = jsdom();
  const home = structuredClone(stored.pages["/"]);
  home.content.push({ type: "Fragile", props: { id: "fragile", surface: "page" } });
  const Fragile = {
    schema: quoteSchema,
    render: (() => {
      if (typeof window !== "undefined" && (window as { __clueBrowser?: boolean }).__clueBrowser) throw new Error("reads window while drawing");
      return null;
    }) as never,
  };
  const live = renderSitePages({ site: { ...site, pages: { "/": home } }, brand, basePath: "", agentSections: { Fragile }, maxOutputBytes: 10_000_000, live: true });
  (dom.window as unknown as { __clueBrowser: boolean }).__clueBrowser = true;
  const container = dom.window.document.createElement("div");
  container.innerHTML = bodyOf(live.pages[0].html);
  dom.window.document.body.appendChild(container);
  const reports: string[] = [];
  const run = hydrateSite({ container, data: live.pages[0].data as LivePageData, agentSections: { Fragile }, report: (m) => reports.push(m) });
  await run.ready;
  assert.ok(reports.some((m) => m.includes("Fragile") && m.includes("reads window while drawing")), JSON.stringify(reports));
  assert.ok(container.querySelector(".brand-root"), "the rest of the page is still there");
  run.unmount();
});
