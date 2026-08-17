import assert from "node:assert/strict";
import test from "node:test";
import {
  createHttpSidebarProjectsRepository,
  getSidebarProjects,
} from "./sidebar-projects.repository";

test("sidebar project fixtures preserve the project and thread hierarchy", async () => {
  const response = await getSidebarProjects();

  assert.equal(response.meta.nextCursor, null);
  assert.ok(response.data.length >= 3);
  assert.ok(response.data.some((project) => project.expanded));
  assert.ok(
    response.data.every((project) =>
      project.conversations.every((conversation) =>
        conversation.href.startsWith(project.href),
      ),
    ),
  );
});

test("HTTP sidebar is one real batch read with nullable-title fallback", async () => {
  const originalFetch = globalThis.fetch;
  let requested = "";
  globalThis.fetch = async (input) => {
    requested = String(input);
    return new Response(JSON.stringify({
      data: [{
        id: "prj_real",
        title: "Untitled project",
        href: "/projects/prj_real",
        conversations: [{
          id: "thr_real",
          title: null,
          href: "/projects/prj_real/chats/thr_real",
          status: "running",
          pinned: true,
          updated_at: "2026-08-10T12:00:00Z",
        }],
      }],
      meta: { next_cursor: "next-page" },
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  try {
    const response = await createHttpSidebarProjectsRepository({
      mode: "http",
      prefix: "/api/clue",
    }).list({ limit: 25 });
    assert.equal(requested, "/api/clue/api/v1/projects/sidebar?limit=25");
    assert.equal(response.data[0].conversations[0].title, "New chat");
    assert.equal(response.data[0].conversations[0].pinned, true);
    assert.equal(response.meta.nextCursor, "next-page");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
