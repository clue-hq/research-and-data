# 2026-07-24 — Phase C5 engineering plan

## Branch and authority

- Opened `platform/c5-recipe-execution` from the integrated C4 head
  `08c1998 feat(stage0): implement governed Recipe 0`.
- Binding child spec:
  `docs/specs/PC-C5-run-graph-recipes-executor.md`.
- Detailed execution plan:
  `docs/superpowers/plans/2026-07-24-phase-c5-run-graph-recipes-executor.md`.
- This was a technical/senior-engineering planning session. No product-manager skill or C5 runtime
  implementation was used.

## Current-state findings

- C4's `ToolbeltRecipeRunner` is intentionally in-memory and has no durable graph state.
- B4's `tool_invocation` is a workspace-scoped 24-hour HTTP idempotency cache, not a permanent run
  journal and not sufficient for crash recovery after its TTL.
- `ToolRegistry` currently has one implementation per name and `ToolResult.references` is untyped;
  C5 needs exact version resolution and typed output schemas before graph edges can be validated.
- The fleet/state-machine/account-ledger substrate is reusable. C5 must preserve it rather than
  implement a second research pipeline.
- C1/M13.4 provide most supervisor signals, but run-specific source failure telemetry and enforced
  account/source controls are still missing.
- `PreSpendRequest` has no source key/execution coordinate, so a run-local source breaker cannot be
  enforced through the current request without a real contract delta.
- Field/source registries already have `active` and `version`, enabling exact compatibility checks;
  unavailable old versions must fail honestly and require an explicit recipe revision.

## Binding C5 decisions

1. Add one platform execution owner, `platform/execution/clue_execution`.
2. The graph history is append-only; a mutable cursor is only a rebuildable scheduling
   materialization.
3. Every production tool invocation belongs to an execution and is journaled by the toolbelt.
4. Validated parameters are artifact-backed; graph/event JSON holds only hashes, safe scalars, and
   references.
5. Execution idempotency is durable for the execution lifetime and uses a stable operation id.
   The A9 HTTP cache remains separate.
6. Recipe-safe effectful tools must prove replay behavior. Run-start identifiers derive from the
   stable operation id.
7. Recipes are immutable revisions with exact pins and fail-before-run compatibility resolution.
8. C5 supports DAGs, explicit gates, and bounded maps; no arbitrary loops or planner mind.
9. Recipe #1 advances the existing `ProjectRun` one expected phase per node. It does not duplicate
   phase handlers.
10. The deep canary uses the existing high-tier resolver, account orchestrator, queue, budgets,
    locks, and ledgers; only cohort admission + supervisor gate are new.
11. The supervisor is deterministic aggregate monitoring plus an optional bounded LLM diagnosis
    leaf. Actions execute through tools and must alter actual scheduler/source behavior.
12. Existing active project runs finish on the old driver. Only new canaried runs route through
    Recipe #1 after output parity.
13. A project run has at most one recipe execution owner. Resume/tier/review surfaces route to that
    owner when present and fall back to the legacy drive task otherwise, so both drivers cannot
    race the same run.
14. Steering tools require actor-attributed, display-safe before/after journal snapshots.
15. Parameter artifacts are content-addressed inside the owning workspace namespace, and failure
    events contain only redacted summaries/codes/refs.
16. The memory kill switch remains live safety authority. An old recipe pin cannot re-enable
    memory; required-memory recipes fail pre-dispatch while it is off, and optional-memory recipes
    pin the disabled state.
17. Recipe-definition digests are unique within a recipe identity, not globally. Execution-wide
    pins use a surrogate key plus `UNIQUE NULLS NOT DISTINCT`; nullable columns are not placed in a
    primary key.

## Planned implementation order

1. C5.0 contracts, typed tool outputs, version registry, replay audit.
2. C5.1 append-only journal and required toolbelt writer.
3. C5.2 immutable recipes and compatibility loader.
4. C5.3 fleet work-handler extraction and crash-resumable executor.
5. C5.4 Recipe #0 migration.
6. C5.5 supervisor, enforced controls, and deep canary.
7. C5.6 Recipe #1 cutover, run views, and golden outcome reproducibility.

## Planning verification / unresolved implementation risks

- No runtime/schema behavior was changed in this planning session.
- The riskiest implementation boundaries are the domain-commit/journal-complete crash window,
  parameter-artifact DSAR reach, fleet-shell generalization, source-breaker context threading, and
  canary integration without forking deep behavior.
- C8 still owns hard fence tokens on all pre-existing research-domain writes. C5 must fence its own
  cursor/journal writes and document the remaining provider/domain residual honestly.
- Before any C5 runtime code, execute and review C5.0. Do not parallelize the shared toolbelt,
  execution schema, compatibility loader, or fleet changes.

## Closing verification

- Relative Markdown-link check passed for the C5 spec/plan and updated Phase-C indexes.
- `git diff --check` passed.
- `uv run alembic heads` reports the single head `1b71451d48cd`.
- `make check` passed: Ruff format/lint, mypy, all 23 import contracts, and pytest
  (`1339 passed, 1019 skipped`; DB/external-service coverage remained environment-gated).
- No runtime code or migration was added. The next action is C5.0 on this branch after human review
  of the technical plan.
