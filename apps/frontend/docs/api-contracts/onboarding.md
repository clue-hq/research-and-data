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

## Workspace setup (slice 2 — NOT yet implemented)

The proposed `POST …/setup` + progress read survive in spirit but bind to the real Stage-0
recon surface (FI-4 D-4/D-5, ratified: granular per-field events, no fake progress; checklist
groups per D-6 incl. the competitors/buyers group; brand-kit item dummy until the design
branch merges — see `brand-kit.md`). Until slice 2 lands, the setting-up/finalizing screens
remain presentation-only theatre reachable in fixture mode; the authenticated flow exits to
the app straight from the profile step and does not traverse them.

## Integration notes

- Passwords touch Clerk only; they never reach a Clue backend or fixture.
- Authentication errors map to field-level messages inside the approved card geometry via the
  additive `.authError` style; the card layout is unchanged.
- The onboarding draft (including the profile fields) survives step navigation via a
  memory-only provider; nothing is written to storage.
- The fixture provisioning twin (`provisionWorkspaceFixture`) keeps the fixture and HTTP
  paths swap-equivalent for tests and design review.
