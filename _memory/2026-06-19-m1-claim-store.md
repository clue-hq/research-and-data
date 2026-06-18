# 2026-06-19 — M1 Claim Store & Merge Policy (ENG-102/110/117/123)

## Goal
Implement Milestone M1 — the typed-claim-with-provenance substrate (the "spine"). Four issues:
M1.1 claim table (ENG-102), M1.2 current_value merge (ENG-110), M1.3 field registry (ENG-117),
M1.4 research_mode + provenance flavors (ENG-123). Build order chosen: M1.1 → M1.3 → M1.2 → M1.4
(M1.2 reads field_definition TTLs; M1.4 ALTERs claim + needs field registry to classify personal
fields). Done solo/sequentially (tightly-coupled shared files: one migration chain + the claimstore
package + core) — not parallel worktrees, which would conflict.

## Environment / DB
- Host Postgres occupies :5432 (no `clue` role) — the documented port conflict. So for local
  verification I run a throwaway container `clue-postgres-m1` on **:5433** and set
  `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:5433/clue`. Do NOT edit the committed
  docker-compose.yml (it documents :5432). `make check` stays green without a DB (tests skip).

## M1.1 — DONE & verified (ENG-102 → Done)
- `alembic/versions/0002_claim_table.py`: `claim` table, §4 envelope + `verification_status`
  (added **FLAGGED** to `core.VerificationStatus` — the one core change). Enum types created here.
  Append-only BEFORE-UPDATE trigger (immutable-column guard; allow-list superseded_by /
  verification_status / corroborations) + BEFORE-DELETE trigger. CHECKs: tier 1..4, confidence
  0..1, tier4⇔llm_synthesis, evidence-span rule (no verified tier-4 without a span). Indexes incl.
  partial live-claims `(entity_id, field_key) WHERE superseded_by IS NULL` + GIN value_json.
- `src/clue_research/claimstore/claims.py`: `insert_claim`, `supersede_claim`, `claims_for`
  (the only sanctioned write/raw-read path). `claimstore/__init__.py` is the seam.
- Decision: `research_mode` column lives in 0002 (it is in §4 base + core.Claim requires it);
  M1.4 (0004) adds the flavor columns around it. CRM/Stage-0 null-research_mode convention deferred.
