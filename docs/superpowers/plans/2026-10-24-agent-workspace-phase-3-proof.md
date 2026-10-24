# Agent Workspace Phase 3: Remaining Workspaces and Proof — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every agent workspace — not just chats — is machine-independent and expires correctly, and it is proven on a real machine rather than inferred from the wiring.

**Architecture:** Phases 1 and 2 built the mechanism; almost nothing new is built here. Task 1 closes the one real gap (the expiry job cannot tell a non-chat caller is running). Task 2 finishes WS-33's last bullet. Tasks 3–5 prove the callers, the two-root reconciliation and the emergency flag through the existing two-root scenario harness. Tasks 6–7 are the live proof on the dushanbe stack and the rollout.

**Tech Stack:** Python 3.12, asyncpg/SQLAlchemy raw SQL, pytest on `clue_dushanbe_test` only; the live check runs against the dushanbe stack.

**Spec:** `docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md` §9 (WS-33, WS-34, WS-34a, WS-35) and §11 tests 9 and 12; rulings AW-1–AW-26 in `docs/superpowers/specs/agent-workspace/rulings.md`. Built on `feat/agent-workspace-phase-3`, branched from Phase 2 (`feat/agent-workspace-retention`).

## What is already true (do not rebuild it)

Checked in the code on 2026-10-24, before this plan was written:

- **WS-33's first two bullets are DONE.** Phase 1 (commit `b489ab416`) already moved research reconciliation onto `acquire_restored` of the source thread `research-quality-<source_execution>`, so it restores from the snapshot and works on any worker (`quality_research_wiring.py:1091`). **Only the third bullet is left**: when the source has no snapshot, say so instead of silently copying nothing. Task 2 is that bullet and nothing more.
- **WS-34's callers already get restore and save** through the shared layer: `account_research_turn_wiring.py:548`, `quality_research_wiring.py:555/998/1091`, `specialist_wiring.py:336`, `onboarding_synthesis_wiring.py:973`, `stage0_trial.py:757`. Phase 3 **proves** them; it does not wire them.
- **The ARV2 entity-research fleet is out of scope** (`account_research_fleet_launch`, `contact_research_fleet_launch`, `contact_entity_research`). It opens no agent workspace at all — its state is LangGraph checkpoints, Postgres rows and artifacts. Confirmed by grep. Do not add one.
- **The gap WS-34a names is real and its cause is specific:** the retention job's `_BUSY` (`agent_workspace_retention.py:115-127`) looks for an `agent_turn` fleet task and a `work_lease` keyed on `thread_work_id(workspace_id, thread_id)`. Every non-chat caller takes its lease on `WorkId(execution_id)` instead (`account_research_turn_wiring.py:772`, `quality_research_wiring.py:720`, `onboarding_synthesis_wiring.py:1247`), which that query can never match and which is not derivable from the thread id.

## Global Constraints

- Tiers and windows are unchanged: `raw_input` (`reads/`, `work/conversation_history/`, `work/large_tool_results/`) 172800 s after last activity; `working_file` (`scratch/`, rest of `work/`) 604800 s; `work_product` (`outputs/` only) **never**.
- The expiry job runs daily (`CLUE_AGENT_WORKSPACE_RETENTION_SWEEP_INTERVAL_S` = 86400), one runner at a time.
- **AW-26 is the hard line.** Nothing may delete an upload, a Gallery artifact, a research claim/result/receipt or provider data. The separate area `<ws>/agent-workspace/<sha>` plus the `is_agent_workspace_key` guard enforce it; no task may weaken either.
- Erasure stays two-phase: `erase_if_unreferenced` inside the transaction, `purge_erased_artifacts` in a fresh one after it commits.
- Agent-facing text is founder-reviewed before it is written (AW-2, D-26). No task here is expected to need new agent-facing prose; if one does, stop and ask.
- Every env flag the code reads appears in `.env.example` and the lane `.env` with its default, at the moment it is introduced.
- Migrations: hash revision id, `down_revision` = current head `3f0b61c7a2d4`, named constraints, reversible, one head.
- DB tests run on `clue_dushanbe_test` only; never the stack DB `clue_nashville_pm_clone`; never a broad suite with real keys (`--ignore-glob='*_live.py'`).
- No Claude/AI attribution in commits. Never push.
- Known PRE-EXISTING failures, not this branch's: `tests/db/test_db_migrations.py`; `tests/api/test_o6_conversation_composition_db.py::test_the_production_turn_pins_seeds_and_indexes_the_brand_knowledge`; two in `test_production_context_s3_db.py`; one in `test_production_context_s31_fleet_db.py`; `test_fleet_wiring.py` when `.env` is sourced; `tests/execution/test_recipes.py::test_latest_recipe0_is_the_only_promoted_executable_stage0_revision`; `tests/compliance/test_governance_e2e.py::test_supported_tier4_synthesis_is_promoted_to_current_value`; a flaky 12-writer race in `tests/storage/test_artifacts_db.py`.

