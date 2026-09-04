# Sealed-discovery launch guard and fleet DB recovery (2026-08-19)

## Founder decision implemented

Account profiling must not launch from a mutable discovery generation. When the current discovery
batch is still running, the main agent's governed gate/direct-launch action now refuses with
`account_discovery_in_progress` and this exact user-facing message:

```text
Account discovery is still in progress. Please wait and try account profiling again after discovery finishes.
```

This is provenance authority, not a budget, coverage, or completeness threshold. Missing discovery,
terminal unsealed discovery, and an inconsistent sealed row have separate fail-closed reasons.

## Implementation

- `account_research_discovery_readiness.py` centralizes the current-generation + immutable-seal
  check.
- `open_directive_confirmation_gate@1` checks it before presenting an approval card, so the main
  agent receives the wait/retry message while discovery is active.
- `launch_selected_account_research@1` checks it before direct confirmation or launch.
- `AccountResearchFleetLauncher` repeats the check under its launch transaction before writing an
  entity-research run, Account run, job, or task. All legacy/alternate launch callers therefore
  retain the same backstop.
- Historical gate and launch replay identities were deliberately left unchanged. Adding the new
  seal hash to their deterministic identity would have minted duplicate run ids on retry. A sealed
  generation is already immutable and cannot be replaced.

Fleet connection recovery is independent:

- every SQLAlchemy async engine now uses `pool_pre_ping=True`, so a closed asyncpg connection left
  by cancellation is rejected and replaced at its next checkout;
- the generic leased-worker loop contains transient SQLAlchemy `InterfaceError` / `OperationalError`
  failures, waits one poll interval, and retries instead of terminating the process; programming and
  integrity errors still fail loudly.

## Verification and runtime isolation

Development used the new isolated database `clue_missoula_seal_worker_20260819` on the existing
local Postgres server. The live `clue` database, frontend, API, durable queues, artifact storage,
Missoula fleet state, and all Tunis instances were not changed. The Missoula fleet was not restarted.

Verified:

- red/green reproduction of the unhandled closed-connection claim and disabled pool pre-ping;
- 68 focused gate, selected-launch, launcher, worker, DB-engine, registry, and contract tests pass;
- strict mypy passes for 732 source files;
- all 26 import/dependency contracts pass;
- targeted Ruff format/lint passes for every changed file.

The repository-wide test pass remains red on the branch's broader existing stale fixtures/contracts
(including old profile versions, schema fingerprints, migration-smoke assumptions, Stage-0 setup,
and research economics assertions). The relevant launch/fleet suites above pass in isolation. The
repository-wide format check likewise already reports nine unrelated files; none were reformatted in
this change.
