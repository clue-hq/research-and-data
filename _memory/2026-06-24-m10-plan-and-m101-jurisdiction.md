# 2026-06-24 — M10 plan + M10.1 jurisdiction resolution (compliance)

## Branch / base
`m10/compliance`, forked off the frozen phase-3 pre-flight base (`1902210`, alembic head
`3df3b2f629fd`). M10 ∥ M11 ∥ M12 (separate worktrees). Full plan: `.context/m10-implementation-plan.md`.

## Key architecture facts verified against live code (not just docs)
- **`compliance/` MAY import `claimstore`/`identity`/`icp`/`sources` + `core`/`config`/`obs`/`db`** —
  the enforced import-linter *independence* rule only forbids importing sibling *worker* packages
  (verification, profiling, narrative, synthesis, durable, discovery_scoring, stage0, review, adapters)
  and `resolvers`. The package README's "core/config/obs only" is narrower than what's enforced.
  Verified: `lint-imports` 11/11 KEPT with compliance importing claimstore/identity/db.
- **Frozen seams (PF-1, do NOT edit):** `core.compliance.UseGate`/`UseDecision`/
  `is_outreach_promotable`; `core.enums.UseReason` (no `objected`); `core.verification.Freshness`
  +`AgeOutCandidate`+`due_for_age_out`; `core.handoff.AccountHandoff` additive fields.
- **Provenance = side tables keyed on claim_id** (PF-2); no `claim` ALTER, no immutable-guard touch.
- **Derived/computed claims** use `source_tier=1, extraction_method=HUMAN` (M6.3 precedent,
  `discovery_scoring/scoring/engine.py:340`). Jurisdiction follows this.
- **No location field-key is registered today** — a contact's location is the `ContactEntity.geo`
  column, the account's is `AccountEntity.hq_geo`. M10.1 reads config-listed location field-keys via
  `current_value` (claim path, for provenance + supersession) AND falls back to the entity columns.
- **`policy_version` for M10.3/4** must come from a DB-backed `client_policy` table (mirror M9.3
  `load_judge_policy` / `judge_policy.version`), NOT `config.ConfigVersion` (in-memory layer
  provenance). Loader lives in `compliance/` (config may not import db). (M10.3/4 work, not M10.1.)
- **Tombstone = supersession** (`claimstore.supersede_claim`); merge is NOT retention-aware
  (M9.5×M1.2 backlog) → M10.5 must tombstone before the merge read. M10.5 selectors:
  `identity.dsar_private_claims`, `TenantScope.private_for_tenant(tenant_id)`.
- Span `compliance.use_gate` already frozen in obs; `compliance.jurisdiction` added by M10.1.

## M10.1 — DONE this session (impl + tests; awaiting full DB run + audit)
Files:
- `config/policy.py` (+): `RegimeMapping` (region→`Jurisdiction`, `region_keys`, `regime_for`),
  `DEFAULT_REGIME_MAPPING` (EU-27+EEA→GDPR, GB/UK→UK_GDPR, US→US_STATE; D8 = config), `STRICT_DEFAULT_REGIME`
  =`Jurisdiction.GDPR`; new `JurisdictionPolicy` fields `regime_mapping`,
  `contact_location_fields=("contact.location",)`, `account_location_fields=("account.hq_location",)`.
  Exported from `config/__init__`.
- `obs/spans.py` (+) `SPAN_COMPLIANCE_JURISDICTION="compliance.jurisdiction"` + export.
- `compliance/fields.py` (NEW): `COMPLIANCE_PACK` with `contact.jurisdiction` SeedField (value_type
  object, PassKind.DEEP, no tier_plan, reuse_scope TENANT_PRIVATE, 180d ttl) + `load_compliance_pack`.
- `compliance/jurisdiction.py` (NEW): `DerivedFrom` enum (contact_location/account_hq/strict_default),
  `JurisdictionResolution`, `JurisdictionResolver` protocol, pure `extract_region`/`region_from_value`/
  `region_to_regime`/`_confidence`, `JurisdictionResolverImpl` (waterfall: contact claim→contact geo
  col→account claim→account hq_geo col→strict-default-fail-closed; writes `contact.jurisdiction` claim
  via `stamp_reuse`+`supersede_claim`; emits span+metrics).
- `compliance/__init__.py` exports the M10.1 surface.
- `tests/compliance/{__init__,conftest,test_jurisdiction}.py`: conftest mirrors verification (migrated
  DB + rollback conn; loads core+compliance packs + test-only `contact.location`/`account.hq_location`
  fields). Tests: pure (region/regime/confidence-ordering) + DB-gated one-per-AC (AC1 provenance, AC2
  account_hq < contact confidence, AC3 strict+unknown, AC4 supersede+reresolve, AC5 config-only,
  tenant_private, account-claim path, contact-geo-col path).

