import assert from "node:assert/strict";
import test from "node:test";
import type { MentionDirectory, MentionDirectoryLoad, MentionDirectoryRepository } from "../data/mention-directory.repository";
import { createMentionDirectoryStore } from "./mention-directory-store";

function directory(etag: string, label: string): MentionDirectory {
  return { complete: true, etag, entities: [{ id: label, label, secondaryLabel: "x", type: "account" }] };
}

function repositoryOf(responses: (MentionDirectoryLoad | Error)[]) {
  const calls: { projectId?: string | null; etag?: string | null }[] = [];
  const repository: MentionDirectoryRepository = {
    async load(input) {
      calls.push({ projectId: input.projectId, etag: input.etag });
      const next = responses.shift();
      if (next instanceof Error) throw next;
      return next ?? { status: "unchanged" };
    },
    async search() {
      return [];
    },
  };
  return { repository, calls };
}

test("the first load is cached and later checks revalidate with its ETag", async () => {
  const { repository, calls } = repositoryOf([
    { status: "loaded", directory: directory('"v1"', "Atrium") },
    { status: "unchanged" },
  ]);
  const store = createMentionDirectoryStore(repository);
  assert.equal(store.peek("prj_1"), null);
  assert.equal((await store.refresh("prj_1"))?.etag, '"v1"');
  assert.equal(store.peek("prj_1")?.etag, '"v1"');
  assert.equal((await store.refresh("prj_1"))?.etag, '"v1"');
  assert.deepEqual(calls, [
    { projectId: "prj_1", etag: null },
    { projectId: "prj_1", etag: '"v1"' },
  ]);
});

test("concurrent refreshes share one request, and a failure keeps the last good directory", async () => {
  const { repository, calls } = repositoryOf([
    { status: "loaded", directory: directory('"v1"', "Atrium") },
    new Error("offline"),
  ]);
  const store = createMentionDirectoryStore(repository);
  const [a, b] = await Promise.all([store.refresh("prj_1"), store.refresh("prj_1")]);
  assert.equal(calls.length, 1);
  assert.equal(a, b);
  assert.equal((await store.refresh("prj_1"))?.etag, '"v1"');
});

test("an unavailable directory (fixture mode) yields nothing, so the caller keeps its fallback", async () => {
  const { repository } = repositoryOf([{ status: "unavailable" }]);
  assert.equal(await createMentionDirectoryStore(repository).refresh(null), null);
});