## Review Focus

1. A non-chat run that is **mid-flight** when the job walks it — the job must not expire its files (Task 1 owns the fix and the test).
2. A run whose window elapses **while it is still running** (longer than 48 h) — the only protection is the Phase 2 rebase; prove it rather than assume it (Task 3).
3. A reconciliation whose **source run never saved a snapshot** — must report, not silently copy nothing (Task 2).
4. **The flag turned off and back on** with a chat saved on either side — a chat saved with snapshots on, then run with them off, then on again, must not lose files or wedge (Task 5).
5. **Unfamiliar thread-id shapes** through path validation and the cache sweep: `delegation-<uuid>`, `onboarding-synthesis-<run>-persona-<icp_key>`, `research-quality-<execution>` (Task 3).

---

### Task 1: A turn that restores marks the chat active (WS-34a)

**Files:**
- Modify: `platform/agents/clue_agents/workspace_snapshotter.py` (`restore`)
- Test: `tests/agents/test_workspace_snapshotter.py`, `tests/api/test_agent_workspace_retention_db.py`

**Interfaces:**
- Consumes: `WorkspaceSnapshotStore.touch(workspace_id=..., thread_id=...)` — already exists, today called only from an unchanged save (`workspace_snapshotter.py:308`).
- Produces: no new names. After this task, a successful `restore` of a chat that HAS a version record has stamped `last_activity_at = now()`.

**Approach (the decision the implementer cannot make alone).** Do NOT try to teach `_BUSY` the other callers' work ids: their lease is on `WorkId(execution_id)`, which is not derivable from a thread id, so that road needs new durable state. Instead make *starting a turn* count as activity, which it is. A run that restores is then never a candidate while it runs, uniformly for every caller — chats, research, delegations, onboarding — with no new state and no new query. `_BUSY` stays as it is: it remains a correct, cheap extra guard for chats.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_restore_marks_the_chat_active(tmp_path):
    # restore a chat that has a version record → store.touch called once for that chat
    # restore a NEW chat (no version record) → no touch (there is no row to stamp)

async def test_a_research_run_that_just_restored_is_not_a_candidate():
    # a research-shaped thread ("account-research-<uuid>") whose snapshot is 9 days old;
    # it IS a candidate; then acquire_restored it; run_once → chats_checked == 0, files_expired == 0
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/agents/test_workspace_snapshotter.py tests/api/test_agent_workspace_retention_db.py -q -p no:cacheprovider -k "restore_marks or just_restored"`
Expected: FAIL — no touch on restore; the aged research thread is still expired.

- [ ] **Step 3: Implement** — in `restore`, after a successful restore that had a pointer (both the warm path and the version path, not the no-record path), call `self._store.touch(...)`. A `touch` failure must not fail the restore: swallow and log, as the last-used stamp does.

- [ ] **Step 4: Run them** — Expected: PASS. Then `uv run pytest tests/agents/test_workspace_snapshotter.py tests/api/test_agent_workspace_retention_db.py tests/api/test_agent_workspace_scenarios_db.py -q -p no:cacheprovider`: all green.

- [ ] **Step 5: Commit** — `fix(workspace): starting a turn counts as activity, so a run in flight is never expired`

---

### Task 2: Reconciliation says when the source has no snapshot (WS-33, last bullet)

**Files:**
- Modify: `platform/api/clue_api/quality_research_wiring.py:1086-1116`
- Test: `tests/api/` — the suite that covers reconciliation (find it: `rg -l "reconciliation" tests/api | head`; if none drives this path, create `tests/api/test_quality_reconciliation_source_db.py`)

**Interfaces:**
- Consumes: `source_lease.snapshot_base` (a `SnapshotBase`; `.pointer is None` means the source never saved a snapshot) and `lease.restore_report`.
- Produces: a `source_snapshot` block in the reconciliation input at `work/reconciliation/input.json`: `{"thread_id": str, "version": int | None, "files_copied": int}`, plus a log line `research.reconciliation.source_snapshot` carrying the same three values.

- [ ] **Step 1: Write the failing test**

```python
async def test_a_source_run_with_no_snapshot_is_reported_not_silently_empty():
    # drive reconciliation whose source thread never saved: the input.json carries
    # source_snapshot == {"thread_id": "research-quality-<exec>", "version": None, "files_copied": 0}
    # and the log line is emitted. The turn still succeeds — a missing source is not an error.