## Design decisions (review)
- **Regime enum reconciliation:** spec ACs name `EU_GDPR`; the M0.4-frozen `Jurisdiction` enum has
  `GDPR` (EU/EEA GDPR-grade). Reused as-is, NOT renamed; mapped EU/EEA→`Jurisdiction.GDPR`. Documented.
- **Spec "OTHER" regime** for unknown → represented as **strict-default regime + `jurisdiction_unknown=True`**
  (fail-closed, strictly safer than a permissive OTHER member). Matches AC-3 ("strict-default regime").
- **Provenance AC:** claim-derived paths carry `provenance_claim_ids`; column-derived (geo/hq_geo) and
  strict-default carry none (no backing claim) — documented honestly (the AC's "carries provenance" is
  met by the claim paths; the column fallback is what makes M10.1 useful TODAY before M8 location fields).
- **≤1 live jurisdiction claim invariant** maintained by supersede-on-resolve; `_store` supersedes the
  newest live prior (or inserts the first).
- **M10.1 = zero migrations** (field is a registry row via the pack loader).

## Adversarial audit (4-lens workflow + per-finding verify) — 10 confirmed of 19; fixed
- **[CRITICAL] value_schema `region: {"type":["string","null"]}` crashed EVERY persist.** The
  substrate validator (`registry._validate_payload` / `_SCALAR_CHECKS`) is keyed by a single scalar
  type string → `dict.get([list])` raises `TypeError: unhashable type: 'list'`. Masked because the DB
  tests skip without Postgres. **Fix:** `region: {"type":"string"}` + `_value_json` OMITS region when
  None (optional key, not `required` → absent validates). Added a **no-DB guard test**
  (`test_value_json_validates_against_registered_schema`) so this regression is caught in `make check`.
  (`_SCALAR_CHECKS` supports string/integer/number/boolean/null — my regime/confidence/derived_from/
  jurisdiction_unknown all validate; only list-unions are unsupported.)
- **[MED/LOW ×3] `_store` superseded only `prior[0]`** (relied on an unenforced ≤1-live invariant).
  **Fix:** added `claimstore.supersede_claims(conn, old_ids, new_claim)` (many→one; the sanctioned home
  for claim SQL, additive — also reusable by M10.5) and `_store` now supersedes ALL live priors. DB
  test `test_store_supersedes_all_live_priors` plants 2 live claims, asserts 1 live after resolve.
- **[LOW] full country NAMES** ("Germany") failed to map → strict-default (safe but the resolver would
  be near-useless on real scraped geo). **Fix:** added `RegimeMapping.name_aliases` (curated full-name
  →ISO, D8-config) consulted by `regime_for`; unknown names still fail closed. + pure test.
- **[LOW] AC6 contradiction** (spec said "none emitted without provenance" but column/strict paths have
  none). **Fix:** reworded AC6 in the M10 spec (claim-derived carry provenance; column/strict carry
  none by construction; the resolution is always *persisted* as a provenance-bearing claim).
- **[LOW] AC2 test** compared column-fallback to contact-claim, not the account-claim band. **Fix:**
  added account-claim confidence-band + ordering assertions to `test_account_location_claim_path`.
- **[LOW] obs/spans.py edit of the Beat-0-frozen file** — kept (additive, collision-free per audit
  option-a); at integration the span constant *could* be relocated to a central obs delta.
- Dismissed (9): stamp_reuse-without-declared-scope (prefix heuristic correct), EU_GDPR→GDPR (documented),
  DRY 4th geo reader (acceptable), DB-gated coverage (the pattern), span-on-success-only, etc.

## Verification performed (FINAL)
ruff + format clean; mypy `Success: no issues found in 210 source files`; import-linter 11/11 KEPT.
**Brought up a throwaway pgvector (port 5455, db clue_m10) and ran the DB-gated suite:** all **18**
`tests/compliance` tests pass; `tests/claimstore` + `test_merge_policy` pass EXCEPT the env-sensitive
wall-clock perf test `test_batch_scales_to_1k_entities` (12.8s vs 5s budget on a cold container —
passes warm; `merge.py` is NOT in my diff, so unrelated to `supersede_claims`). Threw away the DB.

## TODO next
- Commit M10.1 (done in this session). Then M10.2→M10.5 per `.context/m10-implementation-plan.md`.
- M10.3+ add side tables (first migration off `3df3b2f629fd`) → run `make db-smoke` then.
- Integration-time (api root): fill `register_compliance_wiring` (UseGate last; `load_compliance_pack`
  → RESEARCH_PACK_LOADERS; due_for_age_out→tombstone sweep; gather_scope→M4.6).
