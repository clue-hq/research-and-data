# 2026-07-22 — Phase B integration close-out (B2→B3→B1 merged; wiring; review; hardening)

Branch `platform/workspace-restructure`. The three lane PRs (#27 B2, #28 B3, #29 B1) were merged
via GitHub before this session; this session did the **integration work proper**. All commits
local (no push). Final state: every gate green.

## Commits (in order)
1. `5cd4e5f` — **merge-damage repair + alembic join.** The lane merges committed a broken root
   `pyproject.toml` (B3's Rule S3 spliced INTO B1's F2 `forbidden_modules` array → TOML parse
   error, from `12cd2c2` onward; duplicate `known-first-party` lines from `eff8a2d`). Restored
   F2/S3 to their authored forms (+ deliberate hardening: `clue_storage` added to both), unioned
   first-party. `alembic merge` of the three lane heads (`10642c862e43` B1, `d0c2e361f7d4` B2,
   `50b778e4009a` B3) → join `399633c6e1cb`; db-smoke up→down→up green on a throwaway DB.
2. `7d84990` — **B2 api-root wiring** (agent-written): `storage_wiring.py`
   (`build_storage_backend`, `SnapshotBindingPhaseHandler`, `build_data_subject_rights`,
   `run_orphan_blob_sweep`), `storage=` params on deep/retention builders, clue-storage dep.
3. `94c636c` — **B1 api-root wiring** (agent-written): `fleet_wiring.py` (lock factory,
   `tier_priority_from_rubric`, fleet scheduler/driver/worker builders, `enqueue_run_drive`),
   `fleet_main.py`, baseline `AccountScheduler` lock threading, fleet-mode `scheduler` param.
4. `28307a0` — **cross-lane script hygiene**: script 01 demo defaults now per-invocation tagged
   (fixes the DB-suite-vs-scripts hermeticity failure — proven: suite green fresh, on rerun, AND
   after the scripts chain seeded demo data); 02's Next hint fixed (03 rejected the old flags —
   the hint literally crashed 03); 04 gained its missing Next hint.
5. `a31508f` — **review small findings**: 02 `--workspace-id` required (silent workspace-split
   trap, reproduced in review); 04 hint carries `--tier`; first-party completed; merge-revision
   annotation fixed.
6. `2be42f0` — **review hardening** (the big one; agent-written to my design, from the three-way
   Fable review):
   - `fleet_main` **boot handler registration** (`register_boot_handlers` — today only REVIEW is
     settings-composable; DEEP/VERIFICATION are campaign-scoped → per-run; HANDOFF needs
     M8/M10-era concretes) + refuse-to-start on empty registry. Pre-fix the worker failed EVERY
     claimed task (`NoPhaseHandlerRegistered` → parked FAILED) and poisoned resume flows.
   - `clue_api/locks.py::lazy_account_lock_factory` — resolves `get_redis()` at lock
     *acquisition*; now the **default** `lock_factory` of `build_deep_phase_handler` (sentinel
     default; explicit `None` = written test opt-out). Single-flight ships ON.
   - `priority_for` **required** on `build_fleet_deep_scheduler`; `tier_priority_from_rubric`
     unknown-label fallthrough now `fallback_rank + 1 + ladder` (an unknown label could
     previously leapfrog the rubric — `default_tier_priority("top")==0`), with normalization.
   - `storage` **required** on `register_deep_phase_handler` +
     `register_retention_sweeping_handoff_handler` (None = explicit opt-out; forgetting =
     TypeError). Empty-`workspace_id` guard in `SnapshotBindingPhaseHandler` (would have keyed
     tenant snapshots into `public/{sha}`).
   - Orphan sweep **scheduled**: `fleet_main` background task on new
     `CLUE_STORAGE_ORPHAN_SWEEP_INTERVAL_S` (default 6h; ≤0 disables); faults logged, non-fatal.

## The review (founder-required: Fable-model reviewers only)
Three parallel Fable review agents (B2 wiring / B1 wiring / merge-repair+scripts), adversarial
briefs. Key verdicts:
- **Base commits fully clean** — every lane-authored contract entry accounted for (tomllib-parsed
  per-lane-tip comparison); alembic DAG clean; chain empirically re-run green on a throwaway DB.
- **B2 wiring semantically correct end-to-end** (binding lifecycle, ContextVar propagation
  through the real task topology, DSAR two-phase, retention purge leg, orphan sweep) — but was
  all *unreferenced* construction sites with silent-off None-defaults → hardened in `2be42f0`.
- **B1 wiring**: mechanical wiring correct (settings→constructor units all checked; enqueue
  semantics; §1a discipline), but `fleet_main` was a worker that could only fail (fixed) and the
  lock/priority seams were accept-but-nobody-passes (fixed).

## Verification (final state)
- `make check`: ruff clean · mypy 311 files · import-linter **21 kept, 0 broken** · offline
  **1263 passed**.
- Full DB suite on `clue`: **2146 passed / 20 skipped** — fresh, on rerun, and after the scripts
  chain (hermeticity). db-smoke green on throwaway (at the merge commit; no migrations after).
- Recipe-#1: scripts 01→06 complete end-to-end in stub mode by following printed hints alone.
- Known pre-existing (NOT this session): `tests/durable/test_account_run_db.py` two failures when
  the directory runs **solo** against the long-lived DB (`FieldRedefinitionError` — seed residue
  class, same as the B2 lane note); reproduced identically on pre-fix HEAD; full-suite and
  clean-DB runs green.

## Backlog delta (CLAUDE.md + AGENTS.md resynced identical)
- **Removed (resolved):** `[B1×api]` (lock factory wired both schedulers, lazy default ON),
  `[B2×api/ops]` (orphan sweep scheduled in fleet_main).
- **Added:** `[B4×fleet]` per-(client,icp) DEEP/VERIFICATION composition inside the detached
  worker (the delegation-contract design item; worker cleanly drives only boot-composable phases
  until then); `[B2×stage0/M6]` Stage-0/scoring fetches run sink-less until their phases get
  registration surfaces; `[B1×M13.2]` resume-hook drives a bare `CampaignRun` (no ledger/budget)
  vs the fleet driver's full composition — divergent semantics, pre-existing.
- **Unchanged:** `[B1×integration]` fence tokens, `[rename×integration]` stage 2 (NOW DUE — see
  next), `[B3×research]`, `[B2×presign/frontend]`, `[B2×M7/M8]`.

## Immediate next (blocking B4)
**Stage-2 `campaign_run`→`project_run` rename** per
`docs/specs/PB-rename-campaign-run-to-project-run.md` — MUST run now (integration gates are
green) and before B4 opens. Critical pin: `IdempotencyScope` VALUE strings and the
`idempotency_scope` DB enum values are immutable ledger-key data — rename names, never values.
Note: the integration added new `clue_api` files carrying exception-3 names
(`fleet_wiring.py`, `fleet_main.py`, `locks.py`, `deep/composition.py` widened) — the playbook's
repo-wide grep covers them, but expect those call sites in the flip pass.
