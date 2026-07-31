# C7.6 — production governed committee and handoff cutover

## Outcome

C7.6 is complete on `platform/c7-research-views`. Production HANDOFF now resolves the exact
project-run/product committee under identity, claim, retention, binding, and use-policy authority;
materializes the real M12 `AccountHandoff`; and appends the existing outbox event. The former
`narrative_emit_skipped` production writer is gone.

## Implementation

- `platform/api/clue_api/contact_eligibility.py` is the shared API-root join. Its
  `ContactEligibilityResolver` reads only the exact `account_run.references_index`, requires exact
  product scope, follows canonical account/contact survivors, excludes erased/inactive contacts,
  merges referenced role/persona/facet claims, requires strongly bound plausible membership, and
  attaches the latest claim use decision.
- Display and personalization are separate decisions over one governed result. The C7 committee
  adapter may show an eligible contact and display-safe research; both M12 adapters let the
  existing use/binding filters exclude outreach-denied hooks from positioning and handoff.
- Committee discovery, contact fill, scoring reads, narrative positioning, and legacy handoff
  assembly now thread `product_id`. Contact fill passes the product through the shared waterfall
  so tenant-private scope is stamped before product validation.
- `ComposingRunDriver` replaces the gap handler with the retention-wrapped real M12 handler and
  rejects run/ICP product-pin disagreement. Its LRU is now keyed by `project_run_id`, not ICP: two
  runs sharing an ICP cannot share a run-reference-bound committee reader.
- `build_handoff_phase_handler` gives its default readiness reader the same injected connection
  factory as materialization and outbox emission.
- Historical projections and tools still decode `narrative_emit_skipped` checkpoints for backward
  compatibility, but no production composition path writes the marker.

## Correctness coverage

- Eligible committee + verified narrative produces a materialized handoff and one outbox row.
- C7 committee references and legacy M12 handoff references agree.
- Weak membership is excluded; a merged loser redirects to the survivor; DSAR erasure excludes the
  contact.
- A displayable contact with an outreach-denied facet remains visible while the facet is not
  personalization eligible.
- Product A claims/narratives cannot enter product B; run/spec pin mismatch fails before
  composition.
- Empty committee completes honestly without the old gap marker.
- Publisher failure occurs after the durable transaction; replay returns the same logical handoff
  without duplicate materialization or outbox.
- Producer regressions prove product stamping on committee role/persona, contact facets, and value
  narratives. A cache regression proves two project runs with one ICP stay isolated.

## Verification

- Focused C7.6/M12/composition/profiling matrix: 98 passed.
- Clean final full DB-enabled suite: 2,696 passed, 24 skipped.
- Mypy: 432 source files, no issues.
- Import-linter: 24 contracts kept, 0 broken.
- Ruff format/check: all 881 tracked Python files and both new C7.6 files green.
- Alembic: single head `9df19defc755`; clean isolated head → base → head passed.
- `git diff --check`: green.
- First clean full DB-enabled suite reached 100%; one unrelated SIGKILL-recovery subprocess case
  exceeded its fixed 30-second timeout. The exact case passed immediately on rerun.
- The final clean full-suite rerun also passed that crash case.

## Failure notes

- Initial producer tests exposed two useful integration errors:
  - product-scoped claims require a real same-workspace product FK in fixtures;
  - contact-fill product stamping cannot happen in its pre-scope tagger. It now uses the
    waterfall's existing post-scope `product_id` seam.
- The adversarial cache audit found the pre-C7.6 ICP-keyed LRU could reuse one run-bound committee
  reader for another run using the same ICP. The cache is now project-run-keyed and regression
  tested.
- Unrelated untracked `.claude/`, `.codex/`, and
  `docs/architecture/clue-hq-research-model-surface.md` remain preserved.

## Next handoff

C7.7 activates the completed compose/get/re-check tools, HTTP routes, projections, and events;
switches live legacy handoff payload consumers to reference receipts; and retains only the explicit
compatibility surface required for historical rows/checkpoints.
