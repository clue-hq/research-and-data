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
          }
        });
      }}
      type="button"
    >
      {pending ? pendingLabel : label}
    </button>
  );
}
