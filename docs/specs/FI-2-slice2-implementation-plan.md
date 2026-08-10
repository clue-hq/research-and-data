# FI-2 Slice 2 Implementation Plan — C7 lineage convergence

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development — same process as slices 0–1 (Opus implementer + reviewer, fix rounds, orchestrator commits between tasks).

**Goal:** FI-2 §9 slice 2 (as amended by the §7 MVP ruling): the C7 research-view `allowed_run_ids` suppliers migrate from hand-assembled `(project_run_id, account_run.id)` tuples to `run_lineage`, so the platform has exactly ONE claim→project attribution mechanism; plus the substrate-level lens-isolation guarantee test. The deferred project-lens detail endpoints stay deferred (post-MVP; no frontend surface asks).

**Scope guard (lane registry §1.2):** this touches `platform/api/clue_api/research_view_readers.py` (and the other `allowed_run_ids` suppliers found in `research_view_runtime.py` / `research_view_governance.py`) — FI-2's reserved territory. C7's CONTRACTS must not change: the acceptance bar is byte-identical view output before/after.

## Global constraints
- Read first: `docs/specs/FI-2-workspace-account-layer.md` §3+§9-slice-2; `_memory/2026-08-08-fi2-slice0-complete.md` §"Slice-1 handoff" (mixed run-id space; exemption classes); the C7 read family in `claimstore/research_view_queries.py` (`context_scope='project_run_pinned'` filtering, `:230-235`, `:321-327`).
- `run_lineage` read helpers live in `clue_research/claimstore/run_lineage.py` (`project_run_ids(conn, *, workspace_id, project_id)`); if the C7 suppliers need a per-project-RUN variant (runs attributed to one `project_run_id`), add it there with tests — additive only.
- NO C7 contract/route/flag changes; NO migrations expected (head `870fe4f2af87`); byte-identical outputs are the gate; per-branch throwaway DB; TDD; commit local only, no attribution, never push.

### Task 1: supplier migration + equivalence proof
**Files:** modify the `allowed_run_ids` supplier sites (locate all via grep — study citations: `research_view_readers.py:268-272,300-304`, `research_view_runtime.py:79`, `research_view_governance.py:175-206,577`); possibly add a `runs_for_project_run(conn, *, workspace_id, project_run_id)` helper to `run_lineage.py`. Tests: extend the C7 suites + a new equivalence test.
**Steps:** (1) Write the equivalence test FIRST: over a fixture with a composed C7 view (reuse the C7 suites' fixtures), capture the view payload with the legacy tuple supply, then with the lineage-backed supply — assert byte-identical JSON. Include the M8D-shaped case: claims whose run_id is a per-tool-call derived id (registered in lineage with the project) that the legacy `(project_run_id, account_run.id)` tuple did NOT include — decide and document the ruling: if lineage supplies MORE runs than the legacy tuple (it will, for M8D-derived runs), the view's `project_run_pinned` sections may legitimately gain claims that were invisible before. That is a FIX, not a break — but it must be a deliberate, tested, documented delta, not a silent one; capture it as an explicit second assertion (the delta is exactly the derived-run claims) and record it in the C7 section of the report for the founder. (2) Migrate each supplier to one shared lineage-backed function (DRY — one supplier, N call sites). (3) Full C7 suites + the slice-1 frontend_read suites (they must be untouched) + `tests/integration` green.

### Task 2: substrate lens-isolation test
**Files:** `tests/claimstore/test_run_lineage.py` or a new `tests/claimstore/test_lens_isolation.py`.
**Steps:** the spec §9-slice-2 AC: a query-layer test proving the lineage predicate isolates P1's relative claims from P2's on one shared account (two projects, relative claims under each, neutral claims shared) — asserted at the SQL/predicate level (not through an endpoint), so the guarantee outlives any read surface. Plus: the exemption classes (manual/redaction, NULL-project) behave as documented (never appear in either project's lens).

**Sequencing:** Task 1 then 2 (2 is independent but cheap; keep order for ledger simplicity). Non-goals: project-lens endpoints, economics (slice 3), any C7 contract change.
