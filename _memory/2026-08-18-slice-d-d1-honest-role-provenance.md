# 2026-08-18 — Slice D / D1 complete: false-HUMAN role provenance killed (committee worker)

**Branch:** `platform/comprehensive-account-contact-research-v2` (this worktree = Slice D only; B and C run in parallel worktrees). Commit `48c5c250` on top of Slice A head `df1aaf21`.
**Plan:** `docs/specs/FI-comprehensive-account-contact-research-plan.md` Task D1; contract §5.2.
**Workflow (founder instruction):** Opus implements the first round per sub-slice; Fable reviews/verifies/corrects itself and pauses after every sub-slice. SDD ledger: `.superpowers/sdd/FI-comprehensive-account-contact-research-plan/progress.md`.

## What landed (D1)
- `_provenance_params` (`profiling/committee/worker.py`) returns `tuple[ExtractionMethod, SourceTier, str, str] | None`: grounded (URL + non-blank title) → unchanged LLM_SYNTHESIS/tier-4/url/`title:` span; otherwise `None`. The `ExtractionMethod.HUMAN`/tier-1 fallback is deleted — HUMAN is unreachable from the module.
- `_write_role_and_persona` returns `None` before writing anything when ungrounded — role+persona written together or not at all.
- `discover_committee`: ungrounded member still counted `admitted`/`new_admits`, keeps discovery + professional-fact claims, but is skipped from `CommitteeResult.members` (see intermediate state below). 4 new DB tests in `tests/profiling/committee/test_worker.py` (red-first); committee suite 59 passed; +sumble s2c = 63 passed on Fable's independent re-run; make lint/typecheck/contracts clean (implementer run).

## Controller ruling that AMENDED the plan (important)
Plan D1 said "URL optional; span is the promotion requirement". False against frozen core: `Claim` validator (`libs/clue-core/clue_core/claim.py:54-56,202-208`) requires `source_url` for non-DERIVED `LLM_SYNTHESIS`. Ruled: role/persona claims only when BOTH grounding URL and title exist; missing either → honestly roleless (contract §5.2 + ratified decision #3 only demand no-false-human-provenance + honest empties). Frozen core untouched. Consequence for D3: the agent tool's LLM_SYNTHESIS role claims must carry a real `source_url` (inherit the cited evidence claim's url; fallback member grounding url).

## Known intermediate state (fixed by D2)
`CommitteeMemberRef` requires `role_claim_id`/`persona_claim_id`, so an ungrounded member cannot appear in `CommitteeResult.members` yet → absent from `claim_refs`, the references index, and the Sumble tool's discovered-subjects projection (claims durable at rest). D2 (owns `results.py`) makes role fields + claim ids optional-absent and re-admits these members. Also deferred to D2: skip the wasted `infer_role`/`gate_role` spend when provenance is None; honest `needs_review` in both modes.

## Environment facts (persist across sub-slices)
- Workspace `.env` `CLUE_DATABASE_URL` points at a DB stamped at alembic revision `99923d6527c3` — NOT on this branch (parallel worktree's head). DB-gated tests/boot against it fail with "Can't locate revision". Use the per-branch throwaway DB: `export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_task_d1"` (created + migrated). Browser/live testing of this branch needs the stack pointed at a branch-compatible DB.
- `tests/api`+`tests/durable`: 17 pre-existing failures, byte-identical with/without D1 (A/B-verified by implementer).
- D1 has no browser-visible surface; first meaningful browser checkpoint after D2 (production committee shows roleless members — intermediate) and D3 (agent-derived roles).

## Live behavior change to expect (intended)
Sumble People always carry `source_url`, so only title-less Sumble candidates change: previously HUMAN/tier-1 role claims, now honestly roleless.

---

# ADDENDUM 2026-08-18 — D2 complete: discovery/identity separated from role judgment

**Commit `b9d661c7`** (on top of D1 `48c5c250` + memory `d34bde6d`).

## What landed (D2)
- `discover_committee(..., role_inference: RoleInferenceMode = "worker_llm")` — `agent_deferred` mode: admission/identity/discovery+professional claims byte-identical to worker_llm, ZERO role work (no role pre-spend gate, no infer_role/gate_role, zero gateway calls), all members returned roleless. `worker_llm` unchanged for grounded candidates + D1 carry-forward folded in: ungrounded candidates skip the gate+LLM entirely (no wasted spend) and now RE-ENTER `members` roleless (D1's temporary members-skip removed).
- `CommitteeMemberRef`: six role fields optional + all-or-none validator + `has_role`; `claim_refs` always carries discovery+professional ids (closes D1's references-index gap); `committee()` yields role-carrying members only; `as_committee_member()` raises on roleless (frozen handoff shape needs persona).
- `CommitteeResult.needs_review` honest: count of admitted members without a role inference (was hardcoded 0).
- Production `SumbleCommitteeSemanticResearchAction` discovers via new private seam `_discover_committee_members` → `role_inference="agent_deferred"`. Member projection verified role-independent; People-facts integrity rule unchanged (tested). **Ratified intermediate state: production committees are roleless until D3's agent write-back tool lands.**

## Verification (Fable, independent)
Suites: committee+r5+s2c+r11-bridge+api/deep+deep-orchestrator = 162 passed; frontend-read contacts/account-detail + full tests/profiling = 226 passed. Implementer: red-first TDD proven, make lint/typecheck/contracts clean, 16 pre-existing tests/api failures A/B-identical. Browser smoke: API boots clean on this branch vs clue_task_d1 (pilot preflight green), /frontend/v1/accounts 403 auth-gated (route live). Full committee browser check deferred to D3 (roles visible there) + paid D5 exit gate.

## Rulings (D2)
1. `_discover_committee_members` seam accepted (execute undrivable in tests; matches file's tested-private style).
2. role_model fail-loud guard scoped to worker_llm (deferred mode never calls the gateway).

## D3 must-knows (carried)
Tool writes role+persona CLAIMS together via the worker's writer path; LLM_SYNTHESIS claims need a real source_url (frozen core) — cited evidence claim's url, fallback member grounding url; `RoleInferenceMode` exported; needs_review/coverage recompute must reflect post-inference counts; catalog version = next free at implementation time (check live catalog).
