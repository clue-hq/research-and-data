import assert from "node:assert/strict";
import test from "node:test";

import { ResearchSectionSchema } from "./research-display";

test("a section is not pending unless the server says so", () => {
  const section = ResearchSectionSchema.parse({
    key: "why-now",
    h1: "Why now",
    empty: true,
    items: [],
  });
  assert.equal(section.pending, false);
});

test("a pending section keeps its served placeholder sentence", () => {
  const section = ResearchSectionSchema.parse({
    key: "why-now",
    h1: "Why now",
    empty: true,
    items: [],
    pending: true,
    emptyMessage: "Synthesis in progress, please wait a few seconds.",
  });
  assert.equal(section.pending, true);
  assert.equal(
    section.emptyMessage,
    "Synthesis in progress, please wait a few seconds.",
  );
});
