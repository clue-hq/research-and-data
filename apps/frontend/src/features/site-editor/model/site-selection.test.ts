import assert from "node:assert/strict";
import { test } from "node:test";
import { componentProps } from "@clue/site-kit/editor-site";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import { commitFieldEdit, siteInspectorTitle } from "./site-selection";

const site = SiteDocumentSchema.parse({
  id: "doc-a",
  title: "A",
  theme: {},
  pages: {
    "/": {
      root: { props: { title: "Garner for SCSD" } },
      content: [{ type: "StatsBand", props: { id: "proof", heading: "7.4%", stats: [{ value: "1" }, { value: "2" }] } }],
    },
    "/analysis": { root: { props: {} }, content: [] },
  },
  shell: { header: { id: "header", preparedFor: "SCSD" }, footer: { id: "footer", legal: "©" } },
  agent_sections: {},
});

test("a field commit writes the prop at its path and keeps the component id", () => {
  const edit = commitFieldEdit(site, { componentId: "proof", target: "/" }, "heading", "8%");
  assert.equal(edit?.props.heading, "8%");
  assert.equal(edit?.props.id, "proof");
  assert.equal(componentProps(edit!.site, "/", "proof")?.heading, "8%");
});

test("a repeating item's field commits at its index", () => {
  const edit = commitFieldEdit(site, { componentId: "proof", target: "/" }, "stats.1.value", "22");
  assert.deepEqual(componentProps(edit!.site, "/", "proof")?.stats, [{ value: "1" }, { value: "22" }]);
});

test("a header field commits through the shell target", () => {
  const edit = commitFieldEdit(site, { componentId: "header", target: "shell" }, "preparedFor", "Syracuse City School District");
  assert.equal(componentProps(edit!.site, "shell", "header")?.preparedFor, "Syracuse City School District");
});

test("a commit for a section that is gone changes nothing", () => {
  assert.equal(commitFieldEdit(site, { componentId: "gone", target: "/" }, "heading", "x"), null);
});

test("the dock's title: the selected layer's label, else the page title, else the route", () => {
  const row = { active: true, componentId: "proof", icon: "layout-template" as const, key: "/#proof", label: "Stats band", target: "/" };
  assert.equal(siteInspectorTitle(site, "/", row), "Stats band");
  assert.equal(siteInspectorTitle(site, "/", undefined), "Garner for SCSD");
  assert.equal(siteInspectorTitle(site, "/analysis", undefined), "/analysis");
});

// Site element inspector (plan 1): a style commit writes the section's (or the shell part's) _edits.
import { commitStyleEdit } from "./site-selection";

test("a style commit writes the element's override into the section's _edits and keeps its other props", () => {
  const edit = commitStyleEdit(site, { componentId: "proof", target: "/" }, "heading", { fontSize: 48, italic: true });
  assert.deepEqual(edit?.props._edits, { heading: { fontSize: 48, italic: true } });
  assert.equal(edit?.props.heading, "7.4%");
  const again = commitStyleEdit(edit!.site, { componentId: "proof", target: "/" }, "stats.0.value", { fontWeight: 700 });
  assert.deepEqual(componentProps(again!.site, "/", "proof")?._edits, { heading: { fontSize: 48, italic: true }, "stats.0.value": { fontWeight: 700 } });
});

test("clearing the last property removes the element's entry, and an empty _edits goes too", () => {
  const styled = commitStyleEdit(site, { componentId: "proof", target: "/" }, "heading", { italic: true })!.site;
  const cleared = commitStyleEdit(styled, { componentId: "proof", target: "/" }, "heading", {});
  assert.equal("_edits" in (cleared?.props ?? {}), false);
});

test("a header style commits through the shell target", () => {
  const edit = commitStyleEdit(site, { componentId: "header", target: "shell" }, "preparedFor", { color: { token: "text.primary" } });
  assert.deepEqual(componentProps(edit!.site, "shell", "header")?._edits, { preparedFor: { color: { token: "text.primary" } } });
});

test("a style commit that changes nothing, or for a section that is gone, returns null", () => {
  const styled = commitStyleEdit(site, { componentId: "proof", target: "/" }, "heading", { italic: true })!.site;
  assert.equal(commitStyleEdit(styled, { componentId: "proof", target: "/" }, "heading", { italic: true }), null);
  assert.equal(commitStyleEdit(site, { componentId: "gone", target: "/" }, "heading", { italic: true }), null);
});

