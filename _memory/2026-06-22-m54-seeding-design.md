# 2026-06-22 — M5.4 Hybrid lookalike seeding (ENG-119, branch `m5/stage0-front-edge`)

M5.3 committed (`77875d0`), paused. Now building M5.4. Discipline: build → adversarial review → fix →
pause. Keep ENG-119 in sync. Seam-mapped by reading the real M1–M4 + M5.1/5.2/5.3 code (facts below).

## What M5.4 is
`assemble_lookalike_seeds(...) -> SeedSet`: collect + rank + package resolved `account_entity` seeds
for **M6 mode-M1 lookalike expansion** from three sources — (1) M5.1 existing-customer evidence
(`client.customer`), (2) CRM existing customers (M5.3 import flagged `already_customer`), (3) resolved
high-fit imports (M5.3). Produces seeds, NOT the discovery run (that's M6). Per-ICP partition (D5);
non-fit imports excluded from seeding (D6 default); hybrid opt-out → suppressed SeedSet.

## Verified seam facts (read from real code, not assumed)
- **Import back-scores are in-memory only.** M5.3 does NOT persist `account.scoring.*` (M6.3 owns that
  durable write); the only place fit/intent back-scores exist is the returned `ImportResult.resolved`
  (each `ResolvedAccount{account_entity_id, fit_score: core.Score, intent_score, fit_flag,
  already_customer, crm_relationship, resolution_method, matched_signal, resolution_confidence,
  provenance_claim_id}`). ⇒ **M5.4 consumes `ImportResult` directly** (not a persisted `import_batch_ref`).
- **`score_entity(conn, rubric, entity_id, *, scope) -> ScoreResult`** is pure/deterministic and on a
  **claim-less entity returns `fit_score = 0.0`** (all contributions MISSING → raw 0 / total). So
  re-scoring a customer against the target ICP gives a correct per-ICP partition, and a customer with
  no scorable claims scores 0 → excluded by a fit floor. `ScoreResult.as_fit_score()/.as_intent_score()
  -> core.Score`. `get_rubric_version(conn, client_id, icp_key, version) -> ScoringRubric|None`.
- **Fit floor** = `min(band.min_fit for band in rubric.tier_cutoffs.bands)` (the same rule M5.3's
  `_fit_flag` uses; floor 0 ⇒ no bar ⇒ nothing gated). `assign_tier(cutoffs, fit, intent)` exists too.
- **`SeedAccount` (icp_types) already has `{account_entity_id, seed_reason: str, seed_confidence:
  UnitInterval, justifying_claim_ids}`** — reuse it as the per-seed element so M5.4 output slots
  straight into `ICPProposal.seed_accounts` → `confirm_icp` writes `discovery_strategy.seed_account_ids`
  → M6 reads it (store/spec-mediated; no sibling import). `seed_reason` docstring lists
  `existing_customer | case_study | high_fit_import | crm_customer`.
- **Seed provenance = a `discovery.provenance` discovery-flavored claim** (`discovery_claim(...)`,
  `matched_channel` rides in `value_json`, `research_mode=ACCOUNT_DISCOVERY`, found_via=`seed:{reason}`).
  `insert_claim` SKIPS the registry/field check for DISCOVERY claims ⇒ **no new registered field**.
  Stamp tenant_private (the seed selection is client-tuned/competitively-sensitive, same class as
  import provenance). Add `SEED_REUSE_POLICY` = DEFAULT + `discovery.` prefix (compose, don't copy).
- **Customer evidence**: `read_client_kb(conn, client_entity_id, *, client_id, version)` returns
  `{field_key: value}`; `client.customer` is a LIST of `{name, domain}` objects (value_type "list").
  `read_client_kb_claims(...)` returns `{field_key: Claim}` ⇒ the `client.customer` claim id is the
  justifying claim. Resolve each entry via M2 `resolve` + `surviving_id` (deterministic/high-conf
  reuse only by default; admit fresh candidate only if `policy.admit_unmatched_customers`).
- **No PhaseHandler** — seeding is an entry-scenario service entrypoint inside the hybrid proposal
  flow (M5.2), not a campaign phase (no `CampaignPhase.SEEDING`). Mirrors import (3-file, no handler).

## Design (files under src/clue_research/stage0/)
- `seeds_types.py` — `SeedReason` StrEnum; `SkippedSeed{identity_repr, reason}` (customer evidence that
  didn't become a clean seed — surfaced, never silently dropped); `SeedPolicy` (policy-as-data:
  min_resolution_confidence=0.85, min_seed_confidence=0.5, max_seeds=50, admit_unmatched_customers=False,
  w_resolution/w_fit/customer_bonus weights) + `DEFAULT_SEED_POLICY`; `SeedSet{client_id, icp_key,
  icp_version, seeds: tuple[SeedAccount], suppressed, skipped, channels}` + count props.
- `seeds.py` — `assemble_lookalike_seeds(conn, icp_spec_ref, client_kb_ref, *, import_result=None,
  policy=DEFAULT_SEED_POLICY, enabled=True, run_id=None) -> SeedSet`. Flow:
  1. enabled=False ⇒ return suppressed empty SeedSet (import-only path unaffected — opt-out).
  2. rubric = get_rubric_version(icp_spec_ref); fit_floor from tier_cutoffs.
  3. imports: for each resolved FIT import (D6: skip NON_FIT), reason = crm_customer if already_customer
     else high_fit_import; fit = acc.fit_score.value (M5.3 back-score, precondition: scored vs this ICP).
  4. customers: read_client_kb_claims(client.customer); resolve each via M2; reuse existing (conf>=floor)
     or skip; re-score via score_entity against target rubric → fit; reason = existing_customer.
  5. dedup by entity (keep strongest reason: crm_customer > existing_customer > high_fit_import).
  6. seed_confidence = clamp(w_res*res_conf + w_fit*fit + customer_bonus·is_customer); gate on
     res_conf>=min, seed_conf>=min, AND fit>=fit_floor (per-ICP partition + D6); rank desc; cap max_seeds.
  7. persist one seed discovery-provenance claim per chosen seed (tenant_private); SeedAccount carries
     justifying_claim_ids = (source justifying claim, seed provenance id). channels = seed-origin set.
- `reuse.py` += `SEED_REUSE_POLICY` (DEFAULT + `discovery.` prefix).
- `__init__.py` += M5.4 exports.

## Decisions to flag for the user at pause
1. **In-memory `ImportResult` seam** (not a persisted `import_batch_ref`): forced by M5.3 keeping
   back-scores in-memory. OK, or should M5.4 read a persisted import set?
2. **Per-ICP partition by re-scoring customers via `score_entity`** against the target rubric ⇒ a
   customer with NO scorable claims scores 0 and is excluded by a fit floor (honest). Source(1) thus
   yields seeds mainly for customers that are also characterized (CRM/import/researched). OK?
3. **`admit_unmatched_customers=False` default** — a customers-page name with a domain but no store
   entity is reported in `skipped` rather than minting a candidate that would score 0 and be excluded.
   OK, or admit domain'd customers as candidates (for M6's external lookalike resolver)?
4. **Imports precondition**: M5.4 trusts `import_result` was back-scored against `icp_spec_ref` (the
   hybrid same-ICP case). Multi-ICP seeding from imports would re-score (follow-up). OK?

## BUILD STATUS — BUILT, green; under adversarial review
Files: NEW `seeds_types.py`, `seeds.py`, `tests/stage0/test_seeds.py`, `tests/stage0/test_seeds_static.py`;
EDITED `reuse.py` (+SEED_REUSE_POLICY = DEFAULT + `discovery.`), `__init__.py` (exports + docstring),
`tests/stage0/_fakes.py` (+build_confirmed_icp_on_field). NO new field/pack (seed marker is an
unregistered `discovery.provenance` claim), NO PhaseHandler, NO migration.

Key realized choices:
- `assemble_lookalike_seeds(conn, icp_spec_ref, client_kb_ref, *, import_result=None,
  policy=DEFAULT_SEED_POLICY, enabled=True, run_id=None) -> SeedSet`. Per-seed element reuses
  `icp_types.SeedAccount` (slots into `ICPProposal.seed_accounts`).
- Imports: reuse M5.3 in-memory back-scores; FIT only (D6 skips NON_FIT); crm_customer if
  already_customer else high_fit_import.
- Customers: `read_client_kb_claims(client.customer)` → resolve via M2 (reuse-only unless
  `admit_unmatched_customers`) → re-score vs target rubric (`score_entity`) → existing_customer.
- Dedup by entity (keep stronger anchor: crm_customer>existing_customer>high_fit_import; union
  justifying ids). Gate on res_conf>=min, seed_conf>=min, fit>=fit_floor; rank desc; cap max_seeds.
- Per chosen seed: one tenant-private `discovery.provenance` 'seed' marker (SEED_REUSE_POLICY).
- `skipped[]` = customer evidence that failed to RESOLVE (resolution failures only). A resolved
  candidate below the fit floor is a partition decision, not skipped (avoids customer×ICP noise).

Verification: ruff ✓, format ✓, mypy 124 src ✓, import-linter **10/0** (independence holds), no-DB
`pytest` **414 passed / 357 skipped** (+8 static seed tests vs M5.3's 406), full stage0 DB suite on
`clue_m5` **86 passed** (M5.1/M5.2/M5.3 no regressions; M5.4 = 9 DB + 8 static).

## ADVERSARIAL REVIEW (5 lenses, 28 agents, every finding independently verified): 23 raised → 21 confirmed → triaged
Distinct issues after de-duping overlaps (idempotency raised 3×, import-rescore 2×):

**FIXED (code):**
- **A — re-assembly accreted duplicate seed markers (idempotency docstring was false).** `_write_seed_provenance`
  did a plain `insert_claim`; deterministic run_id was computed but never consulted. Fix: read existing live
  `discovery.provenance` markers and reuse the one with `run_id==run` + `matched_channel=='seed'` (explicit guard,
  mirrors M4 waterfall idempotent-skip; the claim table has no unique constraint). Pinned: `test_reassembly_is_stable`
  now asserts marker-count==1 + stable justifying_claim_ids.
- **C — self-seed/dedup compared raw ids (asymmetric, stale-id hazard).** Fix: resolve `client_entity_id` to its
  survivor once at top; resolve each import's entity via `surviving_id` and key `_consider` + self-check on the
  survivor (conventions §2: key on resolved entity_id). Test: `test_import_resolving_to_client_is_not_self_seeded`.
- **D — `customer_seed_count` re-implemented `is_customer_reason` (omitted CASE_STUDY → latent divergence).** Fix:
  reuse `is_customer_reason(SeedReason(s.seed_reason))`. Static test asserts CASE_STUDY counts.
- **E — fit-floor rule duplicated (seeds._fit_floor vs import._fit_flag).** Fix: extracted `icp.fit_floor(cutoffs)`
  beside `assign_tier` (M3.4), exported; both call sites use it (single-sourced D5/D6 partition floor). Static test.
- **nit — redundant `icp_spec_ref.client_id`** → use bound `client_id`.
- **DRY — reuse-policy boilerplate** (4 policies repeated version/enabled/methods; not actually inheriting the M2
  default). Fix: `_extend(*prefixes)` helper via `model_copy` (keeps the shared default a live reference). All 4
  policies refactored.

**ACCEPTED BY DESIGN + FLAGGED to user (B):** imports use M5.3's **in-memory back-scores** (spec: "using M5.3
back-scores where available"); customers have no back-score so they're scored fresh — the asymmetry tracks data
availability, BY DESIGN. The unenforceable precondition (import_result must be scored vs this icp_spec_ref) means
reusing one ImportResult across *different* ICPs (multi-ICP, D5) would mis-partition imports. The wired hybrid
same-ICP flow is correct. Strengthened the docstring; **flag #5 for the user** (re-score imports per-ICP vs keep
in-memory + per-ICP import runs).

**SPEC-DOC SYNC (G):** updated M05 §M5.4 Interface/Data-model to the implemented contract (import_result not
import_batch_ref; SeedSet envelope keyed (client_id,icp_key,icp_version); seeds carry justifying_claim_ids).

**DISMISSED (correctly):** malformed (non-dict) customer entries silently dropped — UNREACHABLE (the
`client.customer` value_schema rejects non-dict items at write; the isinstance filter is defense-in-depth). The
import double-fit-gate is benign (the floor gate is load-bearing for customers). CASE_STUDY reserved-but-unemitted
is fine (consistency handled by fix D). 1 refuted, 1 uncertain (the malformed-entries one).

## Post-fix verification — GREEN
ruff ✓ · format ✓ · mypy 124 src ✓ · import-linter **10/0** (independence holds) · no-DB `pytest` **417 passed /
360 skipped** · full stage0 DB suite on `clue_m5` **92 passed** (M5.4 = 12 DB + 11 static; M5.1/M5.2/M5.3 incl. the
shared-fit_floor refactor of import — no regressions).

## Decisions to flag at pause (final)
1. lawful_basis-style: n/a here. 2. In-memory `ImportResult` seam (forced by M5.3 in-memory back-scores). OK?
3. Per-ICP partition re-scores **customers** via `score_entity` → a claim-less customer scores 0 and is excluded
   (clean anchors). OK? 4. `admit_unmatched_customers=False` default (a domain'd-but-unmatched customer is reported
   in `skipped`, not minted). OK? 5. **Imports keep M5.3 in-memory back-scores (not re-scored per target ICP)** —
   correct for the wired same-ICP flow; multi-ICP reuse of one ImportResult would mis-partition. Keep, or re-score?
