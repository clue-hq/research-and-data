import assert from "node:assert/strict";
import test from "node:test";
import { routeAttachmentFiles } from "./attachment-routing";

const png = { name: "a.png", type: "image/png" } as File;
const md = { name: "b.md", type: "text/markdown" } as File;
const pdf = { name: "c.pdf", type: "application/pdf" } as File;

test("with an ad leg open images go to design references, text to chat", () => {
  assert.deepEqual(routeAttachmentFiles([png, md, pdf], true), {
    design: [png],
    chat: [md, pdf],
  });
});

test("without an ad leg everything goes to chat", () => {
  assert.deepEqual(routeAttachmentFiles([png, md, pdf], false), {
    design: [],
    chat: [png, md, pdf],
  });
});
