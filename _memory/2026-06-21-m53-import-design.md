# 2026-06-21 — M5.3 Import entry scenario (ENG-113, branch `m5/stage0-front-edge`)

Discipline: build → adversarial review → fix → pause (same as M5.1/M5.2). Keep ENG-113 in sync.
Built after a 6-agent seam-map workflow; the maps are summarized below as VERIFIED facts.

## The one decision that overturned three agents' framing
**Back-scoring is a direct `icp.score_entity(...)` call — NOT a new `core` protocol.**
Three of six seam agents flagged "no Pass-A scorer protocol in core → M5.3 must add one + inject a
fake". The m6-scorer agent (which actually read `icp/rubric.py`) found the scorer already exists as
the pure M3.4 function `clue_research.icp.score_entity(conn, rubric, entity_id, *, scope) ->
ScoreResult`, and `icp` is an M1–M4 service stage0 MAY import (M5.2 already imports it). Verified
directly (rubric.py:521-537). So: no `core.PassAScorer`, no injected fake — M5.3 calls
`icp.score_entity` directly (the same primitive M6 will wrap). Matches the spec ("M5.3 does not
re-implement the scorer") AND the independence contract. `discovery_scoring` (M6) is an empty stub.

## Verified seam facts (read from real code)
- **Resolution (M2)**: `identity.resolve_many(conn, observations) -> list[ResolutionResult]`
  (per-row savepoint, never throws; garbage row → `ResolutionMethod.NONE`). `Observation{name,
  entity_type, domain, registry_ids, geo, aliases, linkedin_url, verified_email}`. Result:
  `{method, candidates: tuple[Candidate{entity_id,score,features}], top_score, .top}`.
- **Disposition (M2)**: `identity.disposition(conn, obs, result, *, policy, tenant_id, decided_by,
  subject_entity_id) -> Disposition{outcome, entity_id?, task_id?, top_score}`. Outcome =
  `AUTO_MERGED | ENQUEUED(needs_review) | NEW_ENTITY(admit fresh candidate)`. Bands (policy-as-data,
  `DispositionPolicy`): ≥0.95 auto_merge, 0.70–0.95 review, <0.70 new. **Fuzzy caps at 0.85** so only
  a deterministic strong-key (domain/registry, score 1.0) ever auto-merges → wrong-entity never
  silently collapses (structural). Admit fresh: `insert_account_entity(... status=CANDIDATE)`.
  **Gap to handle: `disposition` NEW_ENTITY does NOT embed** → must call `identity.embed_account`
  after admit, else intra-batch dups aren't caught.
- **Score shapes (core, handoff.py)**: `Score{value, components: tuple[ScoreComponent{name,weight,
  value,evidence_claim_ids}]}`. `ScoreResult.as_fit_score()/.as_intent_score() -> core.Score`.
  Rubric: `icp.get_rubric_version(conn, client_id, icp_key, version)` (reproducibility seam),
  `ScoringRubric.field_keys`, `assign_tier(cutoffs, fit, intent)`, `TierCutoffs/TierBand`.
- **Claim factories (core)**: `discovery_claim(*, entity_id, entity_type, field_key, ...,
  research_mode, found_via, matched_signal, discovery_confidence)` — research_mode MUST be a
  discovery mode (`ACCOUNT_DISCOVERY`); found_via example is literally `"import:row#42"`; sets
  `ClaimFlavor.DISCOVERY`; `insert_claim` SKIPS the registry/field check for discovery claims (so
  field_key `"discovery.provenance"` needs no registration). `account_claim` /
  `contact_claim(... identity_binding, use_class)` (required). `ExtractionMethod.CRM_IMPORT` (URL not
  required). No `lawful_basis` column anywhere in core (M10.5 plans to add it).
- **Field registry**: canonical namespaces (`account.`/`contact.`/`core.`) register WITHOUT a pack;
  vertical packs (`import.`) must pass `pack="import"`. `account.scoring.fit/.intent` (TENANT_PRIVATE)
  + `account.crm_relationship_status` (tier_plan=("crm",), enum customer/open_opportunity/prospect/
  former_customer/none) already exist in CORE_PACK. `get_field(conn, field_key) -> FieldDef|None`.
  `register_field(conn, field_def, *, value_schema, pack=None)` for a canonical field.
- **Reuse**: `identity.stamp_reuse(claim, *, tenant_id, policy)` — fails loud if a claim classifies
  tenant_private with no tenant_id. crm_import method + `account.scoring.`/`contact.`/`import.`
  prefixes → tenant_private. Add `IMPORT_REUSE_POLICY` (adds `import.` prefix) to stage0/reuse.py.
- **CRM (M4)**: stage0 cannot import `resolvers`; drive via `sources.resolve_field(conn, entity,
  field_def, *, mode, run_id, tenant_id, reuse_policy)` → dispatches to bound `"crm"` resolver
  (bound at api root; fake via `sources.bind_resolver` in tests). "Already a customer" = read
  `current_value(account, "account.crm_relationship_status", scope)`.
- **No PhaseHandler**: there is no `CampaignPhase.IMPORT`. Import is an entry scenario / service
  entrypoint that runs BEFORE M6's SCORING phase, store-mediated convergence. Freeze line 70-72:
  "M5 writes resolved candidate accounts; M6's scoring phase scores all candidates uniformly. Neither
  imports the other." So M5.3 = 3-file quartet (import_types / import_fields / import_accounts), no
  handler.

## Design (files under src/clue_research/stage0/)
- `import_types.py` — `ImportRow{row_index, name, domain, registry_ids, geo, aliases, contacts[]}`,
  `ImportContactRow{name, email, linkedin_url, title, use_class?}`, `FitFlag` enum (FIT|NON_FIT),
  `ResolvedAccount{account_entity_id, fit_score: core.Score, intent_score: core.Score, fit_flag,
  already_customer, crm_relationship?, row_index, resolution_method, matched_signal,
  resolution_confidence, provenance_claim_id}`, `NeedsReviewRow{row_index, task_id, top_score,
  candidate_entity_ids, reason}`, `UnresolvedRow{row_index, reason, identity_repr}`,
  `ImportResult{import_batch_id, resolved[], needs_review[], unresolved[], counts}`. All frozen.
- `import_fields.py` — `import.batch` PACK field (TENANT_PRIVATE; grouping marker on client entity)
  + `contact.import_record` canonical contact field (TENANT_PRIVATE, registered pack=None) +
  `load_import_pack(conn)`. `DISCOVERY_PROVENANCE_FIELD = "discovery.provenance"` (unregistered).
- `import_accounts.py` — `import_accounts(conn, rows, icp_spec_ref, *, client_id, client_entity_id,
  import_batch_id=None, crm_enrich=False, decided_by="auto") -> ImportResult`. Flow:
  1. resolve_many over Observations (rows with no name+domain+registry → unresolved up front).
  2. per-row disposition (sequential; in-memory strong-key map for intra-batch new dedup;
     embed_account after NEW_ENTITY). Partition into resolved / needs_review / unresolved.
  3. resolved rows: write `discovery.provenance` DISCOVERY claim (found_via=import:row#N,
     matched_signal, research_mode=ACCOUNT_DISCOVERY) = convergence + audit artifact.
  4. (crm_enrich) resolve_field over rubric scoring fields w/ crm in tier_plan → tier-1 claims;
     read account.crm_relationship_status → already_customer.
  5. back-score: rubric = get_rubric_version(client_id, icp_key, icp_version); score_entity(...,
     scope=for_tenant(client_id)); write account.scoring.fit/.intent claims (stamped); fit_flag from
     rubric tier-cutoff fit floor (assign_tier == fallback → NON_FIT).
  6. contacts: resolve/admit under account; contact_claim on contact.import_record w/
     identity_binding (STRONG if email/linkedin else WEAK) + use_class (default PROFESSIONAL_PUBLIC)
     + lawful_basis in value_json.
  7. write `import.batch` marker on client entity (counts). Return ImportResult.
- `reuse.py` += `IMPORT_REUSE_POLICY` (`import.` prefix). `__init__.py` += M5.3 exports.

## Decisions to flag for the user at pause
1. **lawful_basis location**: no core.Claim column exists (M10.5 will add it). Recording it in the
   contact claim's value_json (forward-compatible). OK, or wait for the core column?
2. **Registering a canonical `contact.import_record` field from stage0** (no pack) to carry governed
   imported-contact data. Minimal/import-specific; M8 owns full contact schema. OK?
3. **D6 non-fit threshold**: using the confirmed rubric's tier-cutoff fit floor as the ICP-relative
   threshold (assign_tier→fallback ⇒ NON_FIT). If rubric sets no fit floor, nothing is flagged
   (honest no-op). OK?
4. **CRM enrich opt-in (`crm_enrich=False`)** + back-scoring scores against currently-known claims
   (CRM tier-1 + prior); sparse imports score mostly MISSING→low (honest, flagged), and M6's full
   Pass A later re-scores. OK?

## BUILD STATUS — BUILT, green, under adversarial review
Files: NEW `import_types.py`, `import_fields.py`, `import_accounts.py`, `tests/stage0/test_import.py`,
`tests/stage0/test_import_static.py`; EDITED `reuse.py` (+IMPORT_REUSE_POLICY), `__init__.py`
(exports + docstring), `tests/stage0/_fakes.py` (+FakeCrmResolver, +build_confirmed_icp),
`tests/stage0/conftest.py` (+load_import_pack seed).
Key design choices realized:
- Back-score via `icp.score_entity` directly (NO core protocol, NO fake scorer) — verified
  importable. M5.3 does NOT persist `account.scoring.*` (M6.3 owns that durable write); back-scores
  returned in-memory as `core.Score`.
- Resolution: filter no-identity rows → unresolved up front; `resolve_many`; sequential
  `disposition` with an in-memory strong-key map for intra-batch dedup + `embed_account` after each
  NEW_ENTITY; ENQUEUED→needs_review, NONE/no-identity→unresolved, AUTO_MERGED/NEW_ENTITY/intra_batch
  →resolved. `surviving_id` after each.
- Provenance: one `discovery.provenance` DISCOVERY claim/resolved row (research_mode=ACCOUNT_DISCOVERY,
  found_via=import:row#N, matched_channel=import) = convergence + audit (left PUBLIC, symmetric w/
  discovery). CRM tier-1 via `sources.resolve_field` over crm-tier fields. Contacts via `contact_claim`
  on canonical `contact.import_record` (registered directly, pack=None) w/ identity_binding+use_class,
  lawful_basis in value_json. `import.batch` marker on client entity (tenant_private).
  Deterministic run_id = uuid5("import:{batch_id}").
- No PhaseHandler (no CampaignPhase.IMPORT).
Verification: ruff ✓, mypy 122 src ✓ (gate is src-only; tests aren't type-gated), import-linter
**10/0** (independence holds), `make check` no-DB **406 passed/347 skipped**, full stage0 DB suite on
`clue_m5` **68 passed** (M5.1+M5.2 no regressions; M5.3 = 10 DB + 7 static).

## Adversarial review (6 lenses, 24 agents, every finding verified): 18 findings → 7 confirmed → ALL FIXED
- **MAJOR registry strong-key not canonicalized** (`_strong_key`): the registry branch used the RAW
  `ns:val` while every M2 DB path canonicalizes via `canonical_registry_id`, so two textual variants
  of one DUNS escaped the intra-batch dedup → a duplicate entity (or an IntegrityError on the registry
  unique index). Fix: canonicalize the registry strong key (skip empties). New DB test
  (registry-only variants collapse) + updated static test to the canonical key.
- **MAJOR account write phase not savepoint-isolated**: only resolve_many (read) + per-contact were
  savepoint-wrapped; the admit+provenance+CRM+back-score writes ran in the outer tx → a poison row
  (raising CRM resolver) aborted the whole batch, breaking the documented no-silent-drop invariant.
  Fix: extracted `_resolve_row` returning a `_RowOutcome`; the per-row admit+write phase runs in its
  own `begin_nested()`; on failure the row → unresolved[] ("resolution write failed — row isolated").
  `admitted_by_key` is updated AFTER the savepoint commits (no dangling index on rollback).
- **MAJOR import provenance written PUBLIC, cross-tenant leak**: "which accounts a client imported"
  is client-tuned/sensitive (same class as account.scoring.*/crm_import). Fix: stamp the
  `discovery.provenance` claim tenant_private — added `discovery.` prefix to `IMPORT_REUSE_POLICY`
  (import-scenario only; a real Scenario-A discovery run uses its own policy) + `stamp_reuse` in
  `_write_resolution_provenance` (threaded client_id). Pinned by an explicit reuse_scope/tenant_id
  assertion. Convergence unaffected (discovery claims never merge; M6 reads under the client scope).
- **NIT** `_identity_signal` now derives from the strong_key (no ladder duplication / double
  registrable_domain). **NIT** dropped never-emitted "probabilistic" from the resolution_method doc.
  **MINOR** added SENSITIVE contact test (lawful_basis="none", no lia_ref) + weak-binding lawful
  basis. **NIT** added the registry-only-row end-to-end dedup test.
- Dismissed correctly (11): the disp.task_id/entity_id None-guards are REQUIRED for mypy Optional
  narrowing (not dead); the convergence test can't compare vs a real discovery account (M6 is a stub);
  `already_customer` excluding open_opportunity is intended (raw crm_relationship surfaces "in
  pipeline"); the re-derive-ICP action is a UI affordance over the surfaced non-fit set (synthesis is
  M5.2); retried-import duplicate review-task + benign provenance/marker re-write are noted follow-ups.
- **Post-fix verification:** ruff ✓, mypy 122 src ✓, import-linter **10/0**, `make check`
  **406 passed/348 skipped**, full stage0 DB suite on `clue_m5` **69 passed** (M5.3 = 11 DB + 7 static).
