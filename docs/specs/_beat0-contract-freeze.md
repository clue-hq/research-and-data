# Beat-0 — Contract Freeze for M5–M9 Parallelisation

> **Status:** landed on branch `beat0/contract-freeze` (off `integration/m4`). This is the shared
> base the four parallel milestone branches fork from. Read it before starting M5, M6, M7, or M9.
>
> **Companion docs:** [`_conventions.md`](./_conventions.md) (the DRY backbone) · the per-milestone
> specs `M05`/`M06`/`M07`/`M09`.

## Why this exists

After M4, the dependency graph opens into a wide parallel band:

```
M1 ─▶ { M2, M3 } ─▶ M4 ─▶ { M5, M6, M7, M9 } ─▶ M8 ─▶ { M10, M11, M12 } ─▶ M13
```

Those four (`M5` stage0, `M6` discovery+scoring, `M7` durable execution, `M9` verification) are not
symmetric peers: **M7 and M9 are substrate** (a runtime everything runs *on*, and a library of gates
everything *calls*) while **M5 and M6 are pipeline phases**. To build them on four parallel branches
without integration pain, everything they **share** is frozen here first, in one commit, so each
branch forks from a stable, compiling base and the only later join is a mechanical `alembic merge`.

The two collision classes Beat-0 removes up front:

1. **Shared-code churn** — if each branch independently added cross-cutting protocols/enums to
   `core`, the four would conflict on `core/__init__.py`, `core/enums.py`, and the seam shapes.
2. **Migration-graph collisions** — the M2/M3 pain (parallel branches both minting `0005/0006/0007`).

## What Beat-0 froze

All cross-milestone contracts live in **`core`** — the only package every milestone may import —
exactly as the `Resolver` and `LLMGateway` protocols already do (conventions §2). Implementations
live in the owning milestone's package and are wired together only at the `api` composition root.

| Added in Beat-0 | Where | Owner of the impl |
|---|---|---|
| `PhaseHandler`, `PhaseContext`, `PhaseResult` | `core/execution.py` | M7 calls; M5/M6/M8/M9/M12 implement |
| `AspectWorker`, `AspectContext`, `WorkerResult` | `core/execution.py` | M7 calls; M8 implements |
| `BudgetEngine`, `Estimate`, `BudgetDecision`, `BurnDown` | `core/execution.py` | M7 implements; M6/M8/M9 call |
| `PreSpendGate`, `PreSpendRequest`, `PreSpendDecision`, `TargetLock` | `core/verification.py` | M9 implements; M8/M11 call |
| `FaithfulnessJudge`, `JudgeResult` | `core/verification.py` | M9 implements; M5.1/M8/M11 call |
| `IdentityBindingGate`, `Binding` | `core/verification.py` | M9 implements; M8 calls |
| `Freshness`, `Staleness`, `ReResearchCandidate` | `core/verification.py` | M9 implements; M7 calls |
| `idempotency_key`, `account_step_key`, `phase_key` | `core/idempotency.py` | pure helpers (M7 uses) |
| `CampaignPhase`, `PhaseStatus`, `WorkerStatus`, `BudgetScope`, `BudgetVerdict`, `PreSpendVerdict`, `JudgeVerdict`, `IdempotencyScope` | `core/enums.py` | shared closed taxonomies |
| `CampaignRunId` + `new_campaign_run_id` | `core/primitives.py` | the outer-run id (distinct from `RunId`) |
| `CAMPAIGN_PHASES` now **derived from** `CampaignPhase` | `obs/spans.py` | one source of truth for phase tokens |
| Independence contract widened to all milestone packages | `pyproject.toml` | machine-enforced isolation |

Everything is signature-only: protocols have `...` bodies, value types are frozen pydantic models.
No behaviour, **no DB migration, no new tables** ship in Beat-0.

## The parallelisation rule (machine-enforced)

The `[tool.importlinter]` **independence** contract now lists every milestone worker package —
`stage0`, `discovery_scoring`, `durable`, `profiling`, `verification`, `narrative`, `compliance`,
`synthesis`, `review` (plus `adapters`). Consequences a branch must respect (`make contracts` fails
otherwise):

- **A milestone package may NOT import another milestone package.** No `stage0 → discovery_scoring`,
  no `profiling → verification`, etc. They coordinate only through the **claim store** and the
  **`core` contracts** above.
- Each milestone package **may** freely import the shared base (`core`, `config`, `obs`) and the
  M1–M4 services (`claimstore`, `identity`, `icp`, `sources`) — that is how M6 calls the waterfall,
  M5 resolves imports, etc.
- A milestone implements a `core` protocol (e.g. `PhaseHandler`); the **concrete instance is
  constructed and registered at the `api` composition root**, which is the only layer allowed to
  import every package (nothing imports `api` — Rule 5). M7's `CampaignRun.register_phase_handler`
  is called there, not inside the phase packages.
- This is *why* M5↔M6 convergence (the Pass-A bridge) is **store/phase-mediated, not an import**:
  M5's import pipeline writes resolved candidate accounts; M6's scoring phase scores all candidates
  uniformly. Neither imports the other.

