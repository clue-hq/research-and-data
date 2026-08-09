"use client";

import { useClerk } from "@clerk/nextjs";
import { useTransition } from "react";

export function SessionSignOut({
  className,
  onClearWorkspace,
}: Readonly<{
  className?: string;
  onClearWorkspace: () => Promise<void>;
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
            await signOut({ redirectUrl: "/sign-in" });
          }
        });
      }}
      type="button"
    >
      {pending ? "Signing out…" : "Sign out"}
    </button>
  );
}
