import assert from "node:assert/strict";
import test from "node:test";
import { routeAttachmentFiles } from "./attachment-routing";

const png = { name: "a.png", type: "image/png" } as File;
const md = { name: "b.md", type: "text/markdown" } as File;

test("with an ad leg open images go to design references, text to chat", () => {
  assert.deepEqual(routeAttachmentFiles([png, md], true), {
    design: [png],
    chat: [md],
  });
});

test("without an ad leg everything goes to chat", () => {
  assert.deepEqual(routeAttachmentFiles([png, md], false), {
    design: [],
    chat: [png, md],
  });
});
