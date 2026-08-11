# Onboarding API contract

Status: **slice 1 implemented** (2026-08-12) — authentication and workspace provisioning are
live against the backend; workspace setup (recon) remains fixture-backed until FI-4 slice 2.
This document records the **ratified** contract (FI-4, `docs/specs/FI-onboarding-contract-gap-review.md`
§8/§9); the original frontend-authored proposal it replaces is preserved in git history.

Figma source: production Clue file, `onboarding-flow` page (`1634:16661`), the seven frames
marked Ready for dev — **visually frozen** (§9 ruling 2026-08-12). One screen was added beyond
the approved set by founder ruling: `verify-email`, designed in-house within the frozen visual
vocabulary.

## Authentication (D-1, ratified)

**There are no backend authentication endpoints.** The previously proposed
`POST /api/v1/auth/{google,sign-in,sign-up}` are rejected — they contradicted the Lane-B
contract (`session.md`). Clerk owns credential verification and the session cookie,
**headlessly**: the frozen screens render every pixel and drive Clerk's custom-flow API
(`password()`, `sso()`, `verifications.sendEmailCode()/verifyEmailCode()`, `finalize()`)
through the `OnboardingAuthAdapter` seam (`src/features/onboarding/data/onboarding-auth.tsx`).
No Clerk component renders anywhere in onboarding. Operational preconditions (founder-ratified):
Clerk bot protection **disabled instance-wide** (no CAPTCHA element mounts); email
verification **on**, served by the `verify-email` step.

Flow: `sign-in`/`sign-up` (provider choice) → email screens → (`verify-email` on sign-up) →
sign-in completes to `/session/establish`; sign-up completes to `profile`. Google OAuth lands
on `/onboarding/sso-callback` (handles first-time-user transfer) and completes to
`/session/establish`. A session without a Clue identity or membership is routed by the session
DAL to `/onboarding/profile` (never `/access-denied`); the codes are
`IDENTITY_NOT_PROVISIONED` and `WORKSPACE_MEMBERSHIP_REQUIRED`.

With `CLUE_AUTH_ENABLED` unset/false, the whole flow runs in **fixture mode**: identical
screens, navigation theatre, no network. `?hold=1` still freezes the setup timer for visual QA.

## Read flow configuration (D-7, ratified)

`GET /api/v1/onboarding` is **retired**. Screen copy, role options, and the setup checklist
art are frontend-owned fixture data (`onboarding.fixture.ts`), validated by
`OnboardingFlowSchema`. Serving button copy over HTTP earned nothing, and the old adapter's
direct-origin fetch crashed auth-configured environments (defect F1).

## Provisioning (D-2/D-3, ratified — replaces `PUT /api/v1/onboarding/profile`)

`POST /api/onboarding/provision` (same-origin Next handler) → backend
`POST /auth/v1/provision`. The dedicated handler exists because the generic `/api/clue` BFF
requires a resolved membership before proxying, and provisioning is the call that creates the
first membership. Requires a live Clerk session; no membership.

Request (snake_case, matching the backend model):

```json
{
  "first_name": "Aakash",
  "last_name": "Shrivastava",
  "job_role": "Founder",
  "company_name": "Company",
  "company_website": "www.company.com"
}
```

`job_role` is a self-described title, never the authorization `role_key`. `company_website`
is normalized server-side (scheme-less input gains `https://`; non-http(s) refused).

One replay-safe backend transaction: links the Clerk identity to a Clue `platform_user`,
creates the workspace (name = company_name), creates its **first brand** (name =
company_name), makes the user the workspace **owner**, persists the profile
(`platform_user.first_name/last_name/job_role`, DSAR-erased with the rest of the profile).
**Idempotent per user**: a browser retry — or a second linked identity — returns the same
workspace (`created: false`), never a second one. A user who already belongs to a workspace
gets `409 PROVISIONING_CONFLICT` (self-serve provisioning is first-time setup only).

Response:

