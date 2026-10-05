"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { refreshLiveSession } from "../model/live-session";
import { SessionSignOut } from "./session-sign-out";

// If Clerk has not answered by then (a slow network), show the card; a late recovery still
// returns the user to the app.
const CHECK_TIMEOUT_MS = 5_000;
// One automatic return per window: if the app sends the user straight back here (the backend
// rejects even a fresh token), show the card instead of bouncing in a loop.
const RECOVERY_KEY = "clue:session-recovered-at";
const RECOVERY_WINDOW_MS = 30_000;

function recoveredRecently(): boolean {
  try {
    const at = Number(window.sessionStorage.getItem(RECOVERY_KEY));
    return Date.now() - at < RECOVERY_WINDOW_MS;
  } catch {
    return false;
  }
}

function returnToApp() {
  try {
    window.sessionStorage.setItem(RECOVERY_KEY, String(Date.now()));
  } catch {
    // Storage is optional; the return itself is what matters.
  }
  window.location.replace("/");
}

export function SessionExpiredCard({
  onClearWorkspace,
}: Readonly<{ onClearWorkspace: () => Promise<void> }>) {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const timeout = window.setTimeout(() => setChecking(false), CHECK_TIMEOUT_MS);
    return () => window.clearTimeout(timeout);
  }, []);

  useEffect(() => {
    if (!isLoaded) return;
    let cancelled = false;
    const attempt = recoveredRecently()
      ? Promise.resolve(false)
      : refreshLiveSession({ isSignedIn, getToken });
    void attempt.then((recovered) => {
      if (cancelled) return;
      if (recovered) returnToApp();
      else setChecking(false);
    });
    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, getToken]);

  if (checking) {
    return <p className="text-[var(--clue-content-subtle)]">Reconnecting…</p>;
  }
  return (
    <section className="w-full max-w-md rounded-xl border border-[var(--clue-border-neutral)] bg-[var(--clue-background-page)] p-6 shadow-[var(--clue-shadow-low)]">
      <h1 className="text-xl font-medium">Your session has expired</h1>
      <p className="mt-2 text-[var(--clue-content-subtle)]">
        Sign in again to securely reconnect your Clue workspace.
      </p>
      <SessionSignOut
        className="mt-5 h-8 rounded-lg bg-[var(--primary)] px-3 text-sm font-medium text-white disabled:opacity-60"
        label="Sign in again"
        onClearWorkspace={onClearWorkspace}
        pendingLabel="Preparing sign-in…"
        redirectUrl="/onboarding/sign-in"
      />
    </section>
  );
}
