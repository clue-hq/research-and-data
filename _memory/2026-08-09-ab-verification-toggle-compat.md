# 2026-08-09 — A+B landed: M12/Lane-E compatibility with the runtime verification toggle

Implements `docs/specs/FI-M12-verification-toggle-compat.md` (RATIFIED 2026-08-08) on
`platform/frontend-integration`, from the primary integration worktree per the §7 demarcation
ruling (Lane E consumes the contract only). TDD throughout — every behavior red-proofed first.

## What landed

### B — the tier-4 merge gate is verification-aware at one chokepoint
- `claimstore/merge.py::active_merge_policy(settings=None)` — the effective default merge policy.
  Enabled (default) returns `DEFAULT_MERGE_POLICY` **by identity** (bit-for-bit unchanged);
  disabled returns a policy with only `require_verified_tier4=False` flipped. `exclude_rejected`,
  `exclude_weak_binding` stay `True`, `fallback_to_unpromotable` stays `False` in both modes.
  Zero-arg form reads `load_settings()` live (no cache — monkeypatching the env in tests works).
- Every production read that defaulted to `DEFAULT_MERGE_POLICY` now resolves `policy=None` →
  `active_merge_policy()`: `merge.current_value/current_values/provenance_index`,
  `research_view_queries.current_values_resolved_for_product/current_field_claims_resolved_for_product`,
  `identity/review.current_value_resolved`, `review/projection.py` score read, and
  `clue_api/contact_eligibility.py` (resolved once per contact). An explicit passed policy is
  untouched. `DEFAULT_MERGE_POLICY` remains exported (it *is* the enabled-mode policy).
- Import note: `claimstore` → `clue_config` is contract-legal (verified against the
  import-linter contracts; 25 kept). The dormant `clue_config.schema.MergePolicy` seam is still
  bypassed — acknowledged debt riding the existing [M9.2×M0.4] backlog item.

### A — write paths and handoff tolerate a missing judge
- `Positioner.__init__` accepts `judge: FaithfulnessJudge | None` (still a required kwarg — the
  composition root must decide). `judge=None`: claim written and left at its **born** status,
  `claim_support` still written, `ref.judge_verdict=None`, and
  `METRIC_NARRATIVE_JUDGE_SKIPPED = "research.narrative.judge_skipped"` emitted (persona attr).
  Judge present ⇒ behavior unchanged (whole suite green).
- `HandoffAssembler(verification_enabled: bool = True)`: enabled keeps the VERIFIED-only
  narrative read; disabled admits unverified (non-REJECTED) narrative claims. The actual per-claim
  `verification_status` rides the wrapper as `AssembledHandoff.narrative_verification`
  (`{claim_id_str: VerificationStatus}`, populated in both modes) — the frozen core
  `ValueNarrativeItem` was NOT edited (extras-ride-the-wrapper pattern, like
  `narrative_citations`). The JSONB materialization (`handoff_store` dumps/validates the whole
  wrapper) carries it automatically; old rows validate via the default.
- `narrative_wiring.build_handoff_assembler(..., verification_enabled=True)` and
  `run_composition.py`'s HANDOFF construction pass `settings.verification_enabled` through.
- **Positioner has zero production constructors** (verified again) — so there was no
  `judge=None` composition site to change; the optional-judge contract + the `_rp_judge`
  precedent is what E3 wires against.

## Verification
- New tests (each watched fail first): 4 in `tests/test_merge_policy.py` (accessor + disabled-mode
  merge semantics incl. REJECTED/WEAK still excluded), 1 DB test in `tests/claimstore/test_merge.py`
  (defaulted `current_value` flips with the env in one txn), 1 in `tests/narrative/test_positioner.py`
  (judge=None: unverified claim + support + skip metric), 1 in `tests/narrative/test_handoff.py`
  (disabled assembles unverified w/ status; REJECTED never; strict default unchanged), 1 in
  `tests/api/test_run_composition.py` (composed HANDOFF assembler follows the toggle, both states).
- Suites on a fresh throwaway DB (pgvector:pg16, this worktree only): merge/claimstore, narrative
  (positioner 28, handoff, service, research views), run-composition, handoff wiring, C7 cutover,
  verification handler, identity, review, frontend_read — all green.
- `make typecheck` (583 files clean), `make contracts` (25 kept), ruff check+format clean on every
  touched file.
- **Broad-sweep attribution (do not re-derive):** a full `pytest -q` against one shared throwaway
  DB showed 31 failures, but re-running every suspicious suite (waterfall, discovery_scoring,
  durable, fleet-composed, db-migrations, project-lens-backfill) on **fresh** DBs at baseline
  (`git stash`) and with the change produced **byte-identical failure sets** — only the two
  documented pre-existing `tests/test_project_lens_backfill.py` failures. The rest of the 31 were
  shared-DB contamination artifacts (e.g. `SourceManifestRedefinitionError: source 'clay' already
  registered` — committed rows from earlier suites), plus the three documented pre-existing
  failures (workspace-rename token guard tripped by a `.context` attachment, clue-design logging
  discipline, stale Stage-0 skill path in agent-registry wiring). Nothing introduced.

## For Lane E (the consumer)
- `prose.py` must be born honoring the same optional-judge rule (§3-A): skip + its own skip
  metric when `judge=None`; E1/E2/E3 acceptance runs validate with `CLUE_VERIFICATION_ENABLED`
  in both states. E1's disabled-mode acceptance now passes the merge gate via
  `active_merge_policy` — no Lane-E edit to `merge.py` needed or permitted (demarcation §2.5).
- Rebase/cherry-pick this change into `platform/lane-e-prose-synthesis` **before E1**.

## Notes / follow-ups
- `active_merge_policy()` calls `load_settings()` per invocation (precedent:
  `clue_config.gateway.get_config`); resolved once per outer read call, negligible next to the DB
  round-trip. If it ever shows up hot, cache behind the same accessor.
- The `[C8§6c]` claim-id-keyed verdict readers (`narrative/support.py::read_faithfulness_citation`,
  review composition) are untouched — that backlog item still stands.
- The handoff `_read_value_narrative` "no project filter" known gap (FI-2 §6.4) is unchanged and
  still documented in place.
