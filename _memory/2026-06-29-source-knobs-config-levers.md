# 2026-06-29 — Lever 1 + 2: confidence thresholds & planner tier-scope are now layered config

## Goal
Make two "boost deep research" knobs **policy-as-data, overridable per client/ICP, versioned** (the
user's lever 1 + lever 2), and actually *read at runtime* by the deep workers — not just a reserved
seam. Default behaviour must be **unchanged** unless an overlay is registered.

- **Lever 1 — confidence thresholds** (the waterfall's per-field-class stop bar). Raising it makes
  tiers 1–3 "succeed" less often → the tier-4 deep-research products get consulted more.
- **Lever 2 — planner tier reach.** `tier_scope` (inclusive max trust tier, `None`=all) + a
  `prefer_deep_sources` toggle that *widens* the band to include tier-4 (never reorders the tiers —
  tier-4 still runs last, least-trusted; the anti-fabrication discipline holds).

## What changed (single definition each — no parallel shapes)
- **`config/schema.py`** is now the canonical home of `ConfidenceThresholds` (relocated from
  `sources/thresholds.py`; it was already `core`-only so `config`-imports-only-`core` holds) and a
  new `SourcePlanPolicy` (`tier_scope` + `prefer_deep_sources` + the pure resolver
  `effective_max_tier(override)`). The `effective_max_tier` logic lives in exactly one place — the
  planner is **not** touched (`plan_sources` already took `tier_scope`; the workers compute the
  effective value and pass it).
- **`config/models.py` + `loader.py`** — `confidence_thresholds` + `source_plan_policy` added to
  `Config` (dense defaults) + `ConfigOverlay` (sparse) + `_merge`. They are the **two *live*** schema
  shapes; the rest of `config/schema.py` is still a reserved seam.
- **`config/__init__.py`** exports `ConfidenceThresholds`, `DEFAULT_CONFIDENCE_THRESHOLDS`,
  `SourcePlanPolicy`, `DEFAULT_SOURCE_PLAN_POLICY`.
- **`sources/thresholds.py`** is now a 3-line re-export of the config definition, so the ~6 existing
  importers (`waterfall`, `contact/fill`, `discovery_scoring/*`, `sources/__init__`) are unchanged.
  New edge **`sources → config`** — allowed (no contract forbids it; `obs → config → core` only
  constrains *config's* imports). `lint-imports`: 11 kept, 0 broken.

## Live wiring (per-run, keyed by the run's client)
The deep workers resolve the merged `Config` via the existing injectable `OverlayStore` seam and
pass `thresholds=` to `resolve_field` and the effective `tier_scope=` to `plan_sources`:
- **Account axis** — `AspectProfilingWorker` gained `config_store` + `_source_policies(rc)`; resolves
  `get_config(rc.client_id, store=...)` once per `research()` and threads both policies into
  `_fill_field`. `ResonanceAspectWorker` passes `config_store` through (its `tier_scope=None` means
  `prefer_deep_sources` is a no-op unless an overlay sets a finite `tier_scope` to cap cost).
- **Contact axis** — `profile_contact` is the single config-resolution point (keyed by its
  `tenant_id`): `thresholds`/`plan_policy` default to `None` → resolved from `get_config`; explicit
  args override. `fill_contact_field`/`_planned_source_keys` gained `plan_policy`.
  `ContactProfileAspectWorker` passes `config_store` through.
- **Composition** — `account.py` (`default_account_worker_builder`/`account_axis_workers`/
  `profile_account`) + `api/deep/composition.py` thread `config_store`; the deep root binds it onto
  the live `profile_account`/`profile_contact` callables via `functools.partial` (only when non-None,
  so production stays on the process default store).

**Default-preserving by construction:** with no overlay, `get_config` returns
`DEFAULT_CONFIDENCE_THRESHOLDS` / `DEFAULT_SOURCE_PLAN_POLICY` → identical to today. A run with no
client coordinate (bare unit test) uses the module defaults without reading config at all.

## Tests
- `tests/test_config_schema.py` — `ConfidenceThresholds` lookup/bounds; `SourcePlanPolicy`
  `effective_max_tier` (default no-op, prefer-deep widens-never-narrows, override precedence,
  tier_scope 1..4 bounds); `Config` carries both defaulted.
- `tests/test_config_loader.py` — overlay override + ICP-over-client precedence for both knobs;
  `overlay_from_mapping` rejects out-of-range `tier_scope`.
- `tests/profiling/test_worker_config.py` (DB-free) — the worker reads the injected overlay's
  policies (`tier_scope=3 + prefer_deep → 4`) and falls back to defaults without a client/overlay.
- `make check` green: 1125 passed, 782 skipped (DB-gated), 11 contracts kept, mypy clean.

## Notes / deferred (not blocking)
- **Config grain is `(client_id, icp_key)`** when both are present on the run (`RunContext` /
  `profile_contact`'s `icp_key` arg). ICP overlay wins over client (same precedence as the loader
  tests). Client-only when `icp_key` is absent.
- **Source-profile weights** (the within-tier ordering, "lever 3") stay DB-rows (mutable target of
  the M13.3 learning loop) — deliberately *not* a static config file; `prefer_deep_sources` is the
  config-layer way to favour tier-4 without touching DB weights.
- Committee discovery doesn't use the planner/waterfall, so it needed no wiring.
- Not committed (left for the user; branch `m13.3/learning-loop` has unrelated WIP in the tree).
