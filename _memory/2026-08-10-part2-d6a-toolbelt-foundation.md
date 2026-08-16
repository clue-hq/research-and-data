# Part II D6 Round A — design toolbelt foundation + three reference domains

Branch `platform/design-integration`, on top of `0d12ddb9` (D5 close). Contract:
`docs/specs/PD-part2-design-substrate.md` slice D6 — gate: *every design mutation behind a
registered, precondition-checked, idempotency-keyed tool*. Round A = the foundation plus
publishes / web accounts / custom components. Documents+scene, brand, assets, ingestion and
personalization are Rounds B/C and were not touched.

## What landed

### New — the design toolbelt (`subsystems/clue-design/apps/api/lumen_api/toolbelt/`)

- `base.py` — `DesignToolHost` (the design app's collaborators as **thunks**, resolved at invoke
  time because the suites mutate `app.state` and monkeypatch `main.compile_custom_component`
  *after* `create_app`) and `DesignTool` (owns the `design_runtime_not_configured` refusal and the
  `asyncio.to_thread` hop that runs the synchronous operation core off the invocation loop).
- `publishes.py` / `accounts.py` / `components.py` — the eight tools + their operation cores.
- `factory.py` — `DESIGN_TOOL_TYPES` / `DESIGN_TOOL_NAMES` / `build_design_tools(host)`.
- `wiring.py` — `DesignToolInvocations`: a REAL `clue_toolbelt.ToolInvoker` over the SAME durable
  tables the platform uses; plus `design_tool_host(...)`.
- `__init__.py` is **deliberately light** (clue_toolbelt + pydantic only; verified: importing it
  pulls no fastapi / clue_design / PIL / playwright). That is load-bearing — see "always
  registered" below.

### New — the platform seam

- `platform/api/clue_api/design_tools.py` — `build_design_tools(*, enabled, storage)`; lazy-imports
  the lumen factory, `DesignRuntimeUnavailable` when unimportable. Fanned into
  `build_toolbelt` (unconditionally; live only when `design_runtime_enabled` + a storage backend).

### Changed

- `platform/api/clue_api/toolbelt_wiring.py` — the fan-in.
- `platform/api/clue_api/agent_registry_wiring.py` — 8 `C6_AGENT_TOOL_AUTHORITY` entries, all `()`
  (granted to NO role until Part III; comment says so at the site).
- `lumen_api/main.py` — `app.state.design_tools`; the `run_design_tool(...)` shim; the seven
  converted routes; `_publish_web` (one publish call shape) used by BOTH the HTTP route and the
  batch loop `_derive_publish_account` (which previously duplicated the whole publish sequence
  inline); `_turn_design_tools(host)` for the turn path.
- `lumen_api/agent_custom_components.py` — `DurableAgentCustomComponentRegistry` now takes
  `invocations: DesignToolInvocations` instead of the compiler knobs, and its two durable writes
  go through the same two component tools with `actor="agent"` (R-D6-5).
- Tests: `tests/api/test_toolbelt_wiring.py` (matrix + bodies + counts),
  `tests/agents/test_tool_authority_audit.py` (count + all-design-are-`()`),
  `apps/api/tests/test_agent_custom_components.py` (new registry ctor).

### New tests

- `apps/api/tests/test_write_path_governance.py` — the no-bypass guard (R-D6-6).
- `apps/api/tests/test_design_toolbelt.py` — refusals, keyed replay, journal/A9 landing.

## Tool inventory (name → replay policy → reason codes)

| tool | replay | reason codes |
|---|---|---|
| `design_publish_web` | OPERATION_IDEMPOTENT (op-id required) | `design_publish_slug_invalid`, `design_document_not_found`, `design_document_not_web`, `design_publish_slug_taken` |
| `design_unpublish_web` | DOMAIN_IDEMPOTENT (status assignment) | `design_publish_not_found` |
| `design_rollback_web_publish` | OPERATION_IDEMPOTENT (op-id required) | `design_publish_not_found`, `design_publish_no_previous` |
| `design_create_web_account` | DOMAIN_IDEMPOTENT (caller-supplied `account_id`) | `design_account_exists`, `design_account_logo_unresolved` |
| `design_update_web_account` | DOMAIN_IDEMPOTENT (value assignment) | `design_account_not_found`, `design_account_patch_invalid`, `design_account_logo_unresolved` |
| `design_delete_web_account` | OPERATION_IDEMPOTENT (op-id required) | `design_account_not_found` |
| `design_write_component_source` | DOMAIN_IDEMPOTENT (`ccsrc_<sha>` + version CAS) | `design_account_not_found`, `design_component_source_invalid` |
| `design_compile_component` | OPERATION_IDEMPOTENT (op-id required) | `design_component_not_found` |

All eight: `ToolEffectClass.WRITE`, `ExternalReplayBoundary.NONE` (the node compiler is a local
subprocess, not a provider), typed reference-only `ToolOutput`, and
`design_runtime_not_configured` when no host is composed.

## Rulings taken, and two deliberate deviations

