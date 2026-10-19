import assert from "node:assert/strict";
import { test } from "node:test";
import { pageSchemaWith } from "../src/schemas";

const page = (id: string) => ({ root: { props: { title: "T" } }, content: [{ type: "Unknown", props: { id } }] });
const idIssues = (id: string) => {
  const result = pageSchemaWith().safeParse(page(id));
  return result.success ? [] : result.error.issues.filter((issue) => issue.message.startsWith("a section id may use only"));
};

test("a section id is letters, digits, - and _ only, so an editor target is never ambiguous", () => {
  for (const id of ["hero", "analysis-hero", "Hero_2", "CtaBand-1a2b3c"]) assert.deepEqual(idIssues(id), [], id);
  for (const id of ["hero.v2", "a#b", "with space", "x".repeat(201)]) {
    const issues = idIssues(id);
    assert.equal(issues.length, 1, id);
    assert.deepEqual(issues[0].path, ["content", 0, "props", "id"]);
    assert.ok(issues[0].message.endsWith(`"${id}" does not`), issues[0].message);
  }
});

// Review finding K1-2: the editor refuses to open a site whose section has no text id
// (site-document.ts ComponentIdSchema), so saving one is refused whatever the section's own schema
// allows — an agent section whose id is optional and left out, a number, or a default never written.
test("K1-2: a section with no id, or an id that is not text, is refused at save", () => {
  const issuesFor = (props: Record<string, unknown>) => {
    const result = pageSchemaWith().safeParse({ root: { props: { title: "T" } }, content: [{ type: "Unknown", props }] });
    return result.success ? [] : result.error.issues.filter((issue) => issue.message.startsWith("every section needs an id"));
  };
  for (const props of [{}, { id: 7 }, { id: null }, { id: "" }]) {
    const issues = issuesFor(props);
    assert.equal(issues.length, 1, JSON.stringify(props));
    assert.deepEqual(issues[0].path, ["content", 0, "props", "id"]);
  }
  assert.deepEqual(issuesFor({ id: "hero" }), []);
});

test("K1-2: the save rule and the editor's read rule are the same rule", async () => {
  const { ComponentIdSchema } = await import("../src/site-document");
  for (const id of ["hero", "Hero_2", "", "a.b", "x".repeat(201), 7, null, undefined]) {
    const editorAccepts = ComponentIdSchema.safeParse(id).success;
    const props = id === undefined ? {} : { id };
    const result = pageSchemaWith().safeParse({ root: { props: { title: "T" } }, content: [{ type: "Unknown", props }] });
    const saveRefusesId = !result.success && result.error.issues.some((issue) => issue.path.join(".") === "content.0.props.id");
    assert.equal(!saveRefusesId, editorAccepts, `id ${JSON.stringify(id)}`);
  }
});
