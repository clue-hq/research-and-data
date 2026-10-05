/**
 * The app sends a user to `/sign-in?reason=session_expired` whenever one request found no
 * usable token. Often the browser's Clerk session is still alive and only the short-lived
 * session cookie went stale (an idle tab, a slow network). Refreshing the token once in the
 * browser rewrites that cookie; if it succeeds the user can go straight back into the app.
 *
 * The server cannot do this refresh: Clerk's server `getToken()` returns the request's own
 * cookie token, and only the browser holds the session that can mint a new one.
 */
export async function refreshLiveSession(session: {
  isSignedIn: boolean | undefined;
  getToken(options: { skipCache: true }): Promise<string | null>;
}): Promise<boolean> {
  if (!session.isSignedIn) return false;
  try {
    return Boolean(await session.getToken({ skipCache: true }));
  } catch {
    return false;
  }
}
