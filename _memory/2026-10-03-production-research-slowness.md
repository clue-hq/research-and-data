# 2026-10-03 — Why the first production account research ran slowly

Observed on the first production research run (worker VM `40.160.37.148`, OVH, Warrenton VA;
Railway Postgres; Cloudflare R2). Nothing was changed in production; this is a diagnosis record.
Fixes are proposed below, not implemented.

## The run

- Project "Start Garner Health ABM", run `8e80c2c7-2492-5124-ae7e-0c5248caeab1`, launched from a
  chat message at 15:23:53 UTC ("please proceed with doing deep research on these two contacts",
  tagging Mortenson and McKee Foods).
- Two account jobs, both started 15:25:07 UTC:
  - McKee Foods — job `20ea09fe-b447-5931-a2b1-265154c4b792`, worker container `vm-batch2-1`.
  - Mortenson — job `edce35a5-eb73-5392-8854-4fcbd00a49ea`, worker container `vm-batch3-1`.
- Ten person jobs (five per account) created at committee nomination. Mortenson's five started
  16:05 UTC after its account job reached claim import; McKee's were still `not_started` at 16:10.
- Langfuse trace (both jobs and the chat turn share it):
  `df90b7ebcd28d5b6489e4e6f830761fc`, named `account-research.turn`, environment `default`.

## Timeline (Mortenson; McKee within a few minutes of it)

| Stage | From → to (UTC) | Duration |
|---|---|---|
| 1. Researching (evidence gathering) | 15:25 → 15:48 | ~23 min |
| Buying committee nominated (5 people) | 15:49 → 15:50 | ~1 min |
| 2. Compiling findings (`save_dossier_section`) | 15:50 → 16:02 | ~12 min |
| 3. Storing claims (`finish_dossier`, finding import) | 16:02 → still running at 16:10 | — |

At 38 minutes in, wall-clock time split (union of intervals from the worker logs):

| | McKee | Mortenson |
|---|---|---|
| Model calls (`model_call_usage.duration_ms`) | 9.8 min | 9.9 min |
| Tool execution (`toolbelt.*_completed.duration_ms`) | 9.0 min | 9.1 min |
| **Neither — waiting** | **19.1 min** | **18.9 min** |

Paid providers were not the cost: Exa page fetches ~0.13 s each, Exa search ≤4 s, one Exa
deep-reasoning report ~40 s per job, AI Ark ≤1 s. Model calls averaged ~10 s (Grok 4.6).

## What was wrong (causes of the slowness)

### 1. A new R2 connection for every storage call
`libs/clue-storage/clue_storage/s3.py:42-58` — `_client()` builds a new `aioboto3.Session()` and
client on every `put`/`get`/`exists`/`delete`/`list`, so every call pays client construction plus
a fresh TCP + TLS handshake to Cloudflare.

Measured from inside `vm-batch3-1` (read-only calls against the production bucket):
`exists` on a missing key 721 ms first, then ~190–230 ms; `exists` ~190–200 ms; `get` of a small
dossier artifact ~200–455 ms. The database through pgbouncer measured 3.3 ms median for
`select 1`, so the database link is not the problem — R2 is.

Locally the storage backend is the filesystem (<1 ms), which is why dev never showed this.

### 2. Evidence recording holds an account-wide lock across R2 calls
`platform/api/clue_api/arv2/quality_evidence.py` `persist_source` (from line 111):
- takes `SELECT … FROM arv2_evidence_manifest … FOR UPDATE` (line ~166) — one row per
  (workspace, run, account), so every evidence write for the account serialises on it;
- then, inside the same transaction, runs `storage.put` to R2 (line ~191) and, when an
  `original_key` exists, `read_verified_artifact` — an R2 `get` plus hash check (line ~202);
- an already-recorded source re-reads its body from R2 too (`_body`, line ~181).

Each `arv2.evidence_recorded` landed ~600–700 ms after the previous one, strictly one after
another. Mortenson recorded 344 items and McKee 327 — roughly 3.5–3.7 minutes of serialised
recording per job.

The serialisation shows up in Langfuse. Round at 15:40:00 (Mortenson): five
`acquire_research_evidence` tool calls started together at 40:00.13, but their inner
`governed.acquire_research_evidence@1` spans started at 40:18.8, 40:19.7, 40:25.7, 40:26.8 and
40:28.0 — 18–28 s of queueing, about one per second. One tool's governed work ended at 40:33.9
and the tool returned to the agent at 40:56.4, 22 s later. A `fetch_page` whose Exa call took
0.13 s took 4.4 s end to end (the rest was recording). The largest idle gaps in the job were
20–40 s each, all on tool admission or tool hand-back.

In dev each critical section is about a millisecond, so parallel tools never visibly queue.

