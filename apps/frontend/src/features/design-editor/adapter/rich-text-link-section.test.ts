import assert from "node:assert/strict";
import test from "node:test";
import type { RichTextSelectionState } from "../engine/webBridge";
import { richTextToolbarValidContext } from "../components/web-rich-text-toolbar.logic";
import {
  richTextLinkCommit,
  richTextLinkPrefill,
  richTextLinkSectionVisible,
} from "./rich-text-link-section";

// W4.8b (contract item 3): the pure decisions behind the TEXT schema's
// conditional "Link to" section — when it exists at all, what it shows, and
// what one commit sends. The section itself is presentation
// (`web-inspector.tsx`'s TextControls region) and this repo's runner has no
// React renderer (`tsx --test`, node:test), so the decisions live here where
// they are testable — the same extraction pattern as
// `components/web-rich-text-toolbar.logic.ts`.

const RANGE: RichTextSelectionState = {
  collapsed: false,
  selectedText: "linked phrase",
  rect: null,
  formats: {
    bold: "off",
    italic: "off",
    underline: "off",
    strikethrough: "off",
  },
  commonClasses: [],
  mixedClasses: [],
  link: { state: "off", href: null, newTab: null },
  blockType: "paragraph",
  structured: false,
  canIndent: false,
  canOutdent: false,
};

// --- visibility (contract item 3: hidden = ABSENT, and only while a live
// rich-text range is selected) ----------------------------------------------

test("no session → the Link-to section is absent", () => {
  assert.equal(
    richTextLinkSectionVisible({
      editingNodeId: null,
      richTextSelection: RANGE,
    }),
    false,
  );
});

test("a session with no selection snapshot yet → absent", () => {
  assert.equal(
    richTextLinkSectionVisible({
      editingNodeId: "t1",
      richTextSelection: null,
    }),
    false,
  );
});

test("a live range carrying text → present", () => {
  assert.equal(
    richTextLinkSectionVisible({
      editingNodeId: "t1",
      richTextSelection: RANGE,
    }),
    true,
  );
});

test("a collapsed caret outside a link → absent", () => {
  assert.equal(
    richTextLinkSectionVisible({
      editingNodeId: "t1",
      richTextSelection: {
        ...RANGE,
        collapsed: true,
        selectedText: "",
      },
    }),
    false,
  );
});

test("a collapsed caret INSIDE a link → present (the link stays editable)", () => {
  assert.equal(
    richTextLinkSectionVisible({
      editingNodeId: "t1",
      richTextSelection: {
        ...RANGE,
        collapsed: true,
        selectedText: "",
        link: { state: "on", href: "/story", newTab: false },
      },
    }),
    true,
  );
});

test("an expanded range selecting no text (and no link) → absent", () => {
  assert.equal(
    richTextLinkSectionVisible({
      editingNodeId: "t1",
      richTextSelection: { ...RANGE, selectedText: "" },
    }),
    false,
  );
});

test("a STRUCTURED caret alone → absent, though the toolbar mounts for it", () => {
  // The one arm that distinguishes this predicate from the toolbar's
  // `richTextToolbarValidContext`: the toolbar carries BLOCK controls
  // (paragraph/list/indent) which act on a bare caret, so a structured caret
  // summons it. Link-to has no such control — a collapsed caret outside a link
  // is no range to bind an href to — so this section stays ABSENT. Asserting
  // both predicates on the SAME selection is the point: swap this function's
  // body for the toolbar's and this case is the one that fails.
  const structuredCaret: RichTextSelectionState = {
    ...RANGE,
    collapsed: true,
    selectedText: "",
    structured: true,
  };
  assert.equal(
    richTextLinkSectionVisible({
      editingNodeId: "t1",
      richTextSelection: structuredCaret,
    }),
    false,
  );
  assert.equal(richTextToolbarValidContext(structuredCaret), true);
});

test("a collapsed caret at a MIXED link boundary → absent (the ruling says on)", () => {
  assert.equal(
    richTextLinkSectionVisible({
      editingNodeId: "t1",
      richTextSelection: {
        ...RANGE,
        collapsed: true,
        selectedText: "",
        link: { state: "mixed", href: null, newTab: null },
      },
    }),
    false,
  );
});

// --- prefill (the toolbar's own semantics: an existing link fills the fields,
// anything else starts empty) ------------------------------------------------

