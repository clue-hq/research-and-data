# 2026-10-06 — expired sessions land on the real sign-in page; sign-out never hangs

Branch `claude/magical-darwin-d91835` (worktree `magical-darwin-d91835`, based on
`website-quality/week1`). Local commits only.

## Base
Issue #99 (`fix/auth-surprise-logouts-99`, PR #100 → research-streaming, #101 → main) had
already landed, so it was merged in first (`fa7d5f9a9`). One conflict in
`onboarding-auth-driver.test.ts`: this branch had rewritten `startGoogleSignIn` onto
`authenticateWithRedirect`, so #99's "already signed in Google start" test now drives
`startGoogleSignIn` with a throwing `authenticateWithRedirect` (it still completes as sign-in).

## What changed (`f5e926c34`)
- `/sign-in?reason=session_expired` stays the single entry point (every redirect site —
  `auth/server.ts`, `session-dal.ts`, `session/establish`, the accounts and email-lookup
  controllers, the recovery-screen link — still points at it, untouched). The card is gone:
  `session-expired-card.tsx` → `session-expired-redirect.tsx`. It keeps #99's reconnect
  (refresh a live Clerk session once, return to `/`, 30 s anti-loop window, 5 s Clerk timeout).
  Otherwise it does the FI-2 cleanup with no button and `location.replace`s
  `/onboarding/sign-in?reason=session_expired`.
- `/onboarding/[step]` reads `reason=session_expired` and the sign-in card shows one line
  under its heading: "Your session expired. Please sign in again." (existing subtle style,
  `role="status"`). It disappears when the user moves to the email step (the query is not
  carried). No other new UI.
- `model/end-session.ts` (`endSession`), shared by `SessionSignOut` and the expired route:
  clear the workspace selection → Clerk `signOut({ redirectUrl })` **only when
  `clerk.session` exists** → full load of `redirectUrl`; a 3 s fallback loads it anyway if a
  step stalls; a failed clear still signs out. Root cause of the hang: with no Clerk session,
  `signOut` starts an in-app navigation that never settles.
- `SessionSignOut` default redirect is `/onboarding/sign-in` (was the redirect-only
  `/sign-in`). Its other caller, `/sign-out`, keeps working (walked live).
- Left alone: the bare `/sign-in` link on `invite/accept` and the `location.replace("/sign-in")`
  in `live-setup-screen.tsx`. Both are full loads, so they cannot hang.

## Verified
- `end-session.test.ts` (5 cases: live session, no session + never-settling signOut, failed
  clear, never-settling signOut, never-settling clear); `npm test` 3282 pass / 0 fail.
- Gate `npm run design-system:build && npm run lint && npm run build`: green (2 pre-existing
  unused-var warnings in an unrelated file).
- Live, Claude desktop in-app browser, this worktree's Next dev only on **:3070**
  (`apps/frontend/.env.local` copied from trenton, `CLUE_APP_ORIGIN` → 3070, API → trenton 8029):
  1. `/sign-out` with a live Clerk session → `/onboarding/sign-in`, session null, the real
     HttpOnly `clue_workspace_id` cookie cleared.
  2. `/sign-out` with Clerk loaded and NO session (the 2026-10-05 hang) → landed within 1.5 s
     (before the fallback); the server log shows only `clearWorkspaceSelection`, no Clerk
     `invalidateCacheAction`, i.e. `signOut` was skipped.
  3. `/accounts` with no session → `/sign-in?reason=session_expired` →
     `/onboarding/sign-in?reason=session_expired` with the notice; the planted workspace
     cookie cleared.
  - "Preparing sign-in…" no longer exists in `src/`.
- Founder approved signing the in-app browser out (localhost Clerk cookies are shared by every
  lane), and re-signs in themselves.

## Open / observed
- One-off, not reproduced: the FIRST `/accounts` visit, a minute or two after the live-session
  sign-out, was accepted server-side (a token reached the backend; it rendered
  `/select-workspace` with the four workspaces); Clerk-js then held no session. Most likely a
  still-unexpired session JWT cookie (60 s lifetime, plus #99's 60 s backend leeway) that
  Clerk-js cleared on load. That is about why a session looks alive, not where it lands, so it
  was not chased.
- Not walked live: the anti-loop path (live Clerk session that the backend rejects → reconnect →
  bounce back → sign out → sign-in page). Signing in on :3070 against trenton's API would
  exercise it exactly (3070 is not an authorized party there), but it needs the founder's
  sign-in.
