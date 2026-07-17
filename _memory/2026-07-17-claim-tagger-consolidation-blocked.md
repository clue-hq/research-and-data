# 2026-07-17 — claim_tagger consolidation attempt: STOPPED (divergences a pre-insert hook can't express)

Task: the PA-A2 DRY item 4 / harness §4.1 `claim_tagger` pre-insert hook on
`sources/waterfall.resolve_field`, letting `profiling/contact/fill.py` rejoin the shared engine.
Outcome: **no code changed.** The fill loop diverges from the waterfall in ways a
`Callable[[Claim], Claim]` hook cannot express, and one existing test cannot pass unchanged
without weakening a deliberate waterfall guarantee. Details (file:line refs verified today):

1. **Tier-mismatch fail-loud vs an oracle test (hard blocker).**
   `waterfall.py::_finalize` (136–139) raises when `claim.source_tier != manifest.tier`
   ("a resolver lying about its tier would corrupt the merge trust order").
   `tests/profiling/contact/test_fill.py::test_fill_writes_lower_tier_weak_unpromotable` (142–176)
   binds a tier-**3** `FakeFacetResolver` to `exa_deep`, whose seeded manifest is tier **4**
   (`sources/seeds.py:178–187`). Under the shared engine that test raises `ValueError`.
   No clean reconciliation: normalizing the claim tier to 4 would then trip fill's tier-4-WEAK
   target-lock drop (claim never written → test still fails); relaxing the check corrupts the
   engine for every caller.

2. **Per-source pre-spend gate (no waterfall seam).** `fill.py:158–173` gates each source
   pre-resolve at that source's manifest tier; REJECT skips *that source* and the walk continues.
   The waterfall has no gate hook (budget envelope only). The aspect-worker precedent
   (`profiling/aspect_worker.py:367–389`) gates once per *field* before `resolve_field` —
   adopting it changes REJECT granularity (kills the whole field) and the `gate_decision` audit
   rows. `tests/api/deep/test_gate_routing_ac6.py::test_deep_contact_facet_fill_records_a_gate_decision`
   pins that the contact facet spend records a gate decision.

3. **Per-claim drop = changed stop semantics.** `fill.py:194` rejects a tier-4 WEAK claim
   *before* write (Decision 13; pinned by `test_fill_rejects_tier4_same_name_stranger`).
   A `Claim -> Claim` tagger can't drop; widening to `Claim | None` also requires moving the
   waterfall's confident-stop + `TierStep` accounting (`waterfall.py:319`, `first_confident_claim`
   over the *raw* resolver claims) onto the post-tagger kept set — otherwise a dropped 0.9-confidence
   claim still yields `CONFIDENT_HIT` with nothing written. That is exactly the "different stop
   semantics" stop-clause.

4. **Secondary drifts** (unpinned by tests today, but real): fill resolves a manifest-less /
   unregistered source (`fill.py:158`, `prior=None`, no gate) where the waterfall skips it as
   UNREGISTERED/INACTIVE (222–231); fill checks `get_resolver` *before* the idempotency read
   (unbound → never reuses) vs waterfall's reuse-before-binding order; cost semantics
   (waterfall charges the manifest cost on an empty result (317–318) and counts idempotent-reuse
   cost in the total; fill sums written claims only — an all-dropped paid call would also charge 0);
   `FacetFillResult.profile_views` is built per-claim at insert — reconstructable post-hoc from
   `claim_refs` (Claim.id is client-generated, `claim.py:98`) but extra machinery.

What a real consolidation needs (if re-attempted): hook type `Callable[[Claim], Claim | None]`
applied pre-`_finalize`-insert with the confident/step accounting moved to kept claims; a
`pre_spend_gate` seam (or per-field gating decision + audit-semantics sign-off); a ruling on the
tier-mismatch guarantee vs the tier-3-fake fixture (probably: fix the fixture to register a real
tier-3 source — but that breaks "tests pass unchanged"); planner injection is already solved by
precedent (`aspect_worker.py:392–396` `field_def.model_copy(update={"tier_plan": plan.tier_plan()})`).