test("a range inside a link prefills its href and new-tab flag", () => {
  assert.deepEqual(
    richTextLinkPrefill({
      ...RANGE,
      link: { state: "on", href: "https://clue.example/pricing", newTab: true },
    }),
    { href: "https://clue.example/pricing", newTab: true },
  );
});

test("a link with null href/new-tab prefills empty, never null", () => {
  assert.deepEqual(
    richTextLinkPrefill({
      ...RANGE,
      link: { state: "on", href: null, newTab: null },
    }),
    { href: "", newTab: false },
  );
});

test("an unlinked range prefills empty even when a stale href rides along", () => {
  assert.deepEqual(
    richTextLinkPrefill({
      ...RANGE,
      link: { state: "off", href: "https://stale.example", newTab: true },
    }),
    { href: "", newTab: false },
  );
});

test("a mixed link prefills empty", () => {
  assert.deepEqual(
    richTextLinkPrefill({
      ...RANGE,
      link: { state: "mixed", href: "https://one.example", newTab: true },
    }),
    { href: "", newTab: false },
  );
});

// --- the commit decision (validated FIRST; a bad href never becomes a
// command) -------------------------------------------------------------------

test("an unsafe href yields the grammar error and NO command", () => {
  const decision = richTextLinkCommit({
    href: "javascript:alert(1)",
    linkState: "off",
    newTab: false,
    trigger: "submit",
  });
  assert.equal(decision.kind, "invalid");
  assert.equal(
    decision.kind === "invalid" ? decision.error : null,
    "Use http(s), mailto, tel, an anchor (#…), or a site-relative path (/…).",
  );
});

test("a valid href becomes ONE trimmed set_link carrying the new-tab flag", () => {
  assert.deepEqual(
    richTextLinkCommit({
      href: "  https://clue.example/pricing  ",
      linkState: "off",
      newTab: true,
      trigger: "submit",
    }),
    {
      kind: "command",
      command: {
        type: "set_link",
        href: "https://clue.example/pricing",
        newTab: true,
      },
    },
  );
});

test("a site-relative path and an anchor are valid hrefs", () => {
  assert.equal(
    richTextLinkCommit({
      href: "/pricing",
      linkState: "off",
      newTab: false,
      trigger: "submit",
    }).kind,
    "command",
  );
  assert.equal(
    richTextLinkCommit({
      href: "#features",
      linkState: "off",
      newTab: false,
      trigger: "submit",
    }).kind,
    "command",
  );
});

test("committing an EMPTY url over an existing link removes it", () => {
  assert.deepEqual(
    richTextLinkCommit({
      href: "",
      linkState: "on",
      newTab: false,
      trigger: "submit",
    }),
    { kind: "command", command: { type: "remove_link" } },
  );
});

test("a whitespace-only url over an existing link removes it too", () => {
  assert.deepEqual(
    richTextLinkCommit({
      href: "   ",
      linkState: "on",
      newTab: true,
      trigger: "submit",
    }),
    { kind: "command", command: { type: "remove_link" } },
  );
});

test("an empty url with no link is a no-op — not an error", () => {
  assert.deepEqual(
    richTextLinkCommit({
      href: "",
      linkState: "off",
      newTab: false,
      trigger: "submit",
    }),
    { kind: "none" },
  );
});

test("an empty url at a mixed link is a no-op (the ruling removes only at on)", () => {
  assert.deepEqual(
    richTextLinkCommit({
      href: "",
      linkState: "mixed",
      newTab: false,
      trigger: "submit",
    }),
    { kind: "none" },
  );
});

// The new-tab checkbox commits immediately, but only when a valid href is
// already present: toggling it must never remove a link and never scold.

test("toggling new-tab with a valid href commits set_link at once", () => {
  assert.deepEqual(
    richTextLinkCommit({
      href: "https://clue.example",
      linkState: "on",
      newTab: true,
      trigger: "toggle",
    }),
    {
      kind: "command",
      command: {
        type: "set_link",
        href: "https://clue.example",
        newTab: true,
      },
    },
  );
});

test("toggling new-tab with an empty url over a link does NOT remove it", () => {
  assert.deepEqual(
    richTextLinkCommit({
      href: "",
      linkState: "on",
      newTab: true,
      trigger: "toggle",
    }),
    { kind: "none" },
  );
});

test("toggling new-tab with an invalid url is silent — no error, no command", () => {
  assert.deepEqual(
    richTextLinkCommit({
      href: "javascript:alert(1)",
      linkState: "on",
      newTab: false,
      trigger: "toggle",
    }),
    { kind: "none" },
  );
});
