# 2026-06-22 — M9.4 Identity-binding gate (ENG-144, strong vs weak)

## State: DONE (impl + adversarial audit + fixes + full DB suite green); awaiting user review
Branch `m9/verification-layer`. Migration `971febbe2906` off M9.3 head `911a1beeb9c1`. `make check`
green (lint/mypy/import-linter 10-0/443 passed-375 skipped); **42/42** M9.4 DB tests + full
verification suite green on docker `clue-m9-pg` (5433); db-smoke up→down→up reversible, single head.

## Adversarial audit (5-dimension workflow + skeptic verify + completeness critic) — outcome
19 confirmed findings (1 critical, 1 high, 7 medium, 6 low, 4 nit) + 8 completeness gaps. **Fixed in
this PR (12 code/test fixes):**
1. **[CRITICAL] same-name guard failed open on NULL-prior (tier-4 open-web) sources.** `exa_deep`/
   `parallel_task` carry no `identity_binding` prior → a handle-less name+employer+geo span reached
   STRONG. Fix (durable, source-agnostic): `strength_from_signals` now treats a prior that is **not
   explicitly STRONG** (WEAK *or* None) as untrusted → criterion-2 requires a handle ("design for the
   strict case / fail closed on unknown prior"). The seed-stamp alternative is a complementary
   backlog item.
2. **[HIGH] verified_email-in-evidence_span forged a handle match.** The span body is attacker-
   controllable; restricted the email handle signal to `source_url` only, and token-bounded it
   (`_token_present`) so `jane@acme.com` ≠ `maryjane@acme.community`.
3. **[HIGH gap] stale-cache hole — cache keyed on `(claim_id, policy_version)`.** Two policies can
   share version=1 (in-code default + a config row), so an in-place K/set edit served the cached
   verdict (AC5 only ever proven across two claims). Re-keyed the `identity_binding_eval` cache on
   `BindingPolicy.fingerprint()` (a sha256 of all content + version) — mirrors M9.3 keying on
   judge_model. Migration: `policy_fingerprint text` + UNIQUE `(claim_id, policy_fingerprint)`;
   `policy_version` kept as an audit column.
4. **[MED] score=1.0 on a WEAK verdict** when `verified_handle_sufficient=False` — score now gated on
   `handle_strong`, not the raw handle flag.
5. **[MED] name-only-never-strong** — criterion-2 STRONG now requires ≥1 *non-name* identifier
   (`non_name_identifier`), encoding the spec's "weak = name match only" (defeats a misconfig K=1).
6. **[MED] static drift guard** extended to the two guard booleans + version (was only K + set).
7. **[NIT→fixed] normalize_url** robust two-pass scheme-less parse (a path with `//` no longer drops
   the host); bare-host profile can't prefix-match an arbitrary path.
8. **load_binding_policy** warns on an unsupported `strong_identifier_set` kind (mirrors M9.3's
   prompt_version fallback warning); `SUPPORTED_IDENTIFIER_KINDS` exported.
9. **Docstrings corrected** — the born-None non-facet caveat (the backstop is the *only* exclusion
   there); the obs-metric duplication note.
10. **New tests** (12): critical untrusted-source-name-match→weak; born-None backstop→rejected+excluded;
    gate-never-mutates-identity_binding; same-claim policy-content re-classify (fingerprint); email
    source_url-not-span + substring + bare-host; untrusted-prior-requires-handle; handle-not-sufficient
    score; name-only-never-strong; fingerprint content-addressing; fractional-score round-trip;
    discovery-flavored ValueError; AC7 ordering keyed on the durable artifact (current_value + eval row).
**Deferred to backlog (CLAUDE.md/AGENTS.md):** M8.4/M8.5 stamp `identity_binding` from
`classify_binding` pre-insert (AC4 integration); born-None non-facet contact merge fail-closed
(M1.2/core); host-normalizer DRY consolidation; obs strong-binding-share metric reconciliation;
merged-contact survivor resolution (errs safe); `_geo_strings`/`_token_present` recall (M9.6);
core protocol docstring "writes claim.identity_binding" wording.

## State: design locked, implemented
Branch `m9/verification-layer`. Migration base: M9.3 head `911a1beeb9c1`. M9.4 is the 4th of 6 M9
issues. **No frozen-surface touch** — `core.verification.IdentityBindingGate` protocol + `Binding`
value type, `core.enums.IdentityBinding` enum, and `obs.spans.SPAN_VERIFICATION_IDENTITY_BINDING`
ALL already exist from the Beat-0 contract freeze. M9.4 only supplies the impl behind them (exactly
like M9.2/M9.3 supplied their gates).

## The one load-bearing design fact: the immutable `identity_binding` column IS the exclusion signal
Verified against the actual substrate (not just the M9.1 gotcha note):
- `claim.identity_binding` is **immutable** (0004 trigger allow-list = only
  `superseded_by/verification_status/corroborations`). The gate CANNOT UPDATE it in place.
- It is **required at insert** for `contact.facet.*` field claims (DB CHECK
  `claim_contact_field_requires_governance` + the `Claim` pydantic validator).
- The M4 waterfall **already stamps** it from `source_manifest.identity_binding_strength` at insert
  (`sources/waterfall.py::_finalize`). So contact claims are *born* with a (provisional) binding.
- `merge._is_eligible` (claimstore/merge.py:133-137) **already excludes weak-binding contact claims**
  from `current_value` via the column, independent of `verification_status`.
- `core.can_be_promoted` returns False for `entity_type==CONTACT and identity_binding==WEAK` — the
  structural promotion kill-switch every promotion site (corroborator/judge/insert_claim) honours.

⇒ The durable exclusion of a weak claim is the **born immutable column**, not a status. So M9.4's
gate's real job is to make that column **authoritative** (the writer stamps the gate's classification
at insert), plus audit + the strong-binding metric, plus a defensive status backstop for drift.

