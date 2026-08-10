# Part II D6 Round C — brand kits, ingestion, assets, personalization + batches (the closing round)

Branch `platform/design-integration`, on top of `0d12ddb9` (D5) **plus the uncommitted, reviewed
D6 Rounds A+B**. Contract: `docs/specs/PD-part2-design-substrate.md` slice D6 — gate: *every
design mutation behind a registered, precondition-checked, idempotency-keyed tool*. Round C is
the conversion round's last pass: it converts everything left in `UNCONVERTED_MUTATIONS` and
lands the correctness fixes the earlier rounds flagged.

**Headline: `UNCONVERTED_MUTATIONS` is now a closed EXEMPTION, not a backlog** — four
run-lifecycle writes (`create_run` / `set_run_result` / `complete_run` / `append_run_event`),
which the fleet lease arbitrates rather than the toolbelt (the D5 fencing contract). The guard
asserts that set *exactly*, so a later round cannot park a new ungoverned write beside them.

## The five correctness fixes (the round is mostly this, not conversion)

### 1. Brand-kit version allocation is serialized + compare-and-set
`POST /brand-kits/{id}/logo` and `/describe-assets` were read-modify-write: read the latest
version, mutate the kit JSON, compute `version + 1` **in Python**, insert. Two concurrent
curations both asked for the same number — the loser died on the composite primary key (an
`IntegrityError` surfacing as a duplicate-kit 409 that named the wrong cause), and had they not
collided the later publish would have silently discarded the earlier one's edits.

`clue_design.brand.publish_next_brand_kit_version` allocates inside the write transaction. **The
lock is on the kit's LOWEST-version row, not its latest** — and that detail is load-bearing:
`SELECT … ORDER BY version DESC LIMIT 1 FOR UPDATE` is useless here, because under READ COMMITTED
a blocked allocator re-checks only the row it already locked and a competitor's new version
arrives as an INSERT (a phantom) its `ORDER BY … LIMIT 1` never re-evaluates — so both would
allocate the same number anyway. The anchor row is the one row of the lineage nothing can insert
around. `expected_base_version` is the second half: a curation prepared against version N cannot
land on version M (that would discard M), so it is a typed 409 (`brand_kit.version_moved`), never
a stray PK error. The allocated number is stamped into `brand_kit["version"]` before the insert,
so the row and the persisted kit JSON can never disagree.

### 2. The generation ledger moved to Postgres
New table `design_generation_result` (migration `2711924d1e29`, off head `ad332dc38f36`).
`lumen_api.image_cache`'s JSON sidecar had three defects, all closed: it lived under the
*wipeable* engine materialization cache; a whole-file rewrite is last-writer-wins across
processes (a lost write is a silent double-spend); and nothing tied an entry to the asset row it
named, so a hard-deleted asset stayed cached forever (the composite FK's `ON DELETE CASCADE`
makes that unrepresentable now).

Shape: `PK (workspace_id, generation_key)`, `asset_id` composite-FK'd to `design_asset`,
`record_json` as the produced-at-the-time snapshot; the READ joins the LIVE `design_asset` row so
later curation is visible to a cache hit. `generation_key` is unchanged —
`image_cache.generation_key` is still the one definition of "the same request"; only storage moved.

