# Asset description mapping audit — 2026-09-22

## Conclusion

The descriptions are **not reliably grounded in their images**. The Wynwood House anomaly is not isolated. Multiple completed records describe an entirely different subject or brand; others contain placeholder/refusal-like text or say pixels were unavailable despite a usable stored preview.

The investigation found **no asset-ID, stored-byte, preview-fingerprint, or frontend join mismatch** in the audited snapshot. Current code and an offline concurrent replay preserve asset identity throughout the mapping path. This supports an analysis/input-rendering/validation problem rather than a general positional shuffle of descriptions. It does not prove exactly what the historical provider decoded: raw request/response receipts were not available for those calls.

This was a read-only review of the running application and its data. No application code, descriptions, overrides, model configuration, or live ingestion state changed. No paid model replay was performed.

Subsequent user-approved live testing is recorded separately in [the four-call replay report](2026-09-22-asset-vision-replay.md). All four new calls recognized the logos; the original unrelated-subject failures did not reproduce. That follow-up does not change the observed bad stored results documented here.

## Scope and snapshot

- Checkout: `san-diego`, branch `asset-ingestion/improvements`, application baseline `32c029b5e`.
- Isolated database: `clue_san_diego` at `127.0.0.1:55170`; durable blobs under this checkout's `.artifacts/`.
- Workspace: `ws_e7b95e2494da4582932fce0a237b95c6`.
- Ingestion: `ingest_a5c175adbaca42858c3fcb31246ea5ff`.
- Snapshot: 560 assets, comprising 489 images and 71 fonts.
- Image analysis states: 158 ready, 15 analyzing, 1 failed, 315 with no description row yet.
- All 489 images received identity/byte-integrity checks. All 158 ready records received preview/source fingerprint checks and a visual contact-sheet screening; suspicious records received full-field inspection.
- The ingestion was still running and results continued arriving. These are fixed snapshot counts, not the final ingestion totals. The remaining 331 images were not counted as successfully analyzed or semantically reviewed.

The contact-sheet pass is a broad visual screening, not a claim that every sentence in all 158 analyses is correct.

## Confirmed failures

All examples below were stored as `ready`, with the generated analysis itself containing the problem and no human override causing the discrepancy. Their registry/original/preview fingerprint checks passed.

| Actual image | Stored analysis problem | Asset ID |
| --- | --- | --- |
| Wynwood House black wordmark | Title and description depict a close-up portrait of a person in a dark jacket; usage recommends human-centered/editorial contexts. Creative type nevertheless says logo. | `asset_ing_a99a08190a65a455` |
| Arbio black wordmark | “Blue Circuit Board”; describes chips and circuitry and says no visible text/logo/branding. | `asset_ing_bdb03352de1a1c47` |
| Another Wynwood House wordmark variant | Correct title, but description and multiple other fields contain candidate-refusal text instead of useful analysis. | `asset_ing_f5c1ac0fff3babbd` |
| The Flex wordmark | Description is `PLACEHOLDER`, despite otherwise recognizable logo observations. | `asset_ing_544fc22bc6490572` |
| Conduit inbox/operator screenshot | Says image pixels were not supplied and no visual description can be produced. The reconstructed preview visibly contains the screenshot. | `asset_ing_256fc4059dcff79a` |
| BaliLuxuryStays wordmark | Says the image is unavailable for visual analysis. | `asset_ing_dc48acd2a1c20cd8` |
| Pass the Keys logo | Described as a Neural Conduit logo with invented visual details. | `asset_ing_357d2708e6cb4750` |
| Roofstock logo | Described as a Conduit logo with a play-button icon. | `asset_ing_d0745ac2fd09272d` |
| API/code card on a gradient | Describes only a gradient and claims no visible text, omitting the main card/code content. | `asset_ing_bd00a0ee9f67884b` |

