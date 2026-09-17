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
const other = {
  ...open,
  address: { nodeId: "frg_b", path: ":nth-child(3)", tag: "p" },
  name: "p · body",
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

// Spec §3.4 / fix round 1: clicking a DIFFERENT element is the same gesture as
// clicking away — a non-blank draft is banked, never lost, and never carried
// across into the new box.
test("opening a different address banks a non-blank draft and starts the new box empty", () => {
  let s = annotationsReducer(EMPTY_ANNOTATIONS, open);
  s = annotationsReducer(s, { type: "edit", note: "Shorter" });
  s = annotationsReducer(s, other);
  assert.deepEqual(
    s.items.map((i) => [i.n, i.note, i.address.nodeId]),
    [[1, "Shorter", "frg_a"]],
  );
  assert.equal(s.pending?.address.nodeId, "frg_b");
  assert.equal(s.pending?.note, "");
  assert.equal(s.nextN, 2);
});

test("opening a different address with a blank draft adds nothing", () => {
  let s = annotationsReducer(EMPTY_ANNOTATIONS, open);
  s = annotationsReducer(s, { type: "edit", note: "  " });
  s = annotationsReducer(s, other);
  assert.equal(s.items.length, 0);
  assert.equal(s.nextN, 1);
  assert.equal(s.pending?.address.nodeId, "frg_b");
});

test("re-opening the SAME element keeps the half-typed draft", () => {
  let s = annotationsReducer(EMPTY_ANNOTATIONS, open);
  s = annotationsReducer(s, { type: "edit", note: "Shorter" });
  s = annotationsReducer(s, open);
  assert.equal(s.items.length, 0);
  assert.equal(s.pending?.note, "Shorter");
});

test("add with no argument stores the pending draft (the click-away path)", () => {
  let s = annotationsReducer(EMPTY_ANNOTATIONS, open);
  s = annotationsReducer(s, { type: "edit", note: " Shorter " });
  s = annotationsReducer(s, { type: "add" });
  assert.equal(s.pending, null);
  assert.deepEqual(
    s.items.map((i) => i.note),
    ["Shorter"],
  );
});

test("dismiss is an explicit cancel — a non-blank draft is dropped, not banked", () => {
  let s = annotationsReducer(EMPTY_ANNOTATIONS, open);
  s = annotationsReducer(s, { type: "edit", note: "Shorter" });
  s = annotationsReducer(s, { type: "dismiss" });
  assert.equal(s.pending, null);
  assert.equal(s.items.length, 0);
  assert.equal(s.nextN, 1);
});
