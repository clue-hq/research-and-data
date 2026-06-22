# `clue_research/adapters/` — Source Layer — modality-adapter framework (M4.3)

**Status:** implemented by **M4.3 (ENG-116)** — `fetch → adapt → extract`, open by registration.

**Spec:** [`docs/specs/M04-source-layer-and-source-intelligence.md`](../../../docs/specs/M04-source-layer-and-source-intelligence.md) §M4.3

A source isn't always "fetch a URL and read text" (staged-flow §7b): video/podcasts go through
transcription, PDFs/journals through text extraction, web pages through HTML→markdown, **before**
claim extraction. This package makes that heterogeneity *open by construction, like the field
registry*: adding "anything on the internet" is registering a manifest (M4.2) + (if non-trivial) an
adapter here — never a fork of the pipeline.

The `ModalityAdapter` protocol and its value types (`RawArtifact` / `NormalizedText` / `ClaimDraft`)
live in `core/` (the M0.2 shared contracts, the modality analogue of `Resolver`); this package holds
the **dispatch** (`run_pipeline`, `cost_estimate`, the adapter registry), the **provider seams**
(`Transcriber`, `PdfTextExtractor`, `ScrapeBackend`, plus the `BytesFetcher` transport and
`ClaimExtractor` extraction seam), the **content-addressed cache**, and the concrete adapters
(`PassthroughAdapter`, `PdfAdapter`, `TranscriptionAdapter`, `FirecrawlHtmlAdapter`).

Key guarantees: adaptation never upgrades trust (tier/`extraction_method` come from the manifest, not
the extractor); every `evidence_span` is grounded in the normalized text (substrate §4); the caller's
`gate_decision` is honored verbatim (D7 spend governance); costly fetch/transcription is done once per
`ref` (the cache, TTL from `freshness_profile`); each of fetch/adapt/extract emits its own cost+latency
span (transcription is a distinct cost). `run_pipeline(..., persist=False)` returns unwritten claims —
the seam M4.5's Firecrawl resolver uses to return claims to the waterfall without double-writing.

## Modular boundary (M0.1 / ENG-101)

Allowed to import source/modality SDKs (e.g. `pypdf`, `firecrawl`), and only inside this package, so
those SDKs are isolated from everything downstream; live clients are **lazy-imported** so CI's
double-driven path needs neither the SDK nor a key. Adapters never import a resolver or another
adapter (import-linter Rule 3 / `_conventions.md` §2). The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
