# M8D R2 — Subject-neutral fleet/job acceptance

> **Status:** Accepted on 2026-08-06 on
> `platform/c8-account-profiling-integration`.
>
> **Scope:** This acceptance closes M8D R2 only. It installs the mechanical account/contact job
> substrate; it does not compose the R3 `create_agent()` runtime or authorize provider work.

## 1. One fleet, two separately authorized run kinds

`EntityResearchRunEnvelope` projects the frozen R0 lifecycle into one of two independently
confirmed run kinds:

```text
account_research -> exact selected accounts -> entity_research_job rows
contact_research -> exact selected contacts -> entity_research_job rows
```

Both use the existing `fleet_task`, `work_lease`, and `LeasedWorkWorker` machinery through one
`ENTITY_RESEARCH_JOB` task kind and one `EntityResearchJobWorkHandler`. There is no account fleet
and contact fleet duplication. The immutable run/job rows retain the exact workspace, project,
product, project run, selection, subject, parent account, profile digest, checkpoint thread,
priority, budget reference, and budget cap authorized by R0.

The database checks the canonical lifecycle/authorization JSON against its indexed scope columns.
An exact launch replay is a no-op; a changed cap, lifecycle, subject set, checkpoint set, or other
authority conflicts instead of widening the existing run.

## 2. Durable state and atomic transitions

Migration `022b1154b3aa` adds:

- `entity_research_run` — separate scope, cap, concurrency, aggregate state;
- `entity_research_job` — exact subject authorization, budget, checkpoint, lease, wait, terminal;
- `entity_research_job_wait` — one active external wait with exact checkpoint/state digest;
- `entity_research_job_finalization` — one immutable accepted R0 finalization receipt; and
- `entity_research_job_event` — append-only observation of every lifecycle transition.

The transition contract is:

```text
QUEUED -> LEASED -> RUNNING
                       |-> WAITING_EXTERNAL -> exact wake -> QUEUED
                       |-> TERMINAL with accepted finalization receipt
QUEUED/RUNNING/WAITING_EXTERNAL -> TERMINAL with accepted cancellation receipt
```

An external wait persists its checkpoint, changes the domain job, and finishes the owning fleet
task in one database transaction. The worker slot and generic lease are then released. An exact
wake reopens that same task and resumes the same checkpoint thread; duplicate callback delivery is
idempotent.

Finalization changes the job and owning task atomically. Cancellation changes every requested job,
wait marker, and fleet task atomically, rewrites suspended task observation to `cancelled`, and
revokes any in-flight generic work lease. A terminal job cannot be woken or re-enqueued.

## 3. Fencing, concurrency, budgets, and observation

Every mutable job write proves all three identities:

1. the domain job records the current worker and generation;
2. the exact `fleet_task` remains claimed by that worker; and
3. the matching `work_lease` generation is still live.

This closes stale-worker writes after cancellation, expiry, task takeover, or crash. Account and
contact runs choose independent concurrency limits while sharing the same admission code. Each job
has its own budget envelope/cap and each run has a distinct run-wide cap. Atomic provider budget
reservation and settlement remain R9-owned; R2 neither spends nor invents an interim budget path.

Run aggregation and the append-only job event stream expose queued, active, waiting, cancelled,
and final states without inspecting model prose. Only an immutable, verified
`ResearchFinalizationReceipt` creates a terminal outcome.

## 4. Composition and R1 boundary

`build_multi_work_worker()` now accepts one optional `entity_research_handler`, so project runs,
recipe graphs, account research, and contact research can drain through the same leased worker.
The production boot deliberately does not pass that handler yet: R3 must supply its exact
LangChain `create_agent()` driver. Therefore R1's `entity_research_agent_not_composed` quarantine
remains the live new-run behavior, and no old preparer/orchestrator has been restored.

## 5. Executable exit-gate evidence

The focused R0–R2 suite proves:

- account and contact runs are launched and scoped separately but create one shared task kind;
- exact replay creates no duplicate run, job, task, or event;
- per-run and per-job caps remain distinct and immutable;
- per-run concurrency admission is enforced without losing the second job's exact scope;
- external wait releases fleet ownership and exact wake resumes the retained checkpoint;
- stale task/lease fences cannot checkpoint or finalize;
- partial run cancellation is rejected before mutation;
- exact cancellation terminalizes queued, running, and waiting jobs, revokes leases, and prevents
  callback resurrection;
- account/contact terminal state requires an accepted engine receipt; and
- migration upgrade -> downgrade to the previous head -> upgrade passes on a fresh disposable
  database, including enum and table removal/recreation.

Verification commands:

```text
.venv/bin/pytest -q tests/fleet/test_entity_research_r2.py \
  tests/fleet/test_entity_research_r2_db.py \
  tests/fleet/test_entity_research_r2_migration.py \
  tests/fleet/test_work_worker.py tests/api/test_fleet_wiring.py \
  tests/api/test_m8d_r1_entity_research_quarantine.py \
  tests/unit/core/test_entity_research_r0_contracts.py
```

The focused battery passed. The wider `tests/fleet` run also passed all R2 and existing fleet tests
except the already-recorded shared-database `core.work_email` field-definition drift in
`test_b4_composed_run_db.py`; that fixture failed before entering fleet execution and is unrelated
to R2.

## 6. Exit decision

R2 is accepted. Account and contact jobs now share one durable queue/lease/checkpoint/wait shell
while remaining separately launched, scoped, budgeted, cancelled, observed, and finalized. R3 may
compose the role-configured `create_agent()` runtime onto this handler without changing the fleet.
