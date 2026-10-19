// Plan 2, Task 4: rich text and new-tab links drawn everywhere they appear — our sections, the
// agent's sections, the clones and the shell — identically on the static page, the live page and in
// the browser that takes a live page over.
import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { z } from "zod";
import type { Kit } from "../src/agent-kit";
import type { Clone } from "../src/clone";
import { fillClone } from "../src/clone";
import { hydrateSite, type LivePageData } from "../src/live-page";
import { renderSitePages } from "../src/render-core";
import { garner, site as readSite } from "./fixtures/garner";

const stored = readSite("garner-syracuse");
const heroClone: Clone = {
  id: "frag_00000000000000cc", role: "section", label: "Hero", page_url: "https://seller.example/", section_index: 0,
  wrapper_class: "lumen-frag-hero",
  html: '<h1 data-lumen-slot="headline"><span class="x">Top</span> words</h1><a href="https://seller.example/demo">Book a demo</a>',
  css: "", slots: { headline: { kind: "text", fallback: "Top words" } },
};

const schema = z.object({
  id: z.string(),
  surface: z.string(),
  quote: z.string().meta({ edit: "inline" }),
  attribution: z.string().meta({ edit: "inline" }),
}).strict();
const QuoteBand = {
  schema,
  render: ((props: z.infer<typeof schema>, kit: Kit) => (
    <kit.Shell surface={props.surface}>
      <blockquote data-clue-el="quote">{props.quote}</blockquote>
      <p data-clue-el="attribution">{props.attribution}</p>
    </kit.Shell>
  )) as never,
};

function siteWithRichText() {
  const home = {
    root: { props: { title: "Rich" } },
    content: [
      {
        type: "ProofCard",
        props: {
          id: "proof", surface: "card", kicker: "Customer", metric: "13%", metricLabel: "less",
          heading: 'Top <strong>results</strong> <span data-s="heading~1">here</span>',
          body: 'See <a href="/analysis" data-new-tab="">the analysis</a> &amp; more',
          source: "", linkLabel: "Read the study", linkHref: "/analysis", linkNewTab: true,
          _edits: { "heading~1": { fontWeight: 700 } },
        },
      },
      { type: "QuoteBand", props: { id: "quote", surface: "page", quote: "Fewer <em>surprises</em>.", attribution: "A buyer" } },
      {
        type: "ClonedSection",
        props: {
          id: "hero", fragmentId: heroClone.id, replacements: [], links: [], newTab: ["1"],
          slots: { headline: 'New <a href="/analysis">words</a> <span data-s="0~1">here</span>' },
          _edits: { "0~1": { italic: true } },
        },
      },
    ],
  };
  const shell = {
    header: { ...stored.shell.header, props: { ...stored.shell.header.props, menuExtra: [{ label: "Analysis", href: "/analysis", newTab: true }] } },
    footer: { ...stored.shell.footer, props: { ...stored.shell.footer.props, privacyHref: "https://garner.example/privacy", privacyNewTab: true } },
  };
  return { title: "Rich", pages: { "/": home, "/analysis": stored.pages["/analysis"] }, shell };
}

function brandWithClone() {
  const brand = garner();
  brand.clones = { ...brand.clones, [heroClone.id]: heroClone };
  return brand;
}

const render = (live = false) =>
  renderSitePages({ site: siteWithRichText(), brand: brandWithClone(), basePath: "/acme", agentSections: { QuoteBand }, maxOutputBytes: 10_000_000, live });

test("our sections draw rich text as markup, links under the base path, and new tabs", () => {
  const html = render().pages[0].html;
  assert.ok(html.includes('data-clue-el="heading"><span data-clue-rich="">Top <strong>results</strong> <span data-s="heading~1">here</span></span>'), html);
  assert.ok(html.includes('See <a href="/acme/analysis" target="_blank" rel="noopener">the analysis</a> &amp; more'), "a rich link opens in a new tab under the base path");
  assert.ok(html.includes('[data-clue-section="proof"] [data-s="heading~1"]{font-weight:700 !important}'));
  assert.match(html, /<a href="\/acme\/analysis" target="_blank" rel="noopener" class="brand-link[^"]*" data-clue-el="linkLabel">Read the study<\/a>/);
  assert.ok(html.includes('data-clue-el="metric">13%</p>'), "plain text stays plain");
});

test("an agent section's inline props are drawn as rich text; plain ones reach it as strings", () => {
  const html = render().pages[0].html;
  assert.ok(html.includes('<blockquote data-clue-el="quote"><span data-clue-rich="">Fewer <em>surprises</em>.</span></blockquote>'), html);
  assert.ok(html.includes('<p data-clue-el="attribution">A buyer</p>'));
});

