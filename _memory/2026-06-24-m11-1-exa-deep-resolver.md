# 2026-06-24 — M11.1 Exa Deep tier-4 grounded-synthesis resolver

## Goal
Design a robust M11 plan, then implement **M11.1** (Exa Deep resolver) on branch
`m11/tier4-synthesis` (forked off the frozen phase-3 pre-flight base `1902210`). Paused after M11.1
per user instruction. M11.2 (Parallel Task) + M11.3 (judge-gating glue) are deferred.

## What M11 is
The **last** capability in the build order (substrate §11 step 6): tier-4 LLM-synthesis resolvers
that fill the fields no deterministic/official/third-party source can answer
(`account.operational_pain`, `account.strategic_moves`, `account.resonance.*`), placed *behind* the
M9 verification layer. M11 implements only the `Resolver` seam; every gate (pre-spend, faithfulness
judge, freshness, evals) wraps it uniformly. **Zero migrations** (the `exa_deep`/`parallel_task`
manifests + synthesis field rows were already seeded; PF-6 fixed their tier_plan keys).

## Architecture chosen (mirrors the tier-1 split, one tier up)
- `resolvers/grounded.py` — the **shared** substrate (M11.1 ships it; M11.2 reuses verbatim):
  `GroundedSynthesisResolver` (tier 4, provider-agnostic) over a `SynthesisBackend` protocol;
  `SynthesizedField`/`SynthesisResult` shapes; `HttpSynthesisBackend` (tier-4 analogue of
  `HttpEnrichmentBackend` over the shared sync `get_json`); the tier-4 disciplines enforced ONCE
  (grounded-only, target-lock, account-only firewall, dedup, no-self-promotion, empty-on-miss);
  `register_synthesis_resolver`. The tier-1 analogue is `DeterministicResolver`+`EnrichmentBackend`.
- `resolvers/exa/__init__.py` — Exa-only pure pieces: `ExaDeepConfig`, `_entity_query` (target-locked
  query: canonical name + aliases + hq_geo + bare domain hint + field-intent — NO hard `site:`),
  `build_exa_request`, `normalize_exa_response` (each Exa **highlight** → one grounded field: the
  passage IS the value+span, cited by the result url), `make_backend`, `register_exa_deep_resolver`.
  Uses `CLUE_EXA_API_KEY` (its own key), **not** the OpenRouter gateway (conventions §2 carve-out).
  Does NOT import `exa_py` — transport is the shared generic HTTP.
- `api/synthesis_wiring.py` (PF-7 home) — `register_synthesis_wiring(accounts=...)` binds Exa Deep.

## Key invariants honored (from core/claim.py)
- tier-4 ⟺ `extraction_method=llm_synthesis`; `llm_synthesis` REQUIRES `source_url`; claims born
  `unverified` (no self-promotion); `evidence_span` optional at construction but **always emitted**
  here (a candidate with no grounding span is dropped — `SynthesizedField` requires it by type).
- The waterfall `_finalize` stamps `source_key`/`run_id`/`research_mode` (resolver passes
  placeholders) and asserts `source_tier==manifest tier`; `stamp_reuse` stamps the cross-tenant
  scope (`account.resonance.*` → tenant_private needs `tenant_id`; `account.operational_pain` →
  public). The resolver builds plain account claims; the engine reclassifies.

## Personal-data firewall (PF-8 dropped, so it's field-routing not a manifest edit)
`GroundedSynthesisResolver` writes **account claims only** — returns `[]` for a contact entity or a
contact-class field. So binding it to the `entity_scope=BOTH` `exa_deep` manifest cannot leak a
`contact.facet.*` claim. Contact-level tier-4 synthesis is a separate M10-governed path (the AC-6 /
contact tests bind their OWN doubles to `exa_deep`, so no conflict).

