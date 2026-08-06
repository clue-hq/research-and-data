# M8D R9 — Parallel execution and external-wait hardening acceptance

**Status:** accepted 2026-08-06
**Roadmap authority:** `M8D-entity-research-agents-and-shared-fleet-refactor-roadmap.md`, R9

## 1. Accepted boundary

R9 hardens the shared account/contact `create_agent()` runtime around one model-proposed tool
wave. It does not add provider-specific judgment to the fleet. The entity agent still chooses
semantic tools; the engine proves dependency, field partition, budget, provider-capacity, replay,
and exact job authority before any provider-capable handler runs.

Independent Exa and Sumble calls may run concurrently. An additive follow-up carrying parent
operation lineage, coverage/finalization decisions, reveal-before-validation, and overlapping
field work without explicit corroboration authority remain sequential. Distinct selected contact
facets may share one wave; duplicate provider work and duplicate facet partitions may not.

## 2. Atomic admission and complete result joining

Provider-capable tool bindings now carry engine-only admission metadata: provider family,
worst-case budget reservation, rate-limit policy reference, and provider concurrency limit. Model
arguments cannot set or override those values. Production account and contact definition
composition fails closed if its provider actions omit them.

`DbEntityResearchToolBatchCoordinator` admits an entire model wave in one short transaction. It
locks the exact running job and research run, serializes each provider-rate policy, and checks:

- the entity-agent concurrency cap;
- complete and stable provider admission metadata;
- job and run spent cost plus all active reservations plus the whole proposed wave;
- active provider permits and one stable concurrency policy;
- subject-axis field authority and disjoint field partitions;
- duplicate provider work, dependency lineage, and facet partitioning; and
- an immutable, content-addressed batch identity tied to the exact agent turn.

No member dispatches if aggregate admission fails. A settled provider result is joined only for
the same job, target, semantic tool, exact input digest, and unchanged provider authority.
Engine-state reads, coverage, and other internal tools are deliberately never joined across
turns, because their identical arguments can observe newer claim or coverage state.

## 3. Partial completion, crash, and wait/resume

Each batch member has append-only completion, wait, or failure evidence. A completed sibling is
persisted before its result returns to the agent. If another member waits externally, the runtime
waits for every sibling to reach a durable disposition, writes one composite wait over the exact
member wait references, checkpoints the agent, and releases the worker slot.

Cold resume can begin directly at LangGraph's persisted tool node, without re-running the model
node. The middleware reconstructs the exact persisted model wave and idempotently re-runs the
same account/contact parallel guard and atomic admission before any resumed handler. A fresh turn
then:

- returns completed provider siblings from their durable result;
- reuses an outstanding exact reservation and active permit after a process crash;
- creates a fresh permit, but not a second reservation, when polling a previously waiting
  operation whose first permit was released;
- treats a pure replay/resume wave as previously admitted exposure, so settlement folded before
  the terminal tool event cannot be double-counted against the active reservation;
- settles each reservation once; and
- cannot submit or charge the already-caused provider operation again.

The composite wake service marks member notifications durably and wakes the R2 job only when all
members are ready and the job still owns that exact composite wait. The R9-composed job store also
reconciles immediately after persisting an R2 wait, closing the callback-before-job-wait race.
Duplicate callbacks are no-ops, and a terminal job cannot be resurrected.

## 4. Durable schema, privacy, and production composition

Migration `0070930672a4` adds immutable batch, member, budget-reservation, provider-permit,
member-event, release, composite-wait, and wait-member ledgers. Database checks bind every batch
to the exact running job, agent turn, run, workspace, subject type, and target. History is
append-only; only composite wait readiness/resolution is mutable.

Joined result payloads can contain complete account/contact projections. R9 therefore indexes
every duplicated account/contact subject, including contacts nested in an account committee
result. Contact erasure performs the existing one-way journal/checkpoint cleanup and also redacts
every indexed R9 result payload. The immutable result digest remains as audit evidence, while
replay excludes erased payloads and fails closed.

Both `build_account_research_fleet_composition()` and
`build_contact_research_fleet_composition()` install the same provider-neutral coordinator and
callback-race-safe R2 job store. The shared fleet remains free of Exa/Sumble branches.

## 5. Acceptance evidence

Verification ran on the disposable `clue_roseau_r9_20260806` Postgres database.

- Five dedicated R9 cases passed: aggregate budget rejection before handler dispatch; actual
  concurrent Exa/Sumble boundaries; partial completion plus composite wait; early callback and
  cold Postgres-checkpoint resume; crash admission reuse; provider-limit enforcement; stale-read
  prevention; dependency/overlap rejection; distinct contact facets; and nested-contact DSAR.
- The focused R0–R9 plus retained M8C C4–C6 matrix passed **159 tests**.
- The R9 migration passed `head -> 7bb3178d7580 -> head`; Alembic reports the single head
  `0070930672a4`.
- Repository mypy passed **565 source files**.
- Import-linter kept all **24 contracts**, with none broken.
- Scoped Ruff, format, and diff checks passed.

Failures discovered and corrected during live-Postgres acceptance included an ambiguous replay
join, missing tool-node cold-resume admission, zero-cost settlement caused by persisting the
LangChain `ToolMessage` wrapper instead of its semantic JSON, stranded crash admissions, stale
internal-tool replay, the provider-callback-before-R2-wait race, and resume rejection caused by
double-counting early-folded spend plus its already-admitted reservation.

## 6. R10 boundary

R9 made no internet request and no paid provider call. Its acceptance uses deterministic provider
boundaries through the real `create_agent()` runtime, Postgres checkpoint, queue/lease, batch,
wait/wake, cost-reservation, replay, and DSAR plumbing. R10 owns credentialed Exa/Sumble account
and contact canaries, provider-side receipt/spend evidence, historical replay retention, final
cutover, and unreachable compatibility-code deletion.

## 7. Exit decision

R9 is accepted while the recorded gates remain green. Independent Exa/Sumble work is admitted and
executed concurrently; dependent follow-up remains sequential; completed siblings survive an
external wait; and a fresh process resumes without duplicating the settled call, reservation,
permit, or spend.
