# FI-2 Slice 3 Implementation Plan — the research economics (P4)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development — same process as slices 0–2.

**Goal:** FI-2 §6 (P4), the last slice: TTL-gated no-respend on project-neutral fields, project-scoped supersede predicates so a second project's research never destroys the first's lens, the provider-bundle shrink, and the Sumble freshness fixes — closed by the spec §9 slice-3 canonical economics fixture.

**Scope guard (lane registry §1.2 — all files reserved to FI-2):** `platform/api/clue_api/account_entity_research.py` (§6.1), `exa_deep_preparation.py` + `account_research_fleet_launch.py` (§6.2), `sumble_account_gaps.py` + `sumble_entity_research_tools.py` (§6.3), `subsystems/research/clue_research/narrative/{positioner,fields}.py` + `discovery_scoring/tiering/engine.py` (§6.4). Explicit non-goals (spec §6.5): no pre-spend-gate knob; no un-quarantining of M8A gap planners; no M9.5 cadence drainer.

## Global constraints
- Read first: `docs/specs/FI-2-workspace-account-layer.md` §6 (all of it — §6.1–§6.5 are the behavior contract) + §9 slice-3 AC; `_memory/2026-08-08-fi2-slice0-complete.md` + the slice-1/2 appendices in `_memory/2026-08-08-fi2-slice1-backend-complete.md`.
- The contact runtime's fresh-skip (`platform/api/clue_api/contact_entity_research.py:331-370`-era; verify live) is THE pattern for §6.1 — port it, don't reinvent: fresh + evidence-backed + conflict-free NEUTRAL fields born-complete, existing claim ids folded into coverage evidence, per-field reasons.
- Species via `resolve_research_scope` (never hardcode; `account.scoring.*` relative by prefix). Claim reads via `current_values` + `WorkspaceScope` (never `claim.workspace_id`).
- Within one project, supersession behaves exactly as today — §6.4 only stops CROSS-project destruction.
- TDD; per-branch throwaway DB (host 127.0.0.1:5432); no migration expected (head `870fe4f2af87`); commit local only, no attribution, never push; M9 verification toggle (`CLUE_VERIFICATION_ENABLED`) stays default-on in tests.

### Task 1 — §6.4 project-scoped supersede predicates (must land first: write-safety)
**Files:** `narrative/positioner.py` (`_live_for_persona` gains the project dimension; payload gains `project_id` riding `value_json` like `icp_key` — see `narrative/fields.py:62`'s "no icp column" precedent; update `fields.py` value schema), `discovery_scoring/tiering/engine.py::persist_tier` (payload + supersede predicate gain the project/run pin, aligning with the discovery-selection path that already pins). Committee: reads are lineage-based post-slice-2 — verify nothing in §6.4 remains for committee writes beyond the ledgered optional same-project supersede refinement; document the verdict.
**Tests:** P2 regenerating the narrative for the same (product, ICP, persona) COEXISTS with P1's (both live, each lens serves its own — assert through the lineage predicate); same-project regeneration still supersedes exactly as today; tier claims likewise. Red-first: today's cross-project supersession is the failing behavior to capture.

### Task 2 — §6.1 fresh-skip in the account entity-research runtime
**Files:** `platform/api/clue_api/account_entity_research.py` (the authorization/first-plan path — where `admitted`/`completed`/`unresolved` are computed from per-job field rows only). Port the contact pattern: one `current_values` read over admitted field keys; born-complete iff project_neutral AND fresh AND evidence span AND no open conflict; NEVER born-complete for project_relative (that is R3's second half); existing claim ids into the coverage ledger as evidence with per-field reasons (`existing_claim_fresh` / `existing_claim_stale` / `existing_claim_conflict`).
**Tests:** two-project fixture — P2's job on a P1-researched account starts with all fresh neutral fields completed (ledger cites P1's claim ids), all relative fields unresolved; a STALE neutral field stays unresolved (gets re-researched); a conflicted neutral field stays unresolved; contact runtime untouched (its suite green).

### Task 3 — §6.2 bundle shrink + estimate netting; §6.3 Sumble fixes
**Files:** `exa_deep_preparation.py` (born-complete fields excluded from the provider bundle; empty account-axis bundle ⇒ no operation reserved), `account_research_fleet_launch.py` (estimate recomputed net of skips — should-have, keep minimal and honest), `sumble_account_gaps.py` (stale-but-confident fields become ELIGIBLE — consult `freshness_state`, not just confidence/conflict) + `sumble_entity_research_tools.py` (the eligibility refusal becomes a governed skip/`EntityResearchGovernedRejection` on the M8D path, not an uncaught raise).
**Tests:** bundle excludes skipped fields (and the zero-field case reserves nothing); Sumble: stale+confident → eligible; fresh+confident → governed skip (not exception) on the M8D path; legacy tool path behavior preserved.

### Task 4 — the canonical economics fixture + slice close-out
**Files:** `tests/integration/test_fi2_slice3_economics.py`.
**The spec §9 slice-3 AC, end-to-end on the two-project fixture:** P2's launch on a fresh-researched account spends ZERO on neutral fields (coverage ledger cites P1's claims as evidence; no provider operation for an all-fresh account-axis), fully researches relative fields, and P1's narrative/tier/scores remain live and unchanged; a stale neutral fact is refreshed once and BOTH lenses see the refresh. Plus the full gate: touched suites + `tests/integration` + slice-1 frontend_read suites green; single head; honest attribution of any pre-existing failures.

**Sequencing:** 1 → 2 → 3 → 4 strictly (write-safety before economics; economics before the fixture that proves both). Ordering note from spec §9: §6.4 must land before any production second-project research run.