The live fresh Arbio inspector was also checked visually: it rendered the Arbio wordmark alongside the circuit-board title and description. Thus this is not merely an audit-script presentation error. The original user tab's Wynwood card similarly used the Wynwood asset ID in its image URL while displaying the portrait title.

Additional screening findings include a misread Nobu Hotels wordmark, incorrect geometry for a white house/shield icon, a black square called white, and repeated loss of white artwork on transparent backgrounds. Correct descriptions also exist for other variants of some affected brands; the failure is not a consistent brand-wide remapping.

## Mapping checks and what they establish

1. **Registry → durable bytes: 489/489 passed.** Record JSON IDs matched registry IDs, media location digests matched media digests, all referenced originals existed, and SHA-256 of the actual bytes matched the registry.
2. **Ready analysis → original/preview: 158/158 passed.** The stored analyzed-original digest matched the original bytes. Reconstructing the production preview from the original (using the stored raster thumbnail for SVGs) reproduced the stored analyzed-preview digest exactly. Source-occurrence ID sets also matched.
3. **Current request construction and concurrent response handling: 158/158 passed offline.** The actual describer ran with a mocked provider at 15 concurrent workers. Each request contained one manifest item and one inline image; the asset ID, decoded image bytes, and preview digest matched. Varied completion order did not alter association.
4. **Out-of-order/foreign responses:** reversed two-item responses still mapped by ID; a response containing only a foreign ID was refused rather than assigned to the requested asset.
5. **Full current enrichment path: 158 ready, 0 failed in an offline replay.** Actual enrichment resolved durable originals/previews and used the actual describer with a mocked provider and in-memory persistence. Per-asset completion tokens and stored results remained associated correctly at concurrency 15. This did not exercise live Postgres locking or the real provider again.
6. **Frontend mapping/repository tests: 41 passed.** The repository merges metadata by `asset.id`; it does not zip a metadata list against the rendered image list.

The first two checks establish integrity of stored lineage. The offline replay establishes current request/mapping behavior. Neither substitutes for the missing historical provider wire receipt or proves semantic correctness.

## Findings in the implementation

### P1: structurally valid but unusable analysis becomes ready

`subsystems/design/clue_design/asset_context.py::validate_analysis` validates the structured schema and exact source-occurrence membership. It does not validate that the text describes the visible image, or reject placeholder/refusal-like output. Ten selected bad or unusable stored analyses passed this production validator during the audit.

`lumen_ingestion/asset_enrichment.py` then finishes the result as ready. Therefore “ready” currently indicates successful structured processing, not verified visual grounding. Incorrect descriptions also affect titles, types, usage recommendations, and downstream asset selection; correcting only the card title would leave the underlying problem.

### P1: analysis previews do not make transparent artwork reliably visible

`subsystems/clue-design/apps/api/lumen_ingestion/describe.py::_downscale_preview` preserves alpha in PNG output without an explicit contrasting matte. Several previews contain white glyphs/wordmarks with transparency. On a white rendering background that content disappears.

Examples include the Bocobay white tree/wordmark (`asset_ing_112d359150dd4a23`), white LinkedIn and YouTube icons (`asset_ing_25517cd9e7ca2b7d`, `asset_ing_afab4b9458bd5c63`), and multiple Alloggio variants whose blue marks were recognized while their white text was omitted (`asset_ing_626ecc8dd09f0a72`, `asset_ing_a2dec30729132ce3`, among others).

The preview behavior and invisible-on-white rendering are confirmed. Their causal contribution to the historical model responses is an inference because provider image compositing was not recorded. This does **not** explain the black Wynwood/Arbio wordmarks being described as unrelated subjects. Small source logos and the maximum-512-pixel preview can also limit recognition, but do not justify confident invention.

### P2: historical provider evidence is insufficient to close the root cause

