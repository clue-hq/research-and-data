import assert from "node:assert/strict";
import test from "node:test";
import { createHttpMentionDirectoryRepository } from "./mention-directory.repository";

const TRANSPORT = { mode: "http" as const, prefix: "/api/clue" };

const ATRIUM = {
  object_type: "account",
  object_id: "acc-atrium",
  label: "Atrium Hospitality",
  secondary_label: "atrium.example",
  image_url: "/api/accounts/acc-atrium/logo",
  version: null,
  account_id: null,
  account_name: null,
};
const PERSON = {
  object_type: "contact",
  object_id: "con-1",
  label: "Dana Reyes",
  secondary_label: "VP Operations",
  image_url: null,
  version: null,
  account_id: "acc-atrium",
  account_name: "Atrium Hospitality",
};

test("a loaded directory maps to picker entities and carries its ETag; revalidation sends it", async () => {
  const seen: { url: string; headers: Headers }[] = [];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ url: String(input), headers: new Headers(init?.headers) });
    return new Response(JSON.stringify({ data: { entities: [ATRIUM, PERSON], complete: true } }), {
      status: 200,
      headers: { "content-type": "application/json", etag: '"v1"' },
    });
  }) as typeof fetch;
  const repository = createHttpMentionDirectoryRepository(TRANSPORT, fetchImpl);
  const result = await repository.load({ projectId: "prj_1", etag: '"v0"' });
  assert.equal(result.status, "loaded");
  if (result.status !== "loaded") return;
  assert.equal(result.directory.etag, '"v1"');
  assert.equal(result.directory.complete, true);
  assert.deepEqual(result.directory.entities[1], {
    accountId: "acc-atrium",
    accountName: "Atrium Hospitality",
    id: "con-1",
    label: "Dana Reyes",
    secondaryLabel: "VP Operations",
    type: "contact",
  });
  assert.equal(result.directory.entities[0].imagePath, "/api/accounts/acc-atrium/logo");
  assert.equal(seen[0].url, "/api/clue/api/v1/mention-directory?project_id=prj_1");
  assert.equal(seen[0].headers.get("if-none-match"), '"v0"');
});

test("a 304 means the cached directory is still current", async () => {
  const fetchImpl = (async () => new Response(null, { status: 304 })) as typeof fetch;
  const repository = createHttpMentionDirectoryRepository(TRANSPORT, fetchImpl);
  assert.deepEqual(await repository.load({ projectId: null, etag: '"v1"' }), { status: "unchanged" });
});

test("server search maps its matches and asks with the query", async () => {
  const urls: string[] = [];
  const fetchImpl = (async (input: RequestInfo | URL) => {
    urls.push(String(input));
    return Response.json({ data: { entities: [ATRIUM] } });
  }) as typeof fetch;
  const repository = createHttpMentionDirectoryRepository(TRANSPORT, fetchImpl);
  const found = await repository.search({ query: "atri" });
  assert.deepEqual(found.map((entity) => entity.id), ["acc-atrium"]);
  assert.equal(urls[0], "/api/clue/api/v1/mention-directory/search?q=atri");
});
