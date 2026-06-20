# 2026-06-20 — Beat-0 contract freeze (M5–M9 parallelisation)

## Goal
Prepare to build M5/M6/M7/M9 on four parallel Conductor branches off `integration/m4`. "Beat-0" =
one shared base commit that freezes everything the four branches share, so the only later join is a
mechanical `alembic merge`. Branch: `beat0/contract-freeze` (off `integration/m4` @ head
`eab62cbb1366`). The four Beat-1 branches fork from this.

## Key findings (verified against the workspace, not assumed)
- Milestone packages already exist as scaffolds: `stage0`=M5, `discovery_scoring`=M6, `durable`=M7,
  `verification`=M9, `profiling`=M8. Foundations M0–M4 are fully implemented.
- The M0/M1 foundation **pre-baked most of M7/M9's surface**: the `claim` table already has
  `run_id`, `research_mode`, `verification_status`, `identity_binding`, `use_class`, `corroborations`,
  `reuse_scope`, `tenant_id`, `source_key`. So **neither M7 nor M9 alters `claim`** — the dangerous
  shared-table ALTER collision does not arise.
- `freshness_state` is **computed read-side** (`CurrentValue.freshness_state` in `claimstore/merge.py`),
  NOT a stored column. Don't add a column without a deliberate M9 decision.
- `obs/spans.py` already had `CAMPAIGN_PHASES`, `phase_span`, `SPAN_VERIFICATION_*`,
  `ATTR_CAMPAIGN_RUN_ID`; `config/schema.py` had `BudgetCaps`/`ScoringRubric`/`FreshnessTtls`.
- Name collision dodged: `GateDecision` is taken by `core/modality.py` (adapter run/skip) → the M9
  pre-spend verdict is `PreSpendVerdict` / `PreSpendDecision`.
- Enum parity is **per-enum** (asserted in the table's own test suite), not global — so core-only
  enums need no DB migration. `eab62cbb1366` head is single.
- Import-linter reality (corrected an over-broad agent summary): milestone packages MAY import
  `core/config/obs` + the M1–M4 services (`claimstore/identity/icp/sources`); they may NOT import
  each other (independence) or provider SDKs (Rule 4) or `api` (Rule 5).

## Decisions
- **Cross-milestone contracts live in `core`** (mirrors `Resolver`/`LLMGateway`), impls in the owning
  package, wired at the `api` composition root. This lets every milestone package be import-isolated.
- **Widened the import-linter `independence` contract** to all milestone packages (`stage0`,
  `discovery_scoring`, `durable`, `profiling`, `verification`, `narrative`, `compliance`, `synthesis`,
  `review`) + extended the resolver-ban rules to them. Now "no branch can import another branch" is
  machine-enforced (`make contracts`).
- **Beat-0 ships NO migration / NO tables** — each branch creates its own (hash ids, `alembic merge`
  at integration). M7 owns `campaign_run`/`account_run`/`campaign_phase_checkpoint`/
  `idempotency_ledger`/`budget_event` + the `campaign_run_status`/`account_run_status` enums; M9 owns
  its config/audit tables + `FreshnessState.EXPIRED`.
- M5↔M6 convergence (Pass-A bridge) is **store/phase-mediated, not an import** (matches the DAG:
  neither depends on the other).
- Overrode both seam-extraction agents' proposal to put protocols in `durable`/`verification` and to
  ship sequential-id migrations — wrong per repo convention.

## Changes made (all on `beat0/contract-freeze`)
- `core/primitives.py`: `CampaignRunId` + `new_campaign_run_id`.
- `core/enums.py`: `CampaignPhase`, `PhaseStatus`, `WorkerStatus`, `IdempotencyScope`, `BudgetScope`,
  `BudgetVerdict`, `PreSpendVerdict`, `JudgeVerdict`.
- `core/execution.py` (new): `PhaseHandler`/`AspectWorker`/`BudgetEngine` protocols + value types.
- `core/verification.py` (new): `PreSpendGate`/`FaithfulnessJudge`/`IdentityBindingGate`/`Freshness`
  protocols + value types.
- `core/idempotency.py` (new): pure `idempotency_key`/`account_step_key`/`phase_key`.
- `core/__init__.py`: exports + `__all__`.
- `obs/spans.py`: `CAMPAIGN_PHASES` now derived from `core.CampaignPhase` (one source of truth).
- `pyproject.toml`: widened independence + resolver-ban contracts.
- `docs/specs/_beat0-contract-freeze.md` (new): the parallelisation + migration-ownership protocol.
- `tests/test_beat0_contracts.py` (new): smoke (imports/exports, runtime-checkable protocols, phase
  parity, idempotency determinism, frozen value types).
- Pointer lines in the 4 milestone package `__init__.py` docstrings.

## Verification
- `make check` green: lint ✓, mypy ✓ (108 files), import-linter ✓ (10 kept, 0 broken), pytest
  381 passed / 293 skipped / 0 failed. `alembic heads` = single `eab62cbb1366` (no migration added).
- Adversarial review (4 reviewers, verify-each-finding): M7 fidelity ship/0, M5-M6+collisions ship/0,
  M9 fidelity fix-first/2 (both applied), governance reviewer failed on a StructuredOutput hiccup —
  scope self-verified against machine checks (contracts pass, single head, claim columns exist).
- Two review fixes folded into the commit: (1) `PreSpendGate.assemble_target_lock` now
  `(entity: AccountEntity | ContactEntity, field: FieldDef) -> TargetLock` to match M09 §M9.5/§46
  (caller M8.1 already holds the resolved entity; no re-lookup); (2) documented `Freshness.evaluate`'s
  `ttl` override semantics. Commit: `ae5adac` on `beat0/contract-freeze`.

## Follow-ups / open
- Recommended merge order: M7 ≈ M9 → M6 → M5; M8 gated on M6+M7+M9 (M5 may trail).
- Decide whether `idempotent()` context manager + ledger is M7-only (current plan) or also needed by
  another branch (then promote to core).
- M6/M7 coordinate the run-telemetry tables (`source_yield_telemetry` already exists).
- Confirm with the user the four-branch fork + whether to push `beat0/contract-freeze`.
