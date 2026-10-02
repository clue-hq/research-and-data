# Asset context and bulk upload implementation

The founder authorized the unchanged September 21 design spec on this branch.
The full ICP-definition study transcript was read from Fredericton on September 21;
its asset discussion confirms the spec, with 15 concurrent descriptions superseding five.
Production work uses the existing description, custody, fleet and repository seams.
The standalone pilot and ICP experiments remain reference material only.

1. Extend the description domain with a validated analysis, source occurrences,
   per-field overrides, input fingerprints, revision and honest lifecycle states.
   Migrate legacy human captions into overrides. Prove tenant isolation and races.
2. Replace top-16 serial processing with continuous, bounded per-image work.
   Reuse ingestion job durability, cache successful results, retain source context,
   carry spend scope across threads and persist each result as it completes.
   Add the asset-enrichment ingestion kind for uploads and individual retries.
3. Feed website placement evidence and stored ad provenance/copy through the
   shared analysis contract. Keep Ad DNA separate. Freeze effective metadata into
   design manifests and expose searchable discovery/inspection in both modes.
4. Extend governed uploads with request idempotency and atomic registration/job
   scheduling; expose additive metadata edits, reset and retry operations.
   Preserve originals and report preview transformations/animated-frame policy.
5. Update the Brand Context API contract and both repository adapters. Load
   paginated assets without requiring a kit; join effective metadata in batches.
   Add independent Type/Used as/Source controls, durable detail edits, and a
   floating multi-file dialog whose controller survives closing the window.
6. Run focused behavior tests, migration up/down/up on a San Diego-only database,
   frontend token/lint/build gates and browser verification. Verify advertised
   formats and a small provider quality sample; historical paid backfill remains
   excluded. Commit coherent checkpoints locally, never push.

Format candidate scope is PNG, JPEG, WebP, SVG, GIF and AVIF; advertise each only
after its custody/preview/analysis/placement path is proven. No HEIC/TIFF/BMP promise.
The workspace's current target instruction remains authoritative for future diffs;
the copied spec's historical target and proposed-status wording are left untouched.

Implementation completed locally on September 21. See the
[verification record](../verification/2026-09-21-asset-ingestion.md) for delivered
behavior, database clone, format checks, live sample, commits and validation limits.
Historical backfill remains excluded. Authenticated browser-to-provider acceptance
and the pre-existing root type-check defect remain outside the verified results.
