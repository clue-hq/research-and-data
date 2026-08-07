# Assets Pipeline V0

`assets/pipeline-v0` defines the portable asset contract inside `lumen-core`.
It does not implement uploads, byte storage, object storage, provider calls, HTTP
routes, MIME sniffing, hashing, image probing, image generation, vectorization,
or export-time asset resolution.

## Ownership Boundary

`lumen-core` owns deterministic asset semantics:

- stable `AssetId` records in `Scene.assets`
- image, logo, vector, and font metadata
- provenance and licensing fields
- structured asset operations
- placement helpers that update existing scene nodes and slot bindings
- strict asset-aware validation helpers
- generation and vectorization request/result hook types

Other workstreams own adapter behavior:

- `api/persistence-v0`: uploaded bytes, storage keys, signed URLs, database rows,
  and durable object metadata
- `agents/design-loop-v0`: generation orchestration, provider selection,
  prompt construction, repair loops, and asset tool calling
- `export/svg-pdf`: resolving `AssetId` values into concrete bytes or rendered
  image/vector/font payloads at export time

## Scene Registry

`Scene` now has:

```rust
pub assets: BTreeMap<AssetId, AssetRecord>
```

The field has a serde default, so older scene fixtures and operation histories
without an asset registry remain readable.

`ImageNode.asset_id` remains the primary image binding. `Node.source_asset_id`
is an optional carrier for non-image asset provenance, especially vector and font
placements where the existing node kind did not previously hold an asset id.
`Node.asset_placement` stores placement-time rendering hints such as fit mode,
focal point, transparency preservation, and alt text so editor/export adapters
can reproduce direct node placement consistently.

## Asset Records

`AssetRecord` stores portable metadata only:

- `id`, `label`, `kind`, `status`
- `source`: uploaded, generated, vectorized, website, brand-guide, manual,
  workspace, URL, system, or unknown
- `media`: MIME type, filename, byte length, digest, and opaque location metadata
- optional `raster`, `vector`, `font`, and `logo` metadata
- optional `AssetLicense`
- provenance notes and tags

`AssetLocation` is intentionally opaque. It can describe a future persistence
adapter's storage key or URL, but `lumen-core` does not dereference it.

## Operations

New operations:

- `UpsertAsset { asset }`
- `RemoveAsset { asset_id }`
- `PlaceAssetInNode { node_id, asset_id, placement }`
- `PlaceAssetInSlot { slot_id, asset_id, placement }`

Placement operations mutate existing scene surfaces:

- raster/logo assets rewrite the target as `NodeKind::Image`
- vector assets rewrite the target as `NodeKind::Vector` when inline path data is
  available, otherwise as `NodeKind::Image`
- font assets attach `source_asset_id` to text nodes
- slot placement uses existing slot `bound_nodes`; it does not create a separate
  placement model
- slot placement respects the declared slot content type. Image/logo slots accept
  image-compatible assets; text-like slots accept font assets; other slot types
  reject asset placement until a dedicated contract exists.
- asset removal rejects assets that are still referenced by `ImageNode.asset_id`
  or `Node.source_asset_id`.

## Validation

`validate_scene(scene)` performs non-strict asset registry checks and preserves
backward compatibility with older scenes that reference image assets not yet
registered.

Use strict validation when the caller expects concrete assets to exist:

```rust
validate_scene_assets(&scene, AssetValidationOptions::strict())
```

Strict validation reports:

- missing node asset references
- image/logo slot bindings to missing or incompatible assets
- text-like slots bound to non-text nodes
- image policy mismatches against available metadata:
  - aspect ratio
  - minimum DPI
  - transparency preservation
  - crop mode without focal point
- licensing violations for export and crop/modify placements

Standalone node-level licensing checks are intentionally deferred. V0 keeps
license fields and slot-placement diagnostics in the contract, while exact export
blocking for unbound/direct node placements remains a follow-up for the export
resolver path.

Brand-kit asset refs can be checked with:

```rust
validate_brand_asset_references(&scene, &brand_kit)
```

This cross-checks brand font face `asset_id`s, logo variant `asset_id`s, and
brand image `asset_id`s against `Scene.assets` without redefining brand-kit
semantics.

## Hook Types

Generation and vectorization hooks are data contracts only:

- `AssetGenerationRequest`
- `AssetGenerationResult`
- `AssetVectorizationRequest`
- `AssetVectorizationResult`

Agents and backend adapters may use these shapes to exchange intent and results,
but providers do not live in `lumen-core`.

## Fixtures

Asset fixtures live under:

```text
crates/lumen-core/fixtures/assets/
```

They cover uploaded logos, generated raster imagery, vectorized SVG records,
font records, and an invalid missing-reference scene.
