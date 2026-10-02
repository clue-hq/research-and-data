import assert from "node:assert/strict";
import { test } from "node:test";
import { PROJECTS_API_BASE_URL_VAR } from "@/features/projects/data/chat-api";
import { getArtifactLibrary } from "./artifact-library.repository";

const row = (id: string) => ({
  id, document_id: id, project_id: "prj", project_title: "P", kind: "web", title: id, status: "draft",
  current_version: 1, created_at: "2026-09-01T00:00:00+00:00", updated_at: "2026-09-01T00:00:00+00:00",
  origin_thread_id: "thr", artifact_type: null, width_px: null, height_px: null, account: null,
  archived_at: null, saved: false, last_viewed_at: null,
});

test("walks every page of the cursor and returns one flat list", async () => {
  // The library reads live or not at all: with the projects transport unconfigured it is in
  // fixture mode and honestly empty, so the paging contract is only observable over HTTP.
  process.env[PROJECTS_API_BASE_URL_VAR] = "/api/clue";
  const calls: Array<Record<string, string | number | undefined>> = [];
  const read = async (_path: string, options?: { searchParams?: Record<string, string | number | undefined> }) => {
    calls.push(options?.searchParams ?? {});
    return calls.length === 1
      ? { data: { artifacts: [row("a"), row("b")] }, meta: { next_cursor: "c2" } }
      : { data: { artifacts: [row("c")] }, meta: { next_cursor: null } };
  };
  const library = await getArtifactLibrary(read as never);
  assert.deepEqual(library.artifacts.map((artifact) => artifact.id), ["a", "b", "c"]);
  assert.equal(calls[0].cursor, undefined);
  assert.equal(calls[1].cursor, "c2");
});

test("with no projects transport configured the library is honestly empty and reads nothing", async () => {
  delete process.env[PROJECTS_API_BASE_URL_VAR];
  const read = async () => {
    throw new Error("fixture mode must not reach the backend");
  };
  assert.deepEqual(await getArtifactLibrary(read as never), { artifacts: [] });
});
