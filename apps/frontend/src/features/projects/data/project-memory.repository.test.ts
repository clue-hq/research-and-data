import assert from "node:assert/strict";
import test from "node:test";
import { createHttpProjectMemoryRepository } from "./project-memory.repository";

test("memory routes go through the frontend/v1 BFF and a rejection surfaces its detail", async () => {
  const original = globalThis.fetch;
  const seen: string[] = [];
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    seen.push(`${init?.method ?? "GET"} ${url}`);
    if (url.endsWith("/memory") && init?.method === "POST") {
      return new Response(
        JSON.stringify({
          error: {
            code: "MEMORY_REJECTED",
            message: "route the fact to the claim store",
            requestId: "r1",
          },
        }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      );
    }
    return new Response(
      JSON.stringify({
        data: [
          {
            id: "m1",
            text: "Short subjects.",
            source_thread_id: null,
            source_thread_title: null,
            created_at: "2026-09-19T00:00:00Z",
          },
        ],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };
  try {
    const repo = createHttpProjectMemoryRepository();
    const notes = await repo.list("prj_1");
    assert.equal(seen[0], "GET /api/clue/frontend/v1/projects/prj_1/memory");
    assert.equal(notes[0].sourceThreadTitle, null);
    await assert.rejects(
      repo.add("prj_1", { text: "Acme's CFO is Jane." }),
      (error: Error & { code?: string }) => {
        assert.equal(error.code, "MEMORY_REJECTED");
        assert.equal(error.message, "route the fact to the claim store");
        return true;
      },
    );
  } finally {
    globalThis.fetch = original;
  }
});
