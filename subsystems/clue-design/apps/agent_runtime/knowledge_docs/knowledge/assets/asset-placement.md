# Asset Placement Guidance

Status: supported now, recognized but not lowered, and future scaffold.

Related: `knowledge/images/placement` (the cover/focal-point + text-over-image scrim
idioms for placing a hero image) and `knowledge/design-systems/logo-and-assets` (brand
logo/asset roles + allowed-surface rules).

## Supported Now

Agents may reference registered or fixture assets by stable asset IDs. Use
assets for logos, hero images, icons, and vector marks only when the scene asset
registry contains the referenced asset.

Good pattern:

```text
logo image asset(account_logo) p(32,32) s(96,48) slot(account.logo)
```

Asset placement should respect:

- aspect ratio
- crop/fit policy
- minimum readable size
- enough whitespace around logos
- provenance/licensing metadata in the asset record

## Recognized But Not Lowered

The current Phase A runtime does not own real upload, storage, provider image
generation, vectorization, or production asset processing. If the user request
requires a missing image, the agent should request/select a fixture asset or
record an asset gap.

## Future Scaffold

Future asset work should add:

- upload/import API
- object storage
- image probing and thumbnails
- generation/vectorization providers
- asset search
- export-time byte resolution and embedding

