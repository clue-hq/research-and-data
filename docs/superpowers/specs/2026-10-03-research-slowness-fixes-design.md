# Research slowness fixes — design

**Status:** draft for founder review (2026-10-03). Design agreed in chat the same day; this file is
the written spec. One PR on branch `perf/research-slowness-fixes`.

**Evidence:** `_memory/2026-10-03-production-research-slowness.md` (diagnosis and production
measurements) and `_memory/2026-10-03-first-production-research-quality-review.md` (quality review,
the stuck person jobs). Every number below was measured in production on run
`8e80c2c7-2492-5124-ae7e-0c5248caeab1` unless it says otherwise.

## 1. Goal

Research jobs take 50–70 minutes in production, of which about 10 minutes is model work. Make the
waiting go away **without changing what the research produces** and **without weakening any
existing guarantee** (content-addressed artifacts, erasure/DSAR safety, idempotent retries).

Also fix one correctness bug found on the same run: a refused `finalize_turn` can make the agent's
own repair impossible (McKee's job ended `needs_review` for this reason).

**Success, measured in production after deploy** (the same method as the diagnosis note):

1. For an account or person job, wall time minus model time minus tool time ("waiting") is under
   10% of wall time (today ~50% for accounts, ~90% for persons).
2. No advisory-lock waits longer than 1 second in a 60-second `pg_stat_activity` sample taken while
   at least 8 research jobs run (today: waits in every sample, the longest 280 s).
3. No fleet task sits `claimed` without its handler running (today: two person jobs claimed for
   50+ minutes while another worker was idle).
4. A refused finalize followed by the requested repair finishes the job (today: `needs_review`).
5. `artifact_derivation` rows written per research artifact are written in one statement, not one
   per parent.

## 2. What we measured (summary)

| Finding | Where | Effect |
|---|---|---|
| A new S3 client and TLS connection for every storage call | `libs/clue-storage/clue_storage/s3.py` `_client()` | ~200 ms per R2 call from the VM (database: 3 ms) |
| Every research artifact save takes the project-wide lock, uploads to R2 and inserts one derivation row per evidence source, all inside one transaction | `platform/api/clue_api/quality_research_artifacts.py` `ResearchArtifacts.persist_body`, which calls `DurableAgentArtifactStore.persist_body` (`agent_turn_wiring.py:236`) on the same transaction | Lock `agent-project-artifacts:{ws}:{project}` held 3–18 s per save; up to 14 transactions queued on it; 280 s waits; all jobs in a project serialise |
| One derivation row per (artifact, evidence source) | same | 1,169,646 rows, 759 MB for one day's research in one workspace; up to 1,835 parents per artifact; each save gets slower as evidence grows |
| Evidence saving uploads to R2 under the account-wide manifest lock | `platform/api/clue_api/arv2/quality_evidence.py` `persist_source` | ~650 ms per evidence item, strictly serial |
| Claim import reads sources from R2 one finding at a time inside one transaction | `arv2/dossier_import.py` → `resolve_source` / `submit_proposal` (`arv2/quality_claims.py`) | ~2.5 s per finding; one transaction open 150 s |
| A worker claims up to 10 tasks but runs at most 4 research jobs | `platform/fleet/clue_fleet/work_worker.py` `drain_once` vs `arv2/account_research_driver.py` `self._jobs` semaphore | Tasks held but not run while another worker is idle |
| A job's tools share one database connection behind one lock | `arv2/account_research_driver.py` `_connection` / `_db_lock` | "Parallel" tools run one at a time |
| `finalize_turn` freezes and empties `outputs/` before a check that can still refuse | `agent_runtime_wiring.py` `finalize_turn` (snapshot ~line 1348) → `agent_execution_wiring.py` `finalize` (unresolved-failure check ~line 2101) | The repair the refusal asks for crashes with `WorkspaceConflict` |
| Lock waiters occupy pgbouncer's 20 server connections | `/srv/clue/pgbouncer.env` `DEFAULT_POOL_SIZE=20` | Unrelated transactions queue inside pgbouncer during contention (inferred; pgbouncer stats are not readable today) |

Not a cause: CPU (workers at 4–24% on an 8-core VM), the database link (3 ms), paid providers.

## 3. Design

Each part is independent and testable on its own. Parts 1–3b remove the waiting; part 4 is a
deliberate non-change, measured; part 5 removes
the hoarding; part 6 is the correctness bug; part 7 is connection capacity and visibility; part 0
gives us the numbers to judge the rest.

### Part 0 — Measure lock-holding sections

A small helper times a critical section and logs one structured line when it ends:
`db.critical_section` with `name`, `held_ms`, and `statements` (when cheap to count). Wrap:
`ResearchArtifacts.persist_body`, `DurableAgentArtifactStore.persist_body`, `persist_source`, and
the dossier import transaction. Log at `info` only when `held_ms` exceeds a threshold
(`CLUE_DB_CRITICAL_SECTION_LOG_MS`, default `500`, added to `.env.example`), so normal operation
stays quiet.

This is how success criteria 1–2 are checked after deploy, and how part 4's decision is made.

### Part 1 — One S3 client per storage backend

`S3Storage` keeps one long-lived `aioboto3` client:

- Created on first use under an `asyncio.Lock`, bound to the event loop that created it. A call on
  a different loop (tests) creates that loop's own client; the backend never shares a client across
  loops.
- Reused by `put`, `get`, `exists`, `delete`, `list_blobs` and `presign`.
- Closed by a new `async close()` on the backend, called from the process shutdown paths that
  already close the database engine (fleet worker, API lifespans).
- Rebuilt once, transparently, if a call fails with a connection-level error (not a 404 and not an
  access error); a second failure surfaces as today's `StorageError`.
- Connection pool size from `CLUE_STORAGE_S3_MAX_POOL_CONNECTIONS` (default `50`) via botocore
  `Config(max_pool_connections=...)`, added to `.env.example`.

The module docstring's reasoning ("snapshot traffic is low volume, per-call setup is noise") is no
longer true and is rewritten.

**Tests:** a stub client factory counts client creations — N calls create 1 client; a simulated
connection reset rebuilds once; `close()` closes it; two event loops get two clients. A timing check
against real R2 is part of the post-deploy measurement, not CI.

### Part 2 — Research artifact saves: short, shared, batched

Three changes, all keeping the storage rule "record the artifact row before the blob upload; the
row lock serialises writers against erasure":

**2a. The project lock becomes shared for writers.** The lock
`agent-project-artifacts:{workspace}:{project}` exists so project erasure (`agent_turn_wiring.py`
~1797 and ~1829) cannot race a new binding. Writers in `DurableAgentArtifactStore.persist_body` take
it with `pg_advisory_xact_lock_shared`; the two erasure sites keep the exclusive
`pg_advisory_xact_lock`. Writers never block each other; erasure still excludes every writer.

**2b. The upload leaves the transaction.** Today `ResearchArtifacts.persist_body` hands the inner
store its own open connection (`same_transaction`), so the inner store's upload — normally after its
commit — runs inside the outer transaction while the project lock is held. Change: the outer method
records everything in its transaction and returns; the upload happens after that transaction
commits, exactly as the plain `DurableAgentArtifactStore.persist_body` already does ("the row is
committed before external storage mutation; a crash here is body-unavailable and fail-closed; retry
converges on the same content-addressed key"). The inner store gets a variant of `persist_body` that
records without uploading, so both paths share one implementation of the recording.

**2c. Derivation edges in one statement.** The per-parent loop of
`INSERT INTO artifact_derivation ... ON CONFLICT DO NOTHING` becomes one
`INSERT ... SELECT :ws, unnest(:parents), :key ON CONFLICT DO NOTHING`. Same rows, one round trip
instead of hundreds.

The number of derivation rows does not change in this PR (see §5, follow-up 1).

**Tests (real Postgres, throwaway DB):**
- Two concurrent research saves in the same project both proceed while each holds the shared lock
  (neither waits on the other); a project erasure waits for both and then excludes a third.
- The upload happens after commit: a storage stub that records whether a transaction is open at
  `put` time sees none.
- A crash between commit and upload leaves the row without a blob, and a retry of the same bytes
  converges (the existing fail-closed behaviour, now covered for the research path).
- Derivation rows written are identical to today's for a fixture with 300 parents, in one statement.

### Part 3 — Evidence saving: the account-wide lock covers only the final writes

In `persist_source` the account-wide manifest lock (`SELECT ... FOR UPDATE` on
`arv2_evidence_manifest`) moves from the start to the end, around the two statements that need it:
the revision increment and the `arv2_evidence_source` insert. The artifact row is still recorded
before the upload (per-key row lock, unchanged), and the upload and the `original_key`
verification read happen before the manifest lock is taken.

The early "already recorded?" check stays before the work, and the final insert becomes
`ON CONFLICT (source_id) DO NOTHING` followed by a re-read, so two concurrent saves of the same
source converge on one row and one revision (today the lock prevents that race by serialising
everything).

**Tests:** concurrent saves of different sources for one account overlap their uploads (a storage
stub with a 200 ms delay; total time well under N × 200 ms); concurrent saves of the same source
produce one row; revisions stay gap-free and strictly increasing in commit order.

### Part 3b — Claim import reads its sources before the transaction

`import_research_dossier` (`arv2/dossier_import.py`) runs one transaction for the whole dossier,
and for every finding `resolve_source` / `submit_proposal` (`arv2/quality_claims.py`) read the cited
sources from R2 with `read_verified_artifact` inside it — one at a time, ~2.5 s per finding, the
transaction open for minutes.

Change: before the transaction opens, collect every source the dossier cites and fetch their bytes
concurrently (bounded by `CLUE_ARV2_IMPORT_PREFETCH_CONCURRENCY`, default `8`, added to
`.env.example`) into an in-memory map keyed by storage key. Inside the transaction, the verified
read keeps every row check (row present, same workspace, not erased/expired/purged, digest and size
match the bytes) but takes the bytes from the map instead of R2. A key missing from the map — not
expected — falls back to today's direct read. The transaction stays one all-or-nothing unit.

**Tests:** a dossier citing 40 sources with a 200 ms storage stub imports in well under 40 × 200 ms;
an artifact erased between prefetch and transaction is still refused (the row check runs inside the
transaction); a digest mismatch in the prefetched bytes is still refused.

### Part 4 — The per-job connection: keep it, measure it

The research driver's rule — one database connection per job, behind `_db_lock` — stays. It bounds
each job to one connection, which keeps pgbouncer demand predictable (§3 part 7). After parts 1–3
the work inside that lock is database-only.

Part 0's log tells us how long tools wait for it. **Only if** the post-deploy measurement shows
tool waits on `_db_lock` above 10% of wall time do we change it, as a follow-up, to a configurable
per-job limit (`CLUE_ARV2_JOB_MAX_DB_CONNECTIONS`, default 1). No code change to it in this PR.

### Part 5 — A worker claims only what it can start

Each work handler may declare `max_in_flight: int | None` — how many tasks of its kind one process
runs at once. `drain_once` skips a kind whose local in-flight count has reached its limit and moves
to the next kind (the round-robin is unchanged); a slot that finds nothing claimable sleeps as
today. The in-flight count is incremented before `claim_next` and released when the task finishes
or the claim comes back empty.

The ARV2 research handler declares `max_in_flight = settings.arv2_account_max_parallel_jobs`. Its
internal semaphore stays as a backstop and, by construction, never waits.

This makes concurrency a deliberate setting rather than an accident of two numbers:
`CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS` is how many research jobs one process runs, and
`CLUE_FLEET_WORKER_CONCURRENCY` is how many tasks of all kinds it runs. The `.env.example` comments
for both say so, and the runbook states the fleet-wide research capacity
(batch workers × research limit; today 3 × 4 = 12).

**Tests:** one worker, concurrency 10, research limit 4, six research tasks queued — it claims
exactly 4; a second worker claims the other 2. A worker at its research limit still claims a
display-page task. A failed task releases its slot.

### Part 6 — Finalize refuses before it freezes outputs

`finalize_turn` (`agent_runtime_wiring.py`) runs, in order: the required-output check, the
completion guard (which writes `outputs/research.json`), artifact persistence, then
`snapshot_outputs(empty_after=True)` (freezes and empties `outputs/`), and only then
`AgentExecution.finalize`, which can still refuse ("Unresolved failed tool attempts remain").

Change: every check that can refuse runs before the completion guard and before the snapshot. The
execution adapter gains `check_finalizable(status)`, which runs the unresolved-failure check;
`finalize_turn` calls it first. `finalize` keeps the same check as a backstop (it can no longer fire
after a passing pre-check within the same turn, because nothing between them creates a failed
attempt).

**Tests:** reproduce McKee's sequence — a failed tool attempt, a `finalize_turn(completed)` that is
refused, a `retry_of` repair, a second `finalize_turn(completed)` — and assert the job completes,
`outputs/research.json` is written once by the second call, and no `WorkspaceConflict` occurs. A
refused finalize leaves `outputs/` untouched.

### Part 7 — Connection capacity and visibility

- **App pool settings made explicit.** `clue_db.create_engine` reads `CLUE_DB_POOL_SIZE` (default
  `5`), `CLUE_DB_MAX_OVERFLOW` (`10`) and `CLUE_DB_POOL_TIMEOUT_S` (`30`) — today's library defaults,
  now visible — from the environment (the existing `clue_db` contract reads env directly), added to
  `.env.example`.
- **pgbouncer visibility.** A read-only stats user is added (`STATS_USERS`) so `SHOW POOLS` shows
  clients waiting for a server connection. The runbook (`docs/deploy/runbook.md`) gets the check.
- **pgbouncer pool 20 → 40, after parts 1–3 are deployed.** Postgres allows 200 and the Railway
  services use about 10. Raising it before the lock fixes would only let more transactions wait on
  the same lock. This is an operator change to `/srv/clue/pgbouncer.env`, documented in the runbook
  with the order: deploy, measure, then raise.

## 4. Rollout

One PR to `research-streaming`, then a release to `main`. The VM deploy restarts the workers, so
deploy when no research is running (a running job is interrupted and retried). After deploy, a
founder-triggered research run on one account plus its committee is measured with the diagnosis
note's method against success criteria 1–5. This spends money and is the founder's to start.

No database migration.

Later (not in this PR): VM deploys move to a scheduled maintenance window, so worker restarts never
interrupt research by surprise. Recorded in the follow-up note.

## 5. Out of scope — follow-ups

1. **The derivation data model.** Every research artifact records one edge to every evidence source
   of its account (1.17M rows in a day). Erasure cascades walk these edges, so changing the model
   changes DSAR semantics and needs its own design. This PR only makes the writes one statement.
   The follow-up PR is described in `_memory/2026-10-03-follow-up-pr-artifact-derivation.md`.
2. **Recording unread search results.** About 89% of recorded sources were never read by the agent.
   Recording lazily changes the evidence model; parts 1–3 make each recording cheap meanwhile.
3. **More, smaller worker processes.** Decide from part 0's numbers and process CPU after deploy.
4. **The per-job connection limit** (part 4), only if measured.
5. **Committee nomination on an unverified identity** and **mis-pointed citations** (quality review).
