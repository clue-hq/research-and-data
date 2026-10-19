// The live page (publishing live sites, phase 1 Task 3): the server draws each route into #clue-site
// with the same tree the browser hydrates, hands back the page's data, and an agent section that
// fails only in the browser is taken down alone and reported by name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { brandForPage, hydrateSite, type LivePageData } from "../src/live-page";
import { parse } from "node-html-parser";
import { renderSitePages } from "../src/render-core";
import { fillClone } from "../src/clone";
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
  const trimmed = brandForPage(brand, page);
  assert.deepEqual(new Set(Object.keys(trimmed.clones)), used);
  assert.deepEqual(trimmed.kit, brand.kit);
  // The browser draws each clone from the page data's `cloneHtml`, so its clones carry none of their
  // captured HTML or CSS (they are most of a brand).
  for (const clone of Object.values(trimmed.clones)) assert.deepEqual([clone.html, clone.css], ["", ""], clone.id);
});

test("a live page records what it drew for each cloned section and draws their CSS once, outside the tree", () => {
  const live = renderSitePages({ site, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000, live: true });
  const home = live.pages[0];
  const clones = (home.data!.page.content as { type: string; props: { id: string } }[]).filter((c) => c.type === "ClonedSection");
  assert.ok(clones.length > 0);
  assert.deepEqual(Object.keys(home.data!.cloneHtml).sort(), clones.map((c) => c.props.id).sort());
  for (const clone of clones) assert.ok(home.html.includes(home.data!.cloneHtml[clone.props.id]), clone.props.id);
  // One stylesheet in front of #clue-site; none inside it.
  assert.equal(home.html.split("<style data-clue-clones").length, 2);
  assert.ok(home.html.indexOf("<style data-clue-clones") < home.html.indexOf('<div id="clue-site">'));
  assert.ok(!bodyOf(home.html).includes("lumen-frag-") || !/<style>[^<]*lumen-frag-/.test(bodyOf(home.html)));
});

test("the browser keeps every cloned section exactly as the server drew it", async () => {
  const dom = jsdom();
  const live = renderSitePages({ site, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000, live: true });
  for (const page of live.pages) {
    const container = dom.window.document.createElement("div");
    container.innerHTML = bodyOf(page.html);
    dom.window.document.body.appendChild(container);
    const fragments = () =>
      [...container.querySelectorAll("[data-lumen-fragment]")].map((el) => [el.previousElementSibling?.outerHTML, el.outerHTML]);
    const drawn = fragments();
    assert.ok(drawn.length > 0 || !JSON.stringify(page.data?.page).includes("ClonedSection"), page.route);
    const reports: string[] = [];
    const run = hydrateSite({ container, data: page.data as LivePageData, agentSections: {}, report: (m) => reports.push(m) });
    await run.ready;
    assert.deepEqual(reports, [], page.route);
    assert.deepEqual(fragments(), drawn, `${page.route}: a cloned section changed when the browser took it over`);
    run.unmount();
    container.remove();
  }
});

test("live mode draws each route into #clue-site and returns its page data; static mode is unchanged", () => {
  const live = renderSitePages({ site, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000, live: true });
  const home = live.pages[0];
  // #clue-site follows the clones' stylesheet, if any, and nothing else.
  assert.match(home.html, /<body>(<style data-clue-clones="">[^]*?<\/style>)?<div id="clue-site">/);
  assert.ok(home.html.endsWith("</div></body></html>"));
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
  // The page itself (React's hoisted image preload, before it, is dropped by hydration).
  const serverHtml = container.querySelector(".brand-root")!.outerHTML;
  assert.ok(serverHtml.includes('<div data-agent-section="Fragile"></div>'), "the server drew the section (empty)");
  const reports: string[] = [];
  const run = hydrateSite({ container, data: live.pages[0].data as LivePageData, agentSections: { Fragile }, report: (m) => reports.push(m) });
  await run.ready;
  assert.ok(reports.some((m) => m.includes("Fragile") && m.includes("reads window while drawing")), JSON.stringify(reports));
  // The one boundary (site-kit's, shared with the editor) leaves a marker where the section was.
  const wrapper = container.querySelector('[data-agent-section="Fragile"]');
  assert.ok(wrapper?.querySelector('[data-agent-section-failed="Fragile"]'), container.innerHTML.slice(-400));
  // Everything else on the page is what the server drew (compared as DOM nodes: hydration may
  // re-set an attribute, which changes only the attribute order in the serialized HTML).
  const expected = dom.window.document.createElement("template");
  expected.innerHTML = serverHtml.replace('<div data-agent-section="Fragile"></div>', '<div data-agent-section="Fragile"><div data-agent-section-failed="Fragile"></div></div>');
  assert.ok(expected.content.firstElementChild!.isEqualNode(container.querySelector(".brand-root")), "the rest of the page is intact");
  run.unmount();
});

