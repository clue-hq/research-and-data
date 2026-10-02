import assert from "node:assert/strict";
import test from "node:test";
import { mergeExpandedState } from "./use-sidebar-projects-controller";

test("a reload keeps the local expanded flags and takes the server's pinned flag", () => {
  const current = [{ id: "a", expanded: true, pinned: false }];
  const next = mergeExpandedState(current as never, [{ id: "a", expanded: false, pinned: true, title: "A", href: "/projects/a", conversations: [] }] as never);
  assert.equal(next[0].expanded, true);
  assert.equal(next[0].pinned, true);
});
