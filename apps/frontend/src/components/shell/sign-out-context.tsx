"use client";

import { useClerk } from "@clerk/nextjs";
import { createContext, useContext, useTransition } from "react";
import { endSession } from "@/features/session/model/end-session";

const SIGN_IN_URL = "/onboarding/sign-in";

// The protected layout hands the shell the server action that clears the workspace selection
// (components may not import data/**). Only a signed-in session provides it, so a consumer that
// finds it can rely on Clerk being mounted.
const ClearWorkspaceContext = createContext<(() => Promise<void>) | null>(null);

export function SignOutProvider({
  clearWorkspace,
  children,
}: {
  clearWorkspace: () => Promise<void>;
  children: React.ReactNode;
}) {
  return <ClearWorkspaceContext.Provider value={clearWorkspace}>{children}</ClearWorkspaceContext.Provider>;
}

/** Whether the shell can sign the person out (a signed-in session). */
export function useCanSignOut(): boolean {
  return useContext(ClearWorkspaceContext) !== null;
}

/** Ends the session the same way as /sign-out; call only when `useCanSignOut()` is true. */
export function useSignOut(): { signOut: () => void; pending: boolean } {
  const clearWorkspace = useContext(ClearWorkspaceContext);
  const clerk = useClerk();
  const [pending, startTransition] = useTransition();
  return {
    pending,
    signOut: () => {
      if (!clearWorkspace) return;
      startTransition(() =>
        endSession({
          clearWorkspace,
          signOut: (params) => clerk.signOut(params),
          hasProviderSession: Boolean(clerk.session),
          navigate: (url) => window.location.assign(url),
          redirectUrl: SIGN_IN_URL,
        }),
      );
    },
  };
}
