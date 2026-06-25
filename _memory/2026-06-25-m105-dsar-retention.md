# 2026-06-25 — M10.5 lawful basis + retention TTLs + DSAR/erasure (compliance)

Branch `m10/compliance` (continues [[2026-06-25-m104-postures]]). M10.5 is the LAST M10 issue: makes
"why are we allowed to hold this" (lawful basis) and "stop holding this" (DSAR/erasure/objection +
retention age-out) first-class, queryable operations (Doc D §4). Third M10 migration.

## What shipped
- **Migration `b56207f907f2`** (off head `196d37e4a179`; single head; `db-smoke` up→down→up reversible).
  Side tables ONLY (PF-2), no `claim` ALTER / merge / core edit:
  - `lawful_basis_record` (claim_id UNIQUE = idempotency key, settable post-insert/UPSERT; `lawful_basis`
    text+CHECK {legitimate_interest,consent,none}; `lia_ref`; `third_party_collected` bool; `regime`
    text audit; `retention_until`; index on third_party_collected).
  - `dsar_tombstone` (erased_claim_id UNIQUE = idempotent; tombstone_claim_id; contact_entity_id;
    tenant_id; `reason` text+CHECK {erasure,objection,retention_expiry}; scope; index on (contact,tenant)).
  - `outreach_objected` (UNIQUE (contact_entity_id, tenant_id); the Art. 21 marker).
  - **No new DB enum** — `lawful_basis`/`reason` are TEXT+CHECK (the `use_decision.regime` precedent),
    drift-guarded by no-DB tests (regex/importlib the migration tuples vs the Python StrEnums).
- **`compliance/lawful_basis.py`** (NEW): `LawfulBasis` enum; pure `derive_lawful_basis(use_class,
  defaults) -> (basis, lia_ref)` (sensitive→NONE/None **in-code Art. 9 floor**; professional/personal→
  config basis +LIA; unknown basis string fails loud); `retention_horizon_for(use_class, RetentionTtls)`
  (sensitive 30d < personal 180d < professional 300d, all < 365d firmographic);
  `is_third_party_collected` (API/SCRAPE/LLM = Art. 14 third-party); `record_lawful_basis` (derive +
  UPSERT; retention_until = (observed_at or collected_at) + horizon; raises on use_class None);
  `load_lawful_basis`; `third_party_notice_report` (Art. 14 aggregate, join to claim for tenant,
  **live-only** `superseded_by IS NULL`).
  Span `compliance.lawful_basis`. Added `LawfulBasisDefaults.lia_ref` to config/policy.py.
- **`compliance/dsar.py`** (NEW): the crux is **erasure = append-only supersession-by-tombstone**.
  - `build_tombstone(target, run_id)` (pure): a new claim superseding the target, `verification_status
    =REJECTED` (the universal merge-ineligibility mechanism — `merge._is_eligible` excludes REJECTED →
    current_value returns None), `extraction_method=HUMAN` (PF-5), tier 1, value = redaction sentinel
    `{"__erased__": True}`, facet targets also get `identity_binding=WEAK` + copied `use_class`; inherits
    the target's exact tenancy.
  - Tombstone written via `supersede_claims([target.id], tombstone, validate_field=False)` — the **one**
    sanctioned `validate_field=False` caller (the redaction sentinel is intentionally not a valid field
    value). Threaded `validate_field` through `claimstore.supersede_claim`/`supersede_claims` (additive,
    M1.1-owned but the same pattern M10.1 used to add `supersede_claims`).
  - `DataSubjectRightsImpl(client_id)` (controller-scoped): `access` (dsar_private_claims + lawful bases),
    `rectify` (supersede_claim with corrected), `erase(contact, scope=ERASE_ALL)` (live tenant-private
    claims filtered by ErasureScope → tombstone), `record_objection` (UPSERT outreach_objected marker +
    tombstone live contact.facet.* hooks). Method named `record_objection` not `object` (builtin shadow).
  - `RetentionSweep(freshness: core.Freshness)` (operator-wide): `sweep_expired` (consumes the FROZEN
    `core.verification.Freshness.due_for_age_out` → AgeOutCandidate → tombstone, reason=retention_expiry;
    compliance may NOT import verification, so the M9.5 engine is injected as the core protocol),
    `sweep_objections` (re-suppress new hooks for objected contacts). Spans `compliance.dsar` /
    `compliance.retention_sweep`.
  - **Key correctness fix (caught by the DB tests):** a tombstone is itself a LIVE `contact.facet.*`
    claim → without a guard, the next erase/objection/sweep re-selects + re-tombstones it (unbounded
    loop; idempotency breaks). Fixed with `_is_tombstone(claim)` (REJECTED + redaction sentinel) +
    `_erasable(claim)` (live and not-a-tombstone) applied at every selection site. A genuinely
    faithfulness-REJECTED *real* claim keeps its real value → still erasable (the sentinel distinguishes).
- `obs/spans.py`+`__init__` (additive M10 spans); `compliance/__init__.py` exports the M10.5 surface.
- Tests: `tests/compliance/test_lawful_basis.py` + `test_dsar.py` (pure + DB-gated, one per AC).

## Design decisions (review)
- **Erasure mechanism**: REJECTED supersession (not a destructive delete; append-only audit preserved;
  the AC is "current_value/handoff return none", not a raw value-purge — the value-purge is the plan's
  separately-scoped harder concern, flagged not done). Verified `merge._is_eligible` excludes REJECTED.
- **Objection vs erasure**: objection blocks outreach hooks (contact.facet.*) + sets a durable marker
  for re-sweep; it is NOT full erasure (committee/structural contact.* data stays). D-OBJ substrate
  exclusion, no UseReason.objected.
