import assert from "node:assert/strict";
import { test } from "node:test";
import { fetchSiteEditorSession } from "./site-editor-session";

test("the session read returns the editor origin, or null when none is configured", async () => {
  const calls: string[] = [];
  const answer = (editorOrigin: string | null) =>
    (async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return new Response(JSON.stringify({ data: { editorOrigin } }), { status: 200 });
    }) as typeof fetch;
  assert.deepEqual(await fetchSiteEditorSession(answer("https://aac8c47153e8e006ea26797aa03615b6.edit.example.com")), {
    editorOrigin: "https://aac8c47153e8e006ea26797aa03615b6.edit.example.com",
  });
  assert.deepEqual(await fetchSiteEditorSession(answer(null)), { editorOrigin: null });
  assert.equal(calls[0], "/api/clue/site-editor/session");
});

test("a refused session read throws with its status", async () => {
  const refused = (async () => new Response("{}", { status: 401 })) as typeof fetch;
  await assert.rejects(fetchSiteEditorSession(refused), /HTTP 401/);
});
