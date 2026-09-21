import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const renderer = readFileSync(new URL("./research-content.tsx", import.meta.url), "utf8");

function body(name: string): string {
  const start = renderer.indexOf(`export function ${name}(`);
  assert.notEqual(start, -1, `${name} exists`);
  const next = renderer.indexOf("\nexport function ", start + 1);
  return renderer.slice(start, next === -1 ? undefined : next);
}

test("every section renderer polls while a section is pending", () => {
  for (const name of ["ResearchDocument", "ResearchStack", "ResearchOverview"]) {
    assert.match(body(name), /usePendingSectionsRefresh\(anySectionPending\(sections\)\)/, name);
  }
});

test("the placeholder sentence is served, never hardcoded on the client", () => {
  assert.doesNotMatch(renderer, /Synthesis in progress/);
});