test("a clone's text slot draws its rich text, keeps its key, and a new-tab link opens in a new tab", () => {
  const html = render().pages[0].html;
  assert.ok(html.includes('<h1 data-lumen-slot="headline" data-clue-el="0">New <a href="/acme/analysis">words</a> <span data-s="0~1">here</span></h1>'), html);
  assert.ok(html.includes('<a href="https://seller.example/demo" data-clue-el="1" target="_blank" rel="noopener">Book a demo</a>'), html);
  assert.ok(html.includes('[data-clue-section="hero"] [data-s="0~1"]{font-style:italic !important}'));
});

test("an unchanged clone slot keeps the captured markup; a plain value is written as text", () => {
  assert.ok(fillClone(heroClone, { headline: "Top words" }).includes('<span class="x">Top</span> words'));
  assert.ok(fillClone(heroClone, { headline: "A & B" }).includes(">A &amp; B</h1>"));
});

test("the header's and footer's links open in a new tab when set", () => {
  const html = render().pages[0].html;
  assert.match(html, /<a href="\/acme\/analysis" target="_blank" rel="noopener" class="brand-navlink" data-clue-el="menu._0"[^>]*>Analysis<\/a>/);
  assert.match(html, /<a href="https:\/\/garner.example\/privacy" target="_blank" rel="noopener" class="brand-link" data-clue-el="privacy">/);
});

test("the browser takes a live page with rich text over with no mismatch", async () => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>");
  Object.assign(globalThis, { window: dom.window, document: dom.window.document });
  Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true, writable: true });
  const page = render(true).pages[0];
  const body = page.html.slice(page.html.indexOf('<div id="clue-site">') + 20, page.html.lastIndexOf("</div></body>"));
  const container = dom.window.document.createElement("div");
  container.innerHTML = body;
  dom.window.document.body.appendChild(container);
  const before = container.innerHTML;
  const reports: string[] = [];
  const errors: unknown[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => errors.push(args);
  try {
    const run = hydrateSite({ container, data: page.data as LivePageData, agentSections: { QuoteBand }, report: (m) => reports.push(m) });
    await run.ready;
    assert.deepEqual(reports, []);
    assert.deepEqual(errors, [], "no hydration mismatch");
    assert.equal(container.innerHTML, before);
    run.unmount();
  } finally {
    console.error = original;
  }
});

// End-of-plan review finding 5: a slot set to exactly its original words keeps the captured markup,
// even when they hold "&".
test("a slot set to its original words keeps the captured markup through the section render", () => {
  const amp: Clone = { ...heroClone, id: "frag_00000000000000ce", html: '<h1 data-lumen-slot="headline">Sales &amp; <span class="grad">Marketing</span><br>teams</h1>', slots: { headline: { kind: "text", fallback: "Sales & Marketing teams" } } };
  const brand = garner();
  brand.clones = { ...brand.clones, [amp.id]: amp };
  const site = { title: "T", pages: { "/": { root: { props: {} }, content: [{ type: "ClonedSection", props: { id: "h", fragmentId: amp.id, slots: { headline: "Sales & Marketing teams" }, replacements: [], links: [] } }] } }, shell: stored.shell };
  const html = renderSitePages({ site, brand, basePath: "", agentSections: {}, maxOutputBytes: 10_000_000 }).pages[0].html;
  assert.ok(html.includes('<span class="grad">Marketing</span><br>teams'), html.slice(html.indexOf("Sales"), html.indexOf("Sales") + 200));
});

// Plan 3: buttons that open in a new tab, and a button's styled words.
test("our buttons and the header's open in a new tab when set, and draw their styled words", () => {
  const site = {
    title: "T",
    pages: { "/": { root: { props: {} }, content: [{ type: "CtaBand", props: { id: "cta", surface: "brand", heading: "H", buttonLabel: 'Book <span data-s="button.label~1">now</span>', buttonHref: "https://garner.example/book", buttonNewTab: true } }] } },
    shell: { ...stored.shell, header: { ...stored.shell.header, props: { ...stored.shell.header.props, ctaNewTab: true } } },
  };
  const html = renderSitePages({ site, brand: garner(), basePath: "", agentSections: {}, maxOutputBytes: 10_000_000 }).pages[0].html;
  assert.match(html, /<a href="https:\/\/garner\.example\/book" target="_blank" rel="noopener" class="brand-btn[^"]*" data-surface="brand" data-clue-el="button">/);
  assert.ok(html.includes('<span data-clue-el="button.label"><span data-clue-rich="">Book <span data-s="button.label~1">now</span></span></span>'), html);
  assert.match(html, /target="_blank" rel="noopener" class="brand-btn[^"]*" data-surface="page" data-clue-el="cta">/);
});
