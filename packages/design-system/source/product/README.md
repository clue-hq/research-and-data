# Clue product tokens

This directory is the frontend-facing semantic layer for Clue product UI.
It reconciles approved Dev Mode values from the main `Clue` product file with
the raw variable mirror in `source/figma`.

## Why this layer exists

The dev-ready account and contact components currently resolve the external
Tier 1/2/3 library's `text-sm` tokens to 13px/18px, while the main file's local
typography collection and the older standalone design-system export still
contain 12px/16px values. Application code cannot safely consume both.

`product-tokens.json` therefore records the verified product contract. It is
not a rewrite of the raw Figma export. Every deliberate divergence is retained
with source nodes and inspection notes so Aakash can reconcile the Figma
libraries later without losing provenance.

## Precedence

1. Product components consume `--clue-ds-product-*` tokens.
2. Product tokens may alias raw `--clue-ds-*` tokens when both sources agree.
3. `source/figma` remains an immutable mirror of the extracted design-system
   file and must not be edited to hide a mismatch.
4. Generated CSS is rebuilt with `npm run design-system:build` and is never
   edited by hand.

## Sync checklist

1. Inspect the approved dev-ready component in Figma Dev Mode.
2. Record the file, page, node, resolved value, and capture date.
3. Update `product-tokens.json` only when the rendered contract changes.
4. Regenerate tokens, run tests and lint, then validate a production build.
