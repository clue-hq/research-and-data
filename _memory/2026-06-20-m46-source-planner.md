# 2026-06-20 — M4.6 Source Profiles serving + config-bounded Source Planner (ENG-129)

## State: DONE on branch `akeshri516/eng-129-m46-source-profiles-config-bounded-source-planner`
Branched off **`integration/m4`** tip `190a6e1` (M4.1–M4.4 joined). Parallel to M4.5 (independent —
only `sources/__init__.py` exports overlap). `make check` (with a fresh per-branch DB on :5442):
ruff + mypy --strict (103 src files) + **8/8** import contracts; full suite **616 passed / 13
skipped** (skips = Redis lock tests); migration up→down→up clean (`test_db_migrations`); **single
head `eab62cbb1366`** (one new migration). **43 new M4.6 tests** (29 initial + 14 from the review)
across 4 files. Local commits only — not pushed.

## What shipped (locked decision #5: REUSE M3.3's store; ADD only intersection + planner + telemetry)
- **`sources/source_profile.py`** (NEW) — the ICP-level serving half:
  - `serve_source_profile(conn, spec)` → `ServedSourceProfile` (merges every `spec.enabled_packs`'
    `get_pack_source_profile` — M3.3, override>default — into one weighted set; `_merge_slot` dedups
    by strongest weight, orders by `(-weight.prior, rank, source_key)` → reproduces §7c for single
    packs). This is the spec's `get_source_profile(icp_version, field_class)` analogue; named
    distinctly so it never shadows M3.3's *pack*-level `get_source_profile`.
  - `resolve_allowed_set(conn, spec, field, *, max_tier=None, entity_scope=None)` → the **allowed
    set = profile ∩ registry-capable** (`sources_for`), enriched from a single `list_sources` pass.
- **`sources/planner.py`** (NEW) — `plan_sources(...) -> OrderedSourcePlan`: allowed set → optional
  config-bounded LLM refinement (hard guard: any off-set `source_key` dropped + audited in
  `dropped_off_set`; the LLM can reorder/pick + write queries but never widen) → STABLE sort by tier
  (tier-1 never after tier-3) → expensive-modality gate (`_gate_for`) → budget halt. LLM optional
  (gateway+planner_model); without it a deterministic config-ordered plan. `SourcePlannerConfig`
  (policy-as-data, mirrors `sources/thresholds.py`). `OrderedSourcePlan.tier_plan()` = the RUN keys
  for the caller to drive the M4.1 waterfall (`field_def.model_copy(update={"tier_plan": ...})`).
- **`sources/source_yield.py`** (NEW) — `record_source_yield(conn, ...)` (append-only DB writer) +
  `get_source_yield(conn, ...)` aggregate (per field_class+source, precision=verified/total). The
  M13 learning-loop substrate; M13 reweights `source_profile_override` from it (config-driven, no
  engine change — proven by a test).
- **Migration `eab62cbb1366_source_yield_telemetry_table.py`** — `source_yield` (hash id off head
  `651b1d7229e2`). Reuses the `field_class` enum (no new enum/CREATE TYPE → no parity burden), named
  CHECKs (incl. `verified <= total`), reversible downgrade leaving the shared enum.
- **`obs`** — `SPAN_SOURCE_PLAN = "source.plan"` + `ATTR_N_SOURCES` (added to STANDARD_ATTRIBUTES
  allowlist + SpanAttributes); planner emits the span.

## KEY DECISION (structural): relocated `GateDecision` to `core`
`GateDecision` (RUN/SKIP) was in `adapters/pipeline.py`, but `adapters → sources` already exists
(pipeline reads the manifest via `get_source`). A planner in `sources` importing `GateDecision` from
`adapters` would form a **sources↔adapters cycle**. Per conventions §2 (shared domain types live in
`core`), moved it to `core/modality.py` (the fetch→adapt→extract contract surface), re-exported from
`core/__init__` and `adapters/__init__` (so `clue_research.adapters.GateDecision` still works — M4.5
+ existing tests unaffected). `run_pipeline`'s `is GateDecision.SKIP` identity check still holds
(same object). The plan now carries the **literal** verdict M4.3 honors. Review confirmed: no cycle,
single definition, identity holds, no PG-enum/parity impact.

