# 2026-08-07 — Part II slice D2.1 executed: workspace entry + DAL foundation

## What landed (branch `platform/design-integration`)
- **R3 workspace entry:** `subsystems/clue-design/apps/api/pyproject.toml` (dist `lumen-api`,
  hatchling, packages `lumen_api` + `lumen_ingestion`) + an explicit exact-path member entry in
  the root `[tool.uv.workspace]` (the `subsystems/clue-design` exclude stays). The app depends
  on `clue-design` (workspace), so it can import the design substrate; verified
  `import lumen_api` + `import clue_design.*` from the root venv.
  - **Deliberately NOT declared:** the agent-runtime trio (`deepagents`/`langchain-anthropic`/
    `langchain-openai`) and `rich` — they belong to `apps/agent_runtime`, are lazy-imported
    (API answers `agent_runtime.unavailable` without them), and their pins are Step-2's "one
    version story" (deferred to D5/Step-2 on purpose).
  - **`pypdf` dropped as a dead dep:** the legacy `requirements.txt` pinned `pypdf>=4.2,<6`,
    which conflicted with `clue-research`'s `pypdf>=6` in the one lockfile — but NOTHING in
    the design tree imports pypdf (all PDF work is `fitz`/pymupdf). Removed rather than
    treaty'd; comment at the pin site.
  - **`py_lumen_config`/`py_lumen_obs` stay PYTHONPATH-provided** (`PYTHONPATH=
    subsystems/clue-design`, as the design run scripts already do) until Step-2 folds them
    into clue-config/clue-obs. Their third-party deps (pydantic-settings, python-dotenv,
    structlog) are declared on `lumen-api` so the runtime env is complete.
- **DAL foundation in `clue_design`:**
  - `errors.py` — `DesignStoreError` / `DesignNotFoundError` (fail-closed: foreign-workspace
    and absent ids raise the SAME refusal — the toolbelt `run_not_found` precedent) /
    `DesignVersionConflictError` (CAS; scene docs gain it in D2.2).
  - `sequences.py` — `allocate_envelope_seq` / `allocate_operation_sequence` /
    `allocate_run_event_seq`: `SELECT … FOR UPDATE` on the parent row (`design_document` /
    `design_agent_run`), then `COALESCE(MAX)+1` over the child. O5 atomicity rule stated as
    binding contract in the module docstring: allocation + the insert that uses it = ONE
    transaction on ONE connection, never split across `asyncio.run` bridge calls.
- **Tests** (`tests/design/test_dal_foundation_db.py`, DB-gated): gapless + independent
  counters; foreign/absent parent → identical `DesignNotFoundError`; run-event allocator; and
  the concurrency proof — writer B demonstrably BLOCKS on the parent lock (~300ms observed)
  until writer A commits, then allocates 2.

## Verification
ruff format/check clean; mypy clean (572 files); 25 contracts kept; offline pytest 2176
passed; design suite **10/10** (6 D1 + 4 D2.1) against a fresh throwaway DB (`clue_d2_dal`,
migrated to head by the suite fixture, dropped after). `uv sync` resolves + installs
`lumen-api` into the root venv.

## Findings worth keeping
- **MVCC nuance in the concurrency test (first version was wrong):** a writer racing a parent
  that another transaction has inserted but NOT committed gets `DesignNotFoundError`, not a
  lock wait — the uncommitted parent is invisible. Correct, fail-closed semantics (you cannot
  append to a document you cannot see); the blocking behavior only applies to a COMMITTED
  parent. The test seeds-and-commits first, then races.
- The one-lockfile pin conflict surfaced exactly where predicted (Step-2 "one version story")
  — resolved trivially this time because the dep was dead; expect real treaties when
  `apps/agent_runtime` enters (deepagents/langchain vs platform pins) at D5/Step-2.

## Next: D2.2 (documents + history port)
Per the approved D2 plan: document/envelope/op-log/snapshot/revision/diagnostic DAL in
`clue_design`; scene-write CAS added; undo/redo against `design_edit_envelope` inverse
batches; the API's document endpoints switch onto it. Then D2.3 brand/assets/ingestion,
D2.4 personalization/web/components, D2.5 API switch + SQLite deletion.
