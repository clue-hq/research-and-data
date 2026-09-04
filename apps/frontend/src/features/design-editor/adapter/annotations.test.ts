import assert from "node:assert/strict";
import test from "node:test";

import { annotationsReducer, EMPTY_ANNOTATIONS } from "./annotations";

const geometry = {
  viewport: { x: 1, y: 2, top: 2, right: 4, bottom: 6, left: 1, width: 3, height: 4 },
  document: { x: 1, y: 2, top: 2, right: 4, bottom: 6, left: 1, width: 3, height: 4 },
};
const open = {
  type: "open" as const,
  address: { nodeId: "frg_a", path: ":nth-child(1) > :nth-child(2)", tag: "h2" },
  name: "h2 · headline",
  textLike: true,
  geometry,
  pageId: "home",
};

test("open then add numbers the annotation and clears the pending box", () => {
  let s = annotationsReducer(EMPTY_ANNOTATIONS, open);
  assert.ok(s.pending);
  s = annotationsReducer(s, { type: "add", note: "Make this shorter" });
  assert.equal(s.pending, null);
  assert.deepEqual(
    s.items.map((i) => [i.n, i.note, i.pageId]),
    [[1, "Make this shorter", "home"]],
  );
  assert.equal(s.nextN, 2);
});

test("a blank note adds nothing (Add is inert on an empty box)", () => {
  const s = annotationsReducer(annotationsReducer(EMPTY_ANNOTATIONS, open), {
    type: "add",
    note: "   ",
  });
  assert.equal(s.items.length, 0);
  assert.ok(s.pending, "the box stays open");
});

test("numbers are never reused after a remove (R-A3: session-only, but stable while it lasts)", () => {
  let s = annotationsReducer(EMPTY_ANNOTATIONS, open);
  s = annotationsReducer(s, { type: "add", note: "one" });
  s = annotationsReducer(s, open);
  s = annotationsReducer(s, { type: "add", note: "two" });
  s = annotationsReducer(s, { type: "remove", n: 1 });
  s = annotationsReducer(s, open);
  s = annotationsReducer(s, { type: "add", note: "three" });
  assert.deepEqual(
    s.items.map((i) => i.n),
    [2, 3],
  );
});

test("clear drops everything", () => {
  const s = annotationsReducer(
    annotationsReducer(annotationsReducer(EMPTY_ANNOTATIONS, open), {
      type: "add",
      note: "x",
    }),
    { type: "clear" },
  );
  assert.deepEqual(s, EMPTY_ANNOTATIONS);
});
