# 2026-08-03 — Tenant-local dynamic Client-KB fields

## Scope

- Implemented Part I of `Phase C Stage 0 — Tenant-Local Dynamic Client-KB Fields and Judged-Claim Verdict Attribution.md` on `platform/c8-context-card`.
- Part II (judged-claim verdict attribution) was deliberately not changed; pause requested after Part I.

## Delivered

- Added a separate immutable `workspace_field_definition` overlay, append-only retirement,
  materialization receipts, and versioned human-authored local readiness policy in Alembic revision
  `282b9c7278c2`.
- Added trusted-scope effective registry APIs and moved claim validation, merge freshness, and
  corroboration policy reads to the workspace-visible definition. Global seed/pack paths remain
  explicitly global-only.
- Dynamic `client.*` proposals now carry bounded schemas, candidate values, durable statement refs,
  and authority flags. Default mode is human confirmation; the optional safe-auto policy is
  supplemental-only, tenant-private, and records its policy actor/version.
- Promotion writes only the workspace overlay. The composition root reuses the artifact evidence
  reader and existing typed-value entailment judge to materialize one tenant-private claim. The
  operation is content-addressed, terminal-receipted, transaction-locked, and replay-safe.
- Split `CLIENT_BASELINE_FIELDS` from open effective Client-KB contents. Supplemental fields do not
  change baseline coverage; an explicit human policy can prospectively add local requirements.
- C8 project cards expose bounded extended field refs/counts, pending proposal refs/counts, retired
  status, and honest overflow omissions. A 200-field Postgres fixture stays under the card byte cap.
- Bumped the Head-of-ABM profile to v12, Stage-0 interview skill to v9, and Recipe 0 to v5 with
  `propose_field@2`. Exact v1 proposal tools remain installed only for historical recipe replay and
  cannot create/promote tenant-local dynamic fields or enter the current model surface.

## Verification

- New dynamic-field suite: 22 passed against isolated Postgres, including cross-workspace schemas,
  human/safe-auto authority, typed materialization, replay/version pinning, readiness separation,
  retirement, erasure/no-resurrection, governed reference-only tools, and 200-field card bounds.
- Broader affected registry/claim-store/Stage-0/proposal/projection/authority/recipe suite passed
  except two independently reproducible branch-baseline tests in untouched behavior:
  `test_recipe1_phase_spine_waits_and_resumes_without_reexecuting_gate` (checkpoint resume remains
  paused) and `test_one_conversation_is_one_source_however_its_values_earned_entry` (unordered
  claim selection can choose the same conversation source).
- Ruff and format checks passed for all touched Python files; mypy passed 463 source files; all 24
  import-linter contracts passed.
- Alembic has one head (`282b9c7278c2`); fresh isolated Postgres completed head -> parent -> head.
- The disposable `roseau-dckb-postgres-20260803` container was verified by exact name/port, stopped,
  and removed. No live model/provider canary was run; that would require separate spend authority.

## Close (Part I checkpoint)

At this checkpoint Part I was implemented and locally verified. The unrelated working-tree edits
and untracked review/spec files remained user-owned. Part II was not begun until the user resumed
it in the next session turn.

## Part II — Judged-claim verdict attribution

### Binding contract

- The written claim id remains the public/actual identity `A`; the pre-write entailment-question id
  remains the content-addressed internal identity `Q`.
- One pure claimstore plan maps ordinary claims to `(A,)` and
  `source_key == client_interview_judged` claims to `(Q, A)`. Q is preferred regardless of verdict
  recency; A is a legacy fallback. Missing evidence on a marked claim raises a typed bounded
  identity error.
- `SOURCE_CLIENT_INTERVIEW_JUDGED` moved beside that plan in claimstore. Stage 0 imports/re-exports
  it rather than defining a second marker. `entailment_judgment_id` remains the sole Q canonicalizer.
- No schema migration, verdict/claim rewrite, re-judge, profile/tool/recipe bump, prompt/policy
  change, or provider call belongs to this fix.

### Delivered

- Added the centralized batch `read_faithfulness_attributions` store. It plans all claims in memory,
  performs one verdict-table query over the union of A/Q candidates, applies ordered Q→A
  precedence, isolates malformed marked claims with a bounded metric/reason, and returns only
  A-keyed attributions (Q never leaves the seam).
- Narrative citations now accept already-scoped `Claim` objects and batch through that store. The
  handoff assembler no longer issues one faithfulness query per narrative line.
- `DbVerificationAnnotationReader` now resolves requested ids through workspace-scoped
  `claims_by_ids` before reading either side table. Cross-workspace/unknown/superseded/expired ids
  cannot acquire visibility from an unscoped verdict row; use decisions remain keyed on A.
- DSAR now derives its redaction candidates from the same A/Q plan. Judged claims redact Q and the
  legacy A fallback; ordinary evidence-bearing claims do not invent Q reachability. A malformed
  marked claim still redacts A and emits a bounded error without blocking erasure.
- Added a closed direct-SQL inventory guard: product SELECTs belong only to the claimstore
  attribution store; the verification judge retains its internal cache SELECT/INSERT and DSAR its
  administrative UPDATE.

### Verification

- 107 affected tests passed on isolated pgvector Postgres across attribution, narrative handoff,
  DSAR, faithfulness, Stage-0 evidence ergonomics, and dynamic Client-KB materialization.
- Final focused proof: 9 passed, including ordinary A, judged Q, legacy-A fallback, Q-over-newer-A,
  mixed malformed isolation, single-query batching, the real `FaithfulnessJudgeImpl` Q producer,
  narrative/review A attribution, cross-workspace refusal, and dual Q/A DSAR redaction.
- Existing Q canonicalization tests continue to cover corrected value/quote/field identities,
  sorted object keys, preserved list order, and unambiguous separators.
- Ruff check + format passed on all Part II files; mypy passed 464 source files; all 24 import
  contracts passed; Alembic still has the single existing head `282b9c7278c2` (no migration added).
- Repository-wide `make check` remains blocked before this slice by 16 unrelated formatting files
  and untracked skill scripts flagged for `print`. A full DB-backed pytest run reached 100% with 11
  unrelated/order-dependent branch baselines (tool/profile count drift, logging capture, Recipe and
  fleet checkpoint wiring, ICP fixture drift, memory/static-secret guards, and the known Stage-0
  independent-source ordering case). The isolated affected suite above is green.
- No live model/provider canary was run and no provider spend occurred; the producer-to-consumer
  proof used the real persistence path with a deterministic fake gateway.
- The disposable `roseau-c8-part2-019fc488` pgvector container was stopped and removed by exact
  name after verification; no shared branch database/container was modified.

### Close (Part II)

Part II is implemented, locally committed as one bounded change, and paused for user review. Keep
all pre-existing unrelated modifications and untracked artifacts out of the commit.
