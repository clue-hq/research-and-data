# C7.3 — deterministic account/contact research-view composition

**Date:** 2026-07-27
**Branch:** `platform/c7-research-views`
**Base checkpoint:** `5676da9` (`feat(c7): add governed claim derivations and entailment`)
**Migration head:** `0ac041814c56` (unchanged; C7.3 adds no persistence)

## Completed

- Added narrative-owned injected seams for canonical subjects, direct and derived claims, fit,
  committee, coverage, activity, and statement governance. Existing authorities cross the seam as
  typed references/candidates; composition authors none of their values.
- Added `DeterministicResearchViewComposer` with exact subject/workspace/product target locks,
  direct/derived flavor separation, complete ordered derivation supports, independent
  display/outreach decisions, hidden-value redaction, safe evidence descriptors, fixed
  account/contact section order, explicit empty states, complete reverse provenance, deterministic
  statement/view ids, and a source-state hash independent of frontend section grouping.
- Added the API-root construction factory. Later concrete owner adapters, routes, snapshots, and
  tools share this one composer rather than creating a second dossier path.
- Added the reference-only nine-block compatibility adapter. It preserves every statement/owner
  reference and reverse-provenance entry, carries the canonical source hash unchanged, emits all
  nine frozen kinds, and copies no research value, evidence span, URL, storage key, or prose.
- Synced implemented account/contact section orders directly to the C7.0 executable frontend
  fixture manifests.

## Verification

- Focused C7.3 plus frozen C7.0 contract/fixture/architecture suite: 50 tests passed before the
  final adversarial additions; final C7.3 file contains 14 green tests.
- Ruff green across the repository with user-owned untracked `.claude/`/`.codex/` excluded; mypy
  green across 427 source files; import-linter green (24 contracts, 0 broken).
- Clean isolated PostgreSQL migration smoke passed head → base → head; sole head remains
  `0ac041814c56`.
- Full repository suite passed on the clean isolated database. The first ambient-database run
  exposed stale external state: that DB was version-stamped at head while its `claim_flavor` enum
  lacked C7.2's `derived` value. No code was changed for that environmental inconsistency; the
  isolated rebuilt schema passed the same DSAR test and the full suite.
- The temporary isolated database was dropped after verification.

## Decisions and audit notes

- Source-state hashing includes scope, exact subject/version, product pin, resolved statement and
  owner-reference state, and coverage counts. It excludes semantic section placement so frontend
  regrouping does not rewrite backend truth.
- A denied personalization candidate is not wrapped as a selectable personalization item. Its
  section remains explicitly `restricted` with `no_outreach_eligible_statement`.
- Product-scoped items in a product-neutral or different-product request fail closed; tenant-private
  claims from another workspace fail closed; wrong-subject candidates fail before view creation.
- C7.3 intentionally adds no table, cache, rendered document, model/gateway call, production
  committee cutover, route, tool, or snapshot. Those remain assigned to C7.4/C7.6/C7.7.

## C7.4 handoff

Start at plan §10. Add reference-only snapshot/ordered-reference/reachable-subject persistence and
the API-root evidence authorization/access service. Reuse the C7.3 composer and nine-block adapter;
do not copy statement values or personal text into snapshot rows. Prove workspace/project/subject/
artifact scope, server-owned preview TTLs, storage-key leakage prevention, snapshot replay after
supersession/erasure, DSAR sentinel removal, idempotent composition, legacy handoff disposition,
clean hash-id migration smoke, and the single authorized `StorageBackend.presign` boundary.