### 3. Claim import is one finding at a time inside one long transaction
After `finish_dossier` (16:02:24), Mortenson imported findings at ~2.5 s each (67 imported by
16:05:12; `arv2.dossier.finding_imported`, emitted from
`platform/api/clue_api/arv2/dossier_import.py:350`, each with a `claimstore.quality_assessed` and
`arv2.evidence_disposition`). A `pg_stat_activity` sample showed a `clue_worker` transaction
`idle in transaction` for 145–151 s whose last statement read an `artifact` row — i.e. the import
held one transaction open while it did non-database work (R2 reads) between statements.

### 4. Every model call resends a large and growing context
Prompt size reached ~176,000 tokens per call by the dossier stage (mostly cached; ~10¢ per call)
and grows ~2k tokens per call. This explains much of the ~10 min of model time; it would be
the same locally. Product decision, not an infrastructure defect.

## Other problems observed on the same run (not causes of the slowness)

- **Langfuse cannot return the trace**: `GET /api/public/traces/<id>` → 422
  `Observations in trace are too large: 100.16MB exceeds limit of 100.00MB`. Each generation
  stores its full ~176k-token prompt, and both jobs plus the chat turn share one trace (the fleet
  task inherits the launching turn's trace). Paged observation reads hit 429 rate limits. The UI
  is likely slow or partial for this trace.
- **Production traces are filed under environment `default`**, and ~1,195 of ~1,200 traces that
  day were FastAPI web-request traces (`GET /auth/v1/session`, principal, page polls). The trace
  also carries 81 raw httpx `POST` spans duplicating `provider.http_attempt`.
- **Job counters stay at zero while running**: `arv2_research_job.model_rounds`, `tool_calls`
  and `cost_usd` read 0 until the job finishes, so the database gives no live progress; only the
  worker logs and Langfuse do.
- **A handled evidence refusal is logged at error level with a traceback**: McKee's
  `search_evidence` failed five times (15:36, 15:44) because the agent passed a source reference
  that is neither a UUID nor an `/evidence/…` path. `resolve_source`
  (`quality_evidence.py:~403`) correctly raises `EvidenceUnavailable("Invalid source reference;
  read <index>")` and the agent repaired, but `toolbelt.search_evidence_failed` is logged at
  `error` with the `ValueError` traceback — noise of the same class as the PreconditionFailed
  Sentry issue (CLUE-PRODUCTION-3).
- **Langfuse warning on every agent model**: "Langfuse was not able to parse the LLM model" —
  generations are recorded without a model name, so Langfuse cannot price them itself.

## Proposed fixes (not started; need sign-off)

1. **One long-lived S3 client per storage backend** (`s3.py`): create the aioboto3 client once
   and reuse it (keep-alive), closed at shutdown. Expected to take R2 calls from ~200 ms to tens
   of ms — to be measured, not assumed.
2. **Upload before locking** in `persist_source`: the artifact key is the content hash, so the
   R2 `put` (and the `original_key` verification read) can happen before the manifest
   `FOR UPDATE`; the lock then covers only the database writes, and parallel tools stop queueing.
3. **Claim import**: read the needed artifacts concurrently before the transaction, or in
   bounded concurrent batches, instead of one R2 read per finding inside a long transaction.
4. (Separate) Langfuse scope and per-task traces — already in progress on
   `obs/agent-scoped-tracing`; that work also addresses the 100 MB trace.

Expected effect of 1–3: most of the ~19 min of waiting and part of the ~9 min of tool time per
job; model time (~10 min) is unchanged. An estimate only.

## How to re-measure (owed: before/after numbers for fixes 1–3)

- Worker log split: `sudo docker logs --since 3h vm-batch3-1 2>&1 | jq -cR 'fromjson? |
  select(.fleet_kind=="arv2_account_research")' > /tmp/x.jsonl`, then take the union of
  `model_call_usage` intervals (`timestamp - duration_ms`) and `toolbelt.*_completed` intervals;
  the remainder is waiting.
- R2 latency: from a worker container, time `storage_from_settings(load_settings()).exists(key)`
  over a few calls.
- Lock/transaction pressure: sample `pg_stat_activity` for `state='idle in transaction'` and
  `wait_event_type='Lock'` during a parallel evidence wave (the 16:05 sample was taken during
  claim import, when no parallel wave was running, so it showed no lock waits).
- No local timing baseline was ever recorded in `_memory/`, so "faster locally" is the founder's
  observation, not a measured comparison. Record one on the next local run.

## Confirmation, 16:40 UTC — the queueing is real, and the lock is a different one

Sampled production while all ten person jobs ran (Mortenson's account job had completed at
16:17:45 after ~53 min; McKee's account job ended `needs_review`, `failure_code=workspace_conflict`,
at 16:32:33 — not yet investigated).

- **Every sample had lock waits** (236/236 over 60 s, ~58 waiters per sample, one wait of 280 s).
  Waiters sit in `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`.
- **One hot key**: `pg_locks` advisory key `5898789434722834039` = `hashtextextended(
  'agent-project-artifacts:ws_0503532073454a10ab541c3fa9bf3e81:prj_92c55a86e82859a1ba0e655fb8c9894b',0)`
  — a lock over the **whole project** (`platform/api/clue_api/agent_turn_wiring.py:289`, inside
  `DurableAgentArtifactStore.persist_body`). Up to 14 transactions queued on it at once; every other
  granted advisory lock's holder was itself waiting on this one. (Method checked: reconstructing
  `classid<<32|objid` from `pg_locks` reproduces `hashtextextended` for a probe key.)
