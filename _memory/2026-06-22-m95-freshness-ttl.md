# 2026-06-22 — M9.5 Freshness TTL engine + re-research cadence (ENG-149)

## State: DONE (impl + 2-reviewer adversarial audit + fixes + full DB suite green); awaiting user review
Branch `m9/verification-layer`. Migration `cb39832d29bb` off M9.4 head `971febbe2906`. `make check`
green (lint/format/mypy/import-linter 10-0; 459 passed in the no-DB lane); **33/33** M9.5 tests
(16 pure + 17 DB-gated) + the full verification DB suite green on docker `clue-m9-pg` (5433);
db-smoke up→down→up reversible on `clue_m9_smoke`, single head `cb39832d29bb`.

## Adversarial audit (2 independent reviewers: correctness + spec-conformance) — outcome
Both converged on one HIGH/CRITICAL item (a false safety invariant in my docstring) + a cluster of
medium/low items. **Fixed in this PR:**
1. **[HIGH — false invariant] "EXPIRED implies past-TTL (retention ≥ ttl)" is FALSE.**
   `RetentionTtls.sensitive_claim_ttl`=30d < `FreshnessTtls.contact.facet`=90d, so a 40d sensitive
   facet claim is EXPIRED (past 30d retention) yet FRESH to the TTL-only merge — it can be served /
   win over a fresh claim until M10.5 erases it. Corrected the module + `staleness` docstrings to
   state EXPIRED is independent of the TTL; hard merge-exclusion of an expired-but-within-TTL claim
   is owned by M10.5 erasure (a retention-aware merge is an M1.2/M10.5 follow-up — backlogged).
   M9.5's contract is *detect + surface* (`due_for_age_out`), which it does correctly.
2. **[MED — real bug] `AgeOutCandidate.retention_days` carried the field TTL, not the horizon.**
   Was `staleness.ttl_days` (the 90d facet TTL); now threads the actual use-class-keyed retention
   horizon onto `_ScanRow` and reports it (a sensitive candidate reports 30, not 90). Test added.
