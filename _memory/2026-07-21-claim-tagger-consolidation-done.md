# 2026-07-21 — claim_tagger consolidation SHIPPED (fill rejoins the shared waterfall)

Implements the three founder-delegated rulings that unblocked the 2026-07-17 STOP
(`2026-07-17-claim-tagger-consolidation-blocked.md`). `profiling/contact/fill.py` no longer
re-implements the source walk — it drives `sources.resolve_field` through two new injected seams.

## The seams (types in clue_core/execution.py, exported from clue_core)
- `ClaimTagger = Callable[[Claim], Claim | None]` — applied in the waterfall AFTER `_finalize`
  (validation + provenance/manifest-prior stamping) and BEFORE `stamp_reuse`/`insert_claim`.
  `None` = dropped: not inserted, not surfaced. **Confident-stop + TierStep accounting
  (n_claims / best_confidence / confident / cost) moved to the KEPT set** (ruling 1) — a dropped
  0.9-confidence claim cannot produce CONFIDENT_HIT; an all-dropped paid step charges the manifest
  cost (same rule as an empty result). With `claim_tagger=None` behavior is byte-identical
  (kept == finalized claims; all pre-existing waterfall tests unchanged and green).
- `SourceGate = Callable[[SourceManifest], Awaitable[bool]]` — consulted per source after the
  resolver binding resolves, before the resolver call (reuse/unbound sources spend nothing → not
  gated, which exactly preserves the old fill's gate_decision row semantics). False → new
  `StepOutcome.GATE_SKIPPED`, walk continues. Gate impl (PreSpendGate.check + audit row) stays in
  fill.py's closure (AC-6 rows unchanged; `tests/api/deep/test_gate_routing_ac6.py` untouched).

## fill.py now
- Planner ordering via the aspect-worker precedent: `field_def.model_copy(update={"tier_plan":
  plan_keys})`.
- Manifest binding priors prefetched per planned source (the engine stamps a non-None prior on the
  claim, but the classifier must see None-vs-declared, so it can't read it off the claim).
- Tagger closure = today's `DefaultBindingClassifier` stamping + use-class tagging + the tier-4
  WEAK same-name drop (Decision 13). NOT upgraded to the M9.4 classifier (still the api-root
  injection, unchanged).
- `FacetFillResult.profile_views` reconstructed post-hoc from kept refs (`_profile_views` re-reads
  by client-generated Claim.id, in ref order).
- Engine semantics adopted (sanctioned): unregistered source → skipped (was: resolved ungated);
  idempotency read before resolver binding (was: after → never reused when unbound); cost =
  waterfall total (manifest cost on empty/all-dropped, reuse cost counted). No test pinned exact
  cost numbers, so no cost-expectation edits were needed.
- fill.py 231 → 244 lines (net +13): the walk is gone, replaced by closures/prior-prefetch/view
  reconstruction + fuller docstrings — the duplication of engine semantics is what was deleted.

## Test changes (all sanctioned / additive)
- `tests/profiling/conftest.py` — new `register_facet_source(conn, source_key="exa_deep", *,
  tier=4)`: registers the facet source at **version 2** (versioned in-txn update over the committed
  v1 seed; deterministic regardless of suite order; rerun-idempotent).
- Ruling-3 re-fixtures (tier-3 fake now behind a genuine tier-3 manifest, product assertions
  identical) in THREE places (the ruling named one; the same fixture bug existed in all three):
  `tests/profiling/contact/test_fill.py::test_fill_writes_lower_tier_weak_unpromotable`,
  `tests/api/test_governance_integration.py::test_injected_classifier_born_binding_weak_on_same_name`,
  `tests/api/deep/test_identity_binding_ac4.py::test_born_binding_weak_and_unpromotable_on_same_name`.
- Manifest registration added (no assertion changes) in: test_fill.py (5 tests), test_target_lock.py
  (2), test_worker.py (4), test_facet_subworkers.py (`_run_worker`), governance `_run_facet_fill`,
  ac4 `_profile_one_facet` (both grew a `manifest_tier` param).
- New waterfall tests (tests/sources/test_waterfall.py): tagger stamps the born-immutable
  identity_binding pre-insert; tagger-drop removes the claim AND does not stop the walk (kept-set
  accounting asserted); source_gate False skips exactly that source (GATE_SKIPPED) + both-hooks-None
  output equals a control run. Gotcha: the `_Fake` doubles carry fixed client-generated claim ids —
  a fake that writes in two runs collides on the claim PK; bind fresh fakes per written run.

## Verification (all green, 2026-07-21)
- ruff fix+format clean; `make check` exit 0 (1151 passed, 794 skipped, no DB).
- `make db-fresh` → full DB suite (1931 passed, 14 skipped) → AGAIN without reset (1931 passed) —
  rerun-idempotence holds.
- `make db-fresh && make db-smoke` exit 0.
- NOT committed (per instruction).

## Follow-ups / notes
- `resolve_fields` (the batch helper) deliberately does NOT thread the new hooks — no caller needs
  it; add when one does.
- StepOutcome is in-memory only (no DB enum), so GATE_SKIPPED needed no migration/parity work.
- The 2026-07-17 blocked note remains as the divergence analysis; this note supersedes its
  "no code changed" outcome.
