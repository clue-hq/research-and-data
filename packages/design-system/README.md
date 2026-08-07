# @clue/design-system

The production design-system package for Clue frontend surfaces.

## Ownership

- Figma is the design-authoring source.
- `source/figma` is the immutable versioned extraction and provenance record.
- `source/product` is the verified frontend contract when approved Dev Mode
  values and an older raw Figma collection disagree.
- `generated` contains deterministic runtime artifacts.
- Product code imports this package; it does not import files from
  `source/figma` directly.

## Commands

From the repository root:

```sh
npm run design-system:build
```

The command reads the versioned Figma collections plus the product-semantic
contract and regenerates `generated/tokens.css`.

## Import

```tsx
import "@clue/design-system/tokens.css";
```

Generated files must not be edited manually.

Product components should consume `--clue-ds-product-*` variables. Raw
`--clue-ds-*` variables remain available for values whose Figma source is
already consistent.