- **Who holds it**: over 45 s, ten different `clue_worker` transactions took turns, each holding it
  3–18 s, almost always `idle in transaction` with last statement
  `INSERT INTO artifact_derivation …` (107 samples) or `INSERT INTO agent_artifact_project …` (21),
  idle up to ~1 s at a time (consistent with R2 calls between statements). So the project lock is
  being held inside longer evidence/page-writing transactions, not only for `persist_body`'s few
  inserts. The exact code path that puts the project lock and the evidence writes in one
  transaction is **not yet pinned** — `fleet_main.py` builds the store with `conn_factory=transaction`
  (its own transaction), and no borrowed-connection store was found in the arv2 path on a first
  read. `quality_pages.publish_page` writes `agent_artifact_project` without the lock, so it is not
  the holder. Pin this first in the fix (e.g. `application_name` per code path, or log lock
  acquisition).
- **A second, in-process queue**: `platform/api/clue_api/arv2/account_research_driver.py` gives the
  agent's tools the driver's own guarded factory — "at most one data connection at a time (the O3
  `_db_lock`)" (module docstring; `_connection`, line ~907). Every tool's database work in one job,
  including transactions that wait on R2, runs behind one `asyncio.Lock`, so a job's parallel tools
  are serial. This, not the evidence-manifest `FOR UPDATE`, is the likeliest cause of the 18–28 s
  admission stagger seen at 15:40; the manifest lock was not observed contended.
- Also seen: one transaction 317 s old on `UPDATE artifact SET expires_at=LEAST(…)`.

Revised fix order: (1) one R2 client per process; (2) no R2 call inside any transaction that holds
a shared lock (project artifact lock, job `_db_lock`, manifest lock) — upload content-addressed
bytes first, then do the short DB transaction; (3) narrow the project-wide
`agent-project-artifacts` lock (it exists to serialise against project erasure; a per-artifact or
shared/exclusive scheme would let writers run in parallel); (4) revisit the single-connection
`_db_lock` once R2 is out of the critical sections; (5) claim import concurrency.

## McKee's failure (16:32 UTC) — not slowness, a finalize ordering bug

Job `20ea09fe…` ended `needs_review`, `failure_code=workspace_conflict`, after 74 model calls,
215 tool calls and $7.97. Chain, from the worker log and code:
1. 15:36 and 15:44 — five `search_evidence` calls failed (bad source reference; the refusal itself
   is correct). The earlier note called these harmless; they were not.
2. 16:26:21 — `finalize_turn` refused: called in the same batch as other tools.
3. 16:26:49 — `finalize_turn` refused: "Unresolved failed tool attempts remain:
   agent_search_evidence_… (5). Correct using retry_of, or finalize with an honest blocked status."
   That check lives in `agent_execution_wiring.py` `finalize()` (~line 2101) and runs **after**
   `agent_runtime_wiring.py` `finalize_turn` has already run the completion guard (wrote
   `outputs/research.json`) and `snapshot_outputs(empty_after=True)` (~line 1348), which freezes
   and empties `outputs/` and sets `_outputs_snapshotted`.
4. 16:30–16:31 — the agent repaired all five (`agent.tool_recovered` ×5), as told.
5. 16:32:32 — the next `finalize_turn` ran the completion guard
   (`quality_research_wiring.py:~1045`), which writes `outputs/research.json` again →
   `WorkspaceConflict("snapshotted outputs are immutable")` (`clue_agents/workspace.py:583`) →
   `agent.runtime_failed` → job contained as `workspace_conflict`.

So any refusal raised after the snapshot makes the very repair it asks for impossible. Fix: run
every refusable check (unresolved failures, batch rule) before the completion guard and the
snapshot, or don't snapshot until nothing can refuse. Claims were already imported
(`quality_state: provisional`, 35 qualified), so the research is not lost — the job just never
completed.

The 317 s transaction on `UPDATE artifact SET expires_at` is from `arv2/media_store.py:284`
(`subjects`, person-job media). Not yet explained: the media download itself runs outside the
transaction, so it was most likely waiting on a lock held by another job. Unconfirmed.
