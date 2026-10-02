# Comprehensive research integrity and settlement repair — 2026-08-19

## Decisions implemented

- Discovery sealing remains a launch-time lineage-integrity requirement.
- A successful launch pins an immutable discovery receipt containing the sealed batch/generation, manifest references and hashes, and stored account membership.
- Downstream account-gap and committee reads validate that pinned receipt and stored membership; they do not recompute membership from later claims.
- Account research may settle only when every requested field is evidence-backed or every applicable authorized source has an actual terminal dispatched attempt.
- Committee work has the same terminal-result-or-exhausted-sources obligation.
- Reservations, tool-call rows, and pre-dispatch failures are not research attempts, so a no-work run cannot settle successfully.
- Coverage includes the complete 21-field comprehensive account profile, including `core.account_name`; derived employee and revenue bands are also represented in the settlement axis.
- Quality controls remain advisory/shadow; identity, tenancy, authorization, hard spend, idempotency, and evidence provenance remain blocking.

## Implementation and verification

- Added the launch receipt contract and threaded it through fleet launch, Sumble account gaps, and committee eligibility/preparation.
- Changed discovery receipt validation to compare exact stored seal artifacts instead of mutable live membership.
- Added execution-completeness derivation and enforced it both at assessment and finalization.
- Updated schema fingerprints and regression tests for immutable seals, no-work settlement rejection, complete 21-field coverage, and historical narrow directives.
- Focused verification passed: comprehensive execution (2 tests), discovery seal (2 tests), and the combined account-research/fleet/derivation suites (45 tests). Earlier contract/readiness selection included 63 passes and 7 DB-dependent skips before the DB-backed run.
- No database migration was required.

## Preserved state and follow-up

- No live browser rerun, service restart, database mutation, provider dispatch, or runtime cleanup was performed during this implementation closeout.
- Tunis and its database/runtime instances were not touched.
- The pre-existing user edit raising Sumble concurrency in `libs/clue-config/clue_config/settings.py` remains uncommitted and untouched.
- A broader full-repository `make check` and the next live browser proof run remain future work because the user instructed this session to stop after the current repair.

## Adversarial-review repair — two settlement deadlocks (same day, launch/authority lane)

- **F3 (unrequestable Sumble authority).** `sumble_organizations` owns `core.company_linkedin_url`,
  `account.total_funding` and `account.recent_funding` under contract §3.1, but its pinned v9
  organization action cannot request them, so those `(field, source)` pairs could never reach a
  terminal attempt and the account could never settle. Fixed at the only place authority is minted:
  `AccountResearchFleetLauncher` now intersects wire-requestability into each field's authorized
  source list (`_source_can_request`, delegating to the resolver's own
  `sumble_action_supports_field`; Exa Deep compiles its schema per bundle so it is unconstrained).
  A field that keeps another owner narrows (`account.*_funding` → `exa_deep`); a field with no
  requestable owner stays **admitted with an empty authority** — nothing outstanding, exhausted by
  construction, reported by the coverage ledger as an honest gap. `FieldSourceAuthority.source_keys`
  therefore lost its `min_length=1`; a launch where *nothing* is requestable and no committee source
  exists is refused loudly instead of emitting an invalid selection. Historical selections are
  unchanged and still readable; new launches hash the new (narrower) authority into `request_sha`.
- **F5 (fresh but span-less claim).** The eligibility ladder refused to re-buy a "confidently
  resolved, fresh, conflict-free" field while the completeness reader satisfies a field only with a
  non-empty evidence span, so a NULL-span winner was unbuyable *and* unsatisfiable. Both sides now
  read one predicate — `CurrentValue.evidence_backed` (new, in `clue_core.handoff`; also adopted by
  `account_field_derivation._live_source_claim`) — and the span-less winner becomes an ordinary gap
  with the new `AccountGapReason.NO_EVIDENCE` and itself as the durable basis.
