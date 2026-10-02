# Lane 3 slice 1b — every provider call on the Postgres ledger — design

**Status:** approved in chat 2026-09-14 (decisions D1–D3 below). Parent: the telemetry and cost
design note (`2026-09-14-telemetry-and-cost-observability-design.md`, §5.5 and §9 item 1b) and the
slice 1 memory note (`_memory/2026-09-14-lane3-slice1-cost-read.md`, "Discovered, recorded, not
done here").

## 1. Purpose

Slice 1 built the cost read over `provider_call_ledger` and `agent_model_call`, and had to print
three ledgers it could not see on every report: the onboarding lane, the display prewrite and the
persona-evidence tool all write their `ProviderCaller` ledgers to JSONL files on disk. Slice 1 also
found that the `openrouter` rows written by the structuring client, the media client and the
catalog reconciler carry no model or token counts, so the per-model view shows them as `unknown`.

Slice 1b closes both gaps. After it, every paid call the platform makes through `ProviderCaller`
lands on `provider_call_ledger`, and every OpenRouter row carries the model and usage the
research agent's rows already carry. The cost read's `not_covered` list shrinks to the design
subsystem (R12 hold) and the conversation-turn rows written before the cost columns existed.

No new table, no new flag, no new service. Postgres stays the ledger of record (R2); nothing is
recomputed.

## 2. What exists (verified 2026-09-14)

- `ProviderCaller.call` writes an estimate row before the wire and a result row after, through a
  `LedgerSink`; raw bodies go through a `RawSink`. Both are protocols (`arv2/sinks.py`).
- `arv2/provider_ledger.py` has the buffered pair (`BufferedRawSink`, `BufferedLedger`), the
  `LedgerStamp`, and `drain_provider_calls(conn, raw=, ledger=, artifacts=, stamp=)`, which persists
  bodies as artifacts then inserts rows (`ON CONFLICT (ledger_id) DO NOTHING`). The discovery and
  account-research drivers already use it.
- `LedgerStamp` requires all four of `workspace_id`, `project_id`, `project_run_id`, `job_id`. The
  three ledger columns behind the last three are nullable, and the table has no foreign key on
  `entity_research_job_id`.
- The onboarding driver (`arv2/onboarding_driver.py`) builds one Exa client per step through
  `ExaClientFactory(run_id=, step_label=)`, whose production implementation builds a caller over
  `FileRawSink` + `JsonlLedger` under `arv2_raw_root/onboarding/<run>/<step>/`. The catalog
  reconciler (`fleet_main._build_catalog_reconciler_factory`) builds the same kind of caller. The
  driver already holds a `conn_factory`, a `db_lock`, and an `ArtifactSink` with `persist_body`.
- The display prewrite (`arv2/display/page.py`) builds one `LunaSectionRunner` per section over a
  file caller; `ensure_page` runs sections concurrently under a semaphore on the caller's one
  connection and sums each runner's totals into `PageResult.cost_usd`.
- The persona-evidence tool (`onboarding_evidence_tools.py`) builds one file caller per invocation;
  its `ToolContext` carries `workspace_id` and `conn_factory` but no project id.
- `openrouter_cost_reader` returns cost and request id only; `ProviderCaller._settle` merges a
  reading's `extras` over the spec's and stamps `cost_source`.

## 3. Design

### 3.1 The stamp

`LedgerStamp` becomes:

```python
@dataclass(frozen=True)
class LedgerStamp:
    workspace_id: str
    project_id: str | None = None
    project_run_id: str | None = None
    job_id: UUID | None = None
```

`_ledger_params` is unchanged (it already passes the fields through). Existing callers pass all
four and keep working.

### 3.2 The onboarding lane (D1)

The driver owns the buffers. Per provider step it creates a `BufferedRawSink` and a
`BufferedLedger`, hands them to the factory that builds the step's client, and drains after the
step's calls, whatever their outcome:

- `ExaClientFactory.__call__(self, *, run_id: UUID, step_label: str, raw: RawSink, ledger: LedgerSink) -> ExaAgentSurface`.
  `build_onboarding_provider_caller(*, raw, ledger)` builds the caller over the given sinks and
  touches no filesystem; `build_onboarding_exa_client_factory` is unchanged in shape.
- The reconciler factory becomes `Callable[[RawSink, LedgerSink], CatalogReconciler]`: the run
  id no longer names a folder, so it no longer reaches the factory. Its `caller_factory` closure
  builds each hop's caller over the step's buffers (both are lock-protected, so several callers
  may share them).
- The driver gains one injectable `drain` callable (default `drain_provider_calls`), in the same
  style as its injected `store` and `synchronize_catalog`, so the offline tests record drains
  without a database. It drains under `self._connection()` in a `finally` after the recon step's
  agent run, after the lineup step's two deep-reasoning calls, and on the catalog step's own
  connection after `synchronize_catalog` returns.
- **D1 (ruled):** the stamp is `LedgerStamp(workspace_id=scope.workspace_id,
  project_id=<the persona ICP's project id when the run is project-local, else None>,
  project_run_id=None, job_id=scope.run_id)`. `make cost-report --job <run id>` then answers "what
  did this onboarding run cost", and the run appears in the report's jobs list, exactly as
  discovery runs do.
- The step's own `cost_usd` bookkeeping (from the client result) is unchanged; the drain report
  is logged, not summed a second time.

### 3.3 The display prewrite (D2)

- `RunnerFactory` becomes `Callable[[RawSink, LedgerSink], LunaSectionRunner]`.
  `default_runner_factory` builds each runner's caller over the sinks it is handed.
- `_write_section` creates one buffer pair per section and returns them on `_Written`.
- `ensure_page` gains `artifacts: ArtifactSink` and `spend_conn_factory: ConnFactory`. After the
  gather it drains every section's buffers **sequentially** under one connection from
  `spend_conn_factory` (concurrent drains on the page's single connection are not allowed), with
  `LedgerStamp(workspace_id=workspace_id)` (a page belongs to an account, not a project or run).
- **D2 (ruled):** the spend rows commit in their own transaction. `scripts/generate_arv2_display.py`
  passes `spend_conn_factory=transaction` and
  `artifacts=DurableAgentArtifactStore(storage=build_storage_backend(settings), conn_factory=transaction)`,
  so a `--dry-run` that rolls the page back still records the money it spent. Tests pass the
  rolled-back test connection for both.
- `PageResult.cost_usd` still sums the runners' totals (unchanged).

### 3.4 The persona-evidence tool (D3)

- `build_onboarding_evidence_tools(*, settings, secrets, artifacts: ArtifactSink | None = None)`.
  `toolbelt_wiring` passes `DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)`
  when a storage backend is composed, else `None`.
- `ExaSearchEvidenceTool` takes `client_factory: Callable[[str, RawSink, LedgerSink], ExaAgentSurface] | None`
  and `artifacts: ArtifactSink | None`.
- **D3 (ruled):** `preconditions` refuses `artifacts_not_configured` when no sink is composed,
  before any spend, in the same posture as `exa_not_configured`.
- `invoke` creates the buffers, runs the call on a worker thread, then drains in a `finally`
  under `ctx.conn_factory()` with `LedgerStamp(workspace_id=ctx.workspace_id)` (the tool context
  carries no project id; the row is workspace spend).

### 3.5 The OpenRouter cost reader

`openrouter_cost_reader` adds to `CostReading.extras`, for every JSON body:
`model` (when the body's `model` is a string), `prompt_tokens`, `completion_tokens` and
`cached_prompt_tokens` (from `usage.prompt_tokens`, `usage.completion_tokens`,
`usage.prompt_tokens_details.cached_tokens`; each an int, 0 when absent). These are the keys the
research agent's rows already use and the cost read's `research_ledger` lines already read, so the
structuring, media, reconcile and display rows join the per-model view with no change to the read.
A non-JSON body still yields an empty reading.

### 3.6 The cost read and the docs

`clue_projections.cost.NOT_COVERED` shrinks to two entries (the design subsystem's providers
under the R12 hold; conversation-turn rows older than the cost columns). The module docstring's
"what this read cannot see" paragraph, the cost DB test, the design note (§3 row, §5.5, §9 item
1b) and the lane index row 1b are updated to say the three ledgers are now on Postgres.

## 4. What does not change

- No legacy research-lane file (R11), no design-subsystem file (R12), no frontend file.
- `ProviderCaller`, its laws (estimate before the wire, raw record before parse, halt latch), and
  the `LedgerRow` shape.
- `arv2_raw_root` stays a setting: the live-test conftest and the file sinks still exist for tests
  and for any future caller that wants files; no production path writes there after this slice.
- The onboarding synthesis turns' model spend, already on `agent_model_call`.

## 5. Testing

- `provider_ledger`: a workspace-only stamp lands NULL project, run and job.
- `openrouter`: the reader's extras for a body with and without `usage`, and a non-JSON body.
- Onboarding driver, offline: the fake Exa factory receives the sinks; every provider step
  records one drain with the D1 stamp (project id from a project-local persona run); a step whose
  call raises still drains. One DB test: a fake client that writes one ledger row lands it on
  `provider_call_ledger` with `entity_research_job_id = run id` and its body as an artifact.
- Display page DB test: sections' rows land with the workspace stamp and NULL project; a
  rolled-back page still called the spend factory (D2 is proven by the script's composition and
  a test that the drain uses the injected factory, not the page connection).
- Evidence tool: `artifacts_not_configured` refusal; an invoke drains one row under the context's
  connection factory with the workspace stamp.
- Cost read: `not_covered` no longer names onboarding, display or evidence.
- Fleet wiring: the reconciler factory is built with the new signature.

Live proof: an onboarding run spends real money (roughly $3–8 per the O3/O4 notes) and is
founder-triggered; the slice's own proof is the DB tests on the lane database plus the cost
report's shrunken `not_covered` list.

## 6. Deferred

- The `chat/completions` rows' `model` extra makes the per-model view complete for new rows only;
  historical rows keep `unknown`. No backfill.
- The design subsystem's paid calls (R12) and the doubled `answering_model` on streamed turns
  (slice 2) are unchanged.
