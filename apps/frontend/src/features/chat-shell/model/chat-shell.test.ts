import assert from "node:assert/strict";
import test from "node:test";
import {
  CHAT_SHELL_INSPECTOR_SELECTIONS,
  parseChatShellInspectorSelection,
} from "./chat-shell";
import {
  IMAGE_EXPORT_FORMATS,
  IMAGE_EXPORT_SCALES,
  imageExportSupportsScale,
} from "./image-export";

test("the chat shell accepts every production inspector selection type", () => {
  assert.deepEqual(CHAT_SHELL_INSPECTOR_SELECTIONS, [
    "canvas",
    "text",
    "image",
    "button",
    "auto-layout",
    "rectangle",
    "ellipse",
    "group",
    "icon",
    "container",
    "section",
  ]);
});

test("inspector selection parsing accepts authored variants and rejects unknown values", () => {
  CHAT_SHELL_INSPECTOR_SELECTIONS.forEach((selection) => {
    assert.equal(parseChatShellInspectorSelection(selection), selection);
  });

  assert.equal(parseChatShellInspectorSelection(undefined), "canvas");
  assert.equal(parseChatShellInspectorSelection("video"), "canvas");
});

test("image export formats expose the v1 contract's capabilities", () => {
  // §2 delta (contract row 6 / §1.11): JPEG is dropped in v1, so PNG is the
  // only scalable (raster) format left. Gate G-E holds the transparency
  // capability out entirely — `imageExportSupportsTransparency` no longer
  // exists, so there is nothing to assert about it.
  assert.deepEqual(IMAGE_EXPORT_FORMATS, ["PNG", "SVG", "PDF"]);
  assert.deepEqual(IMAGE_EXPORT_SCALES, ["1x", "2x", "3x", "4x"]);

  assert.equal(imageExportSupportsScale("PNG"), true);
  assert.equal(imageExportSupportsScale("SVG"), false);
  assert.equal(imageExportSupportsScale("PDF"), false);
});
