# 2026-08-12 — Slice-1 full adversarial review (round 2): verdicts + findings ledger

Two Opus reviewers over commits 6877ad25/ea721812 (backend) and 5dee806e/8ebca7b2 (frontend).
**Backend regression verdict: SHIP — no existing service/contract disrupted** (live-probed).
**Frontend verdict: FIX-FIRST.** Fix wave NOT yet applied — awaiting founder go.

## Regression question (the founder's central ask) — CLEAN, with evidence
Consumer sweep of every changed surface clean (PlatformUser only constructed via
_USER_COLUMNS/_model; IdentityBundle/IdentityErasureResult have zero external consumers;
PrincipalService has no Protocol; both install_auth_wiring call sites updated;
SessionResponse/PrincipalResponse byte-identical to the frontend's .strict() schemas).
Suites: tests/auth 47/47; tests/db 12/12 on a clean DB; api subsets green (the 6 observed
failures reproduced as PRE-EXISTING/environmental: shared-dev-DB agent_turn downgrade guard
c4ccc7b11810 + local .env CLUE_PROJECTIONS_AUTH_MODE/REASONING_TRACE overrides). Migration
probed live over seeded rows incl. down-with-populated-table. 409 path proven to roll back
cleanly under the real transaction factory. /provision absent without conn_factory (404).

## Fix-wave backlog (ranked; FE = frontend reviewer, BE = backend reviewer)
**User-facing flow bugs (fix before slice 2):**
- FE1 Google error unrenderable on sign-in/sign-up (error <p> only in emailMode branch) — hoist.
- FE2 Google button inert on the email screens (controller guard) — enable.
- FE3 clerk-js load-window race: signIn proxy pre-load has HARDCODED status "needs_identifier"
  (verified in ClerkProvider bundle) → successful password sign-in reports "contact support",
  never finalizes. Fix: don't branch on captured status; finalize() when password() errorless
  and treat finalize's error as the failure.
- FE4 clerk-js blocked ⇒ permanent silent hang (gateMethod awaits load forever) — timeout/race.
- FE5 fixture-mode regression: profile validation blocks design-review walkthrough — validate
  clerk-mode only.
- FE6 fixture designer's email ("hello@aakash.design") shown to real users (verify-email after
  refresh; profile header first frames) — clerk mode falls back to ""/signUp.emailAddress.
- FE8 OAuth transfer with missing_requirements escapes to Clerk-hosted UI (no
  NEXT_PUBLIC_CLERK_SIGN_UP_URL, no /sign-up route) — pin AuthenticateWithRedirectCallback
  URLs to in-house screens + .env.example.
- BE1 replayed provision with corrected company_name returns 200 echoing the OLD name with no
  divergence signal (workspace names fixed by design; response misleading) — needs founder
  ruling: rename-on-replay vs divergence flag (frontend schema .strict() → coordinated).
- FE12 backend 422 has no error envelope (RequestValidationError handler missing) → raw
  "Provisioning failed with status 422" in the card.
- FE11 cold deep-link to verify-email → raw Clerk errors; resend without attempt/cooldown.
- FE16 sso-callback renders blank white page — add spinner.
**Product-policy decisions (founder):**
- FE7 revoked ex-member (zero ACTIVE memberships, e.g. revoked) now routes to /onboarding/profile
  and can mint a fresh workspace (pre-slice: /access-denied). If they have a provisioning row:
  silent establish→profile loop. Decide: expose revoked/suspended in /auth/v1/session for DAL
  discrimination, or accept new-workspace-for-revoked-users, or terminal error state.
- BE8 /auth/v1/provision is the only unflagged write surface in the projections app — flag or
  record why not.
- BE7 DSAR: company string survives in workspace.name/brand.name while company_website erased —
  record the org-scoped-survival rationale or tombstone-when-sole-member.
**Consistency/robustness (cheap):**
- BE2 provision kwargs None-handling: profile PUT/display fill-only/website PATCH in one fn;
  None wipes profile at library level — unify None=not-supplied + fix docstring.
- BE3 docstring falsely claims invited users are refused (only ACTIVE refuses; behavior correct).
- BE4 display_name frozen at first composition (can't distinguish user-set from auto) — decide
  or defer with note.
- BE5 add 404 test for /provision absent without conn_factory.
- BE6 advisory lock keys on provider subject but idempotency on user_id → two-identity race
  gets 409 not replay; fix: on rowcount==0 abort, re-read replay instead of raising (or distinct
  retryable code — BE12 same).
- BE9 website normalization accepts mailto:/javascript: shaped junk + stores uppercase — tighten;
  slice-2 scrape guard REQUIRED regardless.
- FE13 drop .strict() (or the parse) on ProvisionedWorkspaceSchema — additive backend field
  would fail a SUCCESSFUL provision.
- FE14 provision handler: forward x-request-id; unify base-URL join with auth/backend.ts.
- FE15 onboarding Log out skips clearWorkspaceSelection — align with session-sign-out.
- FE19 setting-up/finalizing theatre publicly linkable in clerk mode — redirect to profile when
  mode=clerk (or leave to slice 2 which replaces them).
- FE9 test coverage: provision handler test (mirror bff.test.ts), fixture-adapter controller
  tests, WORKSPACE_MEMBERSHIP_REQUIRED reroute test.
**Nits recorded:** FE10 (fixture sign-up-email→verify-email change is the ratified addition —
call out in contract), FE17 submitTarget dead branches + test asserts dead path, FE18 disabled
opacity-50 is an undesigned-but-transient state (name it in freeze record) + resend button has
no disabled styling, FE20 access-denied IDENTITY_NOT_PROVISIONED message unreachable +
ProvisionWorkspaceInputSchema unused as schema + .env.example not updated, FE21 a11y
(aria-describedby/aria-invalid, resend announcement), FE22 router.push to a route handler
(use location.assign), FE23 busy guard stale-closure (useRef latch), BE10 padded values pass
\S CHECK (hand-SQL only), BE11 profile update could resurrect erased display_name (unreachable
today), non-finding note: route correctness DEPENDS on commit-on-exit ConnFactory — add comment.

## Cleared explicitly (both reviewers)
Visual freeze byte-identical on approved screens (only additive error node + disabled attr);
password/code never leave memory; provider gating can't desync (both read same env server-side);
WORKSPACE_MEMBERSHIP_REQUIRED handled at every WORKSPACE_FORBIDDEN site; no Set-Cookie/auth
header leak in the provision handler; ?hold=1 intact; Clerk v7 shapes correct incl. transfer.
