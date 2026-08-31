# 2026-08-08 — Part II D2.3 phase B: ingestion jobs + asset descriptions on Postgres

Branch `platform/design-integration`. Phase A (brand + assets) landed separately; this note
covers the ingestion-job and asset-description domains and the whole-slice D2.3 gate.

## What landed
- **Schema residual (amended the still-uncommitted `cf4f80537c8e`):** `design_snapshot`'s PK is
  now `(snapshot_id, workspace_id)`. Evidence: snapshot ids are CLIENT-SUPPLIABLE (`POST
  /documents/{id}/snapshots` takes the id from the body; the design suite posts literals like
  `snap_before_edit`), so a global PK carried the same cross-workspace squatting flaw
  `7a9881f9717a` fixed for documents/template revisions. `design_template_revision_snapshot_fk`
  already targets the surviving `design_snapshot_workspace_anchor`, so nothing else moved.
  `downgrade()` restores the global key; up→down→up verified by `make db-smoke`.
- **DAL:** `clue_design/ingestion.py` (`new_id`, `create_job`, `update_request`, `get_job`,
  `require_job`, `list_recent`, `set_running`, `set_stage`, `complete`, `fail`) and
  `clue_design/descriptions.py` (`get_many` via `= ANY(:ids)`, the HUMAN-WINS conditional
  `put_ai`, unconditional `put_human`). Workspace-scoped, enum casts, mappers byte-identical to
  the ported row shapes, ISO timestamps, no commits (callers own the transaction).
- **Stores rewritten in place:** `lumen_ingestion/jobs.py::IngestionJobStore` and
  `lumen_ingestion/describe.py::DescriptionStore` keep their public surfaces; `connection` and
  `now_iso` are vestigial, `workspace_id` is a new keyword-only arg, persistence goes through
  `DesignStoreBridge`. `require` still satisfies `raise KeyError` because the bridge's
  `NotFoundError` subclasses `KeyError`.
- **Workspace threading:** the 7 job sites + 2 description sites in `main.py` pass
  `repo.workspace_id`; the 3 background workers (`run_website_ingestion`/`run_pdf_ingestion`/
  `run_asset_ingestion`) gained a `workspace_id=None` kwarg passed from the dispatch site and
  now build a `HybridRepository` (was plain `Repository`) — mandatory, because the job's result
  pointer is a REAL composite FK to `design_brand_kit (id, version, workspace)`. Descriptions
  inside the pipeline take the workspace off `repo` in `_maybe_describe` and pass it only to the
  DEFAULT apply path, so the injected `_ApplyDescriptionsCallable` protocol (and its test stubs)
  is unchanged. The three web-agent manifest `DescriptionStore(connection)` sites keep the
  default workspace (they sit beside default-workspace `HybridRepository` constructions).

## Findings (each fixed, each worth remembering)
1. **The bridge could not be called from inside a running loop.** `DesignStoreBridge._run` did a
   bare `asyncio.run`. Two ported call sites live inside a loop: the one async endpoint
   (`POST /brand-kits/ingest/website`, which awaits the SSRF guard) and — the subtle one — the
   ingestion pipeline's stage reporter, which is invoked from within the pipeline's own
   `asyncio.run(capture(...))`. Fix: `_run_isolated` detects a running loop and hands the call
   to a one-shot worker thread (still one loop / connection / transaction per call). The async
   endpoint additionally does its store call via `run_in_threadpool` so it never blocks the loop.
2. **asyncpg does not map an unknown enum label to `DataError`** — it surfaces
   `InvalidTextRepresentationError` as a bare `DBAPIError`, so the bridge's constraint-parity
   translation missed it and `test_brand_kits_source_check_accepts_website` failed. The bridge
   now also translates SQLSTATE class 22 (data exception) to `sqlite3.IntegrityError`; anything
   else keeps its own type.
3. **Description writes preceded their registry rows.** `design_asset_description` has a real
   1:1 FK now, but all three pipelines ran `_maybe_describe` BEFORE
   `core.persist_records(repo)` — which also meant `resolve_bytes` (a
   `require_asset_record` lookup) could never resolve a freshly captured asset, i.e. describe
   was effectively dead on a first ingest. Reordered: registry first, descriptions second.
4. **`design_ingestion_job.progress` is PG `real` (float4)** while SQLite's REAL was a double, so
   0.4 round-trips as 0.40000000596. Harmless for a progress bar; the one exact assertion is now
   `pytest.approx`. If exact DTO parity is ever wanted it is a one-line ALTER migration — NOT
   done here (out of slice scope).

## Verification
ruff/mypy(581)/lint-imports(25 kept) clean; `make db-smoke` green on a throwaway DB;
`tests/design/` 33 passed (27 prior + 6 new in `test_ingestion_descriptions_dal_db.py`).
offline platform suite 2176 passed / 1474 skipped. **D2.3 gate — full design-API suite against
the throwaway DB: 2 failed, 485 passed, 10 skipped (12m51s).** The two failures are
pre-existing and outside this slice: two custom-component tests
(`test_custom_component_publish::test_publish_rejects_unresolved_tenant_pin_and_malicious_source`,
`test_custom_components::test_custom_component_round_trips_and_participates_in_edit_history`)
fail for reasons outside this slice: the publish test corrupts the scene by writing SQLite
`documents.current_scene_json` directly, but documents have lived on Postgres since D2.2, so the
corruption never reaches the served scene (publish returns 200 instead of the expected 502); the
round-trip test's `move_node` batch is refused by the engine with `LUMW0011` (the page root may
only hold sections), i.e. its container target resolves to the page root. Both belong to the
documents/custom-component lane. Separately,
`test_web_turns::test_web_turn_applied_replays_operations_and_writes_envelope` is flaky (agent-run
event timing — passes in isolation).

## Next: D2.4 (personalization / web / custom components), then D2.5 (API switch + SQLite delete)
The two custom-component failures above sit squarely in D2.4's domain and should be resolved
there, not patched around.
