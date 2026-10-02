import assert from "node:assert/strict";
import test from "node:test";
import { AccountDetailResponseSchema } from "@/features/accounts/model/account-detail";
import { fixtureAccountDetailsRepository } from "@/features/accounts/data/account-details.repository";
import { GET } from "./[accountId]/route";

// This file sits one segment ABOVE the route it exercises, the way
// `api/clue/design/route.test.ts` does: `npm test` hands each path to the
// runner, which glob-expands it, so a test inside `[accountId]/` is silently
// collected as ZERO tests.
//
// The design build switched adapters on `CLUE_API_BASE_URL`; the platform's
// accounts repositories read one explicit opt-in switch instead
// (`data/repository-mode.ts`), so these cases set that.
function useFixtureMode(t: { after(fn: () => void): void }, enabled: boolean) {
  const previous = process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
  process.env.CLUE_ACCOUNTS_FIXTURE_MODE = enabled ? "true" : "false";
  t.after(() => {
    if (previous === undefined) delete process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
    else process.env.CLUE_ACCOUNTS_FIXTURE_MODE = previous;
  });
}

test("project preview requests return the complete canonical account record", async (t) => {
  useFixtureMode(t, true);

  for (const id of ["zafran-security", "openai"]) {
    const response = await GET(new Request(`http://localhost/api/accounts/${id}`), { params: Promise.resolve({ accountId: id }) });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("Cache-Control"), "no-store");
    const { data } = AccountDetailResponseSchema.parse(await response.json());
    const canonical = await fixtureAccountDetailsRepository.get(id);
    assert.deepEqual(data, JSON.parse(JSON.stringify(canonical)));
    assert.ok(data.contacts.length > 0);
  }

  const missing = await GET(new Request("http://localhost/api/accounts/missing"), { params: Promise.resolve({ accountId: "missing" }) });
  assert.equal(missing.status, 404);
});

// On the live path the read is authenticated and `server-only`, so it cannot
// complete outside a request; what this pins is the route's own contract — ANY
// read failure becomes one retryable message, carrying no upstream detail, and
// still uncached.
test("account preview API failures are retryable and do not expose upstream errors", async (t) => {
  useFixtureMode(t, false);
  t.mock.method(globalThis, "fetch", async () => {
    throw new Error("private upstream connection details");
  });
  const response = await GET(new Request("http://localhost/api/accounts/zafran-security"), { params: Promise.resolve({ accountId: "zafran-security" }) });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), { error: "Unable to load account details. Please try again." });
});
