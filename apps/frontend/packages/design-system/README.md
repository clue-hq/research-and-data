# @clue/design-system

The resolved production design-system package for Clue frontend surfaces.

## Sources of truth

The package resolves two current Figma sources into one local contract:

- [Clue production](https://www.figma.com/design/NcLl2r0dzVDN28xAQCwvM1/Clue?node-id=1735-38951) decides which components, states, and patterns product screens use.
- [Clue Design System](https://www.figma.com/design/Gqz4ROcgy5sZ4HMWsLpOVf/Clue-Design-System?node-id=3025-8195) supplies the published reusable components, 43 semantic tokens, 183 primitives, typography styles, and effects.

`source/production` is the only generator input. It contains:

- `variables.json` — the resolved current primitive, semantic, and typography definitions;
- `application.json` — only the shell geometry and motion values consumed by the frontend;
- `components/*.json` — component geometry and provenance for reusable product contracts;
- `manifest.json` — source nodes, live inventory, and conflict-resolution rules.

The removed `source/figma` and `source/product` trees were stale additive layers.
They must not be recreated. A sync replaces the resolved source rather than
merging another override into it.

## Build

From the repository root:

```sh
npm run design-system:build
```

The build validates source identities and live collection counts, rejects
duplicate CSS custom-property definitions, rejects unresolved aliases, and
regenerates `generated/tokens.css` deterministically.

## The legacy-compat layer (D4, 2026-09-09 — temporary)

`generated/legacy-compat.css` carries the 48 `--clue-ds-product-typography-*`
variables that only the PRE-D4 design system defined. This package was ported
into the platform frontend at D4 while most features still read those names, so
the layer keeps them rendering until the CSS re-sync job re-lifts each feature
and deletes the file. It is loaded after `tokens.css`, so it can only ADD names,
never shadow a production one. **Never add to it.**

It was produced once by `scripts/extract-legacy-compat.mjs`, a one-shot that
diffs the defined sets of an old and a new `tokens.css`. That script is NOT part
of `npm run build`; it is kept only so the extraction stays reproducible and
reviewable, and it is deleted alongside its output.

`src/design-system-tokens.test.ts` in the app asserts that every `--clue-*`
variable read without a CSS fallback is defined in `tokens.css`,
`legacy-compat.css`, or `src/app/globals.css` — so the compat layer cannot be
removed before the features depending on it are re-synced.

## Import

```tsx
import "@clue/design-system/tokens.css";
import "@clue/design-system/legacy-compat.css"; // temporary; see above
```

Generated files must not be edited manually. Product code now consumes the
published typography tokens directly. The remaining `--clue-ds-product-*`
namespace contains application geometry, motion, and component contracts only.
