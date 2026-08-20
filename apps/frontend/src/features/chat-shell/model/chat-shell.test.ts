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
  imageExportSupportsTransparency,
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

test("image export formats expose Figma-compatible capabilities", () => {
  assert.deepEqual(IMAGE_EXPORT_FORMATS, ["PNG", "JPEG", "SVG", "PDF"]);
  assert.deepEqual(IMAGE_EXPORT_SCALES, ["1x", "2x", "3x", "4x"]);

  assert.equal(imageExportSupportsScale("PNG"), true);
  assert.equal(imageExportSupportsScale("JPEG"), true);
  assert.equal(imageExportSupportsScale("SVG"), false);
  assert.equal(imageExportSupportsScale("PDF"), false);
  assert.equal(imageExportSupportsTransparency("PNG"), true);
  assert.equal(imageExportSupportsTransparency("SVG"), true);
  assert.equal(imageExportSupportsTransparency("JPEG"), false);
  assert.equal(imageExportSupportsTransparency("PDF"), false);
});
