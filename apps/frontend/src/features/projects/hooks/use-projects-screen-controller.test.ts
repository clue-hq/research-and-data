import assert from "node:assert/strict";
import test from "node:test";
import { paginate, visibleProjects } from "./use-projects-screen-controller";

const p = (id: string, extra = {}) => ({
  id,
  title: id,
  description: "",
  href: `/projects/${id}`,
  status: "active",
  pinned: false,
  brandId: "b",
  productId: null,
  createdAt: "2026-09-01T00:00:00Z",
  updatedAt: "2026-09-01T00:00:00Z",
  archivedAt: null,
  activity: { chats: 0, running: 0, needsInput: 0 },
  ...extra,
});

test("visibleProjects applies filter, query and sort exactly as the dummy did", () => {
  const all = [p("a"), p("b", { status: "archived" }), p("c", { pinned: true })];
  assert.deepEqual(
    visibleProjects(all as never, { filter: "active", query: "", sort: "name" }).map(
      (x) => x.id,
    ),
    ["c", "a"],
  );
  assert.deepEqual(
    visibleProjects(all as never, {
      filter: "archived",
      query: "",
      sort: "name",
    }).map((x) => x.id),
    ["b"],
  );
  assert.deepEqual(
    visibleProjects(all as never, { filter: "active", query: "C", sort: "name" }).map(
      (x) => x.id,
    ),
    ["c"],
  );
});

test("paginate slices 12 per page", () => {
  const many = Array.from({ length: 25 }, (_, i) => p(`p${i}`));
  assert.equal(paginate(many as never, 1).length, 12);
  assert.equal(paginate(many as never, 3).length, 1);
});
