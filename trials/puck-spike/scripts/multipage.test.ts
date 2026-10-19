// Multi-page sites: pages/<name>.json is validated like page.json, a link the page writes to
// "/<name>" must go to a page that exists, the shell's nav is checked, and a clone's own captured
// links keep pointing at the seller's site.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fillClone, type Clone } from "../lib/clone";
import { validate } from "./validate-page";

const site = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "data", "sites", "garner-syracuse.json"), "utf-8"));

function workspace(pages: Record<string, unknown>, shell = site.shell): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "multipage-"));
  fs.writeFileSync(path.join(dir, ".run.json"), JSON.stringify({ brand: "garner", site: "t", route: "/" }));
  fs.writeFileSync(path.join(dir, "shell.json"), JSON.stringify(shell));
  for (const [route, page] of Object.entries(pages)) {
    const file = route === "/" ? "page.json" : path.join("pages", `${route.slice(1)}.json`);
    fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    fs.writeFileSync(path.join(dir, file), JSON.stringify(page));
  }
  return dir;
}

test("a second page is validated like the home page", () => {
  const broken = structuredClone(site.pages["/analysis"]);
  broken.content[0].props.surface = "green";
  const result = validate(workspace({ "/": site.pages["/"], "/analysis": broken }));
  assert.equal(result.valid, false);
  assert.ok(result.errors.some((e) => e.startsWith("pages/analysis.content.0(") && e.includes("surface")), result.errors.join("\n"));
});

test("a link to a page that exists is fine; a link to a missing page names the pages", () => {
  // The phase-1 home page links to /analysis from its closing clone.
  assert.equal(validate(workspace({ "/": site.pages["/"], "/analysis": site.pages["/analysis"] })).valid, true);
  const result = validate(workspace({ "/": site.pages["/"] }));
  assert.equal(result.valid, false);
  assert.ok(result.errors.some((e) => e.includes("links to /analysis, which is not a page of this site") && e.includes("its pages are /")));
});

test("nav links are part of the shell and must go to real pages", () => {
  const shell = structuredClone(site.shell);
  shell.header.nav = [{ label: "The analysis", href: "/analysis" }, { label: "Pricing", href: "/pricing" }];
  const result = validate(workspace({ "/": site.pages["/"], "/analysis": site.pages["/analysis"] }, shell));
  assert.deepEqual(result.errors.filter((e) => e.includes("/pricing")).length, 1);
  assert.ok(result.errors[0].startsWith("shell.header.nav.1.href"), result.errors.join("\n"));
});

test("a page name uses lowercase letters, digits and dashes", () => {
  const result = validate(workspace({ "/": site.pages["/"], "/analysis": site.pages["/analysis"], "/Bad Name": site.pages["/analysis"] }));
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