async def test_a_source_with_a_snapshot_reports_its_version_and_count():
    # source saved 2 files under work/ → version 1, files_copied 2
```

- [ ] **Step 2: Run them** — Expected: FAIL (`KeyError: 'source_snapshot'`).

- [ ] **Step 3: Implement** — count the entries actually copied in the existing loop; read the version from `source_lease.snapshot_base`; add the block to the reconciliation input dict and emit the log line. Do not change what is copied.

- [ ] **Step 4: Run them** — Expected: PASS.

- [ ] **Step 5: Commit** — `fix(research): reconciliation reports a source run that has no snapshot`

---

### Task 3: Every other caller proved end to end (WS-34)

**Files:**
- Modify: `tests/api/test_agent_workspace_scenarios_db.py`

**Interfaces:** consumes the file's existing two-root `World` harness, `AgentWorkspaceRetentionJob`, `build_workspace_files_card`. **No production code.** A failure here is a real bug in Phase 1 or 2 — report it, do not weaken the assertion.

- [ ] **Step 1: Write one scenario per caller shape**, each driving the real factory with that caller's thread id:

```python
def test_15_every_caller_shape_round_trips_and_expires(tmp_path):
    # for each of: "account-research-<uuid4>", "delegation-<uuid4>",
    #              "onboarding-synthesis-<uuid4>-persona-icp_key_1",
    #              "research-quality-<uuid4>"
    #   root A: restore (new), write reads/r.json + scratch/a.md + outputs/o.csv, save
    #   root B: restore cold → all three present, byte-identical
    #   age it; run_once with the production windows
    #   → reads/r.json and scratch/a.md expired with receipts and bytes gone; outputs/o.csv live
    #   → the turn-start card on root B names the two expired and the one live

def test_16_a_run_longer_than_its_window_keeps_its_files(tmp_path):
    # Review Focus 2: root A restores and holds the lease; the chat is aged past the raw window
    # and run_once expires its reads/ file WHILE the run is open; the run then saves.
    # → the save rebases over the expiry-only move; its own new files are saved;
    #   the expired entry stays expired (bytes do not resurrect)
```

- [ ] **Step 2: Run** — `uv run pytest tests/api/test_agent_workspace_scenarios_db.py -q -p no:cacheprovider`. Any failure is a Phase 1/2 bug: report it with the sequence that triggers it.
- [ ] **Step 3: Prove each scenario bites** — break the production code deliberately in the working tree (one mutation per scenario), watch it fail, restore byte-for-byte. Record the mutation table in the report.
- [ ] **Step 4: Commit** — `test(workspace): every workspace caller round-trips, expires and survives a mid-run expiry`

---

### Task 4: §11 test 9 — reconciliation across two roots

**Files:**
- Modify: `tests/api/test_agent_workspace_scenarios_db.py`

**Interfaces:** consumes Task 2's `source_snapshot` block and the `World` harness.

- [ ] **Step 1: Write the scenario**

```python
def test_9_research_reconciliation_reads_the_source_snapshot_across_roots(tmp_path):
    # root A: a source run saves work/notes.md + reads/raw.json to "research-quality-<exec>"
    # root B (different cache root, nothing on disk): reconciliation for that source
    # → the copies land in the reconciling turn's own folders, byte-identical to A's
    # → source_snapshot names the source thread and version, files_copied == 2
```

- [ ] **Step 2: Run** — Expected: PASS if Phase 1's restore path and Task 2 are right; a failure is a real finding.
- [ ] **Step 3: Prove it bites** — point the source thread id at a thread that never saved; the copies must vanish and `files_copied` drop to 0. Restore.
- [ ] **Step 4: Commit** — `test(workspace): §11 test 9 — reconciliation reads the source snapshot on another machine`

---

### Task 5: The emergency flag exercised (WS-35)

**Files:**
- Modify: `tests/api/test_agent_workspace_scenarios_db.py`

**Interfaces:** consumes `CLUE_AGENT_WORKSPACE_SNAPSHOTS_ENABLED` through the factory builder (`build_agent_workspace_factory` composes a local `WorkerArea` with `lock_fd=None` over `<root>/local` when snapshots are off — see `agent_workspace_wiring.py`).

- [ ] **Step 1: Write the scenario** (Review Focus 4)

```python
def test_17_the_emergency_flag_turns_snapshots_off_and_back_on(tmp_path):
    # chat saves v1 with snapshots ON
    # same root, snapshots OFF: a turn runs, reads and writes locally, saves nothing;
    #   the version record is untouched (still v1)
    # snapshots ON again on a DIFFERENT root: restores v1 cold, all files present
    # → nothing wedges, no version is lost, the off-turn's local writes are simply not saved
