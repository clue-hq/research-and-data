# Part II D6 Round B — documents, scene history, web documents, turn enqueues

Branch `platform/design-integration`, on top of `0d12ddb9` (D5) **plus the uncommitted, reviewed
D6 Round A tree** (`_memory/2026-08-10-part2-d6a-toolbelt-foundation.md`). Round A's foundation is
untouched; this round only *adds* to it. Contract: `docs/specs/PD-part2-design-substrate.md` slice
D6 — gate: *every design mutation behind a registered, precondition-checked, idempotency-keyed
tool*. Round C still owns brand kits, assets, ingestion, personalization binding/instances and the
batch family.

## Headline: the scene CAS is closed (R-D6-B1, the slice's #1 correctness fix)

`HybridRepository.update_document_state` and `.replace_scene` now **forward
`expected_base_version`** into `clue_design.documents`, which has checked it under the row lock
(`_check_cas`) since D2.2. Before D6 the facade did not accept the argument at all, so **every
scene-path write silently degraded to last-writer-wins**: the routes' handler-level
`require_base_version` reads the version, the engine round-trip then runs for hundreds of ms, and
only then does the write land. A writer that landed inside that window was lost without a trace.

The handler pre-check **stays** (fast, friendly 409). The DAL CAS is the truth behind it, and the
two produce a byte-identical body (`_base_version_conflict` in `main.py` restates
`require_base_version`'s message verbatim) so no caller can tell which refused.

Where each route now stands:

| path | base version threaded | note |
|---|---|---|
| POST /operations, POST /edits | `payload.base_version` | the hot path; closes the engine-round-trip window |
| POST /undo, /redo, /revert | the version the route just read | read-then-write loops; interleaving is now a 409, not a silent rewind |
| /web/operations, /web/undo, /web/redo, worker persist | unchanged (already CAS'd since D2.2) | now raised from inside the tool; same 409 bodies |
| **PUT /documents/{id}/scene** | **none — honest window documented at the site** | `ReplaceSceneRequest` carries no `base_version`; D6 does **not** invent a request field. The DAL row lock still serializes, but two whole-scene replaces racing remain last-writer-wins. Closing it is an editor wire-contract change. |
| POST /preflight, POST /export persist | `None` (no base version in either contract) | same honesty rule |

**Undo/redo interleaving finding:** no design test depends on interleaving-tolerant undo. The
whole design suite is green with the CAS on, and `perform_undo_step` / the web undo+redo routes
already read `document["current_version"]` immediately before writing, so the added CAS only
fires on a genuine concurrent write.

## Tool inventory (20 new; 8 + 20 = 28 design tools)

All: `ToolEffectClass.WRITE`, `ExternalReplayBoundary.NONE`, `ToolEstimate.free()` (inherited —
no design tool wraps long external work), typed reference-only `ToolOutput`, and
`design_runtime_not_configured` when no host is composed.

### `lumen_api/toolbelt/documents.py` — scene documents, history, diagnostics (13)

| tool | replay | reason codes (beyond `design_runtime_not_configured`) |
|---|---|---|
| `design_create_document` | DOMAIN (caller-supplied `document_id`) | `design_document_kind_unsupported`, `design_document_exists` |
| `design_set_agent_instructions` | DOMAIN (value assignment) | `design_document_not_found`, `design_document_not_scene` |
| `design_set_layout_managed_editing` | DOMAIN (value assignment) | same |
| `design_replace_scene` | OPERATION (op-id required) | + `design_document_finalized` |
| `design_apply_operations` | OPERATION (op-id required) | + `design_document_finalized` |
| `design_apply_edits` | OPERATION (op-id required) | + `design_document_finalized` |
| `design_undo_document` | OPERATION (op-id required) | + `design_document_finalized` |
| `design_redo_document` | OPERATION (op-id required) | + `design_document_finalized` |
| `design_create_snapshot` | DOMAIN (caller-supplied `snapshot_id`) | + `design_snapshot_exists` |
| `design_persist_preflight` | OPERATION (op-id required) | + `design_preflight_actor_invalid` |
| `design_attach_brand_kit` | OPERATION (op-id required) | + `design_document_finalized` |
| `design_finalize_document` | DOMAIN (caller-supplied `template_revision_id`) | + `design_template_revision_exists` |
| `design_record_diagnostics` | OPERATION (op-id required) | + `design_diagnostics_kind_invalid` |

### `lumen_api/toolbelt/web_documents.py` — website-mode documents (5)

| tool | replay | reason codes |
|---|---|---|
| `design_create_web_template` | DOMAIN (caller-supplied `document_id`) | `design_document_exists` |
| `design_derive_web_document` | DOMAIN (caller-supplied `document_id`) | `design_document_exists` |
| `design_apply_web_operations` | OPERATION (op-id required, base_version CAS) | `design_document_not_found`, `design_document_not_web`, `design_document_finalized` |
| `design_undo_web_document` | OPERATION (op-id required) | same |
| `design_redo_web_document` | OPERATION (op-id required) | same |

### `lumen_api/toolbelt/turns.py` — turn enqueues (2)

| tool | replay | reason codes |
|---|---|---|
| `design_start_agent_turn` | OPERATION (op-id required) | `design_run_exists` |
| `design_start_web_turn` | OPERATION (op-id required) | + `design_document_not_found`/`_not_web`/`_finalized` |

`durable_identity` on both says it plainly: the run id is minted per request so each execution is
a new run row, but the OFFER side is domain-idempotent underneath — `enqueue_task` dedups on
`dedup_key = str(work_id)`, and the work id is derived from the run id, so the run row and its
fleet task cannot diverge and a re-offer of the same work id is absorbed rather than duplicated.

**DOMAIN-key else-branch, stated honestly at every site:** the caller-supplied id is REQUIRED on
the tool input and the ROUTE mints one when the client omits it. So the domain key protects a
caller that names its own id (which is the only caller that can meaningfully retry); when the
route mints a random id, two requests are two identities and only a same-operation (journal + A9)
retry replays.

## Deviations from R-D6-B2's suggested inventory, argued

1. **No `design_revert_document`.** Revert owns no durable mutation of its own — it is N undo
   steps, and each step's engine round-trip depends on the scene the previous step wrote. A
   single tool would have to run N engine calls inside itself (forbidden by R-D6-B4) or write N
   envelopes from an off-store scene chain. Instead `/revert` loops the SAME governed
   `design_undo_document` the `/undo` route uses, each step with its own operation id and its own
   base version — so a concurrent edit mid-revert stops the revert with the standard 409 instead
   of quietly rewinding past it. Documented at the route.
2. **`design_record_diagnostics`, not `design_record_brand_governance`.** Brand governance is one
   *caller* of `store_diagnostics`, not its family: six call sites share that one append-only
   write (PUT /scene's structural-validation failure, the preflight error branch, both export
   branches, brand governance, finalize's core-error branch). Naming the tool after one caller
   would have left the other five ungoverned — against the D6 gate — or governed by a tool whose
   name lies about what it writes. One kind-parameterized tool (closed `KINDS` set, enforced as a
   precondition) is the honest one-tool-per-operation-family reading.
3. **Undo/redo were NOT collapsed** into a direction-parameterized tool (R-D6-B2 permitted it).
   Kept separate per doc kind so the journal names the gesture (`design_undo_document` vs
   `design_redo_document`) without an operator decoding the envelope. The durable write is shared:
   `RedoDocumentTool` subclasses `UndoDocumentTool` and `RedoWebDocumentTool` subclasses
   `UndoWebDocumentTool`, differing only in name/description/`_checkpoint_label`/`_direction`.
   Same for `design_apply_edits`, which subclasses `design_apply_operations`.

## /export vs /preflight: the cores DO unify

Checked as R-D6-B2 asked. The two writes were already identical apart from **one string**: same
scene, same diagnostics, same operation-list shape, same `source="system"`, same
`actor_kind="system"`, same `diagnostic_kind="preflight"`, same effective-brand rule. The only
difference is the envelope's **`actor_id`** — `"preflight"` vs `"export_preflight"`. So
`design_persist_preflight` takes that as a parameter (closed set, precondition-checked) and
`main._persist_preflight` is the one call shape both routes use.

**This is also where the one real implementation bug of the round was caught by the suite**: the
positional call `update_document_state(..., "system", "system", "preflight", "preflight", ...)`
is `(source, actor_kind, actor_id, diagnostic_kind)`, and the first draft of the tool read the
third slot as `source` — which is a `design_op_source` enum column, so every preflight/export
persist 500'd with `invalid input value for enum design_op_source: "preflight"`. Six `test_api.py`
tests caught it immediately. The tool's input field is now named `actor_id`, which is what the
column is.

## Route wiring (all in `lumen_api/main.py`, all inside `create_app`)

New shared helpers, added beside Round A's `run_design_tool`:

- `_document_refusals(document_id)` — the exact wire bodies for `design_document_not_found`
  (→ `NotFoundError`), `_not_scene`/`_not_web` (→ 409 `document.kind_unsupported`), `_finalized`
  (→ 409 `document.finalized`), `_exists` (→ 409 `document.exists`), `_kind_unsupported` (→ 422).
- `_snapshot_refusals`, `_finalize_refusals` — the above plus their own domain-key 409s.
- `_base_version_conflict(conflict)` — the CAS's 409, byte-identical to `require_base_version`.
- `_apply_scene_operations(...)` — the one call shape for `design_apply_operations`/`_apply_edits`.
- `_persist_preflight(...)` — the one call shape for /preflight and /export's persist half.
- `_effective_brand_payload(...)` — the ported "persist the effective brand when asked, and always
  when the resolution had no document-level opinion" rule, in one place.
- `_record_diagnostics(...)` — the one diagnostics-append call shape (six callers).
- `_derive_web_document(...)` — the one derive-persist call shape; the **batch loop now calls it
  too** (it previously reproduced the persist inline — same fix Round A made for `_publish_web`).
- `_snapshot_after_write(...)` — the optional post-write snapshot on /operations, /edits and
  /brand-kit. A SECOND governed invocation rather than a field on the state tool: it is a second
  durable write with its own domain key, and folding it in would make the state advance's replay
  policy a lie about one of its two effects.

The worker persist (`execute_web_turn_job`, ~7300) routes through `_turn_design_tools(host)
.invoke("design_apply_web_operations", …, actor="agent", actor_id=envelope.run_id)`. Its
operation-replay verification stays in the worker and stays loud — it is a precondition on
trusting the agent's own history and it needs the engine.

## Response-shape compatibility

Every converted route keeps its exact body and status. Mechanism unchanged from Round A: the tool
returns references, the route re-reads the row (every DAL write ends in its own `get_*` read-back,
so the projection is identical by construction). Two routes read straight off the tool's reference
instead (`agent-instructions`, `layout-managed-editing` — the tool returns the stored value), which
is the same value the re-read would give.

Three intentional micro-changes, all recorded at their sites and all strictly safer:

- POST /documents with a caller-supplied **duplicate `document_id`** was a 500
  `database.error` (an IntegrityError through the sqlite3 handler). It is now a typed 409
  `document.exists` that writes nothing. No test covered the 500.
- POST /snapshots with a duplicate caller-supplied `snapshot_id` — same change, 409
  `snapshot.exists`.
- POST /finalize with a duplicate caller-supplied `template_revision_id` — same change, 409
  `template_revision.exists`.

## Ripples (exactly as Round A did them)

- `platform/api/clue_api/agent_registry_wiring.py` — 20 new `C6_AGENT_TOOL_AUTHORITY` entries, all
  `()`, and 20 new `_RESERVED_REASON` rows (`design_agent_not_wired_until_part_iii`).
- `tests/api/test_toolbelt_wiring.py` — 20 `_MATRIX` rows + 20 `_bodies()` entries; counts
  56 → **76** names, 63 → **83** addresses.
- `tests/agents/test_tool_authority_audit.py` — 56 → **76**.
- `tests/api/test_agent_registry_wiring.py` — 63 → **83** addresses, and the reserved design set
  extended to all 28.
- `lumen_api/toolbelt/factory.py` + `__init__.py` — the 20 new types/exports. Verified the package
  is still import-light (`import lumen_api.toolbelt` pulls no fastapi / clue_design / PIL /
  playwright).
- `tests/test_write_path_governance.py` — 11 store methods + 2 operation cores moved into
  `_GOVERNED`; `UNCONVERTED_MUTATIONS` shrunk to Round C's list plus the dead-code
  `set_document_account`. New `test_the_document_gate_predicates_are_one_contract` pins the
  toolbelt's restated `scene_status_kind` / `is_finalized_document` equal to `main`'s (same
  reasoning as the publish-slug pattern pin — the toolbelt may not import `main`).

## New tests

`subsystems/clue-design/apps/api/tests/test_design_toolbelt_documents.py` (8):

1. `test_the_scene_cas_refuses_a_writer_whose_base_version_moved` — **the CAS-closure proof**.
   Two writers, one 409, proved BELOW the handler: both invocations go straight to the tool with
   the base version writer A read, so `require_base_version` never runs; writer B lands, writer A
   is refused by the DAL, and the assertion checks both the version AND that no history envelope
   was appended.
2. `test_the_route_still_answers_a_stale_base_version_with_its_documented_409` — the pre-check and
   the CAS are one contract.
3. `test_undo_carries_the_version_it_read_into_the_write` — stale undo refuses; live undo lands.
4. `test_a_keyed_snapshot_replays_instead_of_creating_a_second_row` — the **DOMAIN replay proof**
   (`replayed=True`, identical references, exactly one `design_snapshot` row).
5. `test_a_new_operation_against_a_taken_snapshot_id_is_refused_not_duplicated` — the domain key's
   real guarantee: an UNKEYED re-run refuses rather than writing.
6. `test_a_taken_document_id_is_a_typed_refusal_not_a_500`.
7. `test_the_web_turn_worker_persists_through_the_governed_tool` — **the worker-persist
   governance**: the offered turn's ENQUEUE journals with `execution.started_by = human` and its
   PERSIST with `started_by = agent` (REQ-20 parity), and the persist node reaches
   `node.completed`.
8. `test_the_web_turn_persist_honours_the_envelopes_base_version` — a human edit lands mid-turn;
   the turn's persist is refused by the CAS and the run resolves `conflicted` with the human's
   version intact.

## Verification (fresh MIGRATED throwaway DBs; `alembic upgrade head` before every suite)

- `tests/design/ tests/fleet/` — **171 passed** (Round A baseline 171).
- The four registry/guard suites (`tests/api/test_toolbelt_wiring.py`,
  `tests/agents/test_tool_authority_audit.py`, `tests/api/test_agent_registry_wiring.py`,
  `tests/api/test_journaled_invocation_roots.py`) — **35 passed**. Gate 1 total **206**, exactly
  Round A's number.
- Design `tests/test_api.py` — **127 passed** (the six preflight/export failures the enum bug
  caused are fixed).
- New Round B tests — **8 passed**; `test_write_path_governance.py` — **6 passed** (5 + the new
  predicate-parity test); `test_design_toolbelt.py` (Round A) — **10 passed**.
- `uv run mypy` — clean, **591** files. `uv run ruff check` — clean. `ruff format --check` — the
  known **23** pre-existing files, zero overlap with D6 files. `uv run lint-imports` —
  **25 kept, 0 broken**.
- No migration added → no `db-smoke` needed; `alembic heads` = `ad332dc38f36` alone.
- **Full design-API suite** (canonical invocation `uv run pytest tests` from
  `subsystems/clue-design/apps/api`, fresh migrated DB `clue_d6b_full`) — **525 passed / 9
  skipped / 0 failed**, `EXIT=0`, 534 collected. Round A's wall-to-wall baseline was 516/9/0 over
  525 collected; +9 = the 8 new `test_design_toolbelt_documents.py` cases plus the new
  predicate-parity case in `test_write_path_governance.py`. (The suite prints no count line under
  `-q`; these are the progress marks counted, with `EXIT=0` and zero `FAILED` lines.)
- **Design agent-runtime suite** (`apps/agent_runtime/tests`, run SERIALLY) — **551 passed /
  2 skipped**, exactly the baseline.
- **Offline platform suite** (`uv run pytest` from the repo root, no `CLUE_DATABASE_URL`) —
  **2199 passed / 1530 skipped**, exactly the baseline.

## Known environment flake (not a code defect)

Running the design **agent-runtime** suite concurrently with the design **API** suite makes
`test_web_substrate.py::test_web_ops_rejects_invalid_batch` fail with an `OSError` spawning
`target/debug/lumen-api-helper` — two suites contending on the same helper binary. Run them
serially.

## What Round C inherits

- The two remaining ungoverned families are already written down in `UNCONVERTED_MUTATIONS`:
  **brand kits + assets** (`create_brand_kit`, `update_brand_kit_approval`,
  `create_brand_compatibility_report`, `create_asset_record`, `update_asset_status`,
  `delete_asset_record`, `register_scene_assets`) and **personalization + batches**
  (`upsert_binding_set`, `delete_binding_set`, `upsert_instance`, `create_batch`,
  `update_batch_progress`, `upsert_repair_request`, `create_web_batch`,
  `update_web_batch_progress`). Plus `set_document_account`, which is **dead code** (zero callers
  anywhere) — Round C should delete it or govern it, not leave it unlisted.
- The run EXECUTION lifecycle (`create_run`, `set_run_result`, `complete_run`,
  `append_run_event`) stays deliberately ungoverned: it is the execution plane, fenced by the
  fleet lease (the D5 contract), not by the toolbelt. Only the caller-initiated **enqueue** is a
  design mutation, and Round B governs it.
- The `lumen_ingestion/pipeline.py` brand-kit creation flagged by Round A (no idempotency key
  while the reaper re-offers jobs → a re-run re-creates brand kits) is still open and is a Round C
  brand-domain problem.
- `publishes.register_web_publish_revision`'s bare `ValueError` on a content mismatch (→ a 500) is
  still owed a typed refusal (Round A flag, unchanged).
- **Cost, recorded honestly.** Every governed design write now costs a private engine, ~5 short
  journal transactions, one parameter-artifact put, and (new in Round B) a **full-scene parameter
  snapshot** on the operation/edit/undo/redo/replace/preflight/derive paths — because R-D6-B4 puts
  the engine's output *into* the tool. The snapshot is content-addressed, so a re-send dedups, but
  POST /operations is the editor's hot path and this is the round's real performance cost. The fix,
  if it becomes a problem, is a per-loop engine cache in `wiring._ainvoke` and/or a size threshold
  on the parameter snapshotter — never a weaker journal.
