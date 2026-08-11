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

function errorResult(error: {
  message: string;
  longMessage?: string | undefined;
}): OnboardingAuthResult {
  return { status: "error", message: error.longMessage ?? error.message };
}

function ClerkOnboardingAuth({ children }: { children: React.ReactNode }) {
  // Clerk v7 custom-flow ("future") resources: every driver returns { error }, state lives on
  // the mutable resource, and finalize() activates the created session.
  const { signIn } = useSignIn();
  const { signUp } = useSignUp();
  const { signOut } = useClerk();
  const { user } = useUser();
  const email = user?.primaryEmailAddress?.emailAddress ?? null;

  const adapter = useMemo<OnboardingAuthAdapter>(
    () => ({
      mode: "clerk",
      email,
      async signInWithPassword(identifier, password) {
        const { error } = await signIn.password({ identifier, password });
        if (error) return errorResult(error);
        if (signIn.status === "complete") {
          const finalized = await signIn.finalize();
          if (finalized.error) return errorResult(finalized.error);
          return { status: "complete" };
        }
        return {
          status: "error",
          message: "This sign-in needs another verification step. Please contact support.",
        };
      },
      async signUpWithPassword(emailAddress, password) {
        const { error } = await signUp.password({ emailAddress, password });
        if (error) return errorResult(error);
        if (signUp.status === "complete") {
          // A Clerk instance with email verification off completes immediately.
          const finalized = await signUp.finalize();
          if (finalized.error) return errorResult(finalized.error);
          return { status: "complete" };
        }
        const sent = await signUp.verifications.sendEmailCode();
        if (sent.error) return errorResult(sent.error);
        return { status: "needs-verification" };
      },
      async verifyEmailCode(code) {
        const { error } = await signUp.verifications.verifyEmailCode({ code });
        if (error) return errorResult(error);
        if (signUp.status === "complete") {
          const finalized = await signUp.finalize();
          if (finalized.error) return errorResult(finalized.error);
          return { status: "complete" };
        }
        return {
          status: "error",
          message: "Verification did not complete. Please try again.",
        };
      },
      async resendEmailCode() {
        const sent = await signUp.verifications.sendEmailCode();
        if (sent.error) return errorResult(sent.error);
        return { status: "needs-verification" };
      },
      async signInWithGoogle() {
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
      },
      async signOut() {
        await signOut({ redirectUrl: "/onboarding/sign-in" });
      },
    }),
    [email, signIn, signUp, signOut],
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