- Decision: soft FK `entity_id → account_entity(id)` DEFERRED to M2 (table doesn't exist yet).
- **Gotcha (important):** SQLAlchemy+asyncpg does NOT bind `:param` when followed by `::cast`
  (`:x::type` leaves `:x` unbound → syntax error). Use `CAST(:x AS type)` everywhere. Also a `:`
  in an inline SQL literal (e.g. JSON `{"x":1}` → `:1`) is parsed as a bind param — avoid or bind.
- Tests: `tests/claimstore/` with a reusable harness (`conftest.py`: session migrate-to-head +
  rollback-isolated `rollback_conn()`, reuses M0.3 `run_async`/`_db_available`). 11 tests, one per
  acceptance criterion. Updated M0.3 `tests/db/test_db_migrations.py` — the "no domain tables after
  head" test now checks at M0 head (downgrade to 0001) since M1 adds the first domain table.
- Verified: migration up→down→up reversible; full `make check` green (mypy --strict 51 files,
  import-linter 5/0, **178 passed** with live DB; skips cleanly with no DB).

## M1.3 — DONE & verified (ENG-117 → Done)
- `0003_field_definition.py`: §4 contract + extensions (field_class, value_schema, corroboration_min,
  description, active, pack, version, created_at). Enum types field_pass/field_class.
- `claimstore/registry.py`: register_field / get_field / list_fields / validate_value + a small
  dependency-free JSON-shape validator (object/array/scalars/enum/required/properties/items).
  `claimstore/packs.py`: SeedField, idempotent load_pack/load_core_pack, CORE_PACK (10 seed fields
  incl. one account.resonance.* + one contact.facet.* governed deep row).
- Wired validate_value into insert_claim (field claims must match value_schema; unregistered key
  rejected). Discovery claims skip this (added in M1.4).
- Namespace rule: canonical namespaces always admissible; a `<pack>.` namespace admissible only if
  caller passes pack=<namespace>. Re-register identical = no-op; different = FieldRedefinitionError.
- Test harness hardened: pack seeded PER-TEST inside rollback_conn (not committed once), so claimstore
  tests are robust to the M0.3 migration tests downgrading/upgrading the shared schema.

## M1.2 — DONE & verified (ENG-110 → Done)
- `claimstore/merge.py`: pure `merge_claims(claims, ttl, policy, now)` + DB seam
  current_value/current_values(batch)/provenance_index. Winner = LOWEST tier (= highest trust;
  substrate's "highest source_tier" means most-trusted = numerically lowest) → corroborations desc
  → confidence desc → collected_at desc.
- DECISION: Python merge, NOT a SQL view (policy-is-data needs swappable config a frozen view can't
  hold; function seam allows later materialized-view/incremental swap). No migration for M1.2.
- DECISION (D7 freshness): `FreshnessMode` config. Default TTL_GATES_ELIGIBILITY (fresh wins; stale
  is fallback, flagged, never dropped). Alt TRUST_FIRST (highest trust wins even if stale). The
  fresh-low-vs-stale-high edge case is config, not a hardcoded default.
- DECISION (empty+flag): current_value returns None when no eligible claim (empty is correct);
  un-promotable claim stays visible via claims_for. Opt-in fallback_to_unpromotable returns it flagged.
- Extended core.CurrentValue with freshness_state + conflicting_claim_ids; added core.FreshnessState.
- 10 pure unit tests (no DB) + 6 DB tests (incl. 1k-entity batch < 5s).

## M1.4 — DONE & verified (ENG-123 → Done)
- `0004_claim_provenance_flavors.py`: ALTER claim ADD identity_binding, use_class,
  discovery_provenance jsonb, claim_flavor enum(discovery|field_claim). research_mode was already in
  0002 (DECISION). CHECKs: discovery requires provenance+discovery-mode; field_claim forbids
  provenance; contact field_claim requires binding+use_class. Indexes: (research_mode), weak-binding
  partial, GIN discovery_provenance.
- core: added ClaimFlavor enum; extended Claim with claim_flavor + discovery_provenance
  (DiscoveryProvenance moved ABOVE Claim for forward-ref). RELAXED the contact-governance rule to
  apply only to FIELD_CLAIM contacts (a contact DISCOVERY claim, mode M3, needs no binding/use_class).
  factories: discovery_claim() new; field_claim/contact_field_claim are DRY aliases of
  account_claim/contact_claim.
- merge: discovery-flavor claims excluded from current_value eligibility (admission evidence, not
  field truth). Weak-binding exclusion now exercised against the live DB merge.
- 6 pure flavor tests + 9 DB flavor tests (incl. weak-binding↔merge coordination, all 4 modes).

## IMPORTANT gotcha discovered
- SQLAlchemy's asyncpg dialect returns JSONB ALREADY DECODED to Python (dict/list/str/int), NOT raw
  text. So `_row_to_claim` must NOT json-parse a string value_json (a bare string "x" is the decoded
  value, not JSON text). Fixed via `_decode_jsonb` (parse only raw bytes; else passthrough). The dict
  tests masked this until a string-valued jsonb (contact.facet) surfaced it.

## Adversarial review (5-lens workflow → per-finding verify) — DONE. 5 confirmed, 3 refuted.
Confirmed + FIXED:
1. (3 reviewers, same bug) MAJOR — merge `_conflict()` didn't apply `_is_eligible`, so DISCOVERY
   and WEAK-binding contact claims polluted the conflict flag (a non-field-value "source" raised a
   spurious conflict). Fixed: contenders now gated on `_is_eligible(c, policy)`. +2 regression tests.
2. MAJOR — governance CHECK + model required identity_binding+use_class for ALL contact field
   claims, but spec scopes it to PERSONAL (contact.facet.*) claims; it wrongly rejected
   contact.role_on_committee / contact.persona. Fixed: scoped to field_class CONTACT_FACET in both
   the model (classify_field_key) and the 0004 DB CHECK (field_key LIKE 'contact.facet.%'). +2 tests.
3. BLOCKER — the append-only trigger guard (built in 0002) listed only M1.1 columns; 0004 added the
   4 flavor columns but never recreated the function, so identity_binding/use_class/
   discovery_provenance/claim_flavor were silently MUTABLE in place. Fixed: 0004 CREATE OR REPLACEs
   the guard with the full column list (and downgrade restores the M1.1 list before dropping cols).
   +1 regression test (UPDATE of each flavor column rejected). Verified downgrade-to-0003 leaves the
   guard NOT referencing identity_binding.
Refuted (correctly): research_mode NOT NULL (documented decision), empty-string-span edge (caught by
can_be_promoted's `not evidence_span`), merge reading freshness_ttl directly (intra-package, batch).

## State: all 4 M1 issues DONE in Linear + verified + adversarially reviewed. make check green
## (mypy --strict 54 files, import-linter 5/0, **225 passed** with live DB; 37 DB tests skip cleanly
## without a DB). Migration chain 0001-0004 reversible (trigger recreate + restore verified).
## NEXT: commit decision is the user's (commit-on-request). Awaiting branch + go-ahead.

## Standing rules honored
- Commit only on explicit user request (NOT yet given for M1). Linear issues moved to Done as each
  is implemented+verified, with a comment noting commit is pending the M1 batch.
- DB for local verification: throwaway container `clue-postgres-m1` on :5433 (host :5432 is taken).