## Notable interpretation: `tier_scope` is an INCLUSIVE UPPER BOUND, not an exact tier
The planner inherently spans tiers (orders tier-1 before tier-3 in ONE plan), so an exact single-tier
filter contradicts it. `resolve_allowed_set(max_tier=N)` keeps tiers `<= N` (None = all). So
`plan_sources(tier_scope=3)` plans the trust-tiered tiers 1–3 and **excludes the tier-4 placeholders**
(M4 ships tiers 1–3) — elegant. (Fixed from an initial exact-`sources_for(tier=)` filter that the
adversarial review flagged HIGH.)

## Adversarial review (find→verify Workflow, 32 agents, 6 lenses) → 24 confirmed / 2 refuted; fixes:
- **[HIGH] tier_scope exact-tier** → inclusive `max_tier` upper bound (above).
- **[MED] `max_sources` counted SKIP'd sources** → cap counts only RUN sources (SKIP is free, like
  the budget loop + `tier_plan()` already treat it).
- **[MED] FieldClass.PACK slot bleed across packs** → `_slot_field_class` routes pack-namespace
  fields to the unambiguous pack-wide default (PACK is one enum value shared by every namespace, so
  it can't key a per-vertical slot in a multi-pack merge).
- **[LOW] off-set `source_key` named via the LLM `queries` channel** wasn't in `dropped_off_set` →
  now audited there too (anti-fabrication held regardless — queries are consumed only for allowed
  sources).
- **[LOW] N+1** manifest re-fetch in `resolve_allowed_set` → one `list_sources` map.
- **[LOW] DRY**: `for_field_class` fallback was duplicated → factored into `icp.slot_for`, both
  `ResolvedSourceProfile` (M3.3) and `ServedSourceProfile` (M4.6) delegate.
- Added `icp_version` filter to `get_source_yield`; documented planner `queries` are inert/
  target-locked downstream (existence-gate).
- ~10 confirmed **false-green test gaps** closed: per-field-class slot routing, LLM *omitting* an
  allowed source (the "cannot narrow" direction), max_tier bound, max_sources RUN-only, budget
  first-exceeds + SKIP-is-free, off-set-via-queries, yield narrowing/cross-ICP-isolation/forward-
  hooks/precision-None/more CHECKs, SPAN_SOURCE_PLAN observability, entity_scope widening, multi-pack
  strongest-weight dedup.
- REFUTED (verified non-issues): the GateDecision relocation cleanliness; the obs/sources
  `record_source_yield` name collision (different packages, different signatures, documented — kept
  the spec's exact API name).

## NOTES / follow-ups (none block M4.6)
- **Long-tail provider manifests are a prerequisite to PLAN the real starter packs.** Only
  `npi/builtwith/exa_deep/parallel_task` of the starter-pack profile keys are seeded (M4.2); the rest
  (`arxiv/github/glassdoor/google_places/journals/press_releases/engineering_blogs/job_boards/cms/
  semantic_scholar/research_x/job_postings`) have no manifest, so `resolve_allowed_set` for those
  packs is empty until a future vertical-pack milestone seeds their manifests + resolvers. M4.6 is
  correct (can't plan what doesn't exist) — this is registry coverage, not an M4.6 gap.
- Cross-pack within-HIGH-weight order falls back to alphabetical `source_key` (packs restart rank at
  1); documented + the strongest-weight dedup is now tested. M13 override / per-ICP override is the
  intended disambiguator.
- The planner's `queries` are **inert** in M4.6 (no consumer). When a downstream milestone drives
  them, each MUST be target-locked to the resolved `entity_id` (a query string must never introduce
  an entity — the discovery existence-gate).

## NEXT: M4.6 unblocks **M8** (modes M2/M4 consume the planner's ordered set; resonance + long tail)
and **M6** (resonance/discovery ordering). Emits the telemetry **M13**'s learning loop reweights.
See [[2026-06-19-m4-kickoff-handoff]], [[2026-06-20-m42-source-registry]], [[2026-06-20-m43-modality-adapters]].
