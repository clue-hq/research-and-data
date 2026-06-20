# 2026-06-20 — M4.4 deterministic tier-1 resolvers (ENG-122)

## State: DONE on branch `akeshri516/eng-122-m44-deterministic-resolvers-clay-swappable-apollozoominfo`
Branched off **`integration/m4`** (M4.1+M4.2 — M4.4 is parallel, needs no M4.3). `make check` (with
DB): ruff + mypy --strict (src) + **8/8** import contracts; full suite **548 passed, ~13 skipped**
(skips = Redis lock tests); db-smoke reversible; single head **`651b1d7229e2`** (NO new migration —
"No new tables" per spec). 67 new resolver tests.

## What shipped (binds resolvers to the M4.2-seeded source_keys; the waterfall composes them)
- **core/resolver.py**: added `ResolverError` + `RetryableResolverError` (the resolve() contract's
  fault taxonomy — transient → M7 retries, vs a hard miss = empty list). Exported from core.
- **config/secrets.py**: `Secrets.for_auth_ref(auth_ref)` — the M0.2 credential-reference resolver
  (CLUE_* env-var NAME → the SecretStr field). Added `duns_api_key` (was missing → DUNS unresolvable).
- **resolvers/ package** (the whole milestone):
  - `http.py` — shared HTTP/SDK wrapper (decision 3b, built once): `classify_status` (retryable 408/
    425/429/5xx vs hard 4xx `ProviderResponseError`), `resolve_credential` (auth_ref→secret, raises
    `CredentialError`), `get_json` (lazy httpx, `# pragma: no cover` live boundary).
  - `base.py` — `ResolvedField` (the normalized intermediate; required non-empty source_url+span,
    bounded Confidence), `EnrichmentBackend` Protocol (the swap seam), `DeterministicResolver`
    (provider-agnostic tier-1 Resolver; per-call cost on first claim), `build_claim` (via
    core.factories only; placeholder run_id/mode the engine restamps; contact→WEAK placeholder
    +use_class), `normalize_record` (shared flat enrichment normalize), `coerce_confidence`.
  - `live.py` — `AccountLookup` (entity_id→AccountEntity, supplied by M6/M7), `HttpRequest`,
    `fetch_via_http` (account/optional-credential/Mapping guards → normalize), `HttpEnrichmentBackend`
    (the generic live backend every provider wires). Network call is the only uncovered boundary.
  - providers `clay/ apollo/ zoominfo/ builtwith/` (each = SOURCE_KEY + AUTH_REF + a `normalize` +
    `make_resolver`); `registries/` = config-driven `RegistrySpec` family NPI/DUNS/CIK/LEI +
    `registry_normalize`.
  - `__init__.py` — `register_deterministic_resolvers()` binds all 8 (cost read from `SEED_MANIFESTS`
    = single source of truth) + the public seam.

## KEY DECISIONS / mechanics
- **The Resolver protocol is SYNC + minimal Entity (id+type only).** The live backend needs the
  domain/registry-id → injected via `AccountLookup` (M6/M7 supplies the loaded AccountEntity); the
  resolve() path never loads entities (identity is M2's). CI uses backend doubles, so the live
  fetch/`_build_request` are deferred `# pragma: no cover` (mirrors M4.3's deferred firecrawl client).
- **No provider SDKs imported** — transport is generic HTTP (lazy httpx), so Rule 4 is never even
  triggered; resolvers import only core/config + the shared base/live/http.
- **Cost = single source of truth (SEED_MANIFESTS).** Resolver stamps the manifest per-call cost on
  the first claim; the engine sums per-claim cost. A **paid hard-miss** (empty result) charges the
  manifest cost in the WATERFALL (else economics under-count) — see review fix.
- **Provider response shapes are a documented assumed contract** finalized against recorded fixtures
  when live keys land; the *normalization* (response→ResolvedField) is fully unit-tested per provider.

## Adversarial review (17-agent find→verify Workflow, 6 lenses): 10 confirmed, ALL fixed
HIGH: (1) **DUNS auth_ref had no Secrets field** (`extra="ignore"` silently drops the env var) →
added `duns_api_key` + `.env.example` + a drift-guard test (every seeded auth_ref must map to a
Secrets field). (2) **Apollo `account.recent_funding` emitted a bare string** but the field's
value_schema is `{required: amount_usd}` object → `insert_claim` validates values, so a normal
response would CRASH (not miss). Apollo now builds the `{amount_usd, round}` object (or misses if no
amount) + an end-to-end waterfall-write test. (3) **Secret scan missed opaque tokens** → reuse the
runtime `redact` oracle (DRY, catches opaque/prefixed/DSN) + a 3-literal allowlist.
MED: (4/8) paid-miss cost recorded 0 → waterfall charges manifest cost on empty + test. (5)
malformed provider confidence crashed the bounded type → `coerce_confidence` (fallback/clamp). (6)
**ZoomInfo mapped unregistered `contact.title`** → write would reject; dropped it (serves
core.work_email). (7) contact-binding test couldn't tell manifest-stamp from WEAK placeholder →
contrast crm(STRONG) vs apollo(WEAK). LOW: (9) intra-resolver import guard ignored relative imports →
`_imported_modules` resolves them; (10) dead `_PLACEHOLDER_MODE` → wired into build_claim.

## NOTES / for later
- **insert_claim validates value_json against the field value_schema** (claims.py) AND requires the
  field_key registered — a resolver mapping a field MUST match its registered schema/registration, or
  the write fails (not a miss). Tests now drive object/registry fields through insert_claim, not just
  normalize() in isolation. (This caught findings #2 and #6.)
- The waterfall change (charge manifest cost on a paid miss) is in M4.1's `resolve_field`; M4.1 tests
  stay green (no miss-cost assertion there). A retried miss isn't idempotent-cached (no claim written)
  so it re-calls + re-charges — correct (a real re-spend), pre-existing M4.1 behavior.
- Registry yields are still the coarse `account` class (M4.2); NPI vertical-gating is proven at the
  tier_plan level (a healthcare.npi field names npi; non-healthcare fields don't). Finer per-vertical
  yields land with the healthcare pack (M3.3) — unchanged here.

## NEXT (build order): M4.5 (CRM tier-1 + Firecrawl tier-2 — consumes M4.3 run_pipeline; CRM claims
must stamp `tenant_private`); M4.6 (Source Profiles + planner). M4.4 unblocks M6 (Pass-A tier-1 fill +
structured-DB discovery) and M8 (deep-pass deterministic base). See [[2026-06-20-m43-modality-adapters]],
[[2026-06-20-m41-waterfall]], [[2026-06-20-m42-source-registry]], [[2026-06-19-m4-kickoff-handoff]].
