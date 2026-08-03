# C7.8 — adversarial, DSAR, performance, and repository closeout

## Outcome

C7.8 and C7 are complete on `platform/c7-research-views`. The closeout proves the structured
account/contact research-view story end to end without adding a rendered dossier truth store,
unsafe evidence/body cache, alternate research loop, fake committee reader, skipped handoff, or
direct presign path.

## Implementation

- Added six independent default-off settings:
  `c7_research_view_read_enabled`, `c7_snapshot_compose_enabled`,
  `c7_evidence_actions_enabled`, `c7_recheck_enabled`,
  `c7_production_handoff_enabled`, and `c7_legacy_dossier_alias_enabled`.
- Canonical HTTP routes are registered only for enabled capabilities. Legacy aliases additionally
  require the corresponding canonical read/compose flag. Tool preconditions fail with
  `research_view_feature_disabled`. Production handoff registers no handler while off; there is no
  fake-success fallback.
- Expanded the adversarial fixture to 18 exact cases: same-name/wrong-employer/wrong-account,
  identity conflict, sensitive/display-only personal facts, weak binding, workspace/product/role
  violations, injected evidence, and every stale/superseded/rejected/expired/erased/conflicted
  dependency state. Each case records expected outcome/reason and an existing collected test node.
- Added the 10-surface DSAR fixture map for direct/derived/rationale/artifact/snapshot/re-check/
  legacy handoff/cache/event/C6 history. Body-bearing legacy surfaces are purged/redacted;
  reference-only surfaces re-resolve or block cold replay. An architecture test forbids a C7 body
  cache.
- Reworked `DerivationDependencyResolver` from per-node support/claim reads to one support query
  per breadth level plus bulk visible/audit/tombstone/TTL/conflict reads. Limits remain depth 8 /
  128 nodes. The 25-node/24-support test resolves in at most seven SQL statements and proves an
  eight-node cap returns `dependency_node_limit`.
- Added `docs/runbooks/research-views.md`, closed the child/parent/spec-index/implementation-plan
  status, refreshed O11 with the implementation-close date, and reduced the C8 handoff to the one
  genuine residual: hard fencing on legacy project-run/research-domain writes before multi-worker
  production deployment.

## Verification

Clean isolated database:
`postgresql+asyncpg://clue:clue@localhost:5432/clue_c78_dares_20260728_01`.

- Targeted C7 DB/crash matrix across derivations, snapshots, re-check, HTTP/SSE, production
  handoff, DSAR/artifacts/C6 replay, and whole-run composition: 53 passed.
- Executable adversarial matrix: 16 parameter-expanded tests passed.
- Extended DSAR surface matrix: 10 passed.
- Full DB-enabled suite: 2,733 collected; 2,709 passed; 24 external-capability skips.
- Mypy: 434 source files, no issues.
- Import-linter: 24 contracts kept, 0 broken.
- Ruff: 888 tracked/new C7 Python files formatted and clean.
- Alembic: exactly one head `677607ec1cd1`; clean head → base → head passed.
- Stub research eval and verification mechanism-swap eval executed successfully; the latter
  demonstrated its expected fail-gate when the candidate regressed the faithfulness mechanism.
- `git diff --check`: green after documentation and memory closeout.

Commands:

```text
CLUE_DATABASE_URL=... .venv/bin/alembic upgrade head
CLUE_DATABASE_URL=... .venv/bin/pytest -q <targeted C7 DB files>
CLUE_DATABASE_URL=... .venv/bin/pytest -q <adversarial evidence nodes>
CLUE_DATABASE_URL=... .venv/bin/pytest -q <extended DSAR evidence nodes>
(git ls-files '*.py'; include new C7 test) | ruff format --check / ruff check
make typecheck
make contracts
make eval
make eval-verification
CLUE_DATABASE_URL=... .venv/bin/alembic downgrade base
CLUE_DATABASE_URL=... .venv/bin/alembic upgrade head
CLUE_DATABASE_URL=... .venv/bin/pytest -q
```

## Failures and caveats

- The shared default database was behind the C7 enum/schema head, so one attempted mixed-DB
  targeted command failed on the missing `claim_flavor=derived` enum. Verification moved
  immediately to the named clean isolated database; all final DB evidence is from that database.
- `make lint` includes the user-owned untracked `.claude/` and `.codex/` skill scripts, whose
  deliberate CLI `print` calls violate this repo's T201 policy. Those directories were not
  modified. The equivalent format/check gate across all 888 tracked/new C7 Python files is green.
- User-owned `.claude/`, `.codex/`, and
  `docs/architecture/clue-hq-research-model-surface.md` remain preserved and uncommitted.
- No live external model, Redis, or paid source was required; 24 existing external-capability tests
  skipped under their normal gates.

## Feature state and rollback

All six C7 activation flags remain default `false`. Rollback disables the exact route/tool/handler,
not migrations or immutable receipts. Never delete claims/history or reinstate a skipped handoff.

## Exact next handoff

C7 has no remaining implementation slice. C8 is not a miscellaneous feature phase: every
C7-dependent C8 prerequisite is closed. The only genuine Phase-C residual is to extend generation
fencing from C5 graph execution to the legacy project-run/research-domain write path before
multi-worker production deployment.
