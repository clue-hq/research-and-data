# 2026-08-06 — M8D R1 active-path quarantine

## Outcome

Implemented and accepted M8D R1 on `platform/c8-account-profiling-integration`.

New entity-research work now has one fail-closed reason:
`entity_research_agent_not_composed`. The per-run DEEP composition raises it before scheduling the
old account orchestrator. Exact historical entity tool addresses are replay-only: a completed
journal/idempotency record replays, while every cache miss fails before the historical body.

## Composition removed

- No production account-research `create_deep_agent()` runtime/profile.
- No production pre-agent Exa Deep account preparer.
- No production Sumble committee preparer or mechanical contact preparer.
- No old deep scheduler/supervisor/provider-preparation constructor seams.
- No active universal coverage-controller path or automatic account-to-contact progression.
- `account-research-unit-v1` remains loadable from disk but is not seeded as a system recipe.

Provider transports, durable operations, snapshots, claims, evidence, governance, discovery
providers, and lifecycle workers were retained. The lifecycle workers can drain accepted durable
operations but cannot originate new quarantined entity-research work.

## Verification

- R1 quarantine/composition/registry/toolbelt/recipe battery: green (DB-dependent tests skipped
  where configured).
- Ruff over all R1 source/tests: green.
- Mypy over the seven R1 source files: green.
- Accepted Exa, Sumble, deep, contact-research, coverage, resolver, durability, and claim regression
  selection: green/skipped, no failures.
- Repository-wide run exposed one unrelated authority-schema failure:
  `approve_contact_research_selection@1` includes trusted workspace/project fields in its
  model-facing schema.
- The database-backed DSAR rerun reached Postgres but failed fixture bootstrap because the shared
  database has an older `core.work_email` definition than unrelated current worktree edits. This is
  database/schema drift, not an R1 behavioral failure.

## Durable references

- `docs/specs/M8D-R1-active-path-quarantine-acceptance.md`
- `platform/api/clue_api/entity_research_quarantine.py`
- `tests/api/test_m8d_r1_entity_research_quarantine.py`

## Next boundary

R2 may install the subject-neutral account/contact fleet job contract. It must replace the loud
quarantine deliberately; it must not restore any old preparation or automatic progression path.