The route's **pre-spend probe is a READ** (`repo.get_generation_result`) and deliberately not a
tool: it is what avoids the provider call, and it has to run before it. The **write** claims the
key and re-checks the ledger inside its own transaction, so two requests that both miss the probe
still converge on one asset. `design_register_generated_asset`'s replay notes say this plainly
(boundary `NONE` — the tool itself makes no external call; replay cannot un-spend the route's).

**Residual, deliberate:** the AGENT-RUNTIME half (`lumen_agent/tools/substrate.py` ~1178-1232,
~1587-1627) still uses the file sidecar against the engine cache root. The runtime holds no
database handle by design; unifying it is **Part-III** work. `image_cache.py`'s docstring now
says exactly this instead of promising "D5 will fix it".

### 3. The asset-description patch is one statement
`PUT /assets/{id}/description` merged in Python across two transactions — read the row,
substitute non-`None` fields, write the whole record back. Two concurrent patches of *different*
fields each wrote the view they had read, so the later one reverted the earlier one's field. Now
`clue_design.descriptions.merge_human`: one `COALESCE(:field, <existing column>)` upsert
evaluated under the conflicting row's own lock. `put_human` survives as the unconditional
whole-record write (the describe pipeline's shape).

### 4. Batch resume is single-flighted
Both batch loops read the cursor, derived a chunk (minutes of engine work, outside any
transaction) and wrote progress. Two concurrent resumes both derived the chunk and both wrote it.
Now every chunk write carries the cursor it STARTED from and the DAL compare-and-sets it under the
batch row lock; the loser gets `advanced=False` plus the batch's real cursor and the loop stops
and returns live progress — **a resume is never an error**, it just discovers the work is already
being done. The loops also re-read the cursor at the top of each chunk, shrinking the wasted-derive
window to one chunk.

**Residual, stated at the site:** the losing resumer still derives its chunk before discovering
the move (the lock cannot span the engine round-trip). Harmless on the instance side —
`inst_<rev>_<bind>` is deterministic and the write is an upsert — but on the web side one chunk of
orphan `doc_` rows is possible. Closing that needs a real per-batch lease (fleet work).

### 5. The ingestion re-offer hole
`lumen_ingestion/pipeline.py` publishes its kit from the fleet worker while the D5 Round C reaper
re-offers a job whose worker died between publishing the kit and terminalizing the job row. The
kit id was ALREADY per-job deterministic (`brand_kit_ing_<job suffix>` at version 1) — so the
failure mode was not duplicate kits, it was a **hard PK collision that failed the re-offered job
with a database error** instead of completing with the result it had already produced.

**Mechanism (argued from what `create_brand_kit` supports — the DAL has no upsert, and a re-capture
is non-deterministic so content comparison is impossible): `on_conflict = "refuse" | "adopt"` on
`design_create_brand_kit`.** `adopt` returns the existing row's pointer and writes nothing. It is
safe *precisely because the id is derived from the job id*: the only writer that can have filled
that slot is an earlier attempt of the same job. When the CLIENT supplied `brand_kit_id`
(`job_derived_id=False`) the slot is not the job's to adopt and the collision stays the loud
refusal it has always been. Every HTTP caller keeps the default `refuse`.

The worker's kit-create and its captured-asset promotion both go through the tools with
`actor="agent"` (REQ-20 parity), via a minimal `_worker_design_tools(storage)` host (row store +
byte store only; the engine collaborators raise if reached — nothing calls the engine from inside
a tool, R-D6-B4).

## Tool inventory (21 new; 28 + 21 = **49** design tools)

All: `ToolEffectClass.WRITE`, `ExternalReplayBoundary.NONE`, typed reference-only `ToolOutput`,
`design_runtime_not_configured` when no host is composed.

### `lumen_api/toolbelt/brand.py` — brand kits (4 tools, 7 routes + the worker)

| tool | replay | reason codes |
|---|---|---|
| `design_create_brand_kit` | DOMAIN (`kit id + version`) | `design_brand_kit_exists` |
| `design_publish_brand_kit_version` | OPERATION (op-id required; version is ALLOCATED) | `design_brand_kit_not_found` |
| `design_set_brand_kit_approval` | DOMAIN (value assignment) | `design_brand_kit_not_found` |
| `design_create_brand_compatibility_report` | OPERATION (random `brand_report_<uuid>`) | — |

Seven routes → four tools, the same "one tool per operation *family*, never per caller" reading
Round B applied to `design_record_diagnostics`: `POST /brand-kits`, the `/generate` and
`/compile-styles` persist halves and the ingestion worker are FOUR callers of ONE write.

### `lumen_api/toolbelt/ingestion.py` — enqueues (3)

| tool | replay | reason codes |
|---|---|---|
| `design_ingest_website` / `_pdf` / `_assets` | OPERATION (op-id required) | — |

Staged-blob registration stays route-side and is **exempt by construction**: content-addressed and
immutable, no state to lose, no ordering to get wrong, and an abandoned staged blob is what the
orphan sweep already collects. Validation (SSRF guard, `%PDF-` sniff, file-count ceiling, size
limits) stays route-side too — wire contracts with their own 4xx bodies that gate the *upload*, not
the row. `_offer_ingestion_job` became the pure payload builder `_ingestion_offer_payload`.

### `lumen_api/toolbelt/assets.py` — the asset registry (7)

| tool | replay | reason codes |
|---|---|---|
| `design_register_asset_record` | OPERATION (op-id required) | — |
| `design_register_qr_asset` | DOMAIN (`asset_qr_<sha256(payload)[:12]>`) | — |
| `design_register_generated_asset` | DOMAIN (`generation_key`) | — |
| `design_register_captured_assets` | DOMAIN (content-derived ids), BULK | — |
| `design_set_asset_status` | DOMAIN (value assignment) | `design_asset_not_found`, `design_asset_status_invalid` |
| `design_delete_asset` | OPERATION (op-id required) | `design_asset_not_found`, `design_asset_referenced` |
| `design_set_asset_description` | DOMAIN (SQL merge) | `design_asset_not_found` |

- **Upload keeps its re-upload-new-row semantics** (the library is a curation surface: two people
  uploading the same logo want two entries with their own labels). Stated in the replay notes so
  nobody "fixes" it into a dedup.
- **QR became genuinely domain-idempotent**: the payload was always deterministic (the engine
  already reported `deduplicated` on the second call) — the only non-deterministic thing was the
  row id (`asset_qr_<uuid4>`), so identical repeats accumulated rows over one blob. The route now
  derives the id from `(data, label, ec_level, print_media, target_width_mm)`.
- `design_register_asset_record` serves the upload route AND the registered-provider generation
  branch (both mint a fresh id per request); the image-provider branch is the ledger-keyed tool.
  The registered-provider branch was deliberately NOT put on the ledger — extending the cache to
  it would change its response shape and its re-generate behaviour, which is not D6's business.
- `design_register_captured_assets` is BULK because one capture is one gesture, and a per-record
  invocation would cost a private engine + ~5 journal transactions **per captured image**.
- Delete is precondition + row delete + byte GC in ONE core
  (`delete_asset_and_orphaned_bytes`): a window in which the row is gone and the bytes are not is
  a leak nothing records as owed. `record_digest_values` / `delete_stored_digest` moved into it
  verbatim (they had no other caller). The host gained an `engine_cache_dir` thunk for the cache
  mirror unlink.

### `lumen_api/toolbelt/personalization.py` — personalization + both batch families (7)

| tool | replay | reason codes |
|---|---|---|
| `design_upsert_binding_set` | DOMAIN (client-supplied id, mandatory) | — |
| `design_delete_binding_set` | DOMAIN (absence) | — |
| `design_derive_instance` | DOMAIN (`inst_<rev>_<bind>`) | — |
| `design_create_instance_batch` | OPERATION (op-id required) | — |
| `design_advance_instance_batch` | OPERATION (op-id required) + cursor CAS | `design_batch_not_found` |
| `design_create_web_batch` | OPERATION (op-id required) | — |
| `design_advance_web_batch` | OPERATION (op-id required) + cursor CAS | `design_batch_not_found` |

- `design_upsert_binding_set` is the one tool in the whole of D6 whose DOMAIN key has **no**
  route-mints-a-uuid else-branch: the route 422s a payload without `binding_set_id` before the
  invocation.
- `design_delete_binding_set` is DOMAIN, unlike Round A's `design_delete_web_account`
  (OPERATION): the binding-set route has never 404'd, so nothing is gated on existence and there
  is no destructive swap — deleting an absent set is a genuine no-op. Argued at the site.
- `design_derive_instance` is three writes on purpose (instance + generated asset records +
  repair requests): one derivation's footprint, all keyed off the same deterministic id. A
  partial application (an instance whose generated crop was never registered) is exactly the
  state nobody can repair. The ENGINE derive stays route-side (R-D6-B4).

## The two other flagged cleanups

- **`HybridRepository.set_document_account` DELETED** — and `register_scene_assets` with it, for
  the same reason (zero callers; every scene-persist path calls the DAL in-transaction). Minting a
  tool for a write no caller performs would be governance theatre. **Recon correction:**
  `set_document_account` had exactly ONE caller after all — a *test* scaffold
  (`tests/test_web_turns.py`), which now reaches the DAL directly through the bridge (a test may;
  production may not). A new guard test asserts both stay deleted.
- **`publishes.register_web_publish_revision`'s bare `ValueError` → typed refusal → 409.** It now
  raises `DesignArtifactConflictError("web_publish_revision", …)` — the same species the component
  registry names (a content-addressed id re-used with different content). The bridge branches on
  `kind` into a new `WebPublishRevisionConflict`, and `main` registers a handler producing 409
  `web_publish.revision_conflict`. Previously a 500 `database.error`.

## New API-level error types (`lumen_api/database.py`)

- `DesignResourceVersionConflict(kind, key, expected, current)` — the DAL has always carried the
  resource `kind`; the API only had `WebDocumentVersionConflict`, whose `document_id` attribute
  would be a lie for the brand-kit and batch CAS sites. **Documents keep their own type**, so
  every existing handler and every `except WebDocumentVersionConflict` is untouched; the bridge
  branches `if exc.kind == "document"`.
- `WebPublishRevisionConflict(publish_id)` — see above.

## Ripples (exactly as Rounds A/B did them)

- `toolbelt/factory.py` + `__init__.py` — 21 new types/exports. Verified the package is still
  import-light (`import lumen_api.toolbelt` pulls no fastapi / clue_design / PIL / playwright).
- `platform/api/clue_api/agent_registry_wiring.py` — 21 new `C6_AGENT_TOOL_AUTHORITY` entries,
  all `()`, and 21 new `_RESERVED_REASON` rows (`design_agent_not_wired_until_part_iii`).
- `tests/api/test_toolbelt_wiring.py` — 21 `_MATRIX` rows + 21 `_bodies()` entries; counts
  76 → **97** names, 83 → **104** addresses.
- `tests/agents/test_tool_authority_audit.py` — 76 → **97**.
- `tests/api/test_agent_registry_wiring.py` — 83 → **104** addresses; reserved design set → 49.
- `tests/test_write_path_governance.py` — 20 store methods + 2 operation cores into `_GOVERNED`;
  `UNCONVERTED_MUTATIONS` down to the four run-lifecycle writes, asserted by equality. The
  "does this name exist?" check now looks at all THREE workspace-scoped store facades
  (`HybridRepository`, `IngestionJobStore`, `DescriptionStore`) — the guard's textual rule is
  unchanged, only its existence lookup widened.

## Response-shape compatibility

Every converted route keeps its exact body and status; the tool returns references and the route
re-reads the row it needs (every DAL write ends in its own `get_*` read-back). Refusal reason
codes map back through `run_design_tool`'s `refusals=` dict: `design_brand_kit_exists` →
`duplicate_brand_kit_error` (the same `brand_kit.version_exists` 409 the `IntegrityError` catch
produced), `design_brand_kit_not_found` / `design_asset_not_found` → the same `NotFoundError` the
store raised, `design_asset_referenced` → the same 409 string.

**One intentional behaviour change, documented at its site:** an identical QR request now returns
the SAME asset id instead of a new row. No test asserted the old behaviour (the determinism test
checks the digest and `deduplicated`, not the id), and the old behaviour accumulated library rows
over one blob.

## Verification (fresh MIGRATED throwaway DBs; `alembic upgrade head` before every suite)

- `make db-smoke` equivalent (up → down → up on a clean per-branch DB `clue_d6c_smoke`) — clean;
  `alembic heads` = **`2711924d1e29` alone**.
- `tests/design/ tests/fleet/` + the four registry/guard suites — **206 passed**, exactly Round
  B's number.
- New Round C design tests + the three earlier toolbelt/guard files — **42 passed**.
- `uv run mypy` — clean, **592** files. `uv run ruff check` — clean. `ruff format --check` — the
  known **23** pre-existing files (my two new/edited `clue_design` files were formatted).
  `uv run lint-imports` — **25 kept, 0 broken**.
- **Full design-API suite** (canonical invocation `uv run pytest tests` from
  `subsystems/clue-design/apps/api`, fresh migrated DB `clue_d6c_full3`, run EXCLUSIVELY) —
  **543 passed / 9 skipped / 0 failed**, `EXIT=0`, 552 collected. Round B's baseline was 525/9/0
  over 534; +18 = the 17 new `test_design_toolbelt_round_c.py` cases plus the new
  deleted-facade guard in `test_write_path_governance.py`. Log: `/tmp/d6c_full_3.log`.
- **Design agent-runtime suite** (`apps/agent_runtime/tests`, run SERIALLY, after the design
  suite) — **551 passed / 2 skipped**, exactly the baseline. Log: `/tmp/d6c_runtime.log`.
- **Offline platform suite** (`uv run pytest` from the repo root, no `CLUE_DATABASE_URL`) —
  **2199 passed / 1530 skipped**, exactly the baseline. Log: `/tmp/d6c_offline.log`.
- `import lumen_api.toolbelt` still pulls no fastapi / clue_design / PIL / playwright; the
  `invoke_tool(` guard is still zero hits outside tests under `platform/api`,
  `platform/execution`, `subsystems`.
- Two pre-existing-only lint findings confirmed unchanged: `tests/test_api.py` +
  `tests/test_web_turns.py` carry 9 `F401/F821` under isolated ruff, identical at `HEAD`.

### One test instrument had to be narrowed (a real finding, not a weakening)

`test_api.store_files(tmp_path)` globbed **every** file under `default-storage` and called the
count "this test's durable design blobs". Since Round A the same backend also holds the governed
toolbelt's canonical PARAMETER SNAPSHOTS (`{workspace}/{sha256}`, `source_key='tool_parameters'`)
— journal evidence, not asset bytes. Round C is the first round to put a governed write on the
upload path, so a second upload suddenly looked like it cost two extra byte objects
(`test_duplicate_asset_upload_dedups_bytes`, `test_hard_delete_byte_lifecycle_respects_digest_references`).
The glob is now scoped to the `{workspace}/design/` namespace, which is exactly the property the
docstring already claimed to measure. **Anything else that counts objects in the design storage
backend needs the same narrowing.**

### A methodology note worth keeping

The first wall-to-wall design-API run was **invalid**: two full suites were running against the
same throwaway database at once, which produced twelve failures that were entirely artefacts
(byte-count assertions seeing 4 files instead of 2; staged ingestion blobs cleaned by the other
run; the known `lumen-api-helper` contention flake). Every one of them passed in isolation. Run
the design suite **exclusively** — one suite, one database — or the log is noise.

## What is left for the D6 close-out

- **Tool count is 49, not the ~44-46 the brief estimated.** The difference is deliberate and is
  three splits the brief's arithmetic collapsed: QR vs upload vs generated registration (three
  genuinely different replay policies over one core), the bulk captured-assets tool, and the two
  batch families' create/advance pairs. Consolidating any of them would put a two-mode replay
  statement on one tool — the thing Rounds A/B refused to do.
- **Performance, restated.** Every governed design write costs a private engine + ~5 short journal
  transactions + one parameter-artifact put. Round C adds full-record parameter snapshots on the
  asset paths and a whole-manifest snapshot on each batch chunk. The fix, if it bites, is a
  per-loop engine cache in `wiring._ainvoke` and/or a size threshold on the parameter
  snapshotter — never a weaker journal.
- **The agent-runtime generation cache** stays on the file sidecar (Part III).
- **Batch single-flight residual**: one chunk of wasted derivation on the losing web resumer;
  needs a per-batch lease.
- Round A's still-open reviewer decision stands: `clue-api`'s `pyproject.toml` does not declare
  `lumen-api` even though `clue_api` now runtime-requires `lumen_api.toolbelt`.
