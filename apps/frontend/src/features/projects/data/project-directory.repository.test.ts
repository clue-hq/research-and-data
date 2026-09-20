import assert from "node:assert/strict";
import test from "node:test";
import { createHttpProjectDirectoryRepository } from "./project-directory.repository";

function stubFetch(pages: Record<string, unknown>) {
  const calls: {
    url: string;
    method: string;
    body: unknown;
    idem: string | null;
  }[] = [];
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    const headers = new Headers(init?.headers);
    calls.push({
      url,
      method: init?.method ?? "GET",
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
      idem: headers.get("Idempotency-Key"),
    });
    const key = Object.keys(pages).find(
      (k) => url.endsWith(k) || url.includes(k),
    );
    return new Response(JSON.stringify(pages[key ?? ""]), {
      status: init?.method === "POST" && url.endsWith("/blank") ? 201 : 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  return calls;
}

const item = (id: string, pinned = false) => ({
  id,
  title: id,
  description: "",
  href: `/projects/${id}`,
  status: "active",
  pinned,
  brand_id: "b",
  product_id: null,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-02T00:00:00Z",
  archived_at: null,
  activity: { chats: 1, running: 0, needs_input: 0 },
});

test("listAll walks the cursor and every mutation hits its real route", async () => {
  const original = globalThis.fetch;
  // The cursor page is listed first because the first page's query string is a
  // substring of the second's: the more specific match has to win.
  const calls = stubFetch({
    "cursor=cur": { data: [item("two")], meta: { next_cursor: null } },
    "status=active&limit=100": {
      data: [item("one")],
      meta: { next_cursor: "cur" },
    },
    "/blank": { data: item("new") },
    "/projects/one/archive": {
      data: {
        ...item("one"),
        status: "archived",
        archived_at: "2026-09-03T00:00:00Z",
      },
    },
    "/projects/one": { data: item("one", true) },
  });
  try {
    const repo = createHttpProjectDirectoryRepository({
      mode: "http",
      prefix: "/api/clue",
    });
    const all = await repo.listAll("active");
    assert.deepEqual(
      all.map((p) => p.id),
      ["one", "two"],
    );
    const created = await repo.create({
      brandId: "b",
      title: "T",
      description: "D",
      idempotencyKey: "blank:1",
    });
    assert.equal(created.id, "new");
    assert.equal(calls.find((c) => c.url.endsWith("/blank"))?.idem, "blank:1");
    assert.deepEqual(calls.find((c) => c.url.endsWith("/blank"))?.body, {
      brand_id: "b",
      title: "T",
      description: "D",
    });
    const pinned = await repo.update("one", { pinned: true });
    assert.equal(pinned.pinned, true);
    assert.equal(
      calls.find((c) => c.method === "PATCH")?.url,
      "/api/clue/api/v1/projects/one",
    );
    const archived = await repo.setArchived("one", true);
    assert.equal(archived.status, "archived");
    assert.deepEqual(calls.find((c) => c.url.endsWith("/archive"))?.body, {
      archived: true,
    });
  } finally {
    globalThis.fetch = original;
  }
});