```

- [ ] **Step 2: Run** — Expected: PASS or a real finding.
- [ ] **Step 3: Commit** — `test(workspace): the snapshots flag can be turned off and back on without loss`

---

### Task 6: The live proof on the dushanbe stack (§11 test 12, final; WS-35)

**Files:** none — this task produces evidence, recorded in Task 7.

**Pre-approved by the founder; report the real cost.** Estimated $0.60–1.00 (4–6 turns). Stop and report rather than invent a result if any step cannot be driven.

- [ ] **Step 1: Bring the stack to this branch** — `set -a; source .env; set +a`, `uv run alembic upgrade head`, then `./scripts/dev_stack.sh restart-api` and `restart-workers` (each under `timeout 240`; they hang in a trailing `sleep; status`). Confirm with `status` and `grep -iE "traceback|error" /tmp/dushanbe_fleet_worker*.log | tail`.
- [ ] **Step 2: Clean-machine restore.** A real chat turn writes `scratch/`, `outputs/` and a `reads/` file. Then **delete the whole cache root** (`CLUE_AGENT_WORKSPACE_ROOT`), not just the chat's folder. Continue the chat: the agent must find its files. Record warm and cold restore timings (WS-20) from the `agent_workspace.restore` log lines.
- [ ] **Step 3: Expiry live.** Age the chat past both windows; run `AgentWorkspaceRetentionJob` once by hand with the production windows; prove from the data that the `reads/` and `scratch/` bytes are erased AND purged while `outputs/` is live; then one more turn in which the agent reports what it has and what expired.
- [ ] **Step 4: The flag live.** Set `CLUE_AGENT_WORKSPACE_SNAPSHOTS_ENABLED=false`, restart workers, run one turn (it must work, locally), set it back, restart, and confirm the chat restores its last saved version.
- [ ] **Step 5: Record** every timing, the report counts, what the agent said, and the dollar cost. **Do not commit anything in this task** — Task 7 writes it up.

---

### Task 7: Rollout, docs and close-out

**Files:**
- Modify: `docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md` (§3 P3 row status; §11 tests 9 and 12 marked passing with their function names; change log)
- Modify: `CLAUDE.md` (the agent-workspace paragraph: all three phases built and proven)
- Modify: `docs/runbooks/agent-runtime.md` (the final live timings; what to alert on)
- Modify: `_memory/2026-10-22-agent-workspace-f3-spec.md` (closing entry for Phase 3)

- [ ] **Step 1: Write the docs** from Task 6's recorded evidence — the timings and counts that actually happened, never a rounded guess.
- [ ] **Step 2: Full relevant suite** — `uv run pytest tests/agents tests/storage tests/api/test_agent_workspace_*.py tests/api/test_account_research_turn_wiring_db.py tests/db/test_agent_workspace_storage_area_migration.py -q -p no:cacheprovider --ignore-glob='*_live.py'`. Expected: green but for the listed pre-existing failures.
- [ ] **Step 3: Commit** — `F3 P3: the proof, the docs and the close-out`

**Rollout is the founder's call, not a step here.** The flag already ships `true`; what remains is landing the four stacked branches (CRM → Phase 1 → Phase 2 → Phase 3). Task 7 states that plainly in the spec's P3 row rather than doing it.

---

## Self-review

- **Spec coverage:** WS-33 → Task 2 (first two bullets already done by Phase 1, recorded above). WS-34 → Task 3. WS-34a → Task 1. WS-35 → Tasks 5, 6, 7. §11 test 9 → Task 4. §11 test 12 → Task 6.
- **Type consistency:** `source_snapshot` (Task 2) is consumed by Task 4 under that name; `touch` (Task 1) is the existing store method, not a new one.
- **Review Focus:** 1 → Task 1; 2 → Task 3 (`test_16`); 3 → Task 2; 4 → Task 5; 5 → Task 3 (`test_15`'s four shapes).
- **Proportion:** seven tasks, four of which add only tests. The one real behaviour change is a single `touch` call. That is the right shape for a phase whose deliverable is proof.
