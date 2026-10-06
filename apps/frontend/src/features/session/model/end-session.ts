export const END_SESSION_FALLBACK_MS = 3_000;

/**
 * Leave the current session: erase the workspace selection, end the Clerk session if one is
 * alive, then load the sign-in page.
 *
 * Clerk's `signOut` only settles when it had a session to destroy; with none it starts an
 * in-app navigation that can never complete (reproduced 2026-10-05), so it is skipped then.
 * Either step can also stall on a slow network or a restarted server, so the page loads anyway
 * after `fallbackMs`: no caller can stay stuck on its pending label.
 */
export async function endSession({
  clearWorkspace,
  signOut,
  hasProviderSession,
  navigate,
  redirectUrl,
  fallbackMs = END_SESSION_FALLBACK_MS,
}: {
  clearWorkspace: () => Promise<void>;
  signOut: (params: { redirectUrl: string }) => Promise<void>;
  hasProviderSession: boolean;
  navigate: (url: string) => void;
  redirectUrl: string;
  fallbackMs?: number;
}): Promise<void> {
  const fallback = setTimeout(() => navigate(redirectUrl), fallbackMs);
  try {
    await clearWorkspace();
  } catch {
    // End the provider session even if the cookie clear failed.
  }
  try {
    if (hasProviderSession) await signOut({ redirectUrl });
  } catch {
    // The sign-in page is still the right place to land.
  }
  clearTimeout(fallback);
  // Clerk may already have navigated in-app; loading the same page fully is harmless.
  navigate(redirectUrl);
}
