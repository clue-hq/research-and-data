# 2026-08-05 — M8C C3 contact-targeted Exa compiler

## Outcome

C3 is mechanically complete on `platform/c8-account-profiling-integration`. The implementation
adds a transport-free, exact-contact Exa Search Deep compiler and a fail-closed response parser.
C4 still owns durable dispatch, immutable snapshots, settlement, claim materialization, and the
separately authorized live canary.

## Implemented

- Added an exact contact/employer target lock with canonical professional-profile URL, employer
  domain, title/function/location disambiguators, source guidance, and publication bounds.
- Added a bounded `deep-reasoning` request variant that accepts only registered
  `contact.facet.*` schema fields, uses confirmed directional questions, requires source URLs and
  inspectable evidence, and excludes email/phone.
- Added database-backed compilation through the exact confirmed directive, project run, ICP,
  canonical account/contact, effective registry schema, and content-addressed `exa_deep` source
  plan.
- Added contact-subject operation/reuse fingerprints covering identity, employer, questions,
  source plans, wire request, and freshness; no reservation or transport occurs in C3.
- Added exact/unresolved/contradictory citation attribution. Only exact person plus employer
  bindings become provider-neutral candidates; same-name and profile mismatch evidence is retained
  for audit but cannot materialize.
- Added supported, empty, malformed, contradictory-profile, and same-name/wrong-employer fixtures
  behind a checksum manifest.
- Added the deliberate healthcare `CONTACT_FACET -> exa_deep` source-profile override and pinned
  the accepted C3 contract in the contact policy.
- Added `docs/specs/M8C-C3-contact-exa-compiler-acceptance.md` and advanced the M8C roadmap to C4.

## Verification and observed failure

- 88 focused C0-C3/A0-A1/E0-E2 tests passed with no skips against the populated synthetic database.
- Changed-file Ruff passed; full mypy passed 526 source files; 24 import contracts passed.
- The first full-suite run intentionally used the populated development database and proved why
  that is invalid for repository-wide migration tests: the C5.3 downgrade guard rejected existing
  pre-materialized tool nodes and seeded source manifests collided with clean-state fixtures. The
  failed downgrade rolled back; `alembic current` and `heads` both remained `f9281fac77e1`.
- A separate explicitly scoped database was created, migrated base-to-head, and used for the full
  suite. It passed to 100% with exit code 0, then was deleted. The synthetic development database
  was not reset.
- No provider credential lookup, HTTP request, provider operation, or paid spend occurred, as
  required by the C3 exit gate.

## Follow-up

C4 must consume only the C3 preflight, persist the target lock beside the immutable request, use
the contact parser on replay, settle native Exa usage exactly once, and materialize only exact-bound
citations through the existing governed contact-field path.
