import assert from "node:assert/strict";
import { it } from "node:test";
import type { AssetLibraryItem } from "@/features/design-editor/adapter/scene-asset-library";
import { ASSET_LIBRARY_CATEGORIES, logoResultCaption, logoSearchHeading, nextFocusIndex, shouldCloseOnKey, shouldCloseOnPointer, splitLibrarySections } from "./asset-library-panel.logic";

const item = (id: string, pinned: boolean): AssetLibraryItem => ({
  record: { id, kind: "raster_image", label: id, status: "ready", source: { kind: "uploaded", filename: null, uploaded_by: null } },
  pinned, inUse: false, category: pinned ? "logo" : "upload",
});

it("offers the Brand-context categories plus Uploads, in order", () => {
  assert.deepEqual(ASSET_LIBRARY_CATEGORIES.map((c) => c.value), ["all", "logo", "background", "mockup", "upload", "ai-generated"]);
  assert.equal(ASSET_LIBRARY_CATEGORIES.find((c) => c.value === "upload")?.label, "Uploads");
});

it("splits pinned items into the Brand kit section, the rest into Workspace, preserving order", () => {
  const { brand, workspace } = splitLibrarySections([item("a", true), item("b", false), item("c", true)]);
  assert.deepEqual(brand.map((i) => i.record.id), ["a", "c"]);
  assert.deepEqual(workspace.map((i) => i.record.id), ["b"]);
});

it("closes on Escape only", () => {
  assert.equal(shouldCloseOnKey("Escape"), true);
  assert.equal(shouldCloseOnKey("Enter"), false);
});

it("closes on a pointerdown outside the panel, not inside", () => {
  const panel = { contains: (node: unknown) => node === "inside" };
  assert.equal(shouldCloseOnPointer("inside", panel), false);
  assert.equal(shouldCloseOnPointer("outside", panel), true);
  assert.equal(shouldCloseOnPointer(null, panel), true);
});

/** Base UI portals the category chip's listbox (and the Replace-image menu) OUTSIDE the panel, so a
 * press on an option is not `panel.contains`-inside. A target that reports one of those surfaces as
 * an ancestor is still OURS. */
const portalled = (surface: string) => ({
  closest: (selector: string) => (selector.includes(surface) ? { surface } : null),
});

it("keeps the panel open for a pointerdown on its own portalled chip listbox or menu", () => {
  const panel = { contains: (node: unknown) => node === "inside" };
  assert.equal(shouldCloseOnPointer(portalled('[role="option"]'), panel), false);
  assert.equal(shouldCloseOnPointer(portalled('[role="listbox"]'), panel), false);
  assert.equal(shouldCloseOnPointer(portalled('[role="menuitem"]'), panel), false);
  assert.equal(shouldCloseOnPointer(portalled('[role="menu"]'), panel), false);
  assert.equal(shouldCloseOnPointer({ closest: () => null }, panel), true);
});

it("leaves Escape to the chip's popup while it is open, and closes the panel elsewhere", () => {
  assert.equal(shouldCloseOnKey("Escape", portalled('[role="listbox"]')), false);
  assert.equal(shouldCloseOnKey("Escape", { closest: () => null }), true);
  assert.equal(shouldCloseOnKey("Escape", null), true);
  assert.equal(shouldCloseOnKey("Enter", portalled('[role="listbox"]')), false);
});

it("moves focus across a 4-column grid with the arrow keys and clamps at the edges", () => {
  assert.equal(nextFocusIndex(0, "ArrowRight", 10, 4), 1);
  assert.equal(nextFocusIndex(3, "ArrowRight", 10, 4), 4);
  assert.equal(nextFocusIndex(9, "ArrowRight", 10, 4), 9);
  assert.equal(nextFocusIndex(0, "ArrowLeft", 10, 4), 0);
  assert.equal(nextFocusIndex(1, "ArrowDown", 10, 4), 5);
  assert.equal(nextFocusIndex(9, "ArrowDown", 10, 4), 9);
  assert.equal(nextFocusIndex(5, "ArrowUp", 10, 4), 1);
  assert.equal(nextFocusIndex(2, "Tab", 10, 4), null);
});

it("logo search: a tile names the version, its background when one was claimed, and its source", () => {
  assert.deepEqual(logoResultCaption({ kind: "Full logo", background: "light", source: "Brandfetch" }), {
    title: "Full logo · light bg", source: "Brandfetch",
  });
  assert.deepEqual(logoResultCaption({ kind: "Icon", background: null, source: "Website" }), {
    title: "Icon", source: "Website",
  });
});

it("logo search: the heading names the company and counts the versions", () => {
  assert.equal(logoSearchHeading("stripe.com", 6), "stripe.com · 6 versions found");
  assert.equal(logoSearchHeading("stripe.com", 1), "stripe.com · 1 version found");
  assert.equal(logoSearchHeading(null, 2), "2 versions found");
});
