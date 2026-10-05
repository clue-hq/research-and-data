"use client";

import { useClerk } from "@clerk/nextjs";
import { useTransition } from "react";

const SIGN_OUT_FALLBACK_MS = 3_000;

export function SessionSignOut({
  className,
  label = "Sign out",
  onClearWorkspace,
  pendingLabel = "Signing out…",
  redirectUrl = "/sign-in",
}: Readonly<{
  className?: string;
  label?: string;
  onClearWorkspace: () => Promise<void>;
  pendingLabel?: string;
  redirectUrl?: string;
}>) {
  const { signOut } = useClerk();
  const [pending, startTransition] = useTransition();

  return (
    <button
      className={className}
      disabled={pending}
      onClick={() => {
        // Never hang on the pending label: Clerk or the workspace-clear action can stall
        // (a slow network, a restarted server), so navigate anyway after a few seconds.
        window.setTimeout(() => window.location.assign(redirectUrl), SIGN_OUT_FALLBACK_MS);
        startTransition(async () => {
          try {
            await onClearWorkspace();
          } finally {
            await signOut({ redirectUrl });
            // Clerk only navigates when a session existed to destroy. Reaching
            // this line means there was nothing to sign out of (e.g. landing on
            // the expired-session card already signed out — shared localhost
            // dev cookies make this common), so navigate explicitly; when Clerk
            // did navigate, this assigns the same URL and is a no-op.
            window.location.assign(redirectUrl);
          }
        });
      }}
      type="button"
    >
      {pending ? pendingLabel : label}
    </button>
  );
}