## What "Writes claim.identity_binding" means under immutability (resolved)
M9.4 does NOT write the column itself. Two surfaces:
- **`classify_binding(claim, contact, *, account_name, account_aliases, manifest_prior, policy)
  -> Binding`** — PURE, DB-free authoritative classifier. M8.4/M8.5 call this *before insert* and
  stamp `binding.strength` as the claim's `identity_binding` (born-correct, immutable thereafter) —
  upgrading the waterfall's source-prior stamp to a per-claim classification. Unit-tested.
- **`IdentityBindingGateImpl.classify(claim) -> Binding`** (the frozen `IdentityBindingGate` impl) —
  reads the contact entity + parent-account name + source prior, calls `classify_binding`, writes the
  `identity_binding_eval` audit row, drives the defensive status backstop, emits the span + metrics.
  Operates on a (typically) persisted claim, like M9.3's judge.

## Classification rules (deterministic, policy-driven, testable)
STRONG iff (verified-handle match) OR (≥K co-occurring strong identifiers), with the same-name guard:
- **Criterion 1 — verified-handle match:** the claim's `source_url` normalizes to / is under the
  contact's *verified* `linkedin_url` (the profile M2 resolved on), OR the `verified_email` appears
  in `source_url`/`evidence_span`. `verified_handle_sufficient` (policy, default True) → handle alone
  ⇒ strong, score 1.0.
- **Criterion 2 — ≥K identifiers co-occur** in `claim.evidence_span`: count which of
  `strong_identifier_set` (default {full_name, employer, geo}) appear (word-boundary, casefold).
  `full_name` from contact (+aliases); `employer` from the parent `account_entity.canonical_name`
  (+aliases); `geo` from contact.geo values. ("role" is configurable but unavailable as an entity
  column → never fires; honest.) STRONG iff count ≥ `min_identifiers_k`.
- **Same-name guard:** `weak_source_requires_handle` (policy, default True) — a source whose manifest
  prior is WEAK cannot reach STRONG on identifier-count alone (needs a handle match); its score is
  halved. (A name+employer mention on a low-binding web page is exactly the same-name trap.)