- Regression coverage added: selected-Account-outside-the-seal refused before any run/job/account_run
  write; the launch receipt pinned in full and proven to be part of `request_sha` replay identity
  (same seal → same run id, different seal → different run id, second identical launch is idempotent);
  every field of a receipt-vs-stored-seal mismatch failing closed; the comprehensive launch carrying
  no unrequestable pair; an empty authority representable in the R0 contract; and a fresh span-less
  claim compiling as a gap. R0 schema fingerprints bumped `m8d-r0-v6` → `m8d-r0-v7`.
- Verified on a throwaway DB (`clue_sumble_authority_checks`, dropped afterwards). Pre-existing/
  parallel-lane failures observed and attributed, not caused here: the `settle_terminal` provider
  signature change in flight on the Exa/Sumble tool lane, and
  `tests/integration/test_fi2_slice3_economics.py`'s two `account.project_angle` launch failures
  (reproduced identically at HEAD in a clean worktree).
- Open, deliberately not changed: `entity_research_tools.py:~563` still raises the *suspending*
  `EntityResearchToolAuthorityError` when a requested field has no authorized source. For an
  empty-authority field the R10 species doc argues for the model-repairable
  `EntityResearchGovernedRejection` ("a field outside the exact field/source authority"); the file is
  being edited by the parallel provider lane, so the change belongs to its owner.

## Residual findings from the adversarial review — recorded, not fixed (orchestrator, same day)

- **F7 — `exa_targeted_enrichment` still revalidates the *current* generation and live claims.**
  `platform/api/clue_api/exa_targeted_enrichment.py:340-345` calls
  `DbSealedDiscoveryAccountManifestReader.read()` with no receipt, so it takes the
  current-generation branch and adds a live-claim gate (:370-391). This is the
  `enrich_selected_accounts` platform-deepagent toolbelt tool — it has no entity-research job row,
  hence no receipt to consume, which is why 03a69712 could not thread it. Consequence: after a
  re-discovery (generation 2), targeted enrichment against an account validly selected in
  generation 1 fails closed — exactly the mutable-revalidation class §4.4 forbids for job-backed
  work. Needs a design decision: pin a seal at confirmation time for this tool, or accept
  current-generation semantics for non-job enrichment. The two other receipt-less readers
  (`toolbelt_wiring.py:968`, `run_composition.py:537`) are the SCORING phase, where
  current-generation is the correct semantics — do not "fix" those.
- **F7-adjacent:** the receipt path itself still requires `batch.state is SEALED` and an exact
  ICP key/version match (`discovery_seal.py:566-571`) *before* the receipt comparison — a
  mutable-present-day check living inside the immutable-authority path. Not exploitable while
  project-run ICP stays immutable; revisit if ICP versions ever advance in place.
- **F8 — cosmetic:** `discovery_seal.py:623-661` contains self-comparisons that can never fire
  (`account_ids`/`claim_ids` compared against themselves after assignment). The real tamper
  surface (relational bundle vs content-addressed artifacts vs seal row) is intact; reword the
  dead checks at leisure so they stop reading as live cross-checks.
- **Unknown-spend folds settle at zero cost** (accepted): a `spend_outcome_unknown` terminal fold
  closes the operation without adding to job/run spend counters, so recorded spend can undercount
  when a provider charged for a response we refused. Bounded by the per-operation reservation caps;
  revisit with billing reconciliation.
- **Live evidence correction:** the four "reserved-never-dispatched" Exa operations of job
  `04162ed5…` DID reach the provider (`external_research_attempt.dispatched_at` real; one bundle
  refused for truncated structured-output aliases) — only the entity-research ledger's dispatch
  stamp was never written because the all-or-nothing raise unwound the call. Any Exa spend for
  those four is currently unrecorded in run counters.
- **Guard finding (check-triage lane):** `clue_api/__init__.py` is an eager re-export package, so
  the D2 "no turn-serving module can reach a model" guard is a *lexical* rule, not a
  runtime-loading claim; documented in the guard's docstring.
