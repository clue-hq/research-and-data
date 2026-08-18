import assert from "node:assert/strict";
import test from "node:test";
import {
  VIEW_MODE_BASE_TAG,
  VIEW_MODE_LINK_SCRIPT,
  canvasSandbox,
  viewModeHtml,
  viewModeLinkAction,
} from "./view-mode-html";

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
  assert.equal(
    html.replace(VIEW_MODE_BASE_TAG, "").replace(VIEW_MODE_LINK_SCRIPT, ""),
    RENDER,
  );
});

test("exactly one base tag and one link script are injected, however many heads the document mentions", () => {
  const html = viewModeHtml(RENDER);
  assert.equal(html.split(VIEW_MODE_BASE_TAG).length - 1, 1);
  assert.equal(html.split(VIEW_MODE_LINK_SCRIPT).length - 1, 1);
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
  assert.equal(html.split(VIEW_MODE_LINK_SCRIPT).length - 1, 1);
  assert.ok(html.includes("&lt;head&gt;&lt;script&gt;runtime()"));
  assert.ok(html.indexOf(VIEW_MODE_BASE_TAG) < html.indexOf("lumen-custom-component-frame"));
});

// --- the link classifier (founder ruling (a), 2026-08-19) ---------------------

test("a `#fragment` href scrolls the preview in place", () => {
  assert.equal(viewModeLinkAction("#pricing"), "scroll");
});

test("a bare `#` href scrolls too — it is the top-of-page link", () => {
  assert.equal(viewModeLinkAction("#"), "scroll");
});

test("http and https hrefs open a new tab, the Figma-preview convention", () => {
  assert.equal(viewModeLinkAction("https://example.com/pricing"), "new-tab");
  assert.equal(viewModeLinkAction("http://example.com"), "new-tab");
});

test("`mailto:` and `tel:` hrefs open a new tab — they are real destinations", () => {
  assert.equal(viewModeLinkAction("mailto:a@b.com"), "new-tab");
  assert.equal(viewModeLinkAction("tel:+15551234567"), "new-tab");
});

test("a protocol-relative `//host/path` href opens a new tab", () => {
  assert.equal(viewModeLinkAction("//cdn.example.com/x"), "new-tab");
});

test("a relative href is inert, because in the preview it would open an app-origin tab", () => {
  assert.equal(viewModeLinkAction("/story"), "inert");
  assert.equal(viewModeLinkAction("./page"), "inert");
  assert.equal(viewModeLinkAction("page.html"), "inert");
});

test("an empty href is inert", () => {
  assert.equal(viewModeLinkAction(""), "inert");
});

test("a `javascript:` href is inert whatever its casing", () => {
  assert.equal(viewModeLinkAction("javascript:alert(1)"), "inert");
  assert.equal(viewModeLinkAction("JavaScript:alert(1)"), "inert");
});

test("any scheme outside the allow-list is inert — the list is closed, not filtered", () => {
  // Defence in depth: our own href grammar refuses these on the write path, but
  // view mode renders whatever document the server hands back.
  assert.equal(viewModeLinkAction("data:text/html,<b>x</b>"), "inert");
  assert.equal(viewModeLinkAction("file:///etc/passwd"), "inert");
  assert.equal(viewModeLinkAction("vbscript:msgbox(1)"), "inert");
});

test("surrounding whitespace does not change the verdict", () => {
  assert.equal(viewModeLinkAction("  https://example.com  "), "new-tab");
  assert.equal(viewModeLinkAction("\n#pricing\t"), "scroll");
  assert.equal(viewModeLinkAction("   "), "inert");
});

// --- the link script injection -------------------------------------------------

test("the link script lands immediately after the base tag, which stays first", () => {
  const html = viewModeHtml(RENDER);
  const base = html.indexOf(VIEW_MODE_BASE_TAG);
  assert.equal(base + VIEW_MODE_BASE_TAG.length, html.indexOf(VIEW_MODE_LINK_SCRIPT));
  assert.equal(html.indexOf("<head>") + "<head>".length, base);
});

test("the injected script embeds the classifier itself, so tested and shipped behaviour cannot drift", () => {
  // The script is built from `viewModeLinkAction.toString()` — one
  // implementation, and the tests above are tests OF the shipped code.
  assert.ok(VIEW_MODE_LINK_SCRIPT.includes(viewModeLinkAction.toString()));
  assert.ok(VIEW_MODE_LINK_SCRIPT.includes('"new-tab"'));
  assert.ok(VIEW_MODE_LINK_SCRIPT.includes('closest("a[href]")'));
});

test("the script listens in the capture phase and is a single self-invoking `<script>`", () => {
  assert.ok(VIEW_MODE_LINK_SCRIPT.startsWith("<script>"));
  assert.ok(VIEW_MODE_LINK_SCRIPT.endsWith("</script>"));
  assert.ok(VIEW_MODE_LINK_SCRIPT.includes('addEventListener("click"'));
  // The `true` argument: capture, so a document that stops propagation on its
  // own handlers cannot take the preview's link behaviour down with it.
  assert.ok(/\}\s*,\s*true\s*\)/.test(VIEW_MODE_LINK_SCRIPT));
  assert.equal(VIEW_MODE_LINK_SCRIPT.split("<script").length - 1, 1);
});

test("the script scrolls a fragment target and does nothing for a new-tab link", () => {
  // The three actions, as the handler spends them: `scroll` prevents the
  // default and calls scrollIntoView; `inert` prevents the default and stops;
  // `new-tab` is deliberately absent from the handler — the base tag owns it.
  assert.ok(VIEW_MODE_LINK_SCRIPT.includes("scrollIntoView"));
  assert.ok(VIEW_MODE_LINK_SCRIPT.includes("getElementById"));
  assert.ok(VIEW_MODE_LINK_SCRIPT.includes("preventDefault"));
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
