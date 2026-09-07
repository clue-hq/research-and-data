# 2026-09-07 — ARV2 onboarding O1 + O2 executed (SDD, two parallel worktrees) — CLOSE-OUT

Plans: `docs/superpowers/plans/2026-09-07-arv2-onboarding-o1-substrate.md`,
`docs/superpowers/plans/2026-09-07-arv2-onboarding-o2-exa-agent-surface.md`. Base `c279c3bfe`.
Execution: Opus implementers, one per task; every review by Fable first-hand (no reviewer subagents).
SDD ledgers + per-task reports + review packages kept (evidence) under
`.superpowers/sdd/2026-09-07-arv2-onboarding-o{1,2}-*/` (git-ignored) in this workspace and the worktrees.

## Branches to merge (Aryan merges; nothing pushed)
- **O1** `onboarding/o1-substrate` @ `2c0d7aa77` — worktree `~/.claude/worktrees/semarang-o1` (8 commits).
  Migration `0aa95f87eb49` ← `44039cb83844` (single head): onboarding_run/step/document (+ workspace
  anchors + composite FKs), project_product (append-only; FKs on the spine's existing anchors),
  gate kind `product_set_selection` (CHECK union + answer trigger; downgrade text == 064ad0f43519),
  7 `CLUE_ONBOARDING_*` settings + `ONBOARDING_SYNTHESIS_AGENT_MODEL*` env lines, spine
  `ProjectProductSet` + confirm/current/list, `KIND_PRODUCT_SET_SELECTION` + gate-id derivation,
  GATE_KINDS↔DB-CHECK parity test. Smoke green twice on throwaway `clue_o1_substrate`; checklist
  items 3/7 pass; Persona enum untouched. **If D1 lands first: `alembic merge` the two heads.**
- **O2** `onboarding/o2-exa-agent-surface` @ `96d2ed313` — worktree `~/.claude/worktrees/semarang-o2` (6 commits).
  `ExaClient.agent_run` (create/poll/settle, Bearer auth, effort price reserved on create, metered
  settle, failures/timeouts returned never raised), `onboarding_requests.py` (overview schema ==
  contract §2.3 verbatim; reviews; per-product; persona-evidence within /search limits),
  `onboarding_documents.py` (KnowledgeDocument, YAML front matter, fixed H2s, grounding→sources,
  catalog per-product provenance; pyyaml explicit dep), guards + README + memory. Offline 298 green,
  mypy 0, ruff clean. **Live evidence: one low-effort Agent run — completed, 14 polls, $0.025.**
Both branches are fast-forwardable onto `integration/design-improvement` @ `c279c3bfe`.

## Rulings made on the founder's behalf (undo any that are wrong)
1. Local `.env` parity: the nine new onboarding lines appended to semarang + both worktree `.env`s.
2. O1 T2: workspace anchors — UNIQUE (run_id, workspace_id) / (step_id, workspace_id) + composite FKs
   so a step/document can never point at another workspace's run/step.
3. O1 T3: the brief's `product_identity_triple`/`project_identity_triple` indexes were redundant
   (FKs bind to `product_context_anchor` / `project_run_context_anchor`) — removed.
4. O1 T4: `GATE_KINDS` additive (keep plan_approval/budget_approval); brief's 4-tuple was a slip.
5. Test money rule: never `make check` / full pytest with real keys in `.env` — live tests spend;
   use `--ignore-glob='*_live.py'`; DB suites on the throwaway DB only.
6. O1 T5: throwaway DB residue (fleet_task rows, then ~25 tables incl. a legacy global-domain
   index violation) — reset via DROP/CREATE SCHEMA public on `clue_o1_substrate` only.
7. O2 final: mypy narrowing limited to `company_overview_document`; the per-product `.get(key)` loop
   stays (explicit nulls are the front-matter contract).

## Not this lane — listed for triage
- Repo-wide ruff red: two merge migrations (`6eff96862040_*`, `7247c55459c4_*`, I001/F401, from `03658501c`).
- `ruff format --check platform/api` red on `chat/composer_context.py`, `chat/schemas.py` (pre-existing).
- Six lane-D4-neighbourhood tests fail on base (`option_b_acceptance`×2, `model_planned_kickoff`×3, `lane_bd_join`).
- `tests/db/test_db_migrations.py` assumes an empty DB while sibling suites leave rows (reproducible on base).
- `tests/api/test_pilot_budget_controls.py` leaves `fleet_task` rows behind.

## Deferred minors (by design / cosmetic)
Effort settings are `str` (agent_run_body refuses unknown efforts); non-int `usage.searches` → 0;
unrated product → `grounding_confidence` None; the live test prints nothing (cost read from the
ledger); the plan's `-k` subset naming; the R1 client's docstring still says "nine properties".

## Next
O3 (fleet driver; needs D1's `provider_call_ledger` for production sinks) ∥ O4 (synthesis agent;
needs D1's `user` Persona role) ∥ O5 (Knowledge read surface, fixtures first) — per the plan §9.

## Addendum — D1 merged in (2026-09-07, merge commit `071f0fc84`)
`origin/integration/design-improvement` carried track-D (PR #46, ARV2 D1: display substrate migration
`65fb2128c904`, lenient claim writer, answer-key loader, `Persona.USER`, five `CLUE_*` check flags).
Merged into the local branch; three keep-both conflicts (`.env.example`, `clue_config/settings.py`,
`clue_api/arv2/README.md` — both lanes appended blocks at the same spot). Alembic went to two heads
(`0aa95f87eb49` O1, `65fb2128c904` D1) → join revision **`3742d1281a10`** (ruff-fixed template
imports). Verified: one head; up→down→up on `clue_o1_substrate`; `tests/arv2 tests/clue_spine
tests/db` + the product-set gate test green offline (`--ignore-glob='*_live.py'`); `clue_semarang`
upgraded to `3742d1281a10`. Local `.env` gained the five D1 keys. Both O3/O4 plans now name
`3742d1281a10` as the head to chain off; the D1 dependencies (`provider_call_ledger`, `user`
persona) are no longer "watch" items — they are on the branch.
**Not fixed, pre-existing:** the local `.env` is missing ~20 other `.env.example` keys (ARV2 R1/R2,
C7, frontend-read, memory flags) — parity drift older than this session; fix deliberately, not by
blank-stamping secrets.
