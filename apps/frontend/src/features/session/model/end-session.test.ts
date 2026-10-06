import assert from "node:assert/strict";
import test from "node:test";
import { endSession } from "./end-session";

function harness({
  hasProviderSession = true,
  clearWorkspace = async () => {},
  signOut = async () => {},
}: {
  hasProviderSession?: boolean;
  clearWorkspace?: () => Promise<void>;
  signOut?: () => Promise<void>;
} = {}) {
  const calls: string[] = [];
  return {
    calls,
    options: {
      clearWorkspace: async () => {
        calls.push("clear-workspace");
        await clearWorkspace();
      },
      signOut: async (params: { redirectUrl: string }) => {
        calls.push(`sign-out ${params.redirectUrl}`);
        await signOut();
      },
      hasProviderSession,
      navigate: (url: string) => calls.push(`navigate ${url}`),
      redirectUrl: "/onboarding/sign-in",
      fallbackMs: 20,
    },
  };
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test("a live provider session is cleared, signed out, then the sign-in page loads", async () => {
  const run = harness();
  await endSession(run.options);
  await wait(30);
  assert.deepEqual(run.calls, [
    "clear-workspace",
    "sign-out /onboarding/sign-in",
    "navigate /onboarding/sign-in",
  ]);
});

test("with no provider session there is nothing to sign out: go straight to sign-in", async () => {
  // Clerk's signOut with no session navigates in-app and can never settle (2026-10-05 repro).
  const run = harness({
    hasProviderSession: false,
    signOut: () => new Promise<void>(() => {}),
  });
  await endSession(run.options);
  await wait(30);
  assert.deepEqual(run.calls, ["clear-workspace", "navigate /onboarding/sign-in"]);
});

test("a failed workspace clear still signs out and navigates", async () => {
  const run = harness({
    clearWorkspace: async () => {
      throw new Error("server restarted");
    },
  });
  await endSession(run.options);
  assert.deepEqual(run.calls, [
    "clear-workspace",
    "sign-out /onboarding/sign-in",
    "navigate /onboarding/sign-in",
  ]);
});

test("a sign-out that never settles still reaches the sign-in page", async () => {
  const run = harness({ signOut: () => new Promise<void>(() => {}) });
  void endSession(run.options);
  await wait(30);
  assert.deepEqual(run.calls, [
    "clear-workspace",
    "sign-out /onboarding/sign-in",
    "navigate /onboarding/sign-in",
  ]);
});

test("a workspace clear that never settles still reaches the sign-in page", async () => {
  const run = harness({ clearWorkspace: () => new Promise<void>(() => {}) });
  void endSession(run.options);
  await wait(30);
  assert.deepEqual(run.calls, ["clear-workspace", "navigate /onboarding/sign-in"]);
});
