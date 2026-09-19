# 2026-09-12 — project context files (plan 1 of the context + ICP-authoring set)

Branch `research-streaming`, worktree `san-salvador`, lane DB `clue_san-salvador`. Plan
`docs/superpowers/plans/2026-09-12-project-context-files.md`; spec
`docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md` §4.1.
Commits `0e7f6da72` (migration `6c54be5199c8`), `e1b410675`, `5354d933a`, `91b77a327`, fix wave `434858f0e`.

## What shipped

Every production Head-of-ABM turn now seeds two read-only files beside the brand folder and indexes
them in L3:

- `inputs/project/status.md` — compiled from ARV2 rows only (`project_icp_pin`, `project_product`,
  `project_account`, `arv2_discovery_run` + candidates, `arv2_research_run` + jobs). Title names the
  project. Sections: Confirmed ICP, Products, Plan, Accounts, Discovery (asked/found/verified/shown/
  approved), Research (per run, per account job with person-job count; an account with only person
  jobs in a run renders `person research only`), Project documents (empty until plan 2).
- `inputs/project/decisions.md` — the current-effective `project_state` statements
  (`volunteered_statement`, latest-correction-wins) with quotes resolved from the captured input
  artifacts; an erased artifact drops the item.
- Pin: `agent_turn_project_files` (insert-once per turn, append-only, bare-hex digest). Bytes are
  persisted as artifacts with project binding `project_context_file`; a retry reads the pin and
  never recompiles; digest verified at read (`ProjectFilesPinConflict`).
- L3 card `ProjectFilesIndexCard@1` (`card_kind = "project_files_index"`, materialized at
  `context/project/project_files_index.json`): path, workspace path, kind, version, status, literal
  summary. The brand card is untouched.
- Modules: `platform/api/clue_api/project_status.py`, `platform/api/clue_api/project_context_files.py`
  (`project_workspace_path` is the ONE rule mapping a document row path to its workspace path:
  `project/plan.md` → `inputs/project/plan.md`, `audience/icp-x.md` → `inputs/project/audience/icp-x.md`);
  wiring in `agent_turn_fleet_wiring.py`. `clue_api.arv2.discovery_store` now exports
  `SHOWN_DISPOSITIONS` / `PENDING_DISPOSITION`.

No profile/skill/recipe change: plan 2's skill v23 §1 tells the agent to read the two files.

## Verification

Offline/DB (lane DB): `tests/db/test_arv2_project_files_pin_migration.py` (4),
`tests/api/test_project_status.py`, `tests/api/test_project_context_files_db.py`,
`tests/api/test_o6_conversation_composition_db.py` (incl. retry-stability of the project pin),
`tests/api/test_brand_knowledge_context_db.py`, `tests/arv2/test_discovery_store_db.py`,
`tests/arv2/test_import_guard.py` — green; ruff/mypy/lint-imports clean. Pre-existing red when
`.env` is sourced: `tests/api/test_fleet_wiring.py::…discovery_handler…` and
`tests/arv2/test_discovery_driver.py::…not_composed_without_the_flag…` (the real key leaks into the
"keyless" fixtures) — not this work.

Final Opus review: 0 Critical / 4 Important / 6 Minor / 5 Nit; all Important + M1/M2/M4/M5/M6/N2/N5
fixed in `434858f0e`. Parked: M3 (the project-files block holds one pooled connection while
`persist_body` / `artifacts.read` open a second from the same pool — same shape as the knowledge
block; bounded by pool 5+10 vs 3 slots × 2; revisit if slots or pool are retuned), N3, N4.

**Live proof (Task 5) owed:** API twins + workers restarted on this code 2026-09-12 afternoon. The
founder sends one message in a NEW thread of an existing project, then:

```sql
SELECT turn_id, jsonb_array_length(files), files_sha256 FROM agent_turn_project_files ORDER BY pinned_at DESC LIMIT 1;
```
expect one row with 2 files; the turn inspector's context tab lists
`context/project/project_files_index.json`; the agent, asked "where does this project stand?", names
the pinned ICP and the research state.

## Rulings taken during execution (ledger `.superpowers/sdd/2026-09-12-project-context-files/`)

A `summary_of` exported once; B test helper uses `dataclasses.replace`; C decisions loader gets a DB
test; the `project` FK anchor is `project (project_id, workspace_id)` (plans corrected); F the one
workspace-path rule above.