- **Source prior** (`source_manifest.identity_binding_strength`, read by raw SQL like
  pre_spend `_covered_tiers`, no `sources` import) **informs, never overrides** per spec.
- Contact unresolved/None → WEAK, score 0 (can't confirm it's this person).
- `strength_score` (UnitInterval): handle=1.0; else `min(1, count/K)`, ×0.5 for a weak-prior source.
- `signals` dict: verified_handle_match, identifier_matches[], identifier_count, min_identifiers_k,
  source_prior, contact_resolved, (+ a born_binding/drift note when the gate rejects on drift).

## Enforcement (status — the only mutable lever)
- Classified **WEAK** and the claim is already structurally excluded (`not can_be_promoted` — i.e.
  born weak) → leave `verification_status` untouched (`unverified`; spec-literal "never advance past
  unverified"; the column excludes it from merge/handoff).
- Classified **WEAK** but `can_be_promoted(claim)` is True (DRIFT: born strong/None, but the evidence
  says weak) → set `verification_status = REJECTED` (safe direction — a mis-stamped claim must not
  ride a wrong column into the usable set; `merge.exclude_rejected` then drops it). Record the drift.
- Classified **STRONG** → leave status untouched (eligible; judge/corroborator decide promotion).
- Gate runs ONLY on contact field claims: non-contact or discovery-flavored claim → `ValueError`
  (binding is contact field-claim provenance; account claims untouched — AC).

## Shape (mirrors M9.1/M9.2/M9.3 exactly)
- `verification/identity_binding.py`: `IdentityBindingGateImpl`, `BindingPolicy`/
  `DEFAULT_BINDING_POLICY` + `load_binding_policy` (per-client → global → default, ORDER BY version
  DESC, created_at DESC, policy_id DESC — the M9.3 tie-break lesson applied from the start), pure
  helpers `classify_binding`/`handle_matches`/`count_identifier_matches`/`strength_from_signals`/
  `normalize_url`. Injected `conn_factory` (default `db.transaction`), optional `sink`. Span
  `verification.identity_binding`; M9-local metrics
  `research.verification.identity_binding.{classifications,strong,weak}` (share = strong/classif.;
  ALL metrics skipped on a cache replay so the share stays exact — slight, documented divergence
  from M9.3 which counts judgments on replay).
- Migration `<hash>` off `911a1beeb9c1`: `binding_policy` config table (typed cols incl.
  `strong_identifier_set jsonb`, `min_identifiers_k`, the two policy bools, `version`, `created_at`;
  UNIQUE `(client_id, version) NULLS NOT DISTINCT` from the start — avoids the M9.1 NULL-slot gap),
  `identity_binding_eval` audit (`claim_id, contact_entity_id, strength identity_binding,
  strength_score, evidence_signals_json, policy_version, evaluated_at`; UNIQUE `(claim_id,
  policy_version)` = the idempotency/cache key; claim_id + evaluated_at indexes). **No new enum**
  (reuse `identity_binding`), **no `claim` ALTER, no trigger change**. Reversible.
- Tests `tests/verification/test_identity_binding.py`: pure-unit (classifier/handle/identifier/score/
  policy defaults) + DB-gated behaviour, one per §M9.4 acceptance criterion. DB-gated tests build a
  real `contact_entity` (insert_account_entity + insert_contact_entity) and contact claims.

## Out of scope (documented deferrals)
- The pre-insert stamp wiring (M8.4/M8.5 call `classify_binding` before insert) — integration-time
  at the `api` composition root (same deferral pattern as M9.1 AC-6 / M9.3 re-retrieval delivery).
- M10 use-gate (runs AFTER this gate on strong-bound claims only); the ordering test uses a local
  M10 stub (a weak claim never reaches it).
- `role`/`employer` from richer contact claims (vs the entity column) — not pulled cross-milestone.
