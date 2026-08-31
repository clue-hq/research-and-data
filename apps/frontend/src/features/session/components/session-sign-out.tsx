"use client";

import { useClerk } from "@clerk/nextjs";
import { useTransition } from "react";

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
