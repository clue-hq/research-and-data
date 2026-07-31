# C7.5 — governed additive research-view re-check

## Outcome

C7.5 is complete on `platform/c7-research-views`. Stored views can now be re-checked additively
under current policy, optionally request bounded research through the existing durable operation
boundary, and emit body-free change/staleness events without mutating claims or old snapshots.

## Implementation

- Migration `9df19defc755` adds immutable `research_view_change_report`,
  `research_view_change_item`, `research_view_change_operation`,
  `research_view_section_staleness`, and `research_view_event` rows. They store only exact scope,
  reference ids, hashes, closed states, reason codes, and opaque fetch refs.
- `ResearchViewRecheckRequest` is a strict input contract. Its optional section selector is closed,
  unique, and canonical. Policy thresholds, prompts/models, source/field expansion, direct values,
  quality flags, and signed-link TTLs are not accepted.
- `ResearchViewRecheckService` live-resolves the old receipt, optionally requests one governed
  research operation, composes a new superseding receipt, compares body-free item state, and
  atomically appends the report/events. `get_report` resolves the opaque report fetch ref under
  exact workspace scope.
- Deterministic child ids make crashes after research request, after snapshot, and before report
  commit replay-safe. C7.4 snapshot idempotency also now checks the supersession target.
- `ResearchViewSectionStalenessService` traverses direct-item and derivation-support reverse
  indexes and appends `research_view.section_stale` without rebuilding synchronously.
- `recheck_research_view@1` is typed and operation-idempotent. Its API-root requester delegates
  through `ToolInvoker` to existing `run_deep_account@1`, preserving journal, budget, pre-spend,
  and admission ownership. Registry/HTTP activation is held for C7.7.

## Verification

- Focused snapshot/re-check suite: 18 passed.
- Focused C7/architecture/dependency pytest selection: 43 passed, 2 skipped.
- Clean full DB-enabled suite: 2,689 passed, 24 skipped.
- Mypy: 431 source files, no issues.
- Import-linter: 24 contracts kept, 0 broken.
- Ruff format/check: all 877 tracked Python files green.
- Alembic: single head `9df19defc755`; clean isolated head → base → head passed.
- Full offline migration SQL generation and `git diff --check`: green.

## Environment and failure notes

- Postgres.app on port 5432 was used because Docker was unavailable in the prior C7.4 session.
- The first full run had one outdated C7.0 fixture missing the now-required change-report hashes;
  updating it to the C7.5 contract left the implementation unchanged.
- Re-running the entire suite on that already-used database produced expected persistent-fixture
  and migration-downgrade failures. The suite requires a fresh disposable database; recreating it
  yielded the clean 2,689-pass result.
- Unrelated untracked `.claude/`, `.codex/`, and
  `docs/architecture/clue-hq-research-model-surface.md` remain preserved.

## Next handoff

C7.6 implements the production governed committee reader and real M12/C7 handoff emission. It must
reuse one contact-eligibility resolver across committee list, contact detail, handoff, and
personalization, and must prove product scope, weak-binding exclusion, erasure, and retry behavior.
C7.7 then activates the C7 tools/routes/events and completes the legacy handoff payload cutover.
