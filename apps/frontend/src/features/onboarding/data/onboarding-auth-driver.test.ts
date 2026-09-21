import assert from "node:assert/strict";
import test from "node:test";
import {
  startGoogleSignIn,
  pendingVerificationEmail,
  resendPendingEmailCode,
  startPasswordSignIn,
  startPasswordSignUp,
  verifyPendingEmailCode,
  type ClerkSignInDriver,
  type ClerkSignUpDriver,
} from "./onboarding-auth-driver";

function signInDriver(
  status: string,
  factors: string[] = ["email_code"],
): ClerkSignInDriver & {
  calls: string[];
  setStatus(status: string): void;
} {
  let currentStatus = status;
  const calls: string[] = [];
  return {
    calls,
    identifier: "person@example.com",
    supportedSecondFactors: factors.map((strategy) => ({ strategy })),
    get status() {
      return currentStatus;
    },
    setStatus(next) {
      currentStatus = next;
    },
    async password() {
      calls.push("password");
      return { error: null };
    },
    async finalize() {
      calls.push("finalize");
      return { error: null };
    },
    mfa: {
      async sendEmailCode() {
        calls.push("send-sign-in-code");
        return { error: null };
      },
      async verifyEmailCode() {
        calls.push("verify-sign-in-code");
        currentStatus = "complete";
        return { error: null };
      },
    },
  };
}

function signUpDriver(status: string | null): ClerkSignUpDriver & { calls: string[] } {
  let currentStatus = status;
  const calls: string[] = [];
  return {
    calls,
    emailAddress: "new@example.com",
    get status() {
      return currentStatus;
    },
    async password() {
      calls.push("password");
      return { error: null };
    },
    async finalize() {
      calls.push("finalize");
      return { error: null };
    },
    verifications: {
      async sendEmailCode() {
        calls.push("send-sign-up-code");
        return { error: null };
      },
      async verifyEmailCode() {
        calls.push("verify-sign-up-code");
        currentStatus = "complete";
        return { error: null };
      },
    },
  };
}

test("complete password sign-in finalizes the created session", async () => {
  const signIn = signInDriver("complete");

  assert.deepEqual(
    await startPasswordSignIn(signIn, "person@example.com", "secret"),
    { flow: "sign-in", status: "complete" },
  );
  assert.deepEqual(signIn.calls, ["password", "finalize"]);
});

test("Device Trust sends and verifies email code before finalization", async () => {
  const signIn = signInDriver("needs_client_trust");
  const signUp = signUpDriver(null);

  assert.deepEqual(
    await startPasswordSignIn(signIn, "person@example.com", "secret"),
    { status: "needs-verification", purpose: "device-trust" },
  );
  assert.deepEqual(signIn.calls, ["password", "send-sign-in-code"]);
  assert.equal(pendingVerificationEmail(signIn, signUp), "person@example.com");

  assert.deepEqual(await verifyPendingEmailCode(signIn, signUp, "424242"), {
    flow: "sign-in",
    status: "complete",
  });
  assert.deepEqual(signIn.calls, [
    "password",
    "send-sign-in-code",
    "verify-sign-in-code",
    "finalize",
  ]);
});

test("email MFA uses the same verification surface and resend driver", async () => {
  const signIn = signInDriver("needs_second_factor");
  const signUp = signUpDriver(null);

  assert.deepEqual(
    await startPasswordSignIn(signIn, "person@example.com", "secret"),
    { status: "needs-verification", purpose: "second-factor" },
  );
  assert.deepEqual(await resendPendingEmailCode(signIn, signUp), {
    status: "needs-verification",
    purpose: "second-factor",
  });
  assert.deepEqual(signIn.calls, [
    "password",
    "send-sign-in-code",
    "send-sign-in-code",
  ]);
});

test("unsupported Device Trust factor fails explicitly and never finalizes", async () => {
  const signIn = signInDriver("needs_client_trust", ["phone_code"]);

  const result = await startPasswordSignIn(signIn, "person@example.com", "secret");

  assert.equal(result.status, "error");
  assert.match(result.status === "error" ? result.message : "", /isn't available/);
  assert.deepEqual(signIn.calls, ["password"]);
});

test("a thrown Clerk exception becomes a rendered adapter error", async () => {
  const signIn = signInDriver("complete");
  signIn.password = async () => {
    throw new Error("Clerk transport failed");
  };

  assert.deepEqual(
    await startPasswordSignIn(signIn, "person@example.com", "secret"),
    { status: "error", message: "Clerk transport failed" },
  );
  assert.deepEqual(signIn.calls, []);
});

test("a timed-out password call cannot continue into late finalization", async () => {
  const signIn = signInDriver("complete");
  let resolvePassword: ((value: { error: null }) => void) | undefined;
  signIn.password = () =>
    new Promise((resolve) => {
      resolvePassword = resolve;
    });

  const result = await startPasswordSignIn(
    signIn,
    "person@example.com",
    "secret",
    1,
  );
  assert.equal(result.status, "error");
  assert.match(result.status === "error" ? result.message : "", /didn't respond/);

  resolvePassword?.({ error: null });
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.deepEqual(signIn.calls, []);
});

test("sign-up verification still dispatches through the sign-up resource", async () => {
  const signIn = signInDriver("needs_identifier");
  const signUp = signUpDriver("missing_requirements");

  assert.deepEqual(
    await startPasswordSignUp(signUp, "new@example.com", "secret"),
    { status: "needs-verification", purpose: "sign-up" },
  );
  assert.equal(pendingVerificationEmail(signIn, signUp), "new@example.com");
  assert.deepEqual(await verifyPendingEmailCode(signIn, signUp, "424242"), {
    flow: "sign-up",
    status: "complete",
  });
  assert.deepEqual(signUp.calls, [
    "password",
    "send-sign-up-code",
    "verify-sign-up-code",
    "finalize",
  ]);
});

// Provider-boundary fake reproduces Clerk's expired-attempt no-op observed in the browser.
test("Google starts a fresh redirect when an earlier OAuth attempt expired", async () => {
  const redirects: unknown[] = [];
  const signIn = {
    async sso() { return { error: null }; },
    async authenticateWithRedirect(params: unknown) { redirects.push(params); },
  };
  const result = await startGoogleSignIn(signIn);
  assert.deepEqual(redirects, [{
    strategy: "oauth_google",
    redirectUrl: "/onboarding/sso-callback",
    redirectUrlComplete: "/session/establish",
    continueSignIn: false,
  }]);
  assert.deepEqual(result, { status: "redirecting" });
});

test("Google redirect failures become visible errors", async () => {
  const result = await startGoogleSignIn({
    async authenticateWithRedirect() {
      throw new Error("OAuth provider unavailable");
    },
  });
  assert.deepEqual(result, { status: "error", message: "OAuth provider unavailable" });
});

test("Google cannot report success before the auth client loads", async () => {
  const result = await startGoogleSignIn(undefined);
  assert.equal(result.status, "error");
  assert.match(result.status === "error" ? result.message : "", /loading/i);
});

test("Google redirect timeout reports an error without activating a session", async () => {
  const result = await startGoogleSignIn({
    authenticateWithRedirect: () => new Promise<void>(() => {}),
  }, 1);
  assert.equal(result.status, "error");
  assert.match(result.status === "error" ? result.message : "", /didn't respond/);
});
