# 2026-08-04 — M8B A0/A1 critical remediation

## Scope and outcome

- Reopened M8B slices A0 and A1 after the critical review; no downstream slice was started.
- Closed the P1/P2 source-authority gap, completed the Exa account-deep contract, and made the A1 synthetic fixture prove the same governed behavior through direct and production composition.
- No live or paid provider call was made.

## Root cause and resolution

- The observed Sumble-first precedence failure was not an ordering bug. The planner honored the ICP source-profile override, while the pre-spend gate independently checked the shared `field_definition.tier_plan`. Two mutable authorities could therefore disagree about the same field.
- Added a canonical `EffectiveFieldSourcePlan`, keyed by workspace, ICP key/version, and field. It records exact `(source_key, tier)` authorizations and a content digest.
- The planner now computes the canonical intersection of the served source profile and the active capable source registry, freezes it durably, and narrows execution candidates from that frozen plan.
- The pre-spend gate reconstructs and verifies the canonical plan on first use, audits the exact source key and plan digest, rejects forged or mismatched plans, and cannot be widened by a later mutable profile change.
- A rejected source is now a source-local skip in account profiling so valid lower-priority fallbacks remain available.
- Enumeration requests now also validate the exact registered source key and tier. `sumble_teams`, `sumble_people`, and the internal `llm_role_inference` source have explicit registry identities.

## A0 Exa account-deep contract

- Added independent default-off Exa account-deep settings.
- Froze the transport-neutral `/search` request contract for `deep` / `deep-reasoning`, product cap 50, optional 1–10 additional queries, closed structured output, target-lock instructions, retained result content, and per-field grounding.
- Response validation requires a request id, results, structured output, cost, and citations matching retained inspectable result material. Provider confidence remains optional because the official contract does not require it.
- Added content-addressed request/response fixtures and an A0 acceptance document covering endpoint, evidence, spend/error semantics, replay identity, and unresolved transport/persistence decisions.

## A1 governed fixture

- The synthetic fixture now pins explicit budget, jurisdiction/use policy, freshness, recursion, source-plan, and committee-policy references.
- Both the direct profiler path and production-composition path use the real pre-spend gate and assert the same four source-plan-audited account claims plus two committee members.
- Replay is zero-call and zero-write. The prior expected tier-2 rejection was removed because exact effective-plan authorization now resolves the underlying authority conflict.

## Persistence and migration

- Added Alembic revision `e9634dbc522f` for immutable effective source plans and exact gate-decision audit columns.
- Direct plan updates/deletes are rejected; parent ICP deletion can still cascade for lifecycle/erasure correctness.
- Alembic reports exactly one head.

## Verification

- Final committed-HEAD A0/A1 and adjacent integration matrix: 239 passed with the database enabled;
  no skips or failures.
- Mypy: 501 source files passed.
- Import-linter: 24 contracts kept, 0 broken.
- Scoped Ruff formatting/check: passed.
- Clean branch-specific `clue-pg-roseau` database (`localhost:55010/clue`): base → head → base
  → head passed. Its public schema was intentionally reset; no shared database was touched.
- The first post-commit DB run correctly exposed that this two-day-old disposable schema was stale:
  its Alembic stamp did not match the checked-in S2 table shape and old source-registry rows polluted
  rollback-based tests. The run was not counted. Rebuilding from the committed migration chain removed
  both conditions, after which all 239 cases passed.
- Five isolated full-suite failures remain outside this change: one stale Stage-0 tool-schema digest, three tests expecting an older tier-checkpoint guard, and one pre-existing memory import-boundary assertion. Full-repository Ruff also sees unrelated existing/untracked files; all files in this slice pass scoped Ruff.

## Next boundary

- A0 and A1 are mechanically complete after remediation, subject to review of the local commits.
- Do not begin A2/E-series/S2 provider acquisition or any live canary until the user explicitly proceeds.
