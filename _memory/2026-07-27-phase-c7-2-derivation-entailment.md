# C7.2 — derivation and entailment substrate

**Date:** 2026-07-27
**Branch:** `platform/c7-research-views`
**Base checkpoint:** `d2257ee` (`fix(c7): close research-view prerequisite gaps`)
**Migration head:** `0ac041814c56`

## Completed

- Added `ClaimFlavor.DERIVED` to core and PostgreSQL with enum parity. Derived claims are
  field-schema-checked, tier-4/model-authored, carry no fabricated URL/span, retain contact
  governance, and are categorically excluded from factual `current_value`.
- Added the hash-id migration for append-only `claim_derivation` edges and
  `entailment_verdict` rows. The database enforces ordered immutable supports, live
  workspace/reuse/product/subject/role compatibility, strong contact binding, exact
  client-capability product scope, cycle rejection, support freeze after verdict, bounded coherent
  verdict reasons, and deferred terminal-claim lineage.
- Added claimstore `DerivationStore`, stable support hashing, forward/reverse dependency reads, and
  a bounded memoized `DerivationDependencyResolver`. Required supports re-resolve as fresh, stale,
  review-required, unavailable, rejected, redacted, or restricted under current scope, retention,
  supersession, verification, and conflict state.
- Added verification-owned `EntailmentJudgeImpl`: strict JSON only, fenced untrusted inputs,
  requested/answering model attribution, trace/cost metadata, cache lookup, bounded reason codes,
  no free-text rationale, and fail-closed malformed/model-error behavior.
- Added API-root `DerivedClaimService`. Structural gates run before model spend; judge ids/hashes
  are target-locked; accepted confidence is
  `min(required support confidence, entailment confidence, configured ceiling)`; accepted/rejected
  claim, edges, and verdict commit atomically; deterministic row locks and post-lock rechecks make
  retries return the first durable result.
- Kept the existing faithfulness handler off derived claims so the entailment verdict remains the
  sole accuracy authority. Contact derived facets still pass through the use-policy surface.
- Extended DSAR erasure through transitive reverse support reachability, including a contact
  signal copied into an account-targeted derivation. Both original and dependent text are
  tombstoned, and live dependency resolution reports redacted.

## Verification

- Focused C7.2/core/handler/DSAR/DB-enum suites: **67 passed**.
- Clean isolated PostgreSQL migration smoke: head → base → head; `alembic heads` returns only
  `0ac041814c56`.
- Tracked source gates: Ruff format/lint green (**870 files** after excluding the pre-existing
  untracked `.claude/` and `.codex/` directories), mypy green (**425 source files**), import-linter
  green (**24 contracts**, 0 broken).
- Final clean isolated-database full suite: **2,659 passed, 22 skipped**. During the audit, one
  existing SIGKILL recovery case timed out once at its 30-second subprocess boundary and passed on
  immediate isolated rerun; the final clean full run passed it. An earlier run found one C7
  contract-error-message mismatch, which was corrected before the final green run.
- Direct `make check` still scans the user-owned untracked `.claude/`/`.codex/` skill scripts and
  stops on their intentional CLI `print()` calls. Those files were not modified; the equivalent
  tracked-scope gates above are green.

## Decisions and audit notes

- The enum rebuild must drop/recreate every `claim_flavor`-dependent CHECK plus the immutable-update
  trigger during the type swap; otherwise PostgreSQL compares the old and new enum types while
  rewriting the column.
- A public derivation may never depend on tenant-private support. Product-neutral account evidence
  may support a product-specific interpretation, but `client_capability` requires both claims to
  carry the exact same product id.
- A supported verdict carries only `entailed`; an error carries only `model_error`; unsupported
  verdicts cannot contain either. Model-provided engine-only reasons are malformed.
- Downgrade refuses when real derived claims exist because relabeling them as direct field claims
  would invent external provenance. Empty-schema up/down/up remains clean.

## C7.3 handoff

Start at plan §9. Implement injected body-free readers and an API-root `ResearchViewComposer`.
Resolve direct claims through `current_value`, derived claims through the new dependency resolver,
and keep identity, fit, committee, coverage, and activity as owner references. Then build
deterministic account/contact sections plus the nine-block adapter against the frozen C7.0 fixtures.
Composition must make no model call, create no truth/body store, keep display and outreach policy
separate, preserve explicit unknown/stale/restricted/redacted states, and add no prose.