- **Lawful basis derivation is use_class-keyed**; `regime` is recorded for audit (Art. 30) + the future
  per-regime hook (the spec's "(use_class, regime, policy)" — regime-agnostic default documented).
- **DRY note (backlog)**: `retention_horizon_for` duplicates `verification.freshness.retention_horizon_for`
  (keyed there on field_class+use_class) — consolidate onto one shared primitive (M9.5↔M10.5 backlog,
  alongside normalize_host/reference_time/decode_jsonb_scalar).

## Verification (this session)
`make check` green: **927 passed, 663 skipped** (ruff/mypy 214/import-linter 11/11). Throwaway pgvector
(docker `clue-m105-pg`, port 5467, db `clue_m105`): `db-smoke` up→down→up reversible, single head
`b56207f907f2`; **all tests/compliance + tests/db pass = 119 passed (0 skipped, DB up)**. The 2 initial
DB failures (the tombstone-re-tombstone loop) were the real defect above, fixed + green.

## Adversarial audit (5-lens workflow + per-finding verify) — 16 confirmed of 29; fixed
All low/medium (no critical, no outreach leak — the M10.3 gate's in-code floor still blocks *use*).
Several were cross-lens duplicates. Distinct fixes landed:
- **[MED] Art. 9 floor was config-only on the lawful-basis side.** A misconfigured `sensitive_basis`
  could record `legitimate_interest` for special-category data (audit-truth defect; the gate's *use*
  floor was unaffected). Fixed: `derive_lawful_basis` now hard-floors `SENSITIVE → (NONE, None)` in
  **code** before consulting config (mirrors the M10.3 gate / JurisdictionPolicy code-floor). + pure test.
- **[MED] `rectify` had no tenant-isolation** (the lone fail-open of the four rights). Fixed:
  scope-load the target via `dsar_private_claims(corrected.entity_id, client)` and reject if not owned;
  `stamp_reuse` the corrected claim to the controller. + cross-controller rejection test.
- **[MED] `retention_until` used `collected_at`; the M9.5 sweep ages out on `observed_at`.** The
  recorded/disclosed erasure deadline overstated the real one when a source was published before it
  was scraped. Fixed: `(observed_at or collected_at) + horizon` (= `merge._reference_time`). + observed_at test.
- **[MED→LOW] professional retention TTL == firmographic (365d), not "strictly shorter" (AC2); the
  test silently omitted professional.** Fixed: lowered `RetentionTtls.professional_claim_ttl` to 300d
  (still longest personal class, < 365d firmographic; no test pins 365d — M9.5/config compare to the
  field value); the invariant test now asserts all three personal classes < firmographic.
- **[LOW] `third_party_notice_report` counted erased/superseded claims** (no live filter). Fixed: added
  `AND c.superseded_by IS NULL` + an erased-claim-excluded test.
- **[LOW] `access()` exported the redaction-sentinel tombstone rows** as the subject's claims. Fixed:
  filter `_is_tombstone` from the export (the real superseded values stay; bookkeeping rows drop). + test.
- **[LOW] AC handoff clause tested only at `current_value`.** Fixed: erase/sweep tests now also assert
  `provenance_index` omits the field (the in-repo handoff proxy; account_handoff is M12).
- **[LOW] retention sweep wrote `tenant_id=''` for a public-footprint age-out target.** Fixed: skip +
  warn (personal claims are tenant-private by construction; a public claim should have no retention).
- **[LOW] `lawful_basis_record` index on a low-cardinality boolean.** Fixed: partial index
  `(claim_id) WHERE third_party_collected` (matches the report predicate).
- **[LOW] concurrent double-erase could orphan a REJECTED tombstone row** (supersede-then-audit). Fixed:
  **audit-first** — INSERT `dsar_tombstone` (ON CONFLICT DO NOTHING) *before* the supersede; the loser
  (rowcount 0) returns without writing a claim, so no orphan. The UNIQUE on `erased_claim_id` serializes.
- **[MED, cross-package → backlog] erasure leaves personal text in `faithfulness_verdict.rationale`.**
  Compliance may not import verification; the M9-table redaction is an api-root integration task —
  tracked as a new CLAUDE.md backlog item ([[2026-06-22-m93-faithfulness-judge]]).
Dismissed by verify (13): mostly low-confidence / already-covered / documented-deferral restatements.

## Verification (FINAL — after fixes)
`make check` green: **928 passed, 666 skipped** (ruff/mypy 214/import-linter 11/11). Throwaway pgvector
(docker `clue-m105-pg`, port 5467, db `clue_m105`): `db-smoke` up→down→up reversible (incl. the partial
index), single head `b56207f907f2`; **all 123 tests/compliance + tests/db pass** (+ tests/test_config_schema
+ tests/verification/test_freshness 41 pass — the professional_claim_ttl 300d change is safe). 30 M10.5
tests (was 26; +Art.9 floor, observed_at retention, live-filter report, cross-controller rectify, access-
excludes-tombstones, provenance_index handoff assertions). Container left up for the session; tear down after.

## Integration-time follow-ups (api root, NOT this branch)
- Wire `record_lawful_basis` at the M8 contact-claim insert site (inject per-client LawfulBasisDefaults/
  RetentionTtls from get_policy). Inject `DataSubjectRightsImpl` + `RetentionSweep` (inject the M9.5
  `FreshnessImpl` as `core.Freshness`); schedule `sweep_expired`/`sweep_objections` before the merge read
  in the verification phase. Surface `third_party_notice_report` to M13.
- The retention-aware-merge backlog (M1.2/M10.5): the tombstone-before-read sweep is M10's chosen
  mechanism (a runtime precondition enforced by the M11→M10→M12 integration order).