## One base change required: import-linter Rule-4 `ignore_imports`
The api composition root MUST import `resolvers` to wire them, but importing `resolvers` transitively
reaches the **firecrawl SDK** (lazy, behind the M4.3 adapter seam in `adapters/concrete.py`), which
import-linter follows. Added a tightly-scoped `ignore_imports = ["clue_research.adapters.concrete ->
firecrawl"]` to the Rule-4 contract — severs ONLY that one sanctioned (behind-the-adapter) edge; a
direct SDK import by any module is a different edge and still caught. **This unblocks ALL api-root
resolver wiring** (the deferred firecrawl/deterministic composition-root wiring needs it identically);
M11 is just the first to need it. 11/11 contracts KEPT after.

## Adversarial audit (4-lens workflow) → 7 findings, ALL fixed
1. **[CRITICAL] target-lock was a raw substring test** (`name in haystack`) — fixed to **whole-word**
   match (`\b...\b`, case-insensitive) + a ≥2-char floor, in a new `_names_present`. Mirrors M9.4's
   `_token_present` (can't import `verification` from `resolvers`, so re-implemented locally; one
   shared matcher is a post-integration DRY item). Residual: a same-name competitor reproducing the
   EXACT canonical name off-domain is a true ambiguity the resolver can't settle alone — documented;
   caught downstream by corroboration/convergence/human review.
2. **[MAJOR] `ExaDeepConfig.default_cost_cents` was dead config** — threaded through
   `register_synthesis_resolver(..., default_cost_cents=)` → honored.
3. **[MAJOR] AC9 tracing span unasserted** — added 3 span tests (hit/miss/empty outcome + dims) via
   `obs.testing.collect_spans`. (The resolver emits `synthesis.<source_key>` with field_key/
   entity_id/n_retrieved/n_kept/n_claims/cost/outcome; span duration = latency.)
4. **[MAJOR] AC7 timeout/retry unasserted** — added a make_backend threading test + a
   RetryableResolverError-propagates (not swallowed) test.
5. **[minor] `register_synthesis_wiring` untested** — added a binding test.
6. **[minor] SynthesisBackend docstring said `site:<primary_domain>`** (contradicts the resonance
   design) — reworded to "domain as a hint, never a hard `site:` filter".
7. **[minor] grounded-only guard unfalsifiable on the Exa path** — normalize now DROPS a highlight
   absent from a present page `text` (only falls back to the passage when no `text` at all); added a
   test.

## Verification
- 43/43 resolver tests pass against a throwaway Postgres (`docker run ... -p 5433:5432
  pgvector/pgvector:pg16`; `CLUE_DATABASE_URL=...@localhost:5433/clue`). 26 pure (no DB) + e2e.
- ruff/format clean; mypy clean on the new modules; lint-imports 11/11 KEPT.
- Full `make check` run on the fixed code (DB up) — see session tail for the final result.
- **Did NOT run** a separate db-smoke (no new migrations to smoke).

## Files (M11.1 change set — all 8)
NEW: `resolvers/grounded.py`, `resolvers/exa/__init__.py`, `tests/resolvers/test_grounded.py`,
`tests/resolvers/test_exa_deep.py`, `docs/specs/_m11-tier4-synthesis-plan.md`.
MODIFIED: `resolvers/__init__.py` (exports), `api/synthesis_wiring.py` (bind Exa), `pyproject.toml`
(the one `ignore_imports`).

## Follow-ups (deferred, not blocking)
- M11.2 Parallel Task: add `resolvers/parallel/` reusing `grounded.py`; reasoning string → trace,
  never evidence span; independence test (Exa+Parallel → 2 distinct claims).
- M11.3 `synthesis/`: mode-M2 judge-gated workers, Pass-B-only guard, verification-health metric
  (Doc C §6), M9.6 golden-set rows. Field rows already seeded.
- Integration: wire `exa_deep`/`parallel_task` through `PreSpendGate.check` at the api root (M9.1
  AC-6 for the tier-4 spend path).
- DRY backlog (post-integration): one shared `normalize_host` (firecrawl `_registrable_host` ×
  grounded `registrable_host`) and one shared word-boundary name matcher (M9.4 `_token_present` ×
  grounded `_names_present`).
- On-miss realized cost: a paid miss loses the backend's realized `cost_cents` (resolver returns [];
  waterfall falls back to manifest cost) — matches the tier-1 paid-miss pattern; the resolver span
  still records `result.cost_cents`, so it's observable. Acceptable.
