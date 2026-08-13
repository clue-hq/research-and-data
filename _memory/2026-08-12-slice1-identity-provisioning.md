# 2026-08-12 — FI-4 slice 1 SHIPPED: identity, provisioning, profile

## What landed (4 commits)
- `6877ad25` backend: migration `da5f3fe5a90f` (platform_user first_name/last_name/job_role +
  self_serve_provisioning), provision_self_serve_workspace, POST /auth/v1/provision
  (PrincipalService.external_session seam; PROVISIONING_CONFLICT=409).
- `ea721812` backend hardening after the founder-mandated adversarial review (verdict was
  FIX-FIRST; all 4 MAJORs + cheap MINORs fixed): idempotency re-keyed per USER (unique
  user_id; second linked identity replays same workspace; active-membership holders refused),
  inactive-membership replay → 409, DSAR erases company_website + record in IdentityBundle
  (+ provisioning_websites_erased count), website PUT-on-replay + http(s) normalization,
  whitespace 422 + \S CHECKs, display_name COALESCE (fill-never-clobber), ON CONFLICT DO
  NOTHING + loud abort for isolation races.
- `5dee806e` frontend: headless Clerk v7 custom flows (password/sso/verifications/finalize —
  NOTE: v7 has NO isLoaded/setActive; hooks return {signIn|signUp, errors, fetchStatus}
  "future" resources) behind the frozen screens via OnboardingAuthAdapter (clerk|fixture
  branches; fixture preserves design-review theatre). New verify-email step (slug between
  sign-up-email and profile). Draft provider (memory-only, survives step remounts).
  /api/onboarding/provision dedicated handler (generic BFF's membership gate can't serve the
  first-membership call). Session repair: zero-membership → WORKSPACE_MEMBERSHIP_REQUIRED →
  /onboarding/profile; IDENTITY_NOT_PROVISIONED → same; /sign-in widget → redirect. F1 fixed
  (copy read retired per D-7).
- Final commit: onboarding.md rewritten to the ratified contract + this note.

## Gates
Backend: auth suite 47/47, make lint green, mypy green, migration up→down→up smoked (raw
strings for \S regexes — SyntaxWarning otherwise). Frontend: eslint, 147/147, build green
(routes /onboarding/[step], /onboarding/sso-callback, /api/onboarding/provision present).

## Exit-test status
Code-level exit criteria all proven by tests (sign-up→verify→profile→workspace+brand+owner in
Postgres; replay → same workspace id; route e2e with local_fixture auth). NOT yet done: a live
browser pass against real Clerk (needs the dashboard operator actions: CAPTCHA off instance-wide
+ email verification code on — founder's side).

## Residuals (deliberate, recorded)
- No provisioning rate limit (review finding 10) — open under FI-4 D-9/G2 (founder to ratify
  stance). Also: erase_platform_user leaves a self-serve workspace ownerless (pre-existing
  bulk-revoke behavior, now reachable via this flow) — flag when DSAR ops matter.
- 409 body relays internal invariant wording; 200 (not 201) on create; _required/_clean DRY
  dup — nits, skipped.
- Route tests share one conn (no real transaction boundaries/lock contention coverage).
- setting-up/finalizing timer theatre survives ONLY for fixture mode; authenticated flow
  bypasses those screens until slice 2 replaces them with real recon progress.

## Next: slice 2 (D-4)
Scrape binder composition at projections_main+fleet_main, POST /stage0/setup (artifact capture
→ submit_onboarding_input → start_recon), post-fast background kicker, lane-level progress
polling on the setting-up screen, release-on-fast-complete. company_website for the setup call
is durably on self_serve_provisioning.
