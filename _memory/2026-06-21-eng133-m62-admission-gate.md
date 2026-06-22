# 2026-06-21 — ENG-133 / M6.2: Existence/identity gate + discovery-provenance

## Goal
The anti-fabrication admission gate: a discovered candidate is a hypothesis until it resolves to a
real canonical `account_entity` via the M2 identity service; survivors get a discovery-provenance
claim; fabricated candidates die at the gate. Channel-agnostic so import (Scenario B) converges
identically. Branch `m6/discovery-and-pass-a-scoring`; DB `clue_m6`.

## Files (src/clue_research/discovery_scoring/gate/)
- `results.py` — `AdmissionStatus {ADMITTED, NEEDS_REVIEW, REJECTED}`, `AdmissionResult`.
- `existence.py` — pluggable `ExistenceCheck` seam + `DefaultExistenceCheck` (exists iff registrable
  domain or non-empty name; a real DNS/live-domain check is a drop-in).
- `admission.py` — `admit(conn, candidate, run_id) -> AdmissionResult`: existence → `_to_observation`
  (strong key = the candidate's OWN registrable domain, never source_url) → `identity.resolve` →
  `identity.disposition` (AUTO_MERGED/ENQUEUED/NEW_ENTITY) → for admitted, `surviving_id` + one
  idempotent discovery-provenance claim (`core.discovery_provenance`, DISCOVERY flavor → `insert_claim`
  skips field validation; public/no-tenant; never wins a merge). Redis domain-lock (uuid5 of the
  domain) serializes concurrent same-company admits.
- `phases.py` — `DiscoveryPhaseHandler` (phase=DISCOVERY): loads ICP spec → `discover` (M6.1) →
  `admit` per candidate (each in a `begin_nested` savepoint) → persists per-channel yield to
  `source_yield`. Injectable `session_factory` (default `db.transaction`) for testability. Replay-
  stable discovery `run_id` = uuid5(campaign_run_id, icp_key, icp_version).

## Key design calls
- The gate's core is `identity.disposition` (DRY — don't re-implement the band logic). Subject-less
  NEW_ENTITY admits from the observation; subject-less AUTO_MERGED returns the existing survivor
  (the candidate IS the existing entity — dedup, no real merge in the discovery flow).
- Discovery-provenance uses `core.discovery_provenance` UNregistered (discovery claims skip field
  validation). source_tier/extraction_method from the channel's manifest (`get_source`); import →
  tier-1/crm_import; unregistered channel → tier-2/scrape default.
- DISCOVERY PhaseHandler built here (composes M6.1+M6.2 end-to-end); registered at the api root.

## Adversarial review → fixes applied
1. **Merge-blind idempotency (latent dup write):** `_existing_provenance` now checks every member of
   the survivor's merge set (`merged_member_ids`) — `claims_for` doesn't resolve across merges, so a
   provenance on a pre-merge loser would be missed and a duplicate written on replay-after-merge.
2. **Phase double-fault:** moved `savepoint.commit()` OUT of the try (a commit failure was being
   double-rolled-back). `except` narrowed-by-comment + `# noqa: BLE001` (best-effort per-candidate).
3. **Yield mapping (spec-fit for M6.5/M13):** discovery per-channel counts now go in the
   `source_yield.disposition` jsonb hook ({kind:discovery, records_returned, new_candidates,
   queries_issued, errors}) with only spend in cost_cents — not overloading the claim-precision
   columns (claims_total/fields_filled left 0; discovery produces no claims).
4. **Name-only lock gap:** documented (no unique constraint on names; fuzzy/review is the backstop).
5. **Lock coverage:** added a Redis-gated test (skips without Redis, like M2's lock test).

## Verification
- `make check` green; mypy 120 files; import-linter 10/0 (gate imports identity/claimstore/sources/
  locks/db — all allowed). 12 M6.2 tests (8 admission + 3 phase + 1 redis-skip) green on clue_m6.

## Follow-ups
- True-parallelism (two connections) for concurrent admit is backstopped by the DB strong-key unique
  constraint + the M2.4 lock tests; not unit-tested in the rollback harness.
- M6.5 reads the discovery yield from `source_yield.disposition` (raw rows) — not the aggregate
  `get_source_yield` (which sums the count columns). Confirm M6.5's read path against this.
- Next: ENG-138 (M6.3 Pass A scoring) reads admitted `account_entity` rows + the score path.
