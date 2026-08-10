import assert from "node:assert/strict";
import test from "node:test";
import { nextSidebarState } from "./use-desktop-sidebar";

test("collapsed pointer or focus entry opens an overlay preview", () => {
  assert.equal(nextSidebarState("collapsed", "preview"), "hover-preview");
});

test("preview dismissal collapses without changing pinned state", () => {
  assert.equal(nextSidebarState("hover-preview", "dismiss"), "collapsed");
  assert.equal(
    nextSidebarState("pinned-expanded", "dismiss"),
    "pinned-expanded",
  );
});

test("click pins from both collapsed and preview states", () => {
  assert.equal(nextSidebarState("collapsed", "toggle"), "pinned-expanded");
  assert.equal(
    nextSidebarState("hover-preview", "toggle"),
    "pinned-expanded",
  );
});

test("clicking a pinned sidebar collapses it", () => {
  assert.equal(nextSidebarState("pinned-expanded", "toggle"), "collapsed");
});
