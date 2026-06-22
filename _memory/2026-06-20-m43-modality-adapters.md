# 2026-06-20 — M4.3 modality-adapter framework (ENG-116)

## State: DONE on branch `akeshri516/eng-116-m43-modality-adapters` (off `integration/m4`)
Third M4 submodule (after M4.2, M4.1). `make check` (with DB): **501 passed, 13 skipped** (skips =
Redis lock tests); ruff + mypy --strict + **8/8** import contracts; db-smoke reversible; single head
`651b1d7229e2` (NO new migration — the cache is in-process). Not yet committed at time of this note.

## What shipped
- **core/modality.py** (NEW core contract, alongside `Resolver` — M0.2): `ModalityAdapter` protocol
  (`fetch(ref,ctx)->RawArtifact`, `adapt(artifact,ctx)->NormalizedText`,
  `extract(normalized,entity,field)->list[ClaimDraft]`) + value types `RawArtifact`/`NormalizedText`/
  `ClaimDraft`/`AdaptContext`. `ClaimDraft.evidence_span` is required+non-empty (substrate §4 at the
  draft). Carries NO tier/extraction_method/source_key — those are stamped from the manifest, never
  the extractor (adaptation never upgrades trust). Static TYPE_CHECKING conformance block (pos+neg),
  mirroring `resolver.py`. Exported from `core/__init__.py`.