**Deviation 1 — the tools are ALWAYS registered in the platform registry (R-D6-1 said "empty
tuple when disabled").** `build_agent_profile_registry` enforces
`set(registry.names()) == set(C6_AGENT_TOOL_AUTHORITY)` exactly. Absent-when-disabled makes that
audit environment-dependent and turns flipping `design_runtime_enabled` into an `AgentCatalogError`
at composition (`stage0_trial`). It is also incompatible with R-D6-4's demand that the count
assertions be bumped: the count test builds `build_toolbelt(storage=None, gateway=None)` with the
switch off. So the shape is present-but-refusing (the `research_view_tools` shape), and the switch
controls whether the tools are **live**, not whether they **exist**. Documented at both sites.
Consequence, recorded as a residual: `clue_api` now runtime-requires `lumen_api.toolbelt` to be
importable. It is a light module and `subsystems/clue-design/apps/api` is a uv workspace member,
but `clue-api`'s `pyproject.toml` does not declare `lumen-api` (exactly as it does not declare
`clue-fleet`, which `lumen_api.fleet_handler` has needed since D5). **Reviewer decision needed:**
add the packaging dependency, or keep the workspace-provides-it status quo through Part-I Step-2.

**Deviation 2 — `design_compile_component` is OPERATION_IDEMPOTENT, not DOMAIN_IDEMPOTENT on the
`ccart` id.** The artifact IS content-addressed and re-registering is a no-op, but every attempt
also appends a fresh `cccmp_<uuid4>` compilation record (deliberately — that table is the attempt
log). DOMAIN_IDEMPOTENT would be a true statement about the artifact and a false one about the
compilation record. Same reasoning downgraded `design_publish_web`: its revision row is
content-addressed and insert-or-no-op, but `upsert_web_publish` rotates current→previous in the
same statement, so a *new* operation with identical content still burns the one-step rollback
buffer (pre-existing; `previous_available` flips, and the route contract depends on it, so D6
declared the truth rather than changed the behaviour).

## How the invoker composition differs from `build_tool_invoker`

`lumen_api/toolbelt/wiring.py` imports the platform primitives (`ToolInvoker`,
`CanonicalParameterSnapshotter`, `DbInvocationJournal`/`DbExecutionJournal`, `DbIdempotencyStore`)
— only the *composition* is local, because `lumen_api` may not import `clue_api`. Two real
differences:

