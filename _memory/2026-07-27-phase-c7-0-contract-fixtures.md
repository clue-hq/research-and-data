# Phase C7.0 closeout — contract freeze and executable fixture map

**Date:** 2026-07-27
**Branch:** `platform/c7-research-views`
**State:** C7.0 complete; C7.1 prerequisite hardening next

## Outcome

- Added `clue_core.research_view`: frozen strict contracts for exact account/contact subjects,
  direct/derived statements, ordered support refs, independent verification/freshness/conflict/
  display/outreach state, capability-only evidence actions, semantic sections, owner references,
  governed personalization, provenance index, status/coverage summaries, account/contact DTOs,
  reference-only compose/read/re-check outputs, entailment request/result, and reader/composer/
  snapshot/judge protocols.
- Added `clue_core.research_view_species`: the executable section→authority map, the exact
  nine-block compatibility adapter, and legacy dossier aliases delegating to one research-view
  surface.
- Exported the shared vocabulary from `clue_core`; all models are frozen and `extra="forbid"`.
- Added sanitized account/contact frontend manifests and a five-case adversarial map under
  `tests/fixtures/research_views/`.
- Added unit/architecture tests for contract strictness, target lock, support shape, product scope,
  hidden-value leakage, evidence capability shape, display/outreach governance, source ownership,
  block compatibility, reference-only outputs, fixture completeness, and current contract-level
  adversarial failures.

## Important boundaries

- C7.0 did not add `ClaimFlavor.DERIVED`, a DB enum, migration, derivation table, tool handler,
  reader, composer, route, event, or runtime behavior.
- `ClaimFlavor.DERIVED` and immutable claim-store representation remain C7.2 work.
- The inconsistent-pronoun/identity-content fixture is assigned to the C7.3 target-lock resolver
  and C7.8 adversarial eval. A structural schema cannot honestly infer semantic identity conflict.
- Wrong statement subject, wrong-account activity reference, sensitive outreach, and cross-product
  bleed fail at the C7.0 contract.
- Identity, execution, score, committee, coverage, and activity items are reference-only; only
  claim/derivation sections may carry `ResearchStatement` values.
- `compose_dossier@1` remains a compatibility alias to `research_view.compose`; no second
  implementation or document body is authorized.
- Existing `account_handoff.payload` remains unchanged; C7.4 must replace it with references or
  prove subject-indexed legacy purge/rebuild before C7 closeout.

## Files

- `libs/clue-core/clue_core/research_view.py`
- `libs/clue-core/clue_core/research_view_species.py`
- `libs/clue-core/clue_core/enums.py`
- `libs/clue-core/clue_core/__init__.py`
- `tests/unit/core/test_research_view_contracts.py`
- `tests/unit/core/test_research_view_fixtures.py`
- `tests/architecture/test_research_view_species.py`
- `tests/fixtures/research_views/*`

## Verification

- C7.0 tests: 32 passed.
- Shared-core + C7 contract selection: 44 passed.
- `uv run ruff format --check libs subsystems platform tests scripts`: 788 files formatted.
- `uv run ruff check libs subsystems platform tests scripts`: passed.
- `uv run mypy`: 422 source files, no issues.
- `uv run lint-imports`: 24 contracts kept, 0 broken.
- `uv run pytest`: 1,565 passed, 1,083 skipped in 15.90s on the final run.
- `git diff --check`: passed before closeout documentation.

`make check` itself stops at Ruff because the pre-existing untracked `.claude/` and `.codex/`
skill copies contain 16 CLI `print` calls outside the repository's Ruff per-file exclusions. Those
user-owned files were not changed. The same lint, type, contracts, and test gates passed over the
tracked project scope as listed above.

## Next exact entry

C7.1 starts with the named C8 prerequisite tests and smallest required hardening:

1. joint merge/corroboration/research-view conflict equality;
2. retention-expired fail-closed selection/composition;
3. one-way `faithfulness_verdict.rationale` DSAR redaction;
4. evidence-access authorization protocol enforcement before any `presign` consumer;
5. explicit product-fit/contact-class consumption contract.

Do not start C7.2 derivation migrations until C7.1's named gates are green.