## Migration ownership

**Single head at Beat-0:** `eab62cbb1366` (`source_yield_telemetry_table`). Beat-0 adds **no
migration**, so all four branches fork with this as their migration base.

**Process (the adopted convention — see root `CLAUDE.md`):**

1. Each branch creates migrations with `alembic revision -m "<slug>"` → **random hash ids**
   (never hand-picked sequentials). `down_revision` = the branch's current head (starts at
   `eab62cbb1366`).
2. At integration, after merging two branches' code, run `alembic merge -m "merge <a>+<b>" <head1>
   <head2>` to rejoin to one head. `alembic heads` must return exactly one; `make db-smoke` (up → down
   → up on a clean throwaway DB) is the gate.
3. Migrations stay hand-written + reversible; named CHECKs/indexes/triggers; **enum tuples mirrored
   from `core.enums`** with a parity test in the table's test suite (per-enum, not global — there is
   no "every core enum needs a DB enum" check, so the Beat-0 core-only enums need no migration yet).

**Per-branch DB object ownership** (each branch creates these on its own migrations, additively):

| Branch | New tables | New DB enums | Alters to shared tables |
|---|---|---|---|
| **M7 `durable`** | `campaign_run`, `account_run`, `campaign_phase_checkpoint`, `idempotency_ledger`, `budget_event`, `adjustment_journal`, + LangGraph `AsyncPostgresSaver` tables | `campaign_phase` (mirrors `core.CampaignPhase`), `campaign_run_status`, `account_run_status` (M7 owns these two lifecycle enums — they are `durable`-internal, **not** in Beat-0 `core`) | none — `claim.run_id`/`research_mode` already exist |
| **M9 `verification`** | `pre_spend_policy`, `gate_decision`, `conflict_flag`, `judge_policy`, `faithfulness_verdict`, `binding_policy`, `identity_binding_eval`, `cadence_policy`, `re_research_candidate`, `golden_fixture`, `eval_run` | mirror `core.PreSpendVerdict`/`JudgeVerdict` if used as columns; `FreshnessState.EXPIRED` added here (M9-internal; coordinate with `merge.py` + M10.5) | none — `claim.verification_status`/`identity_binding`/`use_class`/`corroborations` already exist |
| **M6 `discovery_scoring`** | `account_tier` (or model tiers as claims) + run telemetry (per-channel yield, coverage report, checkpoint record) — **coordinate with M7** on the run-telemetry tables (`source_yield_telemetry` already exists @ `eab62cbb1366`) | none | none — writes claims/rows only |
| **M5 `stage0`** | none (writes claims + `account_entity` rows via existing APIs) | `ResolveOption` is **M5-internal** (`stage0`, not `core`) | none |

**Key non-collision finding:** the `claim` table already carries every column M7/M9 need
(`run_id`, `research_mode`, `verification_status`, `identity_binding`, `use_class`, `corroborations`,
`reuse_scope`, `tenant_id`, `source_key`). **Neither M7 nor M9 alters `claim`** — so the historically
dangerous shared-table ALTER collision does not arise. `freshness_state` is **computed read-side** in
the merge view (`CurrentValue.freshness_state`), **not** a stored column; do not add one without a
deliberate decision on the M9 branch.

## Recommended merge order

`M7 ≈ M9` (substrate — land seam-complete first) → `M6` (builds on both) → `M5` (consumes M6's Pass-A
scorer via the store + M9's judge; the only one M8 does **not** depend on, so it may trail). M8 is
gated on `M6 + M7 + M9`; pour parallelism into those three to shorten the path to M8.

## What each branch implements against the frozen seam

- **M7 `durable`** — `CampaignRun` (state machine over `CampaignPhase`, calling registered
  `PhaseHandler`s), `AccountResearchGraph` (LangGraph + `AsyncPostgresSaver`, spawning `AspectWorker`s),
  the recursion knob + `SpawnGuard`, a `BudgetEngine` impl, the ledger-backed `idempotent()` context
  manager (using `core.idempotency` keys), and the M7 tables.
- **M9 `verification`** — impls of `PreSpendGate`, `FaithfulnessJudge`, `IdentityBindingGate`,
  `Freshness`; the M9-internal `Corroborator`, the `verify()` umbrella, the eval harness; config/audit
  tables; `FreshnessState.EXPIRED`. Its `VERIFICATION` phase is a `PhaseHandler`.
- **M6 `discovery_scoring`** — `discover`/`admit`/Pass-A `score` (returns `core.Score`)/`assign_tiers`/
  `coverage_report`; its `DISCOVERY`/`SCORING`/`TIER_CHECKPOINT` phases are `PhaseHandler`s (the
  checkpoint uses `PhaseResult(status=PAUSED)`).
- **M5 `stage0`** — reverse-profiling → Client KB, ICP synthesis/confirm, import + lookalike seeding;
  its `REVERSE_PROFILING`/`ICP_CONFIRMED` phases are `PhaseHandler`s. Calls the M9 judge (via the
  `core` protocol, injected) for tier-4 client claims.
