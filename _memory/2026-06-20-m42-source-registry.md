# 2026-06-20 — M4.2 Source Registry + capability manifests (ENG-111)

## State: DONE, on branch `akeshri516/eng-111-m42-source-registry` → merged to `integration/m4`
First M4 submodule. `make check` (with DB): **449 passed, 13 skipped** (skips = Redis lock tests);
ruff + mypy --strict + **8/8** import contracts; db-smoke reversible; single head `b9c6d72ac860`.
Two commits: `df93c69` (impl), `a1fad83` (adversarial-review fixes).

## What shipped
- **migration `b9c6d72ac860`** (hash id off head `0011`): `source_manifest` table. Columns realize
  `core.SourceManifest` (the M0.2 scalar shape — cost_cents numeric, latency_ms int,
  freshness_profile text; NOT §7a's looser jsonb cost, which would contradict core) + the
  decision-#2 wrapper cols (active/provider/auth_ref/rate_limit/requires_adapter/version/created_at).
  NEW pg enums `modality` + `entity_scope` (parity-tested vs core); REUSES `identity_binding` (0004)
  — downgrade does NOT drop the shared enum. Named CHECKs (tier 1..4, cost≥0, latency≥0, version≥1,
  yields/geo are arrays). Indexes: `tier` + partial `active` (NO GIN on yields — see review).
- **sources/manifest.py** — `RegistrySourceManifest` (wraps frozen `core.SourceManifest` + metadata,
  decision #2). Ergonomic delegates: source_key/tier/modality/entity_scope/yields/
  identity_binding_strength/cost_cents/latency_ms/geo_coverage/freshness_profile.
- **sources/registry.py** — `register_source` (yields validated vs M1.3 registry; idempotent no-op /
  same-version-change error / higher-version update / lower-version reject), `get_source`,
  `list_sources` (exact filters), `sources_for(field|class, tier?, entity_scope?)` (capability query;
  class/key widening done in Python via `_yields_match`/`_key_in_class`/`_is_class_token`),
  `registered_source_keys` (completes M3.3's late-bound `validate_pack(known_source_keys=…)` join).
  In-process resolver binding: `bind_resolver`/`get_resolver`→`NoResolverBoundError` (tier-4
  placeholders; waterfall maps to `stop_reason=no_resolver`, never a crash) + clear/unbind/is_bound.
- **sources/seeds.py** — clay/apollo/zoominfo/builtwith + npi/duns/cik/lei (tier-1 structured), crm
  (tier-1, `identity_binding=strong`), firecrawl_site (tier-2 text, requires_adapter `firecrawl_html`),
  resolver-ABSENT tier-4 `exa_deep`/`parallel_task`. `auth_ref` = `CLUE_*` env-var REFERENCES, never
  secrets. yields use real `core.*` keys (require core pack loaded) + canonical classes.
- **tests**: `test_source_manifest.py` (16 DB-backed, one per AC) + `test_static_invariants.py`
  (2 DB-FREE: provider-not-branched, auth_ref-not-secret).

## DECISIONS / structural choices
- **#2 wrapper not redefine**: core.SourceManifest stays the M0.2 capability contract; the registry
  table = core columns + operational metadata; `RegistrySourceManifest` embeds the core manifest.
- The DB stores core's SCALAR cost/latency (not §7a jsonb) — §7a richer cost/latency models can be
  added as columns later without contradicting core. Documented in the migration.
- **sources→resolvers is machine-forbidden** (new import-linter contract "source registry does not
  import resolvers"); **sources→icp PERMITTED** for the M4.6 planner (decision #7). The binding seam
  is one-way: resolvers call `bind_resolver` (resolvers→sources); sources never imports resolvers.
- yields existence rule: a canonical FieldClass (core/account/account.resonance/contact/contact.facet)
  always resolves; a concrete key must be registered; a pack namespace needs ≥1 registered field.

## Adversarial review (find→verify): 1 real defect, 7 judgment, 5 false-pos — all addressed
FIXED: dead `yields` GIN index + false comment (dropped — Python widening can't use a jsonb @>);
DB-free static tests un-gated from `require_db`; no-secret test scans ALL columns; `latency_ms` Ge(0)
in core (matches DB CHECK); machine-enforced sources↛resolvers + fixed the overstated docstring;
added missing wrapper delegates + single-writer concurrency note. NOT changed (verifier: not bugs):
register_source TOCTOU (serial seed path, mirrors sibling registries — documented only).

## NOTES / for later
- Seeding (`seed_source_manifests`) must run AFTER the referenced fields are registered (e.g.
  `load_core_pack`) so yields validation resolves.
- registries (npi/duns/cik/lei) yield the coarse `account` class for now; finer per-vertical yields
  (e.g. `healthcare.npi`) land when the vertical pack loads + M4.4 resolvers.
- The §7a "cost jsonb / latency jsonb" richer model is intentionally NOT used (core scalar wins);
  revisit only if a real per-call/per-record cost model is needed.

## NEXT: M4.1 — waterfall engine (ENG-105). Dispatches through this registry's `get_resolver`
binding; reads field tier_plan; stop-at-first-confident; tier-4 unbound → stop_reason=no_resolver.
Confidence threshold = engine-side config keyed by field_class (decision #1, NOT on FieldDef).
See [[2026-06-19-m4-kickoff-handoff]].
