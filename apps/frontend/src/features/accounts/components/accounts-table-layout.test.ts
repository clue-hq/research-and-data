import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const table = readFileSync(new URL("./accounts-table.tsx", import.meta.url), "utf8");

test("resizable headers constrain their labels without clipping resize handles", () => {
  const header = table.slice(table.indexOf("function HeaderCell("), table.indexOf("function ResearchBadge("));
  assert.match(header, /relative flex min-w-0/);
  assert.match(header, /className="min-w-0 truncate[^\"]*" title=\{label\}/);
  assert.doesNotMatch(header, /overflow-hidden/);
  assert.match(header, /<ColumnResizeHandle/);
});

test("table badges and plain values retain full text while truncating inside cells", () => {
  assert.match(table, /className=\{tableStyles\.cell\}/);
  assert.match(table, /typeof content === "string" \|\| typeof content === "number"/);
  assert.match(table, /title=\{String\(content\)\}/);
  assert.match(table, /function TableBadge\(/);
  assert.match(table, /className="min-w-0 truncate">\{children\}/);
  assert.match(table, /title=\{industry\}/);
  // The owner is `owner ?? createdBy ?? "Unassigned"` (source map §6).
  assert.match(table, /title=\{owner\.name\}/);
});

test("frozen columns release only when the table viewport is too narrow", () => {
  const css = readFileSync(new URL("./accounts-table.module.css", import.meta.url), "utf8");
  const screen = readFileSync(new URL("./accounts-screen.tsx", import.meta.url), "utf8");
  assert.match(screen, /tableStyles\.viewport/);
  assert.match(css, /container: accounts-table \/ inline-size/);
  assert.match(css, /\.pinnedCompany\s*\{\s*left: 56px;\s*position: sticky/);
  assert.match(css, /@container accounts-table \(max-width: 600px\)\s*\{\s*\.pinnedCompany\s*\{\s*left: auto;\s*position: relative/);
  assert.match(css, /\.cell \.badge\s*\{\s*flex: 0 1 auto;\s*max-width: 100%;\s*min-width: 0/);
  assert.equal(table.match(/tableStyles\.pinnedCompany/g)?.length, 2, "Header and rows must use the same pinning rule");
});
