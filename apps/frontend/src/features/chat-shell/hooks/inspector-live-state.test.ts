import test from "node:test";
import assert from "node:assert/strict";
import {
  composeInspectorState,
  DEFAULT_STATE,
  type InspectorPresentationState,
} from "./use-inspector-controller";

// A representative uiState: the real DEFAULT_STATE with a few fields moved off
// their defaults, standing in for stale mount-time copies.
const base = (): InspectorPresentationState => ({
  ...structuredClone(DEFAULT_STATE),
  fillMode: "Fill",
  radius: { all: "9", bottomLeft: "9", bottomRight: "9", topLeft: "9", topRight: "9" },
  openSections: { ...DEFAULT_STATE.openSections, fill: false },
});

test("hydrated wins every key it carries", () => {
  const composed = composeInspectorState(base(), {
    fillMode: "Fit",
    radius: { all: "", bottomLeft: "4", bottomRight: "4", topLeft: "4", topRight: "96" },
  });
  assert.equal(composed.fillMode, "Fit");
  assert.deepEqual(composed.radius, { all: "", bottomLeft: "4", bottomRight: "4", topLeft: "4", topRight: "96" });
});

test("keys hydration does not carry fall back to uiState", () => {
  const composed = composeInspectorState(base(), { fillMode: "Fit" });
  assert.equal(composed.fontFamily, base().fontFamily);
});

test("openSections always come from uiState, never hydration", () => {
  const composed = composeInspectorState(base(), {
    openSections: { ...base().openSections, fill: true },
  } as never);
  assert.equal(composed.openSections.fill, false);
});

test("undefined hydration composes to uiState unchanged", () => {
  assert.deepEqual(composeInspectorState(base(), undefined), base());
});
