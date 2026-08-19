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