```json
{
  "user_id": "usr_…", "workspace_id": "ws_…", "brand_id": "brd_…",
  "membership_id": "wsm_…", "role_key": "owner",
  "company_name": "Company", "company_website": "https://www.company.com",
  "first_name": "Aakash", "last_name": "Shrivastava", "job_role": "Founder",
  "created": true
}
```

Errors use the standard envelope `{"error": {"code", "message", "requestId"}}`; relevant
codes: `AUTHENTICATION_REQUIRED` (401), `PROVISIONING_CONFLICT` (409), 422 for validation.
On success the frontend exits to `/session/establish`, which lands the user in the app.

## Workspace setup (slice 2 — implemented 2026-08-12)

`POST /stage0/setup` (BFF: `/api/clue/stage0/setup`, 202) captures the provisioned company
website as a durable artifact, records the `onboarding_input` (kind `website`, actor `human`),
and drives the governed `start_recon` — fast lane (≤ tier 2, 5¢ envelope) then background lane
(≤ tier 3, 100¢) via the D-4c kicker, all ids deterministic so retries are replays.
`GET /stage0/setup/current` serves lane-level truth resolved through the provisioning record:
`{status, recon_run_id, fast_status, background_status, company_website}` where
`status: "complete"` means the FAST lane finished — the release-into-the-app signal. The
setting-up screen polls it at 1.5s; every tick maps 1:1 to a durable lane row; the 3.2s timer
survives only in fixture mode. Items shown in clerk mode: the fast company-research lane, the
background deep-research lane, and the brand-kit item as the ratified explicit dummy.

**Honest limitation, recorded:** recon currently runs with an EMPTY claim extractor — no
production ClaimExtractor exists in the repo. The fast lane resolves the client, scrapes the
official site under target-lock, captures durable snapshot evidence, and accounts cost, but
drafts **no `client.*` facts from scraped text**; `GET /stage0/recon/{id}/brief` returns
`facts: {}`. The interview (project kickoff) remains the tier-1 `client.*` source; the
LLM extractor is a named, separately-scoped work item (rides naturally with slice 3's
granular-events work). `CLUE_SCRAPE_BACKEND=scrapling` (cost 0) is the honest backend until
that lands. Slice 3 (D-5/D-6): per-field events + the four ratified checklist groups +
Exa-search-backed competitors/buyers fields; brand-kit flips real per `brand-kit.md`.

## Freeze-record notes (round-2 review)

- In-flight submits render the design system's standard disabled state (50% opacity) on the
  approved buttons — a transient interaction state, named here so the visual freeze record is
  complete; no resting appearance changed. Errors render via the additive `.authError` line at
  the card foot in every mode (including the Google-only screens).
- The fixture walkthrough now includes the ratified `verify-email` addition
  (`sign-up-email → verify-email → profile`); everything else in the design-review theatre is
  unchanged, and the profile step remains click-through-able unvalidated in fixture mode.
- With authentication enabled, `/onboarding/setting-up` and `/onboarding/finalizing` redirect
  to the profile step (no fake progress is reachable by a real user); they remain fixture-mode
  QA surfaces until slice 2 replaces them with real recon progress.
- A replayed provision whose submitted company name differs from the recorded workspace name
  returns `company_name_ignored: true` (names are fixed at creation); the response schema is
  deliberately non-strict so additive backend fields can never fail a successful provision.
- `GET /auth/v1/session` carries `has_inactive_memberships`: the session DAL routes lost-access
  users (revoked/suspended) to `/access-denied` and only membership-history-free users to
  `/onboarding/profile`.
- `POST /auth/v1/provision` mounts only when `CLUE_SELF_SERVE_PROVISIONING_ENABLED=true`
  (default off, like every neighbouring write surface).

## Integration notes

- Passwords touch Clerk only; they never reach a Clue backend or fixture.
- Authentication errors map to field-level messages inside the approved card geometry via the
  additive `.authError` style; the card layout is unchanged.
- The onboarding draft (including the profile fields) survives step navigation via a
  memory-only provider; nothing is written to storage.
- The fixture provisioning twin (`provisionWorkspaceFixture`) keeps the fixture and HTTP
  paths swap-equivalent for tests and design review.