3. **[MED — real gap] per-field `freshness_ttl` override stopped shortening the cadence once any
   `cadence_policy` row existed** (the loader populates `cadence_by_field_class` for every class →
   `explicit_cadence` always non-None → the override was ignored for due_at). Fixed: the scan now
   takes `min(explicit_cadence, effective_ttl)` (refresh at the sooner of the class cadence and the
   field's own TTL → never stale-but-never-due). Regression test added.
4. **[LOW — correctness] non-facet `contact.*` with `use_class=None` aged out at the 180d personal
   horizon.** Now an unstamped `use_class` (None) carries NO retention horizon → never EXPIRED (we
   don't guess a horizon for an unclassified claim; M10.2 stamps the use-class first). Test added.
5. **[LOW — obs] `METRIC_FRESHNESS_DUE`/`ATTR_FRESHNESS_DUE` meant two things across the two scans.**
   Added an `op` label (`refresh`/`age_out`) to the span + metrics so the `due` series can't be
   conflated.
**Deferred to backlog (CLAUDE.md/AGENTS.md):** retention-aware merge (M1.2/M10.5); promote
`due_for_age_out`/`record_re_research_candidates`/`AgeOutCandidate` onto the frozen `core.Freshness`
seam at integration (M7/M10.5 can't reach them off-protocol — same deferral as M9.1 AC-6/M9.4);
`re_research_candidate` idempotency key drifts across partial-group refresh (M7 owns drain/dedup);
`core.Freshness.evaluate(ttl=None)` protocol docstring deviates (says reads field_definition; impl
falls back to the in-memory cadence class TTL — correct by design, fix the core wording at a delta);
host-normalizer-style DRY (`reference_time` duplicates `merge._reference_time`).

## Original design (locked) — unchanged below
**No frozen-surface touch** — `core.verification.Freshness` protocol +
`Staleness`/`ReResearchCandidate` value types, `core.enums.FreshnessState` (FRESH/STALE/EXPIRED), and
`obs.spans.SPAN_VERIFICATION_FRESHNESS` ALL already exist from the Beat-0 contract freeze. M9.5 only
supplies the impl behind them (exactly like M9.2/M9.3/M9.4 supplied their gates).

## The one load-bearing design fact: `freshness_state` is DERIVED, never a stored claim column
The M09 spec says M9.5 "writes a new `claim.freshness_state` column". The implemented substrate does
**not** have that column and cannot get one cheaply:
- `Claim` (core/claim.py) has **no** `freshness_state` field; `_SELECT_COLUMNS`/`_INSERT_SQL`
  (claimstore/claims.py) have no such column; **no migration** ever created a `freshness_state` DB
  enum or column (verified: grep across alembic/ — nothing).
- Claims are **immutable/append-only** (substrate §1; the 0004 trigger allow-list is only
  `superseded_by/verification_status/corroborations`). Adding a mutable `freshness_state` column would
  ALTER the frozen claim table + the trigger + frozen `core.Claim` + the M1.2 merge — a large
  cross-milestone blast radius the M9 isolation contract forbids ("alters no shared mutable surface",
  as M9.3/M9.4 migrations state).
- The merge view (M1.2 `merge_claims`) **already** computes FRESH/STALE as a *derived* property on
  `CurrentValue.freshness_state` (not on the claim), from `observed_at|collected_at` vs the field TTL.

⇒ Same resolution pattern as M9.4's immutable `identity_binding`: **M9.5 does not write a claim
column.** `freshness_state` is the *computed* `Staleness.state` returned by `evaluate` (the queryable
signal scoring/merge read), plus the durable `re_research_candidate` rows (the refresh queue) and the
`cadence_policy` config. FRESH/STALE stays derived (merge already does it); M9.5 adds the standalone
per-claim verdict + EXPIRED (retention age-out) + the re-research emitter.

## "Expired never wins the merge" — the STALE half is free; the EXPIRED half is M10.5's
AC1 "the merge view never lets an expired claim win over a fresh one":
- **STALE half (a claim past its freshness TTL):** met by existing M1.2 behavior — the
  `TTL_GATES_ELIGIBILITY` merge prefers FRESH and only falls back to a past-TTL claim when nothing
  fresh exists, so a stale claim never wins over a fresh one. No merge change. (Proven by fixtures.)
- **EXPIRED half (retention age-out):** NOT implied by past-TTL — **corrected from the original note,
  which wrongly claimed `retention ≥ ttl`.** A retention horizon may be *shorter* than the field TTL
  (sensitive 30d < contact.facet 90d — intentional aggressive minimization, Doc D §4), so an EXPIRED
  claim can still be within its TTL → the TTL-only merge serves it and it could win over a fresh
  claim on tier. M9.5 only **detects + surfaces** expired personal claims (`due_for_age_out`) to
  M10.5; hard merge-exclusion is owned by M10.5 **erasure** (DSAR/tombstone), with a retention-aware
  merge as the tracked M1.2/M10.5 follow-up. No merge.py edit, no immutable-column write here.

## Binding to the existing config seams (avoid the M9.2 "third copy" drift)
- `config.schema.FreshnessTtls` (M0.4) already declares the field-class TTL defaults
  (core 365d / account 180d / account.resonance 90d / contact 180d / contact.facet 90d). M9.5's
  `CadencePolicy.ttl_by_field_class` **defaults from it** — one shared definition, not a new copy.
- `config.policy.RetentionTtls` (M0.4, Doc D §4) already declares personal-claim retention horizons
  (personal 180d / sensitive 30d / professional 365d) — the M10.5-owned horizon placeholder. M9.5
  **references** it for EXPIRED (per spec: "retention horizon owned by M10.5, referenced here, not
  redefined"). EXPIRED applies only to contact/contact.facet claims, by `claim.use_class`
  (SENSITIVE→30d, PROFESSIONAL_PUBLIC→365d, else→180d). Non-contact classes → no retention → never
  EXPIRED.

## Surfaces (mirror M9.3/M9.4 shape)
`verification/freshness.py`:
- **Pure (DB-free):** `reference_time(claim)` (= `observed_at or collected_at`, mirrors
  `merge._reference_time` — DRY overlap noted as backlog), `staleness(*, claim_id, reference_time,
  now, ttl, retention_horizon=None) -> Staleness` (EXPIRED if past retention, elif past ttl STALE,
  else FRESH; age clamped ≥0). `retention_horizon_for(field_class, use_class, retention) -> timedelta
  | None`.
- **Policy-as-data:** `CadencePolicy` (`ttl_by_field_class`, `cadence_by_field_class` default = ttl,
  `default_ttl`=90d per spec ~90-day, `retention: RetentionTtls`, `version`) + `DEFAULT_CADENCE_POLICY`
  + `load_cadence_policy(conn, *, client_id=None)` (per-client → global rows, latest version per
  field_class via `DISTINCT ON`, deterministic tie-break; FreshnessTtls/RetentionTtls fill the gaps).
- **`FreshnessImpl`** (the `Freshness` impl): `evaluate(claim, *, now, ttl=None) -> Staleness`
  (PURE-sync per protocol; ttl arg override → cadence-by-field-class → default_ttl; retention by
  field-class/use_class); `async due_for_refresh(*, entity_ids=None, field_keys=None, now=None) ->
  tuple[ReResearchCandidate,...]` (operator scan, STALE-and-due only, grouped per (entity,field),
  ranked by (priority=min tier asc, due_at asc, entity, field); **returns, never fetches**); impl
  extra `async due_for_age_out(...) -> tuple[AgeOutCandidate,...]` (EXPIRED personal claims for
  M10.5); `async record_re_research_candidates(conn, candidates)` (idempotent emit to
  `re_research_candidate`, ON CONFLICT (entity,field,due_at) DO NOTHING). Constructed with
  `policy`, `scope: TenantScope = ALL_TENANTS` (operator maintenance scan; candidates carry ids not
  values, so no cross-tenant data leak), `conn_factory`, optional `sink`.
- Span `verification.freshness` (emitted by the scan methods, not the pure `evaluate` — kept a hot
  pure fn); M9-local metrics `research.verification.freshness.{scanned,stale,expired,due}`. M9-local
  span attrs `verification.freshness.{scanned,stale,expired,due}`.
- `evaluate` is sync (no DB, no span); a per-field `field_definition.freshness_ttl` override is read
  by the async scan (one small `SELECT field_key,freshness_ttl` like merge), passed into the pure
  staleness — so the scan aligns with the merge's per-field TTL; `evaluate(ttl=None)` standalone falls
  back to the in-memory cadence field-class TTL (documented: a field with no per-field TTL is
  "always fresh" to the merge but gets the cadence default in M9.5's refresh detection — intended;
  cadence is the re-research floor).

Migration `cb39832d29bb` off `971febbe2906`:
- `cadence_policy` (policy_id pk, client_id?, `field_class field_class`, `ttl interval`,
  `refresh_cadence interval`, version, created_at; CHECKs version≥1 / ttl>0 / cadence>0; UNIQUE
  `(client_id, field_class, version) NULLS NOT DISTINCT` — the M9.1 NULL-slot lesson applied from the
  start). Reuses the existing `field_class` enum (0003) — **no new enum**. Retention horizon is NOT a
  column (referenced from RetentionTtls / M10.5).
- `re_research_candidate` (id uuid pk, entity_id, field_key, `stale_claim_ids uuid[]`, due_at,
  priority, created_at; UNIQUE `(entity_id, field_key, due_at)` = idempotency key; indexes on due_at
  + entity_id). Append-only emission queue M7 drains. **No claim ALTER, no trigger change.** Reversible.

Tests `tests/verification/test_freshness.py`: pure-unit (staleness FRESH/STALE/EXPIRED, retention by
use_class, reference_time fallback, CadencePolicy defaults from FreshnessTtls, deterministic given
fixed now) + DB-gated (due_for_refresh ranked/scoped, config-swap via cadence_policy, merge
fresh-beats-expired, due_for_age_out surfaces expired personal, record idempotent, scoring-stub
discount, span+metrics) — one per §M9.5 acceptance criterion.

## Out of scope (documented deferrals)
- *Executing* re-research (M7 schedules/runs; M8/M11 produce new claims) — M9.5 only emits candidates.
- The scoring discount math (M6.3) — M9.5 exposes the signal; the AC3 test uses a local M6.3 stub.
- Lawful-retention/erasure/DSAR tombstoning + the authoritative retention horizon (M10.5) — M9.5
  references the RetentionTtls placeholder and surfaces aged-out claims via `due_for_age_out`.
- Per-field `field_definition.freshness_ttl` authoring (M1.3/M3) — M9.5 reads it.
