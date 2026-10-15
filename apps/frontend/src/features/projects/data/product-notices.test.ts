import assert from "node:assert/strict";
import { test } from "node:test";
import { dismissProductNotice, readProductNotices } from "./product-notices";

const notice = { changeId: "chg-1", text: "Products changed on 15 Oct: 8 products merged into Proxon.", outcome: "updated", createdAt: "2026-10-15T10:00:00Z" };

test("the project's notices are read from the platform and a refused read is no notice", async () => {
  const calls: string[] = [];
  const notices = await readProductNotices("prj_1", (async (url: string) => {
    calls.push(String(url));
    return Response.json({ notices: [notice] });
  }) as typeof fetch);
  assert.deepEqual(notices, [notice]);
  assert.deepEqual(calls, ["/api/clue/frontend/v1/projects/prj_1/product-notices"]);
  assert.deepEqual(await readProductNotices("prj_1", (async () => new Response(null, { status: 500 })) as typeof fetch), []);
  assert.deepEqual(await readProductNotices("prj_1", (async () => { throw new TypeError("offline"); }) as typeof fetch), []);
});

test("dismissing posts once per notice and reports whether it landed", async () => {
  const calls: Array<[string, string | undefined]> = [];
  const ok = await dismissProductNotice("prj_1", "chg-1", (async (url: string, init?: RequestInit) => {
    calls.push([String(url), init?.method]);
    return new Response(null, { status: 204 });
  }) as typeof fetch);
  assert.equal(ok, true);
  assert.deepEqual(calls, [["/api/clue/frontend/v1/projects/prj_1/product-notices/chg-1/dismiss", "POST"]]);
  assert.equal(await dismissProductNotice("prj_1", "chg-1", (async () => new Response(null, { status: 404 })) as typeof fetch), false);
});
