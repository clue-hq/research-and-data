# Production context amended S4-A/B — readers and contract freeze

**Date:** 2026-08-14
**Branch:** `platform/onboarding-integration`
**Status:** S4-A and S4-B implemented and verified; S4-C/D/E not implemented by this checkpoint

## Delivered

- Added `client_knowledge_reader.py` as the shared exact-version reader. Client-KB membership now
  comes only from the version marker/run graph. Global `claim.superseded_by` is lineage, so a v1
  row superseded by v2 remains readable to a pinned v1 turn.
- Kept retention separate: historical members load with `include_superseded=True` and
  `include_expired=False`. A same-version replacement is absent from that pinned version; foreign,
  outside-version, non-member, unknown, and expired refs remain non-oracular misses.
- Added deterministic baseline-then-extension ordering, topic/field filters, bounded paging, and
  strict refusal of invented/stale continuation positions. The preliminary `@1` tools now reuse
  this reader and preserve their public schemas.
- Froze final tool contracts as `list_client_knowledge@2` and `inspect_client_claim@2`. `@1` was
  already committed and pinned, so changing it in place would violate immutable versioning.
- `@2` freezes model-visible inputs, trusted runtime scope, strict nested outputs/schema hashes,
  page/response/field byte ceilings, deterministic client/version/filter/limit-bound cursors,
  narrow S1 cursor compatibility, origin-only source URLs plus SHA-256, truncation markers, one
  refusal taxonomy, and the `untrusted_evidence_not_instructions` content marker.
- IDs are UUID-shaped and claim methods/statuses/lineage/timestamps are typed. Untruncated value
  hashes and truncation markers are internally validated. URL sanitization also suppresses
  localhost, private IP literals, and local/internal hostnames.
- Amended `FI-production-deepagent-context-composition.md` with S4-A–E, then S3.1, S5.0, S5, S6.
  The preliminary `@1` registry/profile/skill/recipe graph is compatibility evidence; S4-D alone
  may register and cut production over to `@2` through new immutable resources.

## Verification

- Pure S4-B contract freeze: 7/7 passed, no DB/network/provider fixtures.
- A fresh final PostgreSQL database, `clue_context_s4ab_20260814`, was created and migrated to
  Alembic head `b2f815da0f31`; retain it for review. The complete S1-S4 production-context matrix
  passed 33/33 there, and final S4-A rerun passed 6/6.
- The final toolbelt/profile/recipe/omission compatibility matrix passed 41/41 with DB-backed cases
  enabled. This verifies preliminary `@1` replay compatibility while `@2` remains deliberately
  unregistered until S4-D.
- The DB suite proves v1 remains resolvable after a v2 replacement creates a real supersession
  edge; same-version non-members, foreign/outside-version/expired refs, workspace/client scope,
  included/omitted refs, ordering, pagination, filters, and cursor positions are covered.
- Repository-wide formatting (1,407 files), Ruff, mypy (664 source files), and all 25 import
  contracts passed.
- The monolithic DB suite was intentionally attempted on the earlier retained
  `clue_context_s4_20260814`; it contaminated that database with cross-file durable test state and
  produced the known migration-order/source-manifest failures. On the new clean database, the
  affected waterfall suite passed 30/30 and discovery/durable groups passed 34/34 in isolation.
- Two static baseline guards still fail on pre-existing design-subtree logging tokens and older
  `client_id` tokens; no changed S4 file appears in either offender list. Existing Lane-E
  Terra/verification-policy tests also reproduce their unrelated baseline failures on a clean DB.
  No claim of a completely green monolithic suite is made.

## Boundaries and next handoff

- No provider call is appropriate for S4-A/B: A reads already-durable claims, and B is explicitly
  pure. No live/browser acceptance claim was made.
- Both isolated databases are retained. Use `clue_context_s4ab_20260814` for this checkpoint's
  clean evidence; the earlier `clue_context_s4_20260814` is no longer clean after the diagnostic
  monolithic-suite run.
- S4-C implements the frozen `@2` tool bodies and constitution injection without schema changes.
- S4-D registers/grants `@2` through new immutable authority/profile/skill/recipe versions.
- S4-E closes durable DSAR reach, injection resistance, and replay before S4 is called complete.
