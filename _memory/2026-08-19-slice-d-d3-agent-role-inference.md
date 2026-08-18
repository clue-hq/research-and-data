# 2026-08-19 — Slice D / D3 complete: governed account-agent committee role inference

**Branch:** `platform/comprehensive-account-contact-research-v2` (Slice D worktree).
**Plan:** `docs/specs/FI-comprehensive-account-contact-research-plan.md` Task D3; contract §5.2.

## What landed
- Added closed `CommitteeRoleInference` / `RecordCommitteeRoleInferencesInput` schemas and the
  account engine tool `record_committee_role_inferences`.
- The tool reconstructs exact job-local committee membership and each member's admissible claim
  ids from persisted `discover_buying_committee` result fields. Outsider contacts, cross-contact
  evidence, expired/foreign evidence, cross-run evidence, and duplicate contacts are repairable
  governed refusals. The whole batch validates before either claim of any role/persona pair writes.
- Role/persona writes reuse the committee package's public `write_committee_claim` path:
  LLM_SYNTHESIS, tier 4, PLATFORM_INFERRED, STRONG identity, professional-public use, tenant/product
  scope, and idempotency on `(contact, field, run)`. `plausible=true` is structural; no role gate or
  second classifier is called. URL/span come from one cited claim, or together from the member's
  grounded title fallback.
- Coverage folds the agent-written role/persona claim refs into its ledger. A discovered member
  without the complete pair now persists `committee_status=needs_review`,
  `committee_needs_review`, and `committee_roles_uninferred`; an omitted member is never filled.
- Added immutable account catalog v2 (profile/prompt/skill), promoted resolver and fleet launcher to
  `agent-profile:account-research:v2` + its profile digest, and froze the new tool into the core/R3
  surfaces and R0 fixture.

## Verification
- Red-first collection failure proved the schemas/tool did not exist before implementation.
- Isolated DB: `clue_task_d1` (the workspace `.env` DB is on a parallel migration lineage).
- Green: full R5 DB suite; committee + R5 + runtime R3 + R4 tool surface + authority audit; fresh
  skip; catalog/core/R0 contracts; account fleet composition/launch; first-call authority.
- Green repo gates: `make lint typecheck contracts` (ruff, mypy 727 files, 26 import contracts).
- Independent adversarial review found the false-complete coverage issue and provenance-pairing
  issue; both were corrected and the gates rerun. It also questioned multi-citation retention; the
  exact input ids remain durable in the governed agent tool-call journal while the frozen role
  value schema remains the required four-key shape.

## Limitations / observations
- The requested Fable review could not run: local Claude returned 429 session-limit, reset 3am.
  An independent read-only agent review was used instead; corrections were implemented locally.
- No browser run was claimed for D3. This slice is an engine/catalog/claim change; the complete
  browser-visible committee journey remains the Slice D5 exit gate.
- One broader pre-existing integration economics assertion failed while serving a stale neutral
  pain claim (`test_fi2_slice3_a_stale_neutral_fact_is_refreshed_once_and_serves_both_lenses`);
  the D3-focused and adjacent required suites are green, and this unrelated merge-selection
  behavior was not changed.
