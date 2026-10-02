# 2026-09-07 — ARV2 onboarding O1: substrate landed

Plan: docs/superpowers/plans/2026-09-07-arv2-onboarding-o1-substrate.md (spec: ARV2-ONBOARDING-PLAN.md §3, §6, §10).
Branch `onboarding/o1-substrate` (worktree `~/.claude/worktrees/semarang-o1`), off `c279c3bfe`.

- Migration `0aa95f87eb49` off `44039cb83844`: onboarding_run / onboarding_step / brand_knowledge_document;
  project_product (append-only, composite same-brand FKs); gate kind product_set_selection +
  redefined agent_gate_answer_validate (downgrade text proven identical to 064ad0f43519).
- Settings: seven CLUE_ONBOARDING_* fields + ONBOARDING_SYNTHESIS_AGENT_MODEL lines (parity tests green).
- Spine: ProjectProductSet, confirm_project_product_set / current_project_product_set / list_project_product_sets.
- Gate: KIND_PRODUCT_SET_SELECTION, product_set_selection_gate_id (`platform/api/clue_api/agent_gate.py`).
- Two fix rounds during the lane:
  1. `6bf29e302` — anchor onboarding_step and brand_knowledge_document to their **parent's workspace**
     (composite FKs + unique anchors), so a child can never point at a row in another workspace.
  2. `623b61652` — drop the **redundant identity-triple indexes** on project_product; its FKs rely on the
     spine's existing anchors instead. (The template's "identity triple indexes" phrasing describes the
     pre-fix shape; the landed migration deliberately does not create them.)
- Verification: `alembic heads` = 1 (`0aa95f87eb49`); db-smoke on the throwaway DB **green** —
  `downgrade base` → `upgrade head` twice, no error, ending at a single head; scoped tests
  **76/76 pass** on a freshly-emptied DB; ruff clean over the O1 scope; standing-rule checklist items
  3 and 7 pass; Persona enum untouched (D1's) — `git diff c279c3bfe...HEAD -- libs/clue-core/clue_core/enums.py`
  is empty. `make check` was deliberately NOT run (real provider keys in `.env`; the full suite makes
  paid calls) — the scoped command in the task brief was run instead.
- Not done here (by design): the driver (O3), the gate tool + route (O6), the frontend (O5).
- Alembic merge with D1: **not needed at this time — single head.**

## Throwaway DB residue — what blocked the smoke, and the pre-existing test-isolation defect

The lane's throwaway DB `clue_o1_substrate` is what the worktree `.env` points at. It was **not virgin**
— it carried residue from earlier test runs on it, which blocked the down-to-base leg twice over:

1. **Two `fleet_task` rows of kind `entity_research_job`** (`claimed_by` = `pilot-budget-on` /
   `pilot-budget-off`, claimed 2026-09-07 14:53:48Z). Left by **`tests/api/test_pilot_budget_controls.py`**
   (it claims fleet tasks at lines 261 and 317 and never cleans them up). These tripped the pre-existing
   data guard in `022b1154b3aa_m8d_r2_entity_research_jobs.py` (from commit `7d8ffb124`):
   `cannot downgrade M8D R2 while entity_research_job fleet tasks exist`. Deleted per coordinator ruling
   (`DELETE FROM fleet_task WHERE kind = 'entity_research_job'` — no table FKs onto `fleet_task`, so no
   cascade was needed).
2. **Deeper residue then surfaced a second blocker**: multiple `account_entity` rows sharing
   `primary_domain = 'example.com'` across different workspaces. That is legal under today's
   workspace-scoped uniqueness, but the `82a80fb80c9e` downgrade recreates the **legacy global** unique
   index `account_entity_primary_domain_key`, which then fails with `UniqueViolationError`. Residue spanned
   ~25 tables (216 claims, 18 workspaces, 18 account_entity, …), so table-by-table deletion across ~200
   downgrades was unbounded. Resolved by resetting the throwaway DB to empty —
   `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` then `alembic upgrade head` — which reaches the same
   end state the plan's `createdb`/`dropdb` intended **without creating or dropping a database**
   (only schema `public` existed; the `vector` / `pg_trgm` extensions are recreated by the chain).

After the reset the smoke is green and the scoped tests are 76/76.

**Pre-existing defect worth knowing (NOT O1's, do not "fix" as part of Track O):** the three
`tests/db/test_db_migrations.py` tests (`test_up_down_up_is_clean`, `test_no_domain_tables_at_m0_head`,
`test_downgrade_to_base_drops_the_vector_extension`) each downgrade to base and therefore **require an
empty database**, but sibling DB-backed tests in the same command populate it and never clean up. So:

- On a freshly-emptied DB the full scoped command passes **76/76**.
- Run the *same* command a **second consecutive time** without emptying the DB and those three fail on
  the `account_entity_primary_domain_key` unique violation described above.

This is a test-isolation weakness, not a migration defect — reproducible on the base commit, independent
of O1. **Operational rule for this lane: empty the throwaway DB before any run that includes `tests/db`.**
The lane DB was left reset to a clean `0aa95f87eb49` head.
