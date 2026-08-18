import assert from "node:assert/strict";
import test from "node:test";
import type { RichTextSelectionState, WebNodeRect } from "../engine/webBridge";
import {
  classFacetValue,
  computeToolbarPosition,
  richTextLinkSubmission,
  richTextToolbarValidContext,
  toolbarThemeTokens,
} from "./web-rich-text-toolbar.logic";

// W4.8a: the source toolbar's behavioral contract
// (`WebRichTextToolbar.test.tsx`, 12 React-DOM cases) as far as it translates
// into this repo's renderer-free runner (`tsx --test`, node:test): the render
// gate, the class-facet on/mixed/off read, the theme-token list, the
// positioning math, and the validated link-submit flow. The remaining source
// cases are DOM-event assertions (focus handshake, Tab traversal, disabled
// controls) with no pure surface to test here — they are ported verbatim in
// the component and covered by browser verification.

const RECT: WebNodeRect = {
  x: 100,
  y: 100,
  top: 100,
  right: 300,
  bottom: 120,
  left: 100,
  width: 200,
  height: 20,
};

const RANGE: RichTextSelectionState = {
  collapsed: false,
  selectedText: "linked phrase",
  rect: RECT,
  formats: {
    bold: "on",
    italic: "mixed",
    underline: "off",
    strikethrough: "off",
  },
  commonClasses: ["text-primary"],
  mixedClasses: ["bg-accent"],
  link: { state: "off", href: null, newTab: null },
  blockType: "paragraph",
  structured: false,
  canIndent: false,
  canOutdent: false,
};

const FRAME = { top: 40, left: 20, right: 820, bottom: 640 };

// --- render gate (source: "renders only for a non-collapsed range or a caret
// inside a link") -----------------------------------------------------------

test("a collapsed caret outside a link has no toolbar context", () => {
  assert.equal(
    richTextToolbarValidContext({
      ...RANGE,
      collapsed: true,
      selectedText: "",
      link: { state: "off", href: null, newTab: null },
    }),
    false,
  );
});

test("a collapsed caret INSIDE a link keeps toolbar context", () => {
  assert.equal(
    richTextToolbarValidContext({
      ...RANGE,
      collapsed: true,
      selectedText: "",
      link: { state: "on", href: "/story", newTab: false },
    }),
    true,
  );
});

test("a live range with selected text has toolbar context", () => {
  assert.equal(richTextToolbarValidContext(RANGE), true);
});

test("a structured (body/small) selection always has toolbar context", () => {
  assert.equal(
    richTextToolbarValidContext({
      ...RANGE,
      collapsed: true,
      selectedText: "",
      structured: true,
    }),
    true,
  );
});

// --- class facets (source: "offers only resolved theme tokens…") ------------

test("one common token reads as on; a mixed token reads as mixed; neither reads as off", () => {
  const tokens = ["accent", "primary"];
  assert.deepEqual(classFacetValue(RANGE, "text-", tokens), {
    value: "primary",
    state: "on",
  });
  assert.deepEqual(classFacetValue(RANGE, "bg-", tokens), {
    value: null,
    state: "mixed",
  });
  assert.deepEqual(
    classFacetValue({ ...RANGE, commonClasses: [], mixedClasses: [] }, "text-", tokens),
    { value: null, state: "off" },
  );
});

test("two common tokens on the same facet read as mixed", () => {
  // The reported value is the first match in TOKEN order (the panel's own
  // order), not in selection order — source `:62-67`.
  assert.deepEqual(
    classFacetValue(
      { ...RANGE, commonClasses: ["text-primary", "text-accent"] },
      "text-",
      ["accent", "primary"],
    ),
    { value: "accent", state: "mixed" },
  );
});

// --- theme tokens ----------------------------------------------------------

test("theme tokens are name-sorted pairs", () => {
  assert.deepEqual(
    toolbarThemeTokens({
      bodyFamily: null,
      displayFamily: null,
      tokens: { primary: "#111", accent: "#f54e00" },
    }),
    [
      ["accent", "#f54e00"],
      ["primary", "#111"],
    ],
  );
  assert.deepEqual(toolbarThemeTokens(null), []);
});

