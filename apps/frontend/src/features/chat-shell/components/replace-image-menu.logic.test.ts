import assert from "node:assert/strict";
import { it } from "node:test";
import { REPLACE_IMAGE_MENU_ROWS, replaceImageMenuAction } from "./replace-image-menu.logic";

it("offers exactly two rows, in order, with no format enumeration", () => {
  assert.deepEqual(REPLACE_IMAGE_MENU_ROWS.map((row) => row.id), ["upload", "library"]);
  assert.deepEqual(REPLACE_IMAGE_MENU_ROWS.map((row) => row.label), ["Upload from computer", "Choose from asset library"]);
  for (const row of REPLACE_IMAGE_MENU_ROWS) assert.doesNotMatch(row.label, /png|jpg|jpeg|webp|svg/i);
});

it("maps each row to its action", () => {
  assert.deepEqual(replaceImageMenuAction("upload"), { kind: "open-file-dialog" });
  assert.deepEqual(replaceImageMenuAction("library"), { kind: "open-library" });
});
