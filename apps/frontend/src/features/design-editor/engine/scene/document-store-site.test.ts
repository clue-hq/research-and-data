import assert from "node:assert/strict";
import { test } from "node:test";
import { fetchDocument, SITE_DOCUMENT_IN_SCENE_EDITOR } from "./documentStore";

// Master plan Review focus 1: a site document must never reach a scene-only path.
test("the scene loader refuses a site document instead of drawing it as an ad", async () => {
  const fetchImpl = (async () =>
    new Response(
      JSON.stringify({
        id: "doc-1",
        doc_kind: "site",
        title: "Syracuse",
        scene: { id: "doc-1", pages: { "/": { root: { props: {} }, content: [] } } },
        current_version: 2,
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    )) as typeof fetch;
  await assert.rejects(
    fetchDocument({ apiBaseUrl: "http://design.test", fetchImpl }, "doc-1"),
    (error: unknown) => error instanceof Error && error.message === SITE_DOCUMENT_IN_SCENE_EDITOR,
  );
});
