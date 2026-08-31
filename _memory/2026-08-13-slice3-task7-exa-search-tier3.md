# Slice 3 task 7 — the tier-3 `exa_search` source + resolver

Branch `platform/onboarding-integration`. Follows task 6 (`client.competitor` /
`client.buyer_profile` registered with `tier_plan=("exa_search",)`) and task 4 (the production
`LlmClaimExtractor`).

## What landed

- **Seed manifest** `exa_search` in `sources/seeds.py`: tier 3, provider `exa`, `cost_cents=1`,
  `auth_ref=CLUE_EXA_API_KEY`, `modality=TEXT`, `identity_binding=WEAK`,
  `freshness_profile="snapshot"`.
  `yields=("client.competitor", "client.buyer_profile")` — the two **concrete keys**, not the
  `client` namespace (the brief suggested either). Rationale: the M4.6 planner reads `yields` to
  propose sources for a field, and a namespace claim would offer this source for every owned-surface
  `client.*` field it has no query for.
- **Resolver** `subsystems/research/clue_research/resolvers/exa_search/__init__.py`:
  `ExaSearchConfig` (frozen; **refuses** any `search_type` containing `deep` — that is Exa's tier-4
  research product), `ExaSearchResolver` (tier 3, sync, `Resolver` protocol),
  `register_exa_search_resolver`. Builds one `NormalizedText` of `### RESULT n | url: <url>` blocks,
  calls the shared `ClaimExtractor`, and applies three fail-closed per-draft guards:
  1. **attributable** — `source_url` ∈ the urls this call retrieved (else drop; a multi-record
     source has no honest fallback citation);
  2. **grounded in the CITED record** — `evidence_span` ⊆ that record's own title+text. Tighter
     than the extractor's document-wide check on purpose: a span from record 1 under record 3's url
     passes the document check and would then be target-locked against the wrong page;
  3. **target-lock** — the cited record's host is the client's domain, or name/alias/domain is a
     whole-word match in that record's own text; unsatisfiable identifiers ⇒ refuse.
  Cost rides the first claim only (the waterfall sums per-claim cost). `ExtractionMethod.API`.
- **DRY**: promoted `grounded._names_present` → `names_present` and `_entity_name_tokens` →
  `entity_name_tokens` (public, alongside `registrable_host`) instead of writing a third whole-word
  matcher. Only internal callers updated.
- **Composition**: `run_composition.bind_stage0_search_resolver(...)` (one function, both roots,
  like `build_stage0_claim_extractor`), called from `projections_main.build_application` and
  `fleet_main._build_stage0_scrape_binder` inside the existing `self_serve_provisioning_enabled`
  gate, over the **same extractor instance and the same `Stage0ScrapeBinder`** the scrape lane uses
  (`Stage0ScrapeBinder.key_for` already matches `AccountLookup` — no adapter, binder untouched).

## Decision worth remembering — the credential gate

`resolve_credential` raises at call time when `CLUE_EXA_API_KEY` is unset, and a raising resolver
inside `resolve_field` fails the **whole** recon lane (`client_kb.reverse_profile` re-raises). So
`bind_stage0_search_resolver` **does not bind** without a credential: it logs
`stage0.exa_search_unbound_no_credential` and returns False. The waterfall then records
`NO_RESOLVER` at zero spend and the two fields end honestly empty. Not in the brief; added
deliberately so a keyless deployment cannot lose onboarding over an optional enrichment.

## Boot-order fallout (the carried-forward review item)

Naming `client.*` in `yields` makes the client-knowledge pack a prerequisite of
`seed_source_manifests` (`register_source` validates `yields` against the field registry). Patched
**14** call sites that seeded after loading only the core pack — 4 production
(`exa_websets_materialization`, `contact_channel_enrichment`, `sumble_claim_materialization`,
`exa_targeted_enrichment`) and 10 test harnesses (`tests/{resolvers,sources,verification}/conftest`,
`tests/stage0/test_handler`, `tests/integration/test_fi2_slice3_economics`,
`tests/contact_research/test_c5_*`, `tests/execution/test_recipe_wiring`, three `tests/api/*_db`).
`composition.py` and the two trial fixtures already loaded it. The seeds docstrings now state the
ordering contract. **Any future `seed_source_manifests` caller must load both packs.**

## Verification

- `tests/resolvers/test_exa_search.py` (16 tests, pure — fake `get_json`, real `LlmClaimExtractor`
  over a canned gateway for the headline path so the `### RESULT` header is proven to actually
  ground `source_url`).
- Lane test `tests/stage0/test_reverse_profile.py::test_exa_search_is_skipped_by_the_fast_lane_
  and_paid_only_by_the_background_lane` — fast lane (`max_source_tier=2`) issues **zero** provider
  calls at zero cost and leaves the field empty; background lane (`3`) writes a tier-3, cited,
  span-grounded, `tenant_private` `client.competitor` claim.
- 3 composition tests in `tests/api/test_extractor_composition.py` (bind-with-key, unbound-without,
  fleet root binds over its binder).
- `make lint` / `make typecheck` (635 files) / `make contracts` (25 kept, 0 broken) green.

## Known-noise baselines observed (all proven pre-existing by `git stash`)

- 8 failures in `tests/{resolvers,sources}` and 2 in `tests/execution/test_recipes.py` — a
  **persistent dev DB carrying committed rows** that conflict with the current definitions
  (`SourceManifestRedefinitionError: source 'crm' … different definition`;
  `RecipeVersionConflict: recipe0-stage0@2`). A dev DB reset would clear them.
- 7 `tests/api` failures from `CLUE_CHAT_REASONING_TRACE_MODE=raw` in `.env`.
- 16 `tests/integration` failures — byte-identical list before and after this change.
