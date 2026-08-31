# 2026-08-12 — Slice-1 round-2 fix wave SHIPPED

## Rulings (founder delegated "your three rulings folded in"; recorded in FI-4 contract notes)
1. Lost-access vs first-timer: `/auth/v1/session` + frontend schema gain
   `has_inactive_memberships`; DAL routes revoked/suspended → /access-denied (old behavior),
   membership-history-free → /onboarding/profile. Closes the revoked-user re-provision hole
   (backend independently refuses active-membership holders).
2. Workspace/brand names fixed at creation; replay divergence surfaced via
   `company_name_ignored` on ProvisionResponse (+ non-strict frontend schema, default false).
3. `POST /auth/v1/provision` behind default-off `CLUE_SELF_SERVE_PROVISIONING_ENABLED`
   (projections_app passes conn_factory only when set; local .env sets true — untracked).

## Fixed (backend, commit 420b4ec0)
PATCH-on-None unification in update_platform_user_profile (asyncpg needed explicit CASTs);
display_name recomposes when it equals the previous auto-composition, never touches user-set;
two-identity race: savepoint rollback → replay result instead of 409; website validator refuses
userinfo/dotless hosts + canonicalizes scheme/host; docstrings corrected (invited/suspended/
revoked don't block; erase rationale: workspace/brand names survive as org-scoped by design;
commit-on-exit ConnFactory requirement noted at the route). Tests: 404-without-flag, inactive
signal, company_name_ignored. Auth suite 49/49; make lint + mypy green.

## Fixed (frontend, this commit)
FE1 error line hoisted to card foot (renders in Google-only mode); FE2 Google live on all four
auth screens; FE3 signIn success = password() errorless + finalize() errorless (NEVER read
signIn.status pre-flight — hardcoded pre-load); FE4 15s timeout race around every clerk call
(blocked clerk-js → error line, not eternal hang); FE5 profile validation clerk-mode only
(fixture walkthrough restored); FE6 fixture email never shown in clerk mode (header "" while
loading; verify screen uses draft → signUp.emailAddress → "your email"); FE8 sso-callback pins
every incomplete-flow exit to in-house screens (continueSignUpUrl/firstFactorUrl/signInUrl/
signUpUrl/verifyEmailAddressUrl) + renders a spinner (FE16); FE11 verify/resend guard when no
sign-up attempt; FE12 422 → friendly copy; FE13 non-strict provision schema; FE14 x-request-id
forwarded + prefix-preserving base join; FE15 logOut clears workspace cookie first; FE17
submitTarget deleted (transitions are outcome-driven in the controller; timer hop inline);
FE18 .authHeading button:disabled style; FE19 setting-up/finalizing server-redirect to profile
when auth enabled; FE20 .env.example Clerk URLs + dashboard prerequisites + input schema
actually parsed; FE22 location.assign for /session/establish; FE23 inFlight ref latch (NOT
reset during render — react-hooks/refs forbids ref writes in render; run() finally releases).
Tests added: validateProfileDraft, provision error-envelope/422/additive-field fetch-stub
tests, step-set assertion. Gate: eslint, 153/153, build (type check) green.

## Deliberately NOT done (still-open residuals)
Provisioning rate limit (FI-4 D-9/G2 — founder stance pending); erase leaves self-serve
workspace ownerless (pre-existing bulk-revoke); route-handler test for /api/onboarding/provision
(needs module mocking of Clerk auth — noted FE9 partial); a11y deep pass (aria-describedby per
field); reverse-proxy Origin caveat (shared with BFF, pre-existing); live-Clerk browser pass
still pending founder's dashboard actions (CAPTCHA off + email code on).
