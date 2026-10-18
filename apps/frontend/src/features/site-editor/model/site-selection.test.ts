import assert from "node:assert/strict";
import { test } from "node:test";
import { componentProps } from "@clue/site-kit/editor-site";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import { commitFieldEdit, selectedKeyOf, siteInspectorTitle } from "./site-selection";

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
  shell: {
    header: { type: "SiteHeader", props: { id: "header", accountLine: "SCSD", ctaLabel: "Go", ctaHref: "/" } },
    footer: { type: "SiteFooter", props: { id: "footer", legal: "©" } },
  },
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
  const edit = commitFieldEdit(site, { componentId: "header", target: "shell" }, "accountLine", "Syracuse City School District");
  assert.equal(componentProps(edit!.site, "shell", "header")?.accountLine, "Syracuse City School District");
  assert.equal(edit!.site.shell!.header.type, "SiteHeader", "the entry keeps its type");
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
  const edit = commitStyleEdit(site, { componentId: "header", target: "shell" }, "accountLine", { color: { token: "text.primary" } });
  assert.deepEqual(componentProps(edit!.site, "shell", "header")?._edits, { accountLine: { color: { token: "text.primary" } } });
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
  // Plan 6 (ruling R11): the header's and footer's words are rich like any section's.
  assert.equal(wordsUnavailableReason({ target: "shell", componentType: "ClonedSection", element: { ...element, rich: { prop: "slots.account_line" } } }), null);
  assert.doesNotMatch(wordsUnavailableReason({ target: "shell", componentType: "SiteHeader", element }) ?? "", /header and footer/);
  assert.equal(wordsUnavailableReason({ target: "/", componentType: "ClonedSection", element: { ...element, words: null } }), null, "nothing highlighted");
  assert.equal(wordsUnavailableReason({ target: "/", componentType: "StatsBand", element: { ...element, rich: { prop: "heading" } } }), null);
});

test("the words' own look is not read from stale offsets (review finding 1)", () => {
  const styled = commitWordStyle(wordsSite, headingWords(4, 13, "providers"), (old) => ({ ...old, fontWeight: 700 }));
  assert.ok(styled && "props" in styled);
  assert.equal(wordsOverride(styled.site, headingWords(4, 13, "somethingx")), null);
});

// Plan 3: a selected button — its words' selection, its label's look, and its words.
import type { LabelSource } from "@clue/site-kit/editor-protocol";
import { commitLabelText, labelOverrideOf, labelSelectionOf } from "./site-selection";

const buttonSite = SiteDocumentSchema.parse({
  ...site,
  pages: {
    ...site.pages,
    "/": { root: { props: {} }, content: [
      { type: "CtaBand", props: { id: "cta", heading: "H", buttonLabel: 'Request <span data-s="button.label~1">the analysis</span> now', buttonHref: "/", _edits: { "button.label~1": { fontWeight: 700 }, "button.label": { italic: true } } } },
      { type: "ClonedSection", props: { id: "hero", fragmentId: "frag_0000000000000001", slots: {}, replacements: [], links: [] } },
    ] },
  },
});
const buttonSelection = (source: LabelSource, extra: object = {}) => ({
  componentId: "cta",
  componentType: "CtaBand",
  target: "/",
  element: {
    key: "button", kind: "button" as const, label: "Request the analysis now", computed: TYPO,
    labelElement: { key: "button.label", computed: TYPO, rich: { prop: "buttonLabel" } },
    labelSource: source, words: null, ...extra,
  },
});

test("a button's words are selected as its label: highlighted words style the label's span", () => {
  const selection = buttonSelection({ kind: "prop", prop: "buttonLabel" }, { words: { start: 0, end: 7, count: 1, text: "Request", computed: TYPO } });
  const label = labelSelectionOf(selection)!;
  assert.equal(label.element?.key, "button.label");
  const edit = commitWordStyle(buttonSite, label, (old) => ({ ...old, italic: false }));
  assert.ok(edit && "props" in edit);
  assert.equal(edit.props.buttonLabel, '<span data-s="button.label~2">Request</span> <span data-s="button.label~1">the analysis</span> now');
  assert.deepEqual(labelOverrideOf(buttonSite, selection), { italic: true });
});

