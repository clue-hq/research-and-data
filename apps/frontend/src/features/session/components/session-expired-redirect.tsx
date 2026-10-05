"use client";

import { useAuth, useClerk } from "@clerk/nextjs";
import { useEffect, useRef } from "react";
import { endSession } from "../model/end-session";
import { refreshLiveSession } from "../model/live-session";

const SESSION_EXPIRED_SIGN_IN_URL = "/onboarding/sign-in?reason=session_expired";

// If Clerk has not answered by then (a slow network), stop waiting and go to sign-in.
const CHECK_TIMEOUT_MS = 5_000;
// One automatic return per window: if the app sends the user straight back here (the backend
// rejects even a fresh token), go to sign-in instead of bouncing in a loop.
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

/**
 * The single landing point for an expired session. It first tries to reconnect a still-live
 * browser session and return to the app. Otherwise it does the FI-2 cleanup with no button —
 * erase the workspace selection, sign out any stale Clerk session so the sign-in page cannot
 * answer "You're already signed in" — and loads the normal sign-in page.
 */
export function SessionExpiredRedirect({
  onClearWorkspace,
}: Readonly<{ onClearWorkspace: () => Promise<void> }>) {
  const clerk = useClerk();
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const decided = useRef(false);

  useEffect(() => {
    function decide(recovered: boolean) {
      if (decided.current) return;
      decided.current = true;
      if (recovered) {
        returnToApp();
        return;
      }
      void endSession({
        clearWorkspace: onClearWorkspace,
        signOut: (params) => clerk.signOut(params),
        hasProviderSession: Boolean(clerk.session),
        navigate: (url) => window.location.replace(url),
        redirectUrl: SESSION_EXPIRED_SIGN_IN_URL,
      });
    }
    const timeout = window.setTimeout(() => decide(false), CHECK_TIMEOUT_MS);
    if (isLoaded) {
      const attempt = recoveredRecently()
        ? Promise.resolve(false)
        : refreshLiveSession({ isSignedIn, getToken });
      void attempt.then(decide);
    }
    return () => window.clearTimeout(timeout);
  }, [clerk, isLoaded, isSignedIn, getToken, onClearWorkspace]);

  return <p className="text-[var(--clue-content-subtle)]">Reconnecting…</p>;
}
