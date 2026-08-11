"use client";

import { createContext, useContext, useMemo } from "react";
import { useClerk, useSignIn, useSignUp, useUser } from "@clerk/nextjs";
import type {
  OnboardingAuthAdapter,
  OnboardingAuthResult,
} from "../model/onboarding";

const OnboardingAuthContext = createContext<OnboardingAuthAdapter | null>(null);

export function useOnboardingAuth(): OnboardingAuthAdapter {
  const adapter = useContext(OnboardingAuthContext);
  if (!adapter) {
    throw new Error("useOnboardingAuth requires an OnboardingAuthProvider ancestor");
  }
  return adapter;
}

/**
 * Selects the authentication adapter for the whole onboarding tree (FI-4 D-1).
 *
 * `authEnabled` is resolved server-side (CLUE_AUTH_ENABLED) and passed down so the fixture
 * branch never touches Clerk hooks — with authentication off there is no ClerkProvider and
 * calling the hooks would throw. The two branches are separate components so every hook usage
 * stays unconditional within its component.
 */
export function OnboardingAuthProvider({
  authEnabled,
  children,
}: {
  authEnabled: boolean;
  children: React.ReactNode;
}) {
  if (!authEnabled) {
    return <FixtureOnboardingAuth>{children}</FixtureOnboardingAuth>;
  }
  return <ClerkOnboardingAuth>{children}</ClerkOnboardingAuth>;
}

const SSO_CALLBACK_PATH = "/onboarding/sso-callback";
const SESSION_ESTABLISH_PATH = "/session/establish";
const CLERK_CALL_TIMEOUT_MS = 15_000;

const TIMEOUT_RESULT: OnboardingAuthResult = {
  status: "error",
  message: "The authentication service didn't respond. Check your connection and try again.",
};

function errorResult(error: {
  message: string;
  longMessage?: string | undefined;
}): OnboardingAuthResult {
  return { status: "error", message: error.longMessage ?? error.message };
}

/**
 * clerk-js gates every custom-flow call on its own script load and waits forever if the CDN
 * script is blocked (review finding FE4). Racing against a timeout turns the silent hang into
 * the additive error line; a late resolution is ignored (no navigation happens in here).
 */
function withTimeout(
  action: () => Promise<OnboardingAuthResult>,
): Promise<OnboardingAuthResult> {
  return Promise.race([
    action(),
    new Promise<OnboardingAuthResult>((resolve) => {
      setTimeout(() => resolve(TIMEOUT_RESULT), CLERK_CALL_TIMEOUT_MS);
    }),
  ]);
}

function ClerkOnboardingAuth({ children }: { children: React.ReactNode }) {
  // Clerk v7 custom-flow ("future") resources: every driver returns { error }, state lives on
  // the mutable resource, and finalize() activates the created session. Success is decided by
  // finalize()'s own outcome, never by reading resource status pre-flight — before clerk-js
  // loads, the sign-in proxy serves a HARDCODED status and a status branch misreports a
  // successful sign-in (review finding FE3).
  const { signIn } = useSignIn();
  const { signUp } = useSignUp();
  const { signOut } = useClerk();
  const { user } = useUser();
  const email = user?.primaryEmailAddress?.emailAddress ?? null;
  const pendingEmail = signUp.emailAddress ?? null;

  const adapter = useMemo<OnboardingAuthAdapter>(
    () => ({
      mode: "clerk",
      email,
      pendingEmail,
      signInWithPassword: (identifier, password) =>
        withTimeout(async () => {
          const { error } = await signIn.password({ identifier, password });
          if (error) return errorResult(error);
          const finalized = await signIn.finalize();
          if (finalized.error) return errorResult(finalized.error);
          return { status: "complete" };
        }),
      signUpWithPassword: (emailAddress, password) =>
        withTimeout(async () => {
          const { error } = await signUp.password({ emailAddress, password });
          if (error) return errorResult(error);
          if (signUp.status === "complete") {
            // A Clerk instance with email verification off completes immediately. (The
            // signUp proxy's status IS a live getter, unlike signIn's — safe to read.)
            const finalized = await signUp.finalize();
            if (finalized.error) return errorResult(finalized.error);
            return { status: "complete" };
          }
          const sent = await signUp.verifications.sendEmailCode();
          if (sent.error) return errorResult(sent.error);
          return { status: "needs-verification" };
        }),
      verifyEmailCode: (code) =>
        withTimeout(async () => {
          if (!signUp.status) {
            return {
              status: "error",
              message:
                "We couldn't find a sign-up in progress. Please start again from the sign-up screen.",
            };
          }
          const { error } = await signUp.verifications.verifyEmailCode({ code });
          if (error) return errorResult(error);
          const finalized = await signUp.finalize();
          if (finalized.error) return errorResult(finalized.error);
          return { status: "complete" };
        }),
      resendEmailCode: () =>
        withTimeout(async () => {
          if (!signUp.status) {
            return {
              status: "error",
              message:
                "We couldn't find a sign-up in progress. Please start again from the sign-up screen.",
            };
          }
          const sent = await signUp.verifications.sendEmailCode();
          if (sent.error) return errorResult(sent.error);
          return { status: "needs-verification" };
        }),
      signInWithGoogle: () =>
        withTimeout(async () => {
          // Lands on /onboarding/sso-callback (which also handles the first-time-user
          // sign-in → sign-up transfer), then completes at /session/establish; a brand-new
          // identity is routed onward to /onboarding/profile by the session DAL repair.
          const { error } = await signIn.sso({
            strategy: "oauth_google",
            redirectCallbackUrl: SSO_CALLBACK_PATH,
            redirectUrl: SESSION_ESTABLISH_PATH,
          });
          if (error) return errorResult(error);
          return { status: "complete" };
        }),
      async signOut() {
        await signOut({ redirectUrl: "/onboarding/sign-in" });
      },
    }),
    [email, pendingEmail, signIn, signUp, signOut],
  );

  return (
    <OnboardingAuthContext.Provider value={adapter}>{children}</OnboardingAuthContext.Provider>
  );
}

/** Preserves the pre-integration design-review navigation without any real credentials. */
function FixtureOnboardingAuth({ children }: { children: React.ReactNode }) {
  const adapter = useMemo<OnboardingAuthAdapter>(
    () => ({
      mode: "fixture",
      email: null,
      pendingEmail: null,
      async signInWithPassword() {
        return { status: "complete" };
      },
      async signUpWithPassword() {
        return { status: "needs-verification" };
      },
      async verifyEmailCode() {
        return { status: "complete" };
      },
      async resendEmailCode() {
        return { status: "needs-verification" };
      },
      async signInWithGoogle() {
        return { status: "complete" };
      },
      async signOut() {},
    }),
    [],
  );
  return (
    <OnboardingAuthContext.Provider value={adapter}>{children}</OnboardingAuthContext.Provider>
  );
}