test("the colour picker offers the brand's role colours, not its technical palette ramps (ruling F3)", async () => {
  const { sitePalette } = await import("./site-selection");
  const brand = { kit: { tokens: { colors: { "text.brand": { value: "#006070" }, "palette.neutral.50": { value: "#F6F8FF" } } } } } as never;
  const options = sitePalette(brand, (b) => [{ token: "text.brand", value: "#006070" }, { token: "palette.neutral.50", value: "#F6F8FF" }]);
  assert.deepEqual(options, [{ label: "text.brand", value: "#006070" }]);
});

// Plan 2: styling highlighted words writes the element's text (a styled span) and the section's
// `_edits` (the span's look) in one commit.
import { commitWordStyle, wordsOverride } from "./site-selection";

const TYPO = { color: "#014036", fontFamily: "Garner Serif", fontSize: 48, fontWeight: 400, italic: false, underline: false, textAlign: "left" as const };
const headingWords = (start: number, end: number, text: string, prop = "heading") => ({
  componentId: "proof",
  target: "/",
  element: { key: "heading", kind: "text" as const, label: "7.4%", computed: TYPO, rich: { prop }, words: { start, end, count: 1, text, computed: TYPO } },
});
const wordsSite = SiteDocumentSchema.parse({
  ...site,
  pages: { ...site.pages, "/": { root: { props: {} }, content: [{ type: "StatsBand", props: { id: "proof", heading: "Top providers win", stats: [] } }] } },
});

test("styling highlighted words wraps them in a styled span and writes its look, in one commit", () => {
  const edit = commitWordStyle(wordsSite, headingWords(4, 13, "providers"), (old) => ({ ...old, fontWeight: 700 }));
  assert.ok(edit && "props" in edit);
  assert.equal(edit.props.heading, 'Top <span data-s="heading~1">providers</span> win');
  assert.deepEqual(edit.props._edits, { "heading~1": { fontWeight: 700 } });
  assert.deepEqual(wordsOverride(edit.site, headingWords(4, 13, "providers")), { fontWeight: 700 });
  const again = commitWordStyle(edit.site, headingWords(4, 13, "providers"), (old) => ({ ...old, italic: true }));
  assert.ok(again && "props" in again);
  assert.deepEqual(again.props._edits, { "heading~1": { fontWeight: 700, italic: true } }, "the same words keep their span");
});

test("words whose text no longer matches are refused with a note; a change that changes nothing is null", () => {
  assert.deepEqual(commitWordStyle(wordsSite, headingWords(4, 13, "something"), (old) => ({ ...old, italic: true })), {
    refused: "The text changed. Highlight the words again.",
  });
  assert.equal(commitWordStyle(wordsSite, headingWords(4, 13, "providers"), (old) => old), null);
});

test("a clone slot never set starts from its captured words", () => {
  const cloneSite = SiteDocumentSchema.parse({
    ...site,
    pages: { ...site.pages, "/": { root: { props: {} }, content: [{ type: "ClonedSection", props: { id: "hero", fragmentId: "frag_0000000000000001", slots: {}, replacements: [], links: [] } }] } },
  });
  const selection = {
    componentId: "hero",
    target: "/",
    element: { key: "0", kind: "text" as const, label: "Top", computed: TYPO, rich: { prop: "slots.headline", fallback: "Top<br>words" }, words: { start: 0, end: 3, count: 1, text: "Top", computed: TYPO } },
  };
  const edit = commitWordStyle(cloneSite, selection, () => ({ italic: true }));
  assert.ok(edit && "props" in edit);
  assert.deepEqual(edit.props.slots, { headline: '<span data-s="0~1">Top</span><br>words' });
  assert.deepEqual(edit.props._edits, { "0~1": { italic: true } });
});

test("words highlighted where they cannot be styled on their own say why", async () => {
  const { wordsUnavailableReason } = await import("./site-selection");
  const element = { key: "0.1", kind: "text" as const, label: "x", computed: TYPO, rich: null, words: { start: 0, end: 1, count: 1, text: "x", computed: TYPO } };
  assert.match(wordsUnavailableReason({ target: "/", componentType: "ClonedSection", element })!, /no slot/);
  assert.match(wordsUnavailableReason({ target: "shell", componentType: "SiteHeader", element })!, /header and footer/);
  assert.equal(wordsUnavailableReason({ target: "/", componentType: "ClonedSection", element: { ...element, words: null } }), null, "nothing highlighted");
  assert.equal(wordsUnavailableReason({ target: "/", componentType: "StatsBand", element: { ...element, rich: { prop: "heading" } } }), null);
});
