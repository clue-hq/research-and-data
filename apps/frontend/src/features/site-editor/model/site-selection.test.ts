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
