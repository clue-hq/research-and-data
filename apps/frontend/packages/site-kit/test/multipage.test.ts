// Multi-page sites: pages/<name>.json is validated like page.json, a link the page writes to
// "/<name>" must go to a page that exists, the shell's nav is checked, and a clone's own captured
// links keep pointing at the seller's site.
import assert from "node:assert/strict";
import { test } from "node:test";
import { fillClone, type Clone } from "../src/clone";
import { validateSite } from "../src/validate";
import { garner, site as readSite } from "./fixtures/garner";

const site = readSite("garner-syracuse");
const brand = garner();

/** The site's files as the validator takes them: route -> page, and the shell. */
function validate(pages: Record<string, unknown>, shell = site.shell) {
  return validateSite({ pages, shell }, brand, {});
}

test("a second page is validated like the home page", () => {
  const broken = structuredClone(site.pages["/analysis"]);
  broken.content[0].props.surface = "green";
  const result = validate({ "/": site.pages["/"], "/analysis": broken });
  assert.equal(result.valid, false);
  assert.ok(result.errors.some((e) => e.startsWith("pages/analysis.content.0(") && e.includes("surface")), result.errors.join("\n"));
});

test("a link to a page that exists is fine; a link to a missing page names the pages", () => {
  // The phase-1 home page links to /analysis from its closing clone.
  assert.equal(validate({ "/": site.pages["/"], "/analysis": site.pages["/analysis"] }).valid, true);
  const result = validate({ "/": site.pages["/"] });
  assert.equal(result.valid, false);
  assert.ok(result.errors.some((e) => e.includes("links to /analysis, which is not a page of this site") && e.includes("its pages are /")));
});

test("nav links are part of the shell and must go to real pages", () => {
  const shell = structuredClone(site.shell);
  shell.header.nav = [{ label: "The analysis", href: "/analysis" }, { label: "Pricing", href: "/pricing" }];
  const result = validate({ "/": site.pages["/"], "/analysis": site.pages["/analysis"] }, shell);
  assert.deepEqual(result.errors.filter((e) => e.includes("/pricing")).length, 1);
  assert.ok(result.errors[0].startsWith("shell.header.nav.1.href"), result.errors.join("\n"));
});

test("a page name uses lowercase letters, digits and dashes", () => {
  const result = validate({ "/": site.pages["/"], "/analysis": site.pages["/analysis"], "/Bad Name": site.pages["/analysis"] });
  assert.ok(result.errors.some((e) => e.startsWith("pages/Bad Name.json: a page name")));
});

test("a clone's own links keep pointing at the seller; links the page sets are its own", () => {
  const clone: Clone = {
    id: "frag_0000000000000000", role: "other", label: "x", page_url: "https://seller.example/products/",
    section_index: 0, wrapper_class: "w", css: "",
    html: '<div><a href="/book-a-demo">Demo</a><a href="/customer-stories">Stories</a><a data-lumen-slot="cta" href="/x">Go</a></div>',
    slots: { cta: { kind: "href", fallback: "/x" } },
  };
  const html = fillClone(clone, { cta: "/analysis" }, [], [{ find: "/customer-stories", replace: "/stories" }]);
  assert.match(html, /href="https:\/\/seller\.example\/book-a-demo"/);
  assert.match(html, /href="\/stories"/);
  assert.match(html, /href="\/analysis"/);
});

test("an agent section's links are checked like the page's own: real pages, one destination", () => {
  const sections = { QuoteBand: { schema: { safeParse: () => ({ success: true }) } } };
  const home = structuredClone(site.pages["/"]);
  home.content.push({ type: "QuoteBand", props: { id: "quote", surface: "page", ctaHref: "/pricing" } });
  const pages = () => ({ "/": home, "/analysis": site.pages["/analysis"] });
  const missing = validateSite({ pages: pages(), shell: site.shell }, brand, sections);
  assert.ok(missing.errors.some((e) => e.startsWith("page.content.5(quote).ctaHref: links to /pricing, which is not a page of this site")), missing.errors.join("\n"));
  home.content[5].props.ctaHref = "https://example.com/somewhere-else";
  const two = validateSite({ pages: pages(), shell: site.shell }, brand, sections);
  assert.ok(two.errors.some((e) => e.startsWith("site: a 1:1 page has one primary destination")), two.errors.join("\n"));
});

test("an agent section's surface and look props are held to the brand's", () => {
  const sections = { QuoteBand: { schema: { safeParse: () => ({ success: true }) } } };
  const home = structuredClone(site.pages["/"]);
  home.content.push({ type: "QuoteBand", props: { id: "quote", surface: "canvas", ctaLook: "outline.1", cardLook: "" } });
  const pages = () => ({ "/": home, "/analysis": site.pages["/analysis"] });
  assert.deepEqual(validateSite({ pages: pages(), shell: site.shell }, brand, sections).errors, []);
  home.content[home.content.length - 1].props = { id: "quote", surface: "green", ctaLook: "solid.9", cardLook: "solid.7" };
  const errors = validateSite({ pages: pages(), shell: site.shell }, brand, sections).errors;
  assert.ok(errors.some((e) => e.includes('(quote).surface: "green" is not one of this brand\'s surfaces')), errors.join("\n"));
  assert.ok(errors.some((e) => e.includes('(quote).ctaLook: "solid.9" is not one of this brand\'s button styles')), errors.join("\n"));
  assert.ok(errors.some((e) => e.includes('(quote).cardLook: "solid.7" is not one of this brand\'s card styles')), errors.join("\n"));
});
