import assert from "node:assert/strict";
import { test } from "node:test";
import { httpAssetRepository } from "./asset.repository";

test("deleting an asset archives it on the design API", async () => {
  const calls: Array<{path: string; method?: string}> = [];
  const repository = httpAssetRepository(() => (async (path: string, init?: RequestInit) => {
    calls.push({path, method: init?.method});
    return new Response(JSON.stringify({schema_version: 1, asset: {id: "asset 1"}}), {status: 200});
  }) as typeof fetch);
  await repository.archive("asset 1");
  assert.deepEqual(calls, [{path: "/assets/asset%201/archive", method: "POST"}]);
});

test("a refused delete surfaces the design API's own message", async () => {
  const repository = httpAssetRepository(() => (async () =>
    new Response(JSON.stringify({detail: {message: "You cannot delete this asset."}}), {status: 403})) as typeof fetch);
  await assert.rejects(repository.archive("asset_1"), /You cannot delete this asset\./);
});
