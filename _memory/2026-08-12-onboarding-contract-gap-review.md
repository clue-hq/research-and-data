# 2026-08-12 — Onboarding contract-gap review (FI-4) written

## What happened
Wrote `docs/specs/FI-onboarding-contract-gap-review.md` (FI-4) — the branch-charter-required
contract-gap review for the seven imported onboarding screens — from three parallel read-only
code studies (frontend onboarding+session; backend Stage-0 recon surface; backend
auth/workspace/brand provisioning). Full evidence with file:line cites is in the doc itself.

## Load-bearing findings (verified, not guesses)
- `provision_workspace_owner` has zero HTTP callers; fresh Clerk user dead-ends at
  `/access-denied` (`IDENTITY_NOT_PROVISIONED`, or synthesized `WORKSPACE_FORBIDDEN` on
  `memberships: []`). No brand/product-creation surface exists; `brand_id` NOT NULL on
  `onboarding_input`/`recon_run`/`project`/`project_run` → chain: identity → workspace →
  brand → recon. `provision_workspace_owner` is NOT idempotent (replay = second workspace).
- `platform_user` has only `display_name`; profile fields (first/last/role) need new schema +
  `erase_platform_user` DSAR wiring. `role_key` must not carry the job title.
- `start_recon` refuses `stage0_recon_not_configured` at ALL production call sites —
  `stage0_scrape_binder` never passed to `build_toolbelt` (verifies the CLAUDE.md backlog item).
  Also withheld from every agent surface. Background lane has NO driver (runs only on a second
  `start_recon` call). `submit_onboarding_input` works over `POST /tools/...` today.
- Honest recon event vocabulary: ≤4 events (`run.step.progress`, payload.kind=
  `stage0.recon.transition`, lane×status), committed atomically per lane (no in-flight signal),
  and unreachable over SSE (token mint 404s for non-project_run ids) — write-only rows.
  No per-field events anywhere in `reverse_profile`. Polling projections DO exist and serve:
  `GET /stage0/recon/{id}/progress` and `/brief` (facts = 9 client.* fields, post-fast only).
- Frontend: repository is a single `getFlow()` read; HTTP adapter bypasses BFF and activates on
  the shared `CLUE_API_BASE_URL` (crashes screens in any auth-configured env — defect F1);
  profile draft lost across step remounts; `finalizing` is a dead end; auth screens are pure
  navigation theatre (Google → profile). Chat feature already has the SSE/polling repository
  pattern to reuse (`chat-stream.repository.ts`).

## Ratified (founder, this session)
Brand-kit checklist item stays dummy/omitted (design branch owns it); no-fake-progress
re-affirmed (1:1 real event ticks). Recorded in FI-4 §9. Everything in §8 (D-1…D-9) awaits
founder sign-off — esp. D-5 (lane-level MVP vs granular per-field events; doc proposes
granular) and D-2 (provisioning endpoint shape, lazy vs explicit identity provisioning).

## Next
Founder reviews FI-4 §8; on ratification, amend `apps/frontend/docs/api-contracts/onboarding.md`
and start slice 1 (Clerk-native auth screens + provisioning + profile schema).