test("ruling F3: palette-* ramp tokens are hidden from the color panels", () => {
  assert.deepEqual(
    toolbarThemeTokens({
      bodyFamily: null,
      displayFamily: null,
      tokens: {
        "palette-primary-500": "#123456",
        accent: "#f54e00",
        "palette-neutral-100": "#eee",
      },
    }),
    [["accent", "#f54e00"]],
  );
});

// --- positioning (source: fixed-position math, EDGE_GAP 12 / RANGE_GAP 10) --

test("a range with room above places the toolbar above it, centered and clamped", () => {
  assert.deepEqual(
    computeToolbarPosition({
      frame: FRAME,
      range: RECT,
      toolbar: { width: 400, height: 40 },
      viewport: { width: 1000, height: 800 },
    }),
    // rangeTop 140, rangeBottom 160, center 220 → above = 140-40-10 = 90 ≥ 12
    { left: 20, top: 90, placement: "above" },
  );
});

test("a range too close to the top flips the toolbar below it", () => {
  assert.deepEqual(
    computeToolbarPosition({
      frame: FRAME,
      range: { ...RECT, top: 0, bottom: 20, y: 0 },
      toolbar: { width: 400, height: 40 },
      viewport: { width: 1000, height: 800 },
    }),
    // above = 40-40-10 = -10 < 12 → below at rangeBottom(60) + 10
    { left: 20, top: 70, placement: "below" },
  );
});

test("the toolbar never crosses either viewport edge", () => {
  assert.equal(
    computeToolbarPosition({
      frame: FRAME,
      range: { ...RECT, left: 0, x: 0, width: 10, right: 10 },
      toolbar: { width: 400, height: 40 },
      viewport: { width: 1000, height: 800 },
    })?.left,
    12,
  );
  assert.equal(
    computeToolbarPosition({
      frame: FRAME,
      range: { ...RECT, left: 780, x: 780, width: 20, right: 800 },
      toolbar: { width: 200, height: 40 },
      viewport: { width: 830, height: 800 },
    })?.left,
    // 830 - 200 - 12 = 618, below the centered 710
    618,
  );
});

test("a range scrolled out of the frame yields no position", () => {
  assert.equal(
    computeToolbarPosition({
      frame: FRAME,
      range: { ...RECT, top: -100, bottom: -60, y: -100 },
      toolbar: { width: 400, height: 40 },
      viewport: { width: 1000, height: 800 },
    }),
    null,
  );
  assert.equal(
    computeToolbarPosition({
      frame: FRAME,
      range: { ...RECT, left: 900, x: 900, width: 20, right: 920 },
      toolbar: { width: 400, height: 40 },
      viewport: { width: 1000, height: 800 },
    }),
    null,
  );
});

// --- link submit (source: "rejects unsafe links, applies safe links…") ------

test("an unsafe href is refused with the engine's message and sends no command", () => {
  const submission = richTextLinkSubmission("javascript:alert(1)", false);
  assert.equal(submission.ok, false);
  assert.match(submission.ok ? "" : submission.error, /^Use http\(s\)/);
});

test("an empty href is refused before anything is sent", () => {
  const submission = richTextLinkSubmission("   ", true);
  assert.equal(submission.ok, false);
  assert.equal(submission.ok ? "" : submission.error, "Enter a link URL.");
});

test("a safe href becomes exactly one trimmed set_link command", () => {
  const submission = richTextLinkSubmission("  /safe  ", true);
  assert.equal(submission.ok, true);
  assert.deepEqual(submission.ok ? submission.command : null, {
    type: "set_link",
    href: "/safe",
    newTab: true,
  });
});

test("http, mailto and anchor hrefs are all accepted", () => {
  for (const href of [
    "https://example.com/lane-c",
    "http://example.com",
    "mailto:hi@example.com",
    "tel:+1555",
    "#section",
    "/relative",
  ]) {
    assert.equal(richTextLinkSubmission(href, false).ok, true, href);
  }
});
