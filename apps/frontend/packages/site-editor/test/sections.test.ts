import assert from "node:assert/strict";
import { test } from "node:test";
import { SectionLoadError, loadSections } from "../src/client/sections";

const DIGEST = "c".repeat(64);
const LINK = { digest: DIGEST, name: "AnalysisSteps", propsSchema: { type: "object" }, token: "tok_0123456789abcdef" };
const MODULE = { render: () => null, schema: { safeParse: () => ({ success: true }) } };

test("each section loads its module and stylesheet from this origin's token-checked route", async () => {
  const imported: string[] = [];
  const sheets: string[] = [];
  const loaded = await loadSections([LINK], {
    addStylesheet: (_digest, href) => sheets.push(href),
    importModule: async (url) => {
      imported.push(url);
      return MODULE;
    },
  });
  assert.deepEqual(imported, [`/sections/${DIGEST}.mjs?t=tok_0123456789abcdef`]);
  assert.deepEqual(sheets, [`/sections/${DIGEST}.css?t=tok_0123456789abcdef`]);
  assert.equal(loaded[0].name, "AnalysisSteps");
  assert.deepEqual(loaded[0].propsSchema, { type: "object" });
});

test("a module that fails to import, or exports no schema and render, fails the init with its name", async () => {
  await assert.rejects(
    loadSections([LINK], {
      addStylesheet: () => undefined,
      importModule: async () => {
        throw new TypeError("Failed to fetch dynamically imported module");
      },
    }),
    (error: unknown) => error instanceof SectionLoadError && error.sectionName === "AnalysisSteps",
  );
  await assert.rejects(
    loadSections([LINK], { addStylesheet: () => undefined, importModule: async () => ({ default: 1 }) }),
    SectionLoadError,
  );
});