test("retyping a button's words keeps the look of the words that stayed; the source decides where they go", () => {
  const edit = commitLabelText(buttonSite, buttonSelection({ kind: "prop", prop: "buttonLabel" }), "Request the analysis today");
  assert.ok(edit && "props" in edit);
  assert.equal(edit.props.buttonLabel, 'Request <span data-s="button.label~1">the analysis</span> today');
  const gone = commitLabelText(buttonSite, buttonSelection({ kind: "prop", prop: "buttonLabel" }), "Book a demo");
  assert.ok(gone && "props" in gone);
  assert.deepEqual(gone.props._edits, { "button.label": { italic: true } }, "the gone span's entry goes too");
  const slot = { ...buttonSelection({ kind: "slot", slot: "cta_label" }), componentId: "hero", componentType: "ClonedSection" };
  slot.element.labelElement = { key: "0.1", computed: TYPO, rich: { prop: "slots.cta_label", fallback: "Book a demo" } } as never;
  const viaSlot = commitLabelText(buttonSite, slot, "Talk to us");
  assert.ok(viaSlot && "props" in viaSlot);
  assert.deepEqual(viaSlot.props.slots, { cta_label: "Talk to us" });
  const replaced = { ...buttonSelection({ kind: "replacement", find: "Book a demo" }), componentId: "hero", componentType: "ClonedSection" };
  replaced.element.labelElement = { key: "0.1", computed: TYPO, rich: null } as never;
  const viaReplacement = commitLabelText(buttonSite, replaced, "Talk to us");
  assert.ok(viaReplacement && "props" in viaReplacement);
  assert.deepEqual(viaReplacement.props.replacements, [{ find: "Book a demo", replace: "Talk to us" }]);
  assert.equal(commitLabelText(buttonSite, buttonSelection({ kind: "fixed", reason: "ask the agent" }), "x"), null);
  assert.equal(commitLabelText(buttonSite, buttonSelection({ kind: "prop", prop: "buttonLabel" }), "Request the analysis now"), null, "the same words");
});

import { labelTextOf } from "./site-selection";

test("the Text row shows a button's words as stored, wherever they live", () => {
  assert.equal(labelTextOf(buttonSite, buttonSelection({ kind: "prop", prop: "buttonLabel" })), "Request the analysis now");
  const slot = { ...buttonSelection({ kind: "slot", slot: "cta_label" }), componentId: "hero", componentType: "ClonedSection" };
  slot.element.labelElement = { key: "0.1", computed: TYPO, rich: { prop: "slots.cta_label", fallback: "Book <strong>a demo</strong>" } } as never;
  assert.equal(labelTextOf(buttonSite, slot), "Book a demo", "a slot never set shows its captured words");
  const replaced = { ...buttonSelection({ kind: "replacement", find: "Book a demo" }), componentId: "hero", componentType: "ClonedSection" };
  assert.equal(labelTextOf(buttonSite, replaced), "Book a demo", "no replacement yet: the captured words");
  assert.equal(labelTextOf(buttonSite, buttonSelection({ kind: "fixed", reason: "ask the agent" })), null);
  assert.equal(labelTextOf(buttonSite, null), null);
});

import { wordsUnavailableReason } from "./site-selection";

test("words highlighted in a button are judged by its label's rich text, not the box's", () => {
  const words = { words: { start: 0, end: 7, count: 1, text: "Request", computed: TYPO } };
  const header = { ...buttonSelection({ kind: "prop", prop: "header.ctaLabel" }, words), target: "shell", componentType: "SiteHeader" };
  header.element.labelElement = { key: "cta.label", computed: TYPO, rich: { prop: "header.ctaLabel" } } as never;
  assert.notEqual(wordsUnavailableReason(header), null, "the box itself holds no rich text");
  assert.equal(wordsUnavailableReason(labelSelectionOf(header) ?? header), null);
});

test("a line break in a button's words shows as a space in the Text row (review 9)", () => {
  const broken = SiteDocumentSchema.parse({ ...buttonSite, pages: { ...buttonSite.pages, "/": { root: { props: {} }, content: [
    { type: "CtaBand", props: { id: "cta", heading: "H", buttonLabel: "Book<br>now", buttonHref: "/" } },
  ] } } });
  assert.equal(labelTextOf(broken, buttonSelection({ kind: "prop", prop: "buttonLabel" })), "Book now");
});

test("the selection names its element, else its background while the background is selected, else nothing", () => {
  const box = { fill: "#FFFFFF", borderColor: "", borderWidth: 0, radius: [0, 0, 0, 0], paddingY: 0, paddingX: 0, width: 100 };
  const sectionBox = { outer: { key: "root", box }, inner: { key: "root.inner", container: { ...box, gap: 0, layout: "text" as const, contentAlign: "start" as const, name: "Box" } } };
  assert.equal(selectedKeyOf({ element: null, sectionBox: null, backgroundKey: "root" }), null);
  assert.equal(selectedKeyOf({ element: null, sectionBox, backgroundKey: "root" }), "root");
  assert.equal(selectedKeyOf({ element: { key: "heading", kind: "text", label: "H" } as never, sectionBox: null, backgroundKey: "root" }), "heading");
});
