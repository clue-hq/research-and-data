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
