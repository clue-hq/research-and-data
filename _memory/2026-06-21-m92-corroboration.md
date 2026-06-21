# 2026-06-21 — M9.2 Corroboration rules (ENG-134)

## State: DONE (impl + adversarial review + fixes + full DB suite green); awaiting user review
Branch `m9/verification-layer` (pushed to origin earlier this session). Migration base: M9.1 head
`8aefd82b6d59`. M9.2 is the 2nd of 6 M9 issues. **No frozen-surface touch** (core/*, obs/spans.py,
pyproject untouched — the `verification.corroboration` span already existed from the Beat-0 contract
delta).

## What M9.2 shipped
- **`verification/corroboration.py`** — `Corroborator` (M9-internal seam; no core protocol — it is a
  standalone pass, not a gate other milestones call). `evaluate(entity, field, *, scope, entity_type=None)`:
  reads non-superseded FIELD claims → groups by agreement (`EqualityMode` exact/numeric_tol/semantic)
  → counts **independent tier≤3 sources** per group (union-find: non-independent if share a non-empty
  host OR source_key; anonymous claims collapse to one) → writes each claim's `corroborations` →
  promotes `verification_status` to `verified` when group ≥ `corroboration_min` independent sources OR
  a tier-1 claim on a `single_source_sufficient` field → raises `conflict_flag` when ≥2 tier≤2 groups
  disagree (and then promotes nothing — never auto-picks). Plus `CorroborationPolicy` (tier bands +
  numeric/semantic tolerances), `CorroborationResult`/`ValueGroup`, and pure helpers `values_agree`,
  `group_by_agreement`, `independent_source_count`. Emits `verification.corroboration` span + 3
  metrics (`research.verification.corroboration.{evaluations,promoted,conflicts}`).
- **Migration `b3b636f67bd8`** (down_revision `8aefd82b6d59`): `equality_mode` pg enum + ALTER
  `field_definition` ADD `single_source_sufficient bool DEFAULT false`, `equality_mode DEFAULT 'exact'`
  (the threshold N **reuses the existing `corroboration_min`** — no third column); `conflict_flag`
  table with a **partial unique index** `(entity_id, field_key) WHERE resolved_by IS NULL` (the
  ON-CONFLICT target → idempotent re-eval, one open flag per pair). **No `claim` ALTER, no trigger
  change** (verification_status/corroborations already in the 0002/0004/0008 mutable allow-list).
- **`claimstore/claims.py`** — `record_verification(conn, claim_id, *, status, corroborations=None)`:
  the only in-place claim mutation besides supersession; sets the trigger-allowlisted columns; M9.3/M9.4
  will reuse it (status-only). DB CHECK `claim_tier4_verified_requires_span` stays the backstop.
- **`claimstore/registry.py`** — `register_field` extended with `single_source_sufficient` +
  `equality_mode` (mirrors the existing `corroboration_min` kwarg; threaded into `_SELECT`/`_INSERT`/
  `_comparable`); `get_corroboration_config(conn, field_key) -> CorroborationConfig|None` (plain-typed
  reader, keeps `field_definition` SQL in its owner module; claimstore never imports verification).
  `packs.py` `SeedField`/`_seed`/`load_pack` thread the two new fields (defaults preserve behavior;
  core pack unchanged in effect).

## Key decisions / mechanics
- **`verification_status` (M1.1) is the spec's `verification_state`.** Reused, not re-created — the
  spec text ("defines the milestone-wide verification_state column") predates M1.1 shipping it. Enum
  has `flagged` too; M9.2 never writes `flagged` (it uses the `conflict_flag` table) and leaves
  `rejected`/`flagged`/tier-4 claims untouched (tier-4 is M9.3's job).
- **Independence = connected components** over shared-host/shared-source_key edges (conservative
  anti-gaming; documented). A claim with neither host nor source_key collapses into one anonymous
  component. In practice resolvers always stamp `source_key`.
- **Conflict blocks ALL promotion** for the (entity, field) and raises a flag for M13.1 — the
  defensible reading of "never auto-pick silently" / "surface as a flag for review". A lone tier-2
  disagreeing with a tier-3 is NOT a conflict (needs ≥2 tier≤2 groups).
- **`corroborations` counts tier≤3, non-rejected, promotable sources** in the value-group; stored on
  every claim in the group (incl. tier-4, informative for merge tie-break). Promotion uses the same
  count vs `corroboration_min`.
- **Idempotent**: deterministic sort `(tier, collected_at, id)`; no-op verdict UPDATEs skipped;
  conflict_flag upserted (raised_at stable). Re-eval → same verdicts, no new rows.
- Conn injection mirrors M9.1: `conn_factory` default = `db.transaction()` (one committed txn:
  reads + verdict UPDATEs + flag upsert); tests inject a rollback-bound factory.

## Adversarial self-review (multi-agent workflow) — outcome
Ran a 4-dimension review (spec-conformance / correctness / schema-migration / isolation-DRY) →
skeptic verification → synthesis. 9 confirmed findings; **5 fixed in this PR, 2 deferred (backlog).**
- **Fixed:** (a) FLAGGED claims must not corroborate — `_is_counting`/`_is_authoritative` now exclude
  both REJECTED *and* FLAGGED (`_NON_SOURCE_STATUSES`). (b) `_host` IPv6/scheme-less parsing — switched
  to `urlsplit(...).hostname` (handles brackets/port/userinfo) with a `//`-prefix reparse fallback for
  scheme-less URLs (the old `rsplit(':')` corrupted IPv6). (c) Non-transitive conflict masking — conflict
  is now a **pairwise** authoritative-disagreement check (not group-count), so 960/1000/1040 at rel-tol
  0.05 still flags 960↔1040 even though 1000 bridges them; conflicting_claim_ids = each authoritative
  claim that disagrees with another. (d) DRY — extracted `canonical_json` to `claimstore.merge`
  (exported), reused in both merge and the corroborator (removed the duplicated `_canonical`). (e) Tests
  added: FLAGGED-not-corroborating, IPv6/scheme-less host, distinct-IPv6, non-transitive-conflict,
  open-conflict-suppresses-would-promote-group.
- **Deferred (recorded in CLAUDE.md/AGENTS.md backlog):**
  - **[M9.2×M1.2]** merge `current_value.conflict` uses exact equality while the corroborator uses the
    field's `equality_mode` → for numeric_tol/semantic fields merge over-flags (safe direction; no
    consumer reads `.conflict` yet). Proper fix relocates `EqualityMode`/`values_agree` into the shared
    substrate so merge can be mode-aware — M1.2's domain, explicitly out of M9.2 scope.
  - **[M9.2×M0.4]** `conflict_tier_threshold`/`MergePolicy` shape duplicated in 3 layers; alignment only
    runtime-asserted. Pre-existing; M9.2 added the third copy. Source from `config/schema.py` seam later.

## Verification performed
- `make check` (no DB) **green**: lint ✓ + typecheck ✓ (mypy 110 src files) + import-linter **10 kept /
  0 broken** + pytest **403 passed / 337 skipped**.
- M9.2 + M9.1 verification suite: **55/55** pass against isolated DB `clue_m9` (host localhost:5432, NOT
  shared `clue`); conftest migrates `clue_m9` (was at `8aefd82b6d59`) to the new head automatically.
  claimstore suite green (the load-sensitive `test_batch_scales_to_1k_entities` perf test flaked once
  under concurrent load, passes in isolation — `canonical_json` is a pure rename, no perf impact).
- `make db-smoke` on a fresh isolated DB `clue_m9_smoke`: up → down → up reversible through
  `b3b636f67bd8`; `alembic heads` single (`b3b636f67bd8`).
- Pushed `m9/verification-layer` to origin at the start of the session (per user instruction).

## Gotchas for the next M9 issues
- The `record_verification` helper is the shared verdict-write path — M9.3 (judge → rejected/verified)
  and M9.4 (binding) call it with `status` only.
- `get_corroboration_config` is the pattern for reading field-level M9 config off `field_definition`
  without importing verification into claimstore.
- DB-test DBs: `clue_m9` (test DB) + `clue_m9_smoke` (db-smoke) on host localhost:5432. Never migrate
  the shared `clue`.
- Per-(ICP, source) precision metric is only labeled by field today — thread ICP/source labels at the
  api composition root (the corroborator request carries neither). Noted in code.
