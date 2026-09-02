import assert from "node:assert/strict";
import { it } from "node:test";
import type { AssetLibraryItem } from "@/features/design-editor/adapter/scene-asset-library";
import { ASSET_LIBRARY_CATEGORIES, nextFocusIndex, shouldCloseOnKey, shouldCloseOnPointer, splitLibrarySections } from "./asset-library-panel.logic";

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
