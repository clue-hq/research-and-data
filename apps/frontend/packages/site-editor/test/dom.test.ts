import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { clickIntent, rectOf } from "../src/client/dom";

const dom = new JSDOM(`
  <div class="brand-root">
    <header><a id="nav" href="/analysis">Analysis</a></header>
    <div data-puck-component="proof"><h2 id="heading">Stats</h2><a id="cta" href="https://garnerhealth.com">Go</a></div>
    <a id="anchor" href="#top">Top</a>
    <footer><span id="legal">©</span></footer>
  </div>`);
const byId = (id: string) => dom.window.document.getElementById(id);

function summary(intent: ReturnType<typeof clickIntent>) {
  const { action, preventDefault } = intent;
  if (action.kind === "navigate") return { href: action.href, kind: action.kind, preventDefault };
  if (action.kind === "shell") return { kind: action.kind, part: action.part, preventDefault };
  if (action.kind === "component") return { componentId: action.componentId, kind: action.kind, preventDefault };
  return { kind: action.kind, preventDefault };
}

test("preview mode follows links and leaves in-page anchors to the browser", () => {
  assert.deepEqual(summary(clickIntent(byId("nav"), "preview")), { href: "/analysis", kind: "navigate", preventDefault: true });
  assert.deepEqual(summary(clickIntent(byId("cta"), "preview")), {
    href: "https://garnerhealth.com",
    kind: "navigate",
    preventDefault: true,
  });
  assert.deepEqual(summary(clickIntent(byId("anchor"), "preview")), { kind: "none", preventDefault: false });
  assert.deepEqual(summary(clickIntent(byId("heading"), "preview")), { kind: "none", preventDefault: false });
});

test("edit mode selects the header, the footer or a section, and never follows a link", () => {
  assert.deepEqual(summary(clickIntent(byId("nav"), "edit")), { kind: "shell", part: "header", preventDefault: true });
  assert.deepEqual(summary(clickIntent(byId("legal"), "edit")), { kind: "shell", part: "footer", preventDefault: false });
  assert.deepEqual(summary(clickIntent(byId("heading"), "edit")), { componentId: "proof", kind: "component", preventDefault: false });
  assert.deepEqual(summary(clickIntent(byId("cta"), "edit")), { componentId: "proof", kind: "component", preventDefault: true });
  assert.deepEqual(summary(clickIntent(byId("heading")?.firstChild ?? null, "edit")), {
    componentId: "proof",
    kind: "component",
    preventDefault: false,
  });
});

test("geometry is the element's box in viewport and document coordinates", () => {
  const element = { getBoundingClientRect: () => ({ bottom: 60, height: 50, left: 5, right: 105, top: 10, width: 100, x: 5, y: 10 }) };
  const geometry = rectOf(element as unknown as Element, { x: 0, y: 400 });
  assert.equal(geometry.viewport.top, 10);
  assert.equal(geometry.document.top, 410);
  assert.equal(geometry.document.y, 410);
  assert.equal(geometry.document.left, 5);
});
