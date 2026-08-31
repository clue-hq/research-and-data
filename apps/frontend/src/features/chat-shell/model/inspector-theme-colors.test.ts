import assert from "node:assert/strict";
import test from "node:test";
import {
  INSPECTOR_THEME_COLORS,
  resolveInspectorThemeColors,
} from "./inspector-theme-colors";

// W4.0: `ColorControl` renders whatever option list it is given; every mount
// that supplies none keeps the dummy's fixture palette, pixel-identical.

test("no supplied options — the Theme tab's source is the fixture palette", () => {
  assert.equal(resolveInspectorThemeColors(undefined), INSPECTOR_THEME_COLORS);
});

test("an empty theme falls back too — never an empty Theme tab", () => {
  assert.equal(resolveInspectorThemeColors([]), INSPECTOR_THEME_COLORS);
});

// RULING A23 (2026-08-21): where a REAL palette source is wired, its absence
// must read as absence rather than as six invented colours. The fixture
// existed because there was no data source; the ad lane now has one, and it
// opts out of the fallback. The web lane's calls are untouched (the default),
// so nothing the web inspector shows changes.

test("A23: with the fallback declined, no options means an EMPTY Theme tab", () => {
  assert.deepEqual(resolveInspectorThemeColors(undefined, false), []);
  assert.deepEqual(resolveInspectorThemeColors([], false), []);
});

test("A23: declining the fallback never suppresses a palette that does exist", () => {
  const real = [{ label: "surface.brand", value: "#533AFD" }];
  assert.equal(resolveInspectorThemeColors(real, false), real);
});

test("supplied options win outright", () => {
  const real = [{ label: "Primary", value: "#0A5" }];
  assert.equal(resolveInspectorThemeColors(real), real);
});

test("the fixture palette is the dummy's, verbatim", () => {
  assert.deepEqual(INSPECTOR_THEME_COLORS, [
    { label: "Primary", value: "#44483F" },
    { label: "Secondary", value: "#D85A00" },
    { label: "Tertiary", value: "#00F59B" },
    { label: "Dark", value: "#1C2028" },
    { label: "Light", value: "#FFFFFF" },
    { label: "Subtle", value: "#EEF1F5" },
  ]);
});
