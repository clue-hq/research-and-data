import assert from "node:assert/strict";
import test from "node:test";
import {
  DirectoryPageWireSchema,
  filterDirectory,
  formatProjectDate,
  sortDirectory,
} from "./project-directory";

const wire = (id: string, extra: Record<string, unknown> = {}) => ({
  id,
  title: id,
  description: "",
  href: `/projects/${id}`,
  status: "active",
  pinned: false,
  brand_id: "brand_1",
  product_id: null,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-02T00:00:00Z",
  archived_at: null,
  activity: { chats: 0, running: 0, needs_input: 0 },
  ...extra,
});

test("the directory wire becomes camelCase view models", () => {
  const page = DirectoryPageWireSchema.parse({
    data: [wire("a")],
    meta: { next_cursor: "c" },
  });
  assert.equal(page.nextCursor, "c");
  assert.deepEqual(page.projects[0].activity, {
    chats: 0,
    running: 0,
    needsInput: 0,
  });
  assert.equal(page.projects[0].brandId, "brand_1");
});

test("sorting is pinned-first, then the chosen comparator; search matches title and description", () => {
  const page = DirectoryPageWireSchema.parse({
    data: [
      wire("beta", { updated_at: "2026-09-05T00:00:00Z" }),
      wire("alpha", {
        pinned: true,
        updated_at: "2026-09-01T00:00:00Z",
        description: "launch plan",
      }),
      wire("gamma", { created_at: "2026-09-09T00:00:00Z" }),
    ],
    meta: { next_cursor: null },
  });
  assert.deepEqual(
    sortDirectory(page.projects, "updated").map((p) => p.id),
    ["alpha", "beta", "gamma"],
  );
  assert.deepEqual(
    sortDirectory(page.projects, "name").map((p) => p.id),
    ["alpha", "beta", "gamma"],
  );
  assert.deepEqual(
    sortDirectory(page.projects, "created").map((p) => p.id),
    ["alpha", "gamma", "beta"],
  );
  assert.deepEqual(
    filterDirectory(page.projects, "LAUNCH").map((p) => p.id),
    ["alpha"],
  );
  assert.equal(formatProjectDate("2026-09-02T00:00:00Z"), "Sep 2");
});
