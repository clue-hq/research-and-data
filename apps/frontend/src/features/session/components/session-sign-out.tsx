"use client";

import { useClerk } from "@clerk/nextjs";
import { useTransition } from "react";
import { endSession } from "../model/end-session";

export function SessionSignOut({
  className,
  label = "Sign out",
  onClearWorkspace,
  pendingLabel = "Signing out…",
  redirectUrl = "/onboarding/sign-in",
}: Readonly<{
  className?: string;
  label?: string;
  onClearWorkspace: () => Promise<void>;
  pendingLabel?: string;
  redirectUrl?: string;
}>) {
  const clerk = useClerk();
  const [pending, startTransition] = useTransition();

  return (
    <button
      className={className}
      disabled={pending}
      onClick={() => {
        startTransition(() =>
          endSession({
            clearWorkspace: onClearWorkspace,
            signOut: (params) => clerk.signOut(params),
            hasProviderSession: Boolean(clerk.session),
            navigate: (url) => window.location.assign(url),
            redirectUrl,
          }),
        );
      }}
      type="button"
    >
      {pending ? pendingLabel : label}
    </button>
  );
}
