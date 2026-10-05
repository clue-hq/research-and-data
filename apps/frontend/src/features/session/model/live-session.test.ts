import assert from "node:assert/strict";
import test from "node:test";
import { refreshLiveSession } from "./live-session";

function session(isSignedIn: boolean, token: () => Promise<string | null>) {
  const calls: Array<{ skipCache: true }> = [];
  return {
    calls,
    isSignedIn,
    async getToken(options: { skipCache: true }) {
      calls.push(options);
      return token();
    },
  };
}

test("a live session refreshes its token exactly once, bypassing the cache, and recovers", async () => {
  const live = session(true, async () => "fresh-token");
  assert.equal(await refreshLiveSession(live), true);
  assert.deepEqual(live.calls, [{ skipCache: true }]);
});

test("a signed-out browser does not try to refresh and stays on the expired card", async () => {
  const signedOut = session(false, async () => "unused");
  assert.equal(await refreshLiveSession(signedOut), false);
  assert.deepEqual(signedOut.calls, []);
});

test("a refresh that returns no token or fails does not recover, and is not retried", async () => {
  const empty = session(true, async () => null);
  assert.equal(await refreshLiveSession(empty), false);
  assert.equal(empty.calls.length, 1);

  const failing = session(true, async () => {
    throw new Error("network");
  });
  assert.equal(await refreshLiveSession(failing), false);
  assert.equal(failing.calls.length, 1);
});