The affected isolated database had no `design.ingestion.describe` provider ledger rows at the time queried. Ingestion was still running; unit-end buffer draining is a possible explanation. Independently, `platform/api/clue_api/design_fleet.py::_drain_design_spend` explicitly drains with `artifacts=None`, so raw response bodies are not persisted to the platform artifact store through this path.

Stored analyzed inputs contain useful model/prompt/digest lineage, but they do not establish the exact request bytes received by the provider or the raw response returned for these historical anomalies. Provider routing, image decoding, or response-generation failure cannot be distinguished conclusively from this evidence. A new instrumented replay would test current behavior, not reconstruct the missing historical calls.

### P2: existing library tabs can miss newly initialized analysis rows

`apps/frontend/src/features/brand-context/hooks/use-asset-library.ts` polls known `queued`/`analyzing` assets. An asset initially loaded without a description row can remain stale after enrichment later creates/completes that row. The existing tab showed the Arbio item as unknown/stale while a fresh tab showed its completed circuit-board analysis. This affects freshness, not association between different asset IDs.

## Source trace

- `subsystems/clue-design/apps/api/lumen_ingestion/pipeline.py::_make_resolve_bytes`: requested asset ID → registry record → digest → durable bytes.
- `subsystems/clue-design/apps/api/lumen_ingestion/asset_enrichment.py::enrich_assets`: per-asset original/preview fingerprints, one item per describe call, validation, and token-associated completion.
- `subsystems/clue-design/apps/api/lumen_ingestion/describe.py::OpenRouterDescriber`: local request manifest + inline image, returned objects indexed by asset ID.
- `subsystems/design/clue_design/descriptions.py::{get_many,begin_analysis,finish_analysis}`: workspace/asset-scoped reads, current-fingerprint/token checks and scoped completion writes.
- `subsystems/clue-design/apps/api/lumen_api/main.py`: keyed description reads and asset-ID-based byte serving.
- `apps/frontend/src/features/brand-context/data/{asset.repository,brand-context.repository}.ts`: metadata batches merged as ID-keyed records, joined using `metadata[asset.id]`.
- `apps/frontend/src/features/brand-context/model/brand-context-mapping.ts`: image URL uses the same asset ID.

## Recommended correction sequence (not implemented in this review)

1. Capture per-asset request/response receipts at the existing provider seam, with input hashes, model/prompt/provider identifiers and call IDs, under the existing workspace privacy boundary.
2. Build a small representative visual regression set from the observed failure classes, and run an instrumented provider reproduction before choosing a model/prompt fix. Include black wordmarks, white transparent logos, tiny logos, screenshots and photographs.
3. Make analysis previews preserve visible contrast while retaining originals unchanged and recording the preview transform. Verify the actual provider-visible result.
4. Reject placeholder/refusal/unavailable-pixel responses as successful analysis, and introduce appropriate grounding checks/uncertainty handling. Schema checks and keyword rejection alone cannot catch fluent but unrelated descriptions.
5. Repair the library polling gap, then reanalyze affected records after the generation/validation fixes are verified. Preserve human overrides and do not silently overwrite them.

## Local evidence and verification

Ephemeral audit material lives in `/tmp/san-diego-asset-audit/`: `snapshot.json`, `normalized.json`, `ready.json`, `checks.json`, reconstructed previews, eight contact sheets, `audit.py`, `probe.py`, `probe-results.json`, and `frontend-tests.log`. These contain local diagnostic data and were not staged into Git.

Frontend command, run from `apps/frontend/`:

```sh
node --import tsx --test src/features/brand-context/model/brand-context-mapping.test.ts src/features/brand-context/data/brand-context.repository.test.ts
```

Result: 41 passed, 0 failed. The offline probe used the existing Python environment with provider calls mocked and an in-memory description store. No live write or paid call occurred. An attempted browser navigation to the BFF JSON route was blocked by the browser and abandoned; evidence came from read-only database/blob inspection and the rendered UI, without bypassing that block. Temporary audit tabs were closed; the user's existing tabs were retained.
