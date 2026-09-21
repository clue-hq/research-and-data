"use client";

import { createContext, useContext, useMemo } from "react";
import { useClerk, useSignIn, useSignUp, useUser } from "@clerk/nextjs";
import type {
  OnboardingAuthAdapter,
} from "../model/onboarding";
import {
  acceptInvitationTicket,
  pendingVerificationEmail,
  resendPendingEmailCode,
  startGoogleSignIn,
  startPasswordSignIn,
  startPasswordSignUp,
  verifyPendingEmailCode,
} from "./onboarding-auth-driver";

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

function ClerkOnboardingAuth({ children }: { children: React.ReactNode }) {
  // Clerk v7 custom-flow ("future") resources expose a real state machine after every driver
  // call. `finalize()` is legal only at `complete`; Device Trust and email MFA first route through
  // the same in-house verification screen as sign-up. The pure driver module owns that branching
  // so the live SDK contract is covered without rendering Clerk UI.
  const { signIn } = useSignIn();
  const { signUp } = useSignUp();
  const clerk = useClerk();
  const { signOut } = clerk;
  const { user } = useUser();
  const email = user?.primaryEmailAddress?.emailAddress ?? null;
  const pendingEmail = pendingVerificationEmail(signIn, signUp);

  const adapter = useMemo<OnboardingAuthAdapter>(
    () => ({
      mode: "clerk",
      email,
      pendingEmail,
      signInWithPassword: (identifier, password) =>
        startPasswordSignIn(signIn, identifier, password),
      signUpWithPassword: (emailAddress, password) =>
        startPasswordSignUp(signUp, emailAddress, password),
      acceptInvitation: (params) => acceptInvitationTicket(signUp, params),
      verifyEmailCode: (code) => verifyPendingEmailCode(signIn, signUp, code),
      resendEmailCode: () => resendPendingEmailCode(signIn, signUp),
      signInWithGoogle: () => startGoogleSignIn(clerk.client?.signIn),
      async signOut() {
        await signOut({ redirectUrl: "/onboarding/sign-in" });
      },
    }),
    [email, pendingEmail, signIn, signUp, signOut, clerk],
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
        return { status: "needs-verification", purpose: "sign-up" };
      },
      async verifyEmailCode() {
        return { status: "complete" };
      },
      async resendEmailCode() {
        return { status: "needs-verification", purpose: "sign-up" };
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