// Plan 4: a copied section's `order` is applied the same way in the static render and on a live page.
test("a live page and the static render draw a copied section's children in its order", () => {
  const stored = structuredClone(site);
  const home = stored.pages["/"];
  const item = (home.content as { type: string; props: Record<string, unknown> }[]).find((c) => c.type === "ClonedSection")!;
  const drawn = parse(fillClone(brand.clones[String(item.props.fragmentId)]));
  const parent = drawn.querySelectorAll("[data-clue-el]").find((el) => el.childNodes.filter((n) => (n as { getAttribute?: unknown }).getAttribute && (n as unknown as { getAttribute: (a: string) => string | undefined }).getAttribute("data-clue-el")).length >= 2)!;
  const key = parent.getAttribute("data-clue-el")!;
  const children = parent.childNodes.flatMap((n) => {
    const k = (n as unknown as { getAttribute?: (a: string) => string | undefined }).getAttribute?.("data-clue-el");
    return k ? [k] : [];
  });
  const order = [...children].reverse();
  item.props._edits = { [key]: { order } };
  const inOrder = (html: string) => {
    const box = parse(html).querySelectorAll("[data-clue-el]").find((el) => el.getAttribute("data-clue-el") === key && el.closest(`[data-clue-section="${item.props.id}"]`))!;
    return box.childNodes.flatMap((n) => {
      const k = (n as unknown as { getAttribute?: (a: string) => string | undefined }).getAttribute?.("data-clue-el");
      return k ? [k] : [];
    });
  };
  const live = renderSitePages({ site: stored, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000, live: true, routes: ["/"] }).pages[0];
  const still = renderSitePages({ site: stored, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000, routes: ["/"] }).pages[0];
  assert.deepEqual(inOrder(live.html), order);
  assert.deepEqual(inOrder(still.html), order);
  assert.ok(live.data!.cloneHtml[String(item.props.id)].indexOf(`data-clue-el="${order[0]}"`) < live.data!.cloneHtml[String(item.props.id)].indexOf(`data-clue-el="${order[order.length - 1]}"`));
});

test("a live page draws a copied section's alt texts as the static render does", () => {
  const stored = structuredClone(site);
  const item = (stored.pages["/"].content as { type: string; props: Record<string, unknown> }[]).find((c) => c.type === "ClonedSection" && /<img/.test(brand.clones[String(c.props.fragmentId)]?.html ?? ""))!;
  const img = parse(fillClone(brand.clones[String(item.props.fragmentId)])).querySelectorAll("img[data-clue-el]")[0];
  const key = img.getAttribute("data-clue-el")!;
  item.props.alts = { [key]: "Students at lunch" };
  const live = renderSitePages({ site: stored, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000, live: true, routes: ["/"] }).pages[0];
  const still = renderSitePages({ site: stored, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000, routes: ["/"] }).pages[0];
  for (const html of [live.html, still.html]) assert.match(html, new RegExp(`data-clue-el="${key.replace(/\./g, "\\.")}"[^>]*alt="Students at lunch"|alt="Students at lunch"[^>]*data-clue-el="${key.replace(/\./g, "\\.")}"`));
});

// Plan 6 (ruling R2): a template header is drawn the same on both sides.
test("a live page with a template header hydrates with no mismatch", async () => {
  const dom = jsdom();
  const TEMPLATE = "frag_00000000000000ab";
  const b = garner();
  b.clones[TEMPLATE] = {
    id: TEMPLATE, role: "site_header", label: "Header template", page_url: "https://garnerhealth.com/", section_index: 0,
    wrapper_class: `lumen-frag-${TEMPLATE}`, html: '<header><span data-lumen-slot="account_line">Prepared for you</span></header>',
    css: "", slots: { account_line: { kind: "text", fallback: "Prepared for you" } },
  } as never;
  const shell = { header: { type: "ClonedSection", props: { id: "header" as const, fragmentId: TEMPLATE, slots: { account_line: "Built for Syracuse" }, replacements: [], links: [] } }, footer: stored.shell.footer };
  const live = renderSitePages({ site: { ...site, shell }, brand: b, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000, live: true });
  for (const page of live.pages) {
    assert.ok((page.data as LivePageData).brand.clones[TEMPLATE], "the page's brand carries the header's clone");
    const container = dom.window.document.createElement("div");
    container.innerHTML = bodyOf(page.html);
    dom.window.document.body.appendChild(container);
    const reports: string[] = [];
    const run = hydrateSite({ container, data: page.data as LivePageData, agentSections: {}, report: (m) => reports.push(m) });
    await run.ready;
    assert.deepEqual(reports, [], page.route);
    assert.ok(container.innerHTML.includes("Built for Syracuse"));
    run.unmount();
  }
});
