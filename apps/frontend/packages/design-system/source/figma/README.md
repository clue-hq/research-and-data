# Clue Design System

This directory is the local, versionable mirror of the separate
[Clue Design System](https://www.figma.com/design/Gqz4ROcgy5sZ4HMWsLpOVf/Clue-Design-System?node-id=3019-28601).
It replaces `figma/mvp-design` as the imported Figma source for the
`@clue/design-system` package.

## What is complete

- All 278 local variables are preserved with Figma IDs, keys, modes, aliases,
  scopes, descriptions, resolved types, and literal primitive color values.
- All 14 text styles, 10 paint styles, and 19 effect styles are preserved.
- All 12 pages are inventoried, including 16 component sets and 1,805
  components/variants.
- The semantic variables are compiled into `../../generated/tokens.css`, which
  is exported by `@clue/design-system` and consumed globally by the Next.js
  application.
- Existing `--clue-*` variables are compatibility aliases only. New frontend
  work should consume the generated `--clue-ds-product-*` variables for
  product semantics and raw `--clue-ds-*` variables only when the Figma
  collections agree.

## Files

- `primitives.json`: 183 primitive variables.
- `tokens.json`: 43 semantic and component color variables.
- `typography.json`: 52 typography variables.
- `styles.json`: text, paint, effect, and grid style definitions.
- `component-index.json`: authoritative page IDs and component counts.
- `manifest.json`: extraction provenance, totals, and completion status.

## Known extraction boundary

Figma enforced the Full-seat MCP call limit while the 1,805 individual
component records and 1,553 icon SVGs were being expanded. The component pages,
counts, and Checkbox node map are verified, but the per-component asset export
is explicitly marked pending in the manifest. No approximate or third-party
icon has been substituted.

When Figma MCP access is available again, resume with the component pages in
`component-index.json`, export each custom vector as SVG, and update
`assetExport.status` only after validating the local file count against Figma.

## Sync rules

1. Figma aliases remain aliases; do not flatten semantic tokens manually.
2. Regenerate `packages/design-system/generated/tokens.css` from the JSON
   mirror after a design-system update with `npm run design-system:build`.
3. Preserve the source variable and node IDs so future diffs are deterministic.
4. Do not modify exported SVG paths by eye.
5. Run `npm run lint` and `npm run build` after every token sync.
6. Do not alter this raw mirror to compensate for a product-file mismatch;
   record verified divergences under `../product` instead.