- **adapters/** package (the framework, `clue_research.adapters`):
  - `seams.py` — provider seams `Transcriber` / `PdfTextExtractor` / `ScrapeBackend` / `BytesFetcher`
    / `ClaimExtractor` (Protocols) + `AdapterError`/`FetchError`/`AdaptError`.
  - `cache.py` — content-addressed `ArtifactCache` (Protocol) + `InMemoryArtifactCache`,
    `content_key(source_key,ref)` (NUL-separated sha256), `freshness_ttl(profile)` policy map
    (realtime/livecrawl → 0 = never cache), `is_fresh(entry,ttl,now=)`, `CachedArtifact`. Caller-owned
    (default off) — no hidden process-global cache.
  - `extractors.py` — `CallableClaimExtractor` (wrap a fn) + `span_for(text,needle)` grounding helper.
  - `concrete.py` — `PassthroughAdapter` (text/structured), `PdfAdapter`, `TranscriptionAdapter`,
    `FirecrawlHtmlAdapter`; default backends `InlineBytesFetcher`/`FileBytesFetcher`,
    `PypdfTextExtractor` (lazy `pypdf`), `FirecrawlScrapeBackend` (lazy `firecrawl`, injectable client
    so the map-to-RawArtifact logic is unit-tested with a fake; live build deferred to M4.5).
  - `registry.py` — `register_adapter(key,adapter)` (key = modality name OR `requires_adapter`) +
    `get_adapter`/`is_adapter_registered`/`clear_adapters` (+ structural conformance check on register).
  - `pipeline.py` — `run_pipeline(conn, source_key, ref, entity, field, *, run_id, research_mode,
    extractor=None, gate_decision=RUN, cache=None, clock=utc_now, persist=True, params=None)
    -> list[Claim]` + `cost_estimate(conn, source_key, ref)` + `GateDecision{run,skip}` +
    `UnknownSourceError`. Dispatch: `requires_adapter` else modality key, else built-in passthrough for
    text/structured when an `extractor` is passed (pdf/av REQUIRE a registered adapter →
    `AdapterNotRegisteredError`). Per-stage spans `adapter.{pipeline,fetch,adapt,extract}.<key>`;
    transcription cost on the **adapt** span (distinct), scrape/pdf cost on **fetch**. Grounding guard:
    every draft span must be a substring of the normalized text else `AdaptError`. Materializes via
    `core.factories` (account_claim/contact_claim), stamps source_key via model_copy+revalidate
    (mirrors waterfall `_finalize`), extraction_method = structured→api / text|pdf|av→scrape /
    tier4→llm_synthesis. Per-call cost attributed to the FIRST claim (cache hit → 0).
  - `__init__.py` — public seam; README updated.
- **obs**: `spans.py` adds `SPAN_ADAPTER_*` + `adapter_span(stage,source_key)`; `attributes.py` adds
  `latency_ms`/`cost_estimate_cents`/`cache_hit`/`gate_decision`/`modality`/`n_claims` to
  `STANDARD_ATTRIBUTES` (known-safe, native-coerced — numeric/bool stay native, not stringified).
- **pyproject**: `pypdf>=6` dependency (anticipated by the M4 kickoff) + mypy override
  (`pypdf`,`firecrawl` ignore_missing_imports — lazy SDK boundary, like `openai`).
- **tests**: `tests/test_core_modality.py` (DB-free protocol/value-type) + `tests/adapters/`
  (conftest DB harness mirrors M4.2; `test_pipeline.py` = one test per AC + persist=False/unknown-
  source/missing-adapter/grounding; `test_cache.py`; `test_static.py` adapters↛resolvers scan +
  registry; `test_firecrawl_backend.py` fake-client logic). 33 new tests.

## KEY DECISIONS / mechanics
- **ModalityAdapter protocol lives in `core`** (spec: "registered in M0.2 alongside Resolver"); the
  framework, seams, and concrete adapters live in `adapters/`. core imports only core.
- **`persist=False`** is the seam M4.5's Firecrawl resolver uses: it returns materialized-but-unwritten
  claims so the waterfall (the composer) writes them once — avoids a double-write. `run_pipeline`
  default writes (the headline AC) and returns the written claims.
- **`run_chain`/materialize are inlined** in run_pipeline (private `_fetch_and_adapt`/`_extract`/
  `_materialize`); `persist` + `extractor` params give M4.5/M8 the flexibility without a 2nd public fn.
- **Cache = cost-idempotency, not write-idempotency.** Re-running run_pipeline on the same ref reuses
  the normalized artifact at 0 cost (AC5), but does NOT dedupe claim ROWS — write-idempotency stays the
  caller/M7.4 concern (the waterfall owns it for the resolver path). Documented.
- **Hermetic CI (decision #3):** every test uses doubles; live pypdf/firecrawl/transcriber paths are
  lazy-imported + `# pragma: no cover`. The Firecrawl scrape *logic* is unit-tested via an injected
  fake client (mirrors the M0.4 gateway's `client_factory`).
- **reuse_scope:** claims written `public_footprint` by default (same as the waterfall); CRM/resonance/
  personal tenant-stamping is M4.5 (decision #6) — deferred, documented in run_pipeline docstring.

## Local-env gotcha (not a code issue)
A **native postgres** on `127.0.0.1:5432` shadows the docker container's port map; `make db-up`/`down -v`
won't reset it. The tests/alembic hit the native DB. If it's in a dirty mid-migration state, reset with
`DROP SCHEMA public CASCADE; CREATE SCHEMA public;` on `postgresql://clue:clue@localhost:5432/clue`,
then re-run (the `migrated_db` fixture re-migrates from empty). CLUE_DATABASE_URL must be exported.

## Adversarial review (find→verify Workflow, 5 lenses × 23 agents): 18 raw → 11 confirmed, all addressed
FIXED (behavior): (1) `_select_adapter` silently downgraded a **declared-but-unregistered**
`requires_adapter` (e.g. firecrawl_html) to passthrough when an extractor was passed → would extract
from the un-normalized ref. Now the passthrough fallback is gated on `requires_adapter is None`; a
named-but-missing adapter raises `AdapterNotRegisteredError` (+ regression test). (2) `cost_cents` was
emitted on BOTH the leaf stage span AND the parent `adapter.pipeline` span → a span-tree SUM
double-counts. Dropped from the parent (realized cost lives on the stage span; parent keeps only the
ESTIMATE) — mirrors the waterfall's one-granularity rule.
FIXED (DRY): added `core.revalidate_with(claim, **updates)` (the model_copy-skips-validators stamp) —
both `waterfall._finalize` and `pipeline._stamp_source_key` now call it (CLAUDE.md DRY). Extracted
`_estimate(manifest, ref)` so `cost_estimate()` and run_pipeline's span estimate can't drift.
FIXED (tests): added the **CONTACT path** (binding-from-manifest + use_class-from-draft positive +
two fail-loud negatives) and a **hermeticity** subprocess test (import adapters with pypdf/firecrawl
masked → still imports, proving the lazy-import discipline Rule 4 alone can't enforce).
DOCUMENTED (not changed — correct as-is): use_class is required for ALL contact claims through
run_pipeline (the `contact_claim` factory's contract, stricter than the model's facet-only rule) —
message + docstring clarified; a paid-but-zero-yield call carries its cost on the span only, not a
claim (matches the waterfall). Final: 506 passed, 13 skipped; make check + db-smoke green.

## NEXT (build order): M4.5 (CRM tier-1 + Firecrawl tier-2 scrape — consumes run_pipeline / the
HTML→markdown adapter; must stamp CRM claims `tenant_private`). M4.4 deterministic resolvers parallel.
**Known follow-up for M4.5:** the Firecrawl *resolver* (resolvers/) calling the adapter framework
(adapters/) is forbidden by import-linter Rule 3 (resolvers↛adapters independence) — M4.5 must either
use `run_pipeline(persist=False)` via a permitted path or add a one-way carve-out (like sources→icp,
decision #7). See [[2026-06-20-m41-waterfall]], [[2026-06-20-m42-source-registry]],
[[2026-06-19-m4-kickoff-handoff]].
