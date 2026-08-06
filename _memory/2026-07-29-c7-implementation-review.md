# C7 branch implementation review (multi-agent audit)

**Date:** 2026-07-29
**Branch:** `platform/c7-research-views` (full diff vs origin/main, ~21k lines)
**Method:** 11 finder angles (line-scan ×3, removed-behavior, cross-file, reuse, sweeper,
efficiency, altitude, conventions, spec-thoroughness) → 53 candidates → every candidate
adversarially verified by independent verifier agents; ~8 refuted.

## Verified-good

- 9/11 C7.8 closeout claims re-verified true in code: six default-off flags with real gating,
  no fake-success handoff fallback, derived claims excluded from factual current_value,
  bounded entailment reason codes, body-free snapshots (no value/span/rationale columns,
  append-only triggers, locator-rejecting validators), single presign consumer, recheck only
  via C5/C6 durable ops, live dependency invalidation incl. retention-expired supports
  (claims.py `_retention_eligible_sql` closes the pre-sweep window — tested), runtime
  depth/node caps. Migrations: hash ids, one head, reversible, enum parity. No import-boundary
  or commit-attribution violations.

## Confirmed gaps (report given to founder; none fixed yet)

1. **No production `StatementGovernanceReader` / no caller of `build_research_view_composer`**
   — read stack is Protocol + test stubs only; `c7_research_view_read_enabled` cannot actually
   be turned on without writing the production governance reader at the api root.
2. **C7-D7 use-policy bullet unmet:** DerivationDependencyResolver never reads
   `use_class`/`use_decision` of SUPPORT claims; composer governs only the derived claim
   (supports carried as bare ids). Use-disallowed support content can be laundered via a
   derived claim. derivations.py:558 / research_views.py:605.
3. **Retention/objection sweeps are narrower than interactive erase:** `sweep_expired` doesn't
   expand to derived dependents (dsar.py:747 vs erase path 659) and neither sweep purges
   legacy `account_handoff.payload` (only erase:546 / objection:613 do). No tests cover either.
4. **Multi-product blind spots:** review projection reads persona/role product-blind
   (projection.py:256) while worker product-stamps; supersede predicate allows dual live fit
   claims (claim_writes.py:61); `research_view_change_report` has no product_id so the status
   projection attributes a recheck cross-product (clue_projections/research_views.py:112);
   account_handoff UPSERT key lacks product (latent).
5. **Entailment judge strict JSON parser** (entailment.py:144) rejects fence-wrapped valid
   verdicts (faithfulness `_first_json_object` already solved this); whole judge harness is a
   parallel copy of faithfulness.py.
6. FLAGGED derived claim returns REVIEW_REQUIRED before support aggregation → masks REDACTED
   support state (derivations.py:432); no served leak provable today (no prod governance
   reader); missing adversarial fixture FLAGGED+erased-support.

## Simplification debt (confirmed by verifiers)

- research_view.py: status_summary/provenance_index required-then-revalidated (derivable from
  sections; make computed).
- 4-way statement/item-id union-walk duplication + snapshots importing private names from
  research_views (_VIEW_NAMESPACE etc.).
- ~50-line subject-auth SQL duplicated tools vs API (3 input-contract divergences already).
- Evidence capability broker `resolve()`/_prune dead surface (no production consumer).
- 3× copy-pasted tool activation guards; "contact.class"/facet-prefix literals; claim→subject
  reachability SQL byte-identical in handoff_store.py:67 and research_view_wiring.py:83
  (neither resolves merged_into); scoring engine stamps product via model_copy not
  revalidate_with.
- Efficiency: contact_eligibility per-claim surviving_id/get_contact N+1 (hot GET),
  resolve_contact resolves whole committee for one contact, sequential compose section reads +
  per-candidate governance loop (own-connection readers, gather-safe), snapshot per-row
  INSERTs, DSAR access lawful-basis N+1.

## Refuted (do not re-report)

Depth/node guards in resolver are load-bearing (frontier children in supports map); retention
window closed by read guard; positioner does stamp product_id; hashes NOT NULL; restricted
personalization state unconstructible (core validator); objection dependent-tombstoning is
correctly hook-scoped; DERIVED no-span/no-url promotion is C7-D2-sanctioned design.

## State

Review-only session; no code changed. Report delivered 2026-07-29.
