// T1 contracts: one Zod schema per component is the single source of truth for what a page may
// contain. These tests pin what the schemas must accept and refuse, and that the editor's fields
// never drift from them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { COMPONENT_SCHEMAS, PageSchema, formatIssues, shellSchemaWith } from "../src/schemas";
import { fillClone } from "../src/clone";
import { makeConfig } from "../src/config";
import { validateSite } from "../src/validate";
import { garner, site } from "./fixtures/garner";

test("the phase-1 pages and shells validate clean", () => {
  for (const name of ["garner-syracuse", "conduit-atrium"]) {
    const s = site(name);
    for (const [route, page] of Object.entries(s.pages)) {
      const result = PageSchema.safeParse(page);
      assert.ok(result.success, `${name}${route}: ${result.success ? "" : formatIssues(result.error)}`);
    }
    const shell = shellSchemaWith().safeParse(s.shell);
    assert.ok(shell.success, `${name} shell: ${shell.success ? "" : formatIssues(shell.error)}`);
  }
});

const garnerHome = () => structuredClone(site("garner-syracuse").pages["/"]);
const issues = (page: unknown) => {
  const result = PageSchema.safeParse(page);
  assert.equal(result.success, false, "expected the page to be refused");
  return result.success ? "" : formatIssues(result.error);
};

test("an unknown component type is refused, naming the allowed types", () => {
  const page = garnerHome();
  page.content.push({ type: "HeroBanner", props: { id: "x" } });
  const message = issues(page);
  assert.match(message, /HeroBanner/);
  assert.match(message, /StatsBand/);
});

test("free styling is refused: no className, style or colour props", () => {
  for (const extra of [{ className: "bg-red-500" }, { style: { color: "red" } }, { color: "#ff0000" }]) {
    const page = garnerHome();
    const stats = page.content.find((item: { type: string }) => item.type === "StatsBand");
    Object.assign(stats.props, extra);
    const message = issues(page);
    assert.match(message, new RegExp(Object.keys(extra)[0]));
  }
});

test("a surface outside the brand's choices is refused by the validator, listing the brand's surfaces", () => {
  const page = garnerHome();
  const stats = page.content.find((item: { type: string }) => item.type === "StatsBand");
  stats.props.surface = "green";
  const syracuse = site("garner-syracuse");
  const { errors } = validateSite({ pages: { ...syracuse.pages, "/": page }, shell: syracuse.shell }, garner(), {});
  assert.ok(errors.some((e) => e.includes('.surface: "green" is not one of this brand\'s surfaces') && e.includes("brandSubtle")), errors.join("\n"));
});

test("a cloned section needs a fragment id of the right shape", () => {
  const page = garnerHome();
  page.content[0].props.fragmentId = "hero-section";
  assert.match(issues(page), /fragmentId/);
});

test("a stats band needs one to four stats", () => {
  const page = garnerHome();
  const stats = page.content.find((item: { type: string }) => item.type === "StatsBand");
  stats.props.stats = [];
  assert.match(issues(page), /stats/);
});

test("every component's editor fields match its schema (no drift)", () => {
  const config = makeConfig(garner(), { cloneHtml: fillClone, basePath: "/s/x" });
  for (const [type, schema] of Object.entries(COMPONENT_SCHEMAS)) {
    const fields = Object.keys(config.components[type]?.fields ?? {}).sort();
    const keys = Object.keys(schema.shape).filter((key) => key !== "id").sort();
    assert.deepEqual(fields, keys, `${type}: editor fields vs schema`);
  }
});
