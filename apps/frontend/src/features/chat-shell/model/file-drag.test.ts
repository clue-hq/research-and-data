import assert from "node:assert/strict";
import test from "node:test";
import { dragCarriesFiles, filesFromDrop, nextDragDepth } from "./file-drag";

test("only a drag that carries files counts", () => {
  assert.equal(dragCarriesFiles(["Files"]), true);
  assert.equal(dragCarriesFiles(["text/plain"]), false);
  assert.equal(dragCarriesFiles(undefined), false);
});

test("the drag depth survives crossing between child elements", () => {
  // enter the pane, enter a child: two levels deep, so the leave the child
  // fires on the way in must NOT clear the target.
  let depth = nextDragDepth(0, "enter");
  depth = nextDragDepth(depth, "enter");
  depth = nextDragDepth(depth, "leave");
  assert.equal(depth, 1);
  assert.ok(depth > 0, "still over the pane");
});

test("leaving the last level clears the target, and a stray leave cannot go negative", () => {
  assert.equal(nextDragDepth(1, "leave"), 0);
  assert.equal(nextDragDepth(0, "leave"), 0);
});

test("a drop hands over its files as a real array", () => {
  const one = new File(["one"], "one.md", { type: "text/markdown" });
  const two = new File(["two"], "two.txt", { type: "text/plain" });
  // A real `DataTransfer.files` is a FileList: array-LIKE, never an Array. The
  // fake is shaped the same way, so a `return dataTransfer.files` that skipped
  // the copy would fail this assertion instead of sliding through.
  const fileList: ArrayLike<File> = { length: 2, 0: one, 1: two };
  const files = filesFromDrop({ files: fileList });
  assert.ok(Array.isArray(files));
  assert.deepEqual(
    files.map((file) => file.name),
    ["one.md", "two.txt"],
  );
  assert.deepEqual(filesFromDrop({ files: { length: 0 } }), []);
  assert.deepEqual(filesFromDrop(null), []);
  assert.deepEqual(filesFromDrop(undefined), []);
});
