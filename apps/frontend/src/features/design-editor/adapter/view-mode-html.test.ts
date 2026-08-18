import assert from "node:assert/strict";
import test from "node:test";
import { VIEW_MODE_BASE_TAG, canvasSandbox, viewModeHtml } from "./view-mode-html";

// W4 addendum (founder rulings, 2026-08-19): the two pure decisions behind the
// view-mode canvas — what the view document's html needs before it is mounted,
// and which sandbox grants each mode's iframe gets. Both are one-liners at
// their call sites, which is exactly why they live here: this repo's runner has
// no React renderer (`tsx --test`, node:test), so a decision left inline in
// `web-artifact-canvas.tsx` would be untestable.

// A cut-down but structurally faithful render: the design API's clean render
// (no `bridge`, no `runtime_src`) is a complete standalone page — doctype,
// `<head>` with inline `<style>`, anchors already carrying `target="_blank"`
// where the author asked for it, and ZERO top-level `<script>` tags.
const RENDER = [
  "<!DOCTYPE html>",
  '<html lang="en">',
  "<head>",
  "<style>:root{--brand:#000}</style>",
  "</head>",
  "<body>",
  '<a href="https://example.com">Plain link</a>',
  '<a href="https://example.com" target="_blank" rel="noopener noreferrer">New-tab link</a>',
  "</body>",
  "</html>",
].join("\n");

// --- the base-target injection ----------------------------------------------

test("the view document carries `<base target=\"_blank\">` right after its `<head>`", () => {
  const html = viewModeHtml(RENDER);
  assert.ok(html.includes(VIEW_MODE_BASE_TAG));
  assert.equal(html.indexOf("<head>") + "<head>".length, html.indexOf(VIEW_MODE_BASE_TAG));
});

test("the base tag lands BEFORE the head's own content, so nothing in the head can outrank it", () => {
  const html = viewModeHtml(RENDER);
  assert.ok(html.indexOf(VIEW_MODE_BASE_TAG) < html.indexOf("<style>"));
});

test("everything else in the render is preserved byte for byte", () => {
  const html = viewModeHtml(RENDER);
  assert.equal(html.replace(VIEW_MODE_BASE_TAG, ""), RENDER);
});

test("exactly one base tag is injected, however many heads the document mentions", () => {
  const html = viewModeHtml(RENDER);
  assert.equal(html.split(VIEW_MODE_BASE_TAG).length - 1, 1);
});

// --- defensive: no head at all -----------------------------------------------

test("html with no `<head>` passes through unchanged", () => {
  // The empty/error shapes the render endpoint can hand back. Injecting into a
  // document that has no head would be inventing markup, so the input is
  // returned as-is and the canvas mounts exactly what the server sent.
  assert.equal(viewModeHtml(""), "");
  assert.equal(
    viewModeHtml("<html><body>no head here</body></html>"),
    "<html><body>no head here</body></html>",
  );
});

// --- nested custom-component frames ------------------------------------------

test("a nested custom-component srcdoc keeps its own escaped `<head>` untouched", () => {
  // Verified live (2026-08-19): a custom component instance renders as
  // `<iframe class="lumen-custom-component-frame" sandbox="allow-scripts"
  // srcdoc="…">` whose ~208KB srcdoc is an html-ESCAPED document carrying its
  // own head and the component runtime's scripts. Because that head is escaped
  // (`&lt;head&gt;`), a first-literal-`<head>` insertion cannot reach it — the
  // nested document must keep the base target its own author gave it, and the
  // outer base must not be smuggled into its markup.
  const nested = [
    "<!DOCTYPE html>",
    "<html>",
    "<head>",
    "<style>body{margin:0}</style>",
    "</head>",
    "<body>",
    '<iframe class="lumen-custom-component-frame" sandbox="allow-scripts"',
    ' srcdoc="&lt;html&gt;&lt;head&gt;&lt;script&gt;runtime()&lt;/script&gt;&lt;/head&gt;&lt;body&gt;card&lt;/body&gt;&lt;/html&gt;"></iframe>',
    "</body>",
    "</html>",
  ].join("\n");

  const html = viewModeHtml(nested);
  assert.equal(html.split(VIEW_MODE_BASE_TAG).length - 1, 1);
  assert.ok(html.includes("&lt;head&gt;&lt;script&gt;runtime()"));
  assert.ok(html.indexOf(VIEW_MODE_BASE_TAG) < html.indexOf("lumen-custom-component-frame"));
});

// --- the sandbox decision -----------------------------------------------------

test("editing keeps exactly the grants today's bridged editor has", () => {
  assert.equal(canvasSandbox(true), "allow-scripts");
});

test("viewing adds popups AND lets the opened tab escape the sandbox", () => {
  assert.equal(
    canvasSandbox(false),
    "allow-scripts allow-popups allow-popups-to-escape-sandbox",
  );
});

test("both modes keep allow-scripts, because nested custom components need it", () => {
  // An ancestor sandbox constrains nested browsing contexts, so dropping
  // `allow-scripts` from the outer frame would kill the custom-component
  // runtime inside its own `sandbox="allow-scripts"` iframe.
  for (const editing of [true, false]) {
    assert.ok(canvasSandbox(editing).split(" ").includes("allow-scripts"));
  }
});
