# 2026-10-05 — Auth: surprise logouts + "already signed in" (issue #99)

Shipped on branch `fix/auth-surprise-logouts-99` (off `research-streaming`, commit `1aa4a19e4`).
Built and walked first on `claude/exciting-knuth-35e342` (off the trenton lane's `website-quality/week1`,
commit `e528ff30c`); re-applied here so the PR carries only this fix. One adaptation on this base:
research-streaming's Google sign-in returns a bare `{status:"complete"}` when the OAuth redirect starts,
so the controller establishes the session only on `flow === "sign-in"` (what `session_exists` yields),
and the Google `session_exists` test exercises `runClerkStep` (no `startGoogleSignIn` helper here).

## What changed
- `onboarding-auth-driver.ts`: Clerk `session_exists` (top-level code `api_response_error`, the
  `session_exists` code sits on `errors[]`; both checked) → `{status:"complete", flow:"sign-in"}`.
  Controller: sign-up and Google now `establishSession()` on that result.
- `/sign-in?reason=session_expired` renders `SessionExpiredCard` (client): if Clerk says signed in,
  one `getToken({ skipCache: true })`; success → `location.replace("/")`. Shows the expired card
  if that fails, after 5 s without an answer, or if it already bounced back within 30 s
  (sessionStorage `clue:session-recovered-at`; loop guard).
- `SessionSignOut`: navigates to its redirect URL after 3 s no matter what (no hang on
  "Preparing sign-in…"); the expired card sends to `/onboarding/sign-in`.
- `clerk.py` `clock_skew_seconds` default 5 → 60 (only prod caller `auth_wiring.py` uses the default).

## Decisions (founder, 2026-10-05)
- **No server-side retry.** Clerk's server `getToken()` returns the request's own cookie token
  (`createGetToken` in `@clerk/backend`; `skipCache` is browser-only), and Backend-API-minted
  tokens lack `azp`, which our API requires. The one retry lives in the browser on the
  session-expired page — every logout path (8 sites) lands there.
- Recovery returns to `/` (no original-page tracking).
- Dropped the planned server-side `auth()` check on the sign-in page: it would loop forever on a
  persistent backend 401 (e.g. azp misconfig) with no guard.

## Verification
- Frontend gate green (design-system:build, lint — 2 pre-existing warnings in canvasOperations.ts —
  build); `npm test` 3277 pass / 0 fail; new driver tests red-checked (3 fail without the fix).
- `tests/auth/test_clerk_authenticator.py` 14 pass (new: 30 s-expired accepted, 2 min rejected).

## Owed
- ~~Clerk dashboard: inactivity timeout + max lifetime ≥ 3 h~~ — checked 2026-10-05, NOT needed: both
  the Production and Development instances of app "Clue" already have the inactivity timeout OFF
  (no idle logout) and maximum lifetime 7 days. Left unchanged — enabling the timeout at 3 h would
  add an idle logout. Both settings are Pro-gated (workspace is on Hobby).
- ~~In-app-browser acceptance walk~~ — DONE 2026-10-05 (this branch's frontend on :3033 via
  `.claude/launch.json` "frontend-3033" + trenton `.env.local` with `CLUE_APP_ORIGIN` → 3033, against
  trenton's API 8029/8019; Clerk dev instance, founder's existing session):
  - `/sign-in?reason=session_expired` with a live session → back on `/` in ~4 s. PASS.
  - Second visit within 30 s → "Reconnecting…" then the expired card, no loop. PASS.
  - Clerk FAPI held (window.fetch patch) ~2.5 min across token expiry, then navigating: no logout —
    Clerk's Next middleware renews `__session` server-side, so the stale-cookie failure did not
    reproduce on this setup. Soft-navigating to the expired page with FAPI held: "Reconnecting…",
    card at ~5 s; releasing FAPI → page returned to `/` on its own within 6 s. PASS.
  - Already signed in → "Continue with Google" on `/onboarding/sign-in` → `/session/establish` 307 →
    `/`, no error, no OAuth round trip. PASS.
  - NOT walked: email+password while signed in (no password typing; covered by unit test), the
    2-hour idle tab, clicking "Sign in again" (would sign the founder out; 3 s fallback is code-only).
