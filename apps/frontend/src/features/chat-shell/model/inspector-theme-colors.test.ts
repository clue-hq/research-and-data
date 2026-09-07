import assert from "node:assert/strict";
import test from "node:test";
import { resolveInspectorThemeColors } from "./inspector-theme-colors";

// Founder ruling 2026-09-04: no fixture palette anywhere. The Theme tab shows
// the document's real palette or nothing — never six invented colours.

test("no supplied options — the Theme tab is EMPTY, never a fixture palette", () => {
  assert.deepEqual(resolveInspectorThemeColors(undefined), []);
});

test("an empty palette stays empty", () => {
  assert.deepEqual(resolveInspectorThemeColors([]), []);
});

test("supplied options win outright, untouched", () => {
  const real = [{ label: "Surface-page", value: "#BAC8DA" }];
  assert.equal(resolveInspectorThemeColors(real), real);
});

test("nothing in the palette module is the sample site's mint green", () => {
  assert.equal(JSON.stringify(resolveInspectorThemeColors(undefined)).includes("00F59B"), false);
});