1. **Per-invocation engine, not the process-global one.** `build_tool_invoker` takes
   `clue_db.transaction` (the `db_lifespan` engine). The design request path deliberately never
   enters that lifespan (the O5 rule — one engine/connection/transaction per call, bound to this
   call's loop). So `_ainvoke` creates a private engine for its own loop and hands the journal /
   A9 store / artifact store independent transactions from it; each still commits independently.
   The workspace row is ensured first (the `execution.workspace_id` FK).
2. **The run-event transport is a documented no-op.** `build_tool_invoker` wires
   `ExecutionRunEventWriter → clue_research.durable.emit_run_event`. Design must not import
   research internals, and a design invocation has no `project_run` to key that outbox on. The
   *journal* is written in full; only the SSE outbox projection is skipped, because design still
   has its own `design_run_event` stream. **D7 retires that stream and unifies the two** (the
   master plan's `subject_kind`/`subject_id` widening) — minting a design-specific transport now is
   exactly what D7 would have to unpick. `execution_id` is threaded (automatic via `ToolInvoker`).

Also: `StorageParameterArtifactStore` is re-implemented as `_DesignParameterArtifactStore` (same
`{workspace_id}/{sha256}` key, `source_key='tool_parameters'`, row-before-blob) because the
original lives in the app layer.

The public shim is **synchronous** (`DesignToolInvocations.invoke`) — design routes are `def`, and
the agent registry is called from a worker thread. It uses the same `asyncio.run`-on-a-loopless-
thread hop as `DesignStoreBridge._run_isolated` and dies with the rest of the O5 scaffolding at
Part IV / Part-I Step-2.

## The no-bypass guard's mechanical rule

`apps/api/tests/test_write_path_governance.py`. For each **governed name**, every call site under
`lumen_api/` + `lumen_ingestion/` must be in that name's allowlist:

- **store mutations** (attribute call `.<name>(`) — allowed in `design_store.py` (the definition)
  and anywhere under `lumen_api/toolbelt/`;
- **operation cores** (bare call `<name>(`, `def` lines excluded) — allowed in their defining
  module and under `lumen_api/toolbelt/`;
- the two component store mutations additionally allow their own operation-core module, so the
  chain route/agent → tool → core → store is closed end to end.

Route handlers, the batch loop, `fleet_handler`, `fleet_reaper`, the ingestion pipeline and the
agent gateway are excluded by construction; a regression names the file and line. Rounds B/C
extend `_GOVERNED` — one dict. Companion tests: every governed name exists on
`HybridRepository`/the core modules; `UNCONVERTED_MUTATIONS` lists the still-ungoverned methods
explicitly (so "what is left?" is a fact in the tree); `DESIGN_TOOL_NAMES` is pinned; and the
publish-slug regex restated in `toolbelt/publishes.py` is asserted equal to `main`'s.

## Response-shape compatibility

Every converted route keeps its exact body and status. Mechanism: the tool returns references and
the route re-reads the row it needs. The three write DALs (`create_web_account`,
`create_custom_component_source_revision`, `record_custom_component_compilation`) already return
via their own `require_*` reader, so re-reading is byte-identical by construction. Refusal reason
codes are mapped back to the legacy bodies by the `refusals=` dict on `run_design_tool`; the
`PreconditionFailure.message` strings were written to equal the pre-D6 messages verbatim
(`web_publish.bad_slug`, `web_publish.slug_taken`, `web_publish.not_found`,
`web_publish.no_previous`, `web_account.exists`, `web_account.logo_unresolved`,
`custom_component.source_invalid`), and `NotFoundError` is re-raised (not hand-built) where the
app-level handler already produces the body. Evidence: `test_web_accounts` (14),
`test_custom_components`, `test_custom_component_compiler`, `test_custom_component_publish`,
`test_agent_custom_components`, `test_web_export`, `test_web_documents`, `test_web_batches` all
green with unchanged assertions.

Two intentional micro-changes, both documented at their sites:

- `POST /web/accounts` now 409s on a duplicate id even when the id was *minted* (previously only
  when caller-supplied). Practically unreachable (uuid4) and strictly safer.
- the `web_publish_unpublished` log event no longer carries `document_id`/`publish_id` (the tool
  returns slug+status). Logs, not a contract.

## Verification

Fresh MIGRATED throwaway DBs (`alembic upgrade head` before every suite — an unmigrated DB is
~319 design failures).

- `tests/design/ tests/fleet/` — **171 passed** (baseline 171).
- `tests/api/test_toolbelt_wiring.py` + `tests/agents/` + `tests/api/test_journaled_invocation_roots.py`
  — **194 passed**.
- Offline platform suite (`uv run pytest`, no `CLUE_DATABASE_URL`) — **2199 passed, 1530 skipped**
  (baseline exactly).
- Design agent runtime (`apps/agent_runtime/tests`) — **551 passed, 2 skipped** (baseline exactly).
- New design tests — **15 passed** (`test_design_toolbelt.py` 10 + `test_write_path_governance.py` 5).
- Registry: 48 → **56 names**, 55 → **63 addresses**; authority map 48 → **56**; the HEAD_OF_ABM
  capability disclosure 55 → **63 addresses** (a third count assertion the brief did not list —
  `tests/api/test_agent_registry_wiring.py`).
- `uv run mypy` — clean, 591 files. `uv run ruff check` — clean. `ruff format --check` — the known
  23 pre-existing. `uv run lint-imports` — **25 kept, 0 broken** (no contract edit needed:
  `lumen_api` is not a root package, and neither T1 nor S4 is touched).
- Design tree: `ruff check --isolated --select F,E9` clean over `lumen_api/` and the new tests.
- `invoke_tool(` guard: still zero hits under `platform/api`, `platform/execution`, `subsystems`.
- Full design-API suite (canonical invocation, fresh MIGRATED throwaway DB) — **501 passed,
  9 skipped, 0 failed** over all 510 pre-existing tests, exactly the D5 baseline. That run was
  collected before the two new design test files existed, and the tree has since changed by
  exactly one unreachable edit (`_publish_refusals` now takes the document id instead of the slug
  and additionally maps `design_document_not_web`); the covering re-run over
  `test_web_export` + `test_web_batches` + `test_custom_component_publish` + the two new files is
  **42 passed**. A second wall-to-wall run including the new files was still in flight when this
  note was written — the host was swap-thrashing (load ~6.5, 10.7M swapins) and the suite had
  slowed ~5x; re-run it before landing if you want the single-number version.
- No migration added → no db-smoke needed.

## What Rounds B/C inherit

- The foundation is done: `DesignToolHost`, `DesignTool`, `DesignToolInvocations`, `run_design_tool`,
  the platform seam and every registration ripple. A new tool = a class + a `factory.py` entry + an
  authority entry + a matrix entry + two count bumps + one `_GOVERNED` line.
- The still-ungoverned mutation list is already written down in `UNCONVERTED_MUTATIONS`.
- **Flagged for Round B/C (from the write-path recon):** `lumen_ingestion/pipeline.py` creates
  brand kits on the worker path with no idempotency key while the reaper re-offers jobs — a re-run
  re-creates brand kits. `design_store.update_document_state` silently drops `expected_base_version`
  that `clue_design.documents` accepts (a scene-path TOCTOU). `HybridRepository.set_document_account`
  is dead code (zero callers). `publishes.register_web_publish_revision` raises a bare `ValueError`
  on a content mismatch that nothing catches → a 500 (now inside a tool, so it is at least
  journaled as a failed attempt; a typed refusal is still owed).
- Performance: every governed design write now costs a private engine plus ~5 short journal
  transactions plus one parameter-artifact put. Acceptable, but the design suite got noticeably
  slower; if it becomes a problem the fix is a per-loop engine cache in `wiring._ainvoke`, not a
  weaker journal.
