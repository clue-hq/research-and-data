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
