# Resolved production source

This directory is the single input to the Clue runtime token build.

## Resolution model

- Product usage and product-local component state come from the production
  `Clue` file (`NcLl2r0dzVDN28xAQCwvM1`).
- Published component definitions, semantic tokens, primitives, typography,
  and effects come from `Clue Design System` (`Gqz4ROcgy5sZ4HMWsLpOVf`).
- Actual published text styles win when stale variable metadata disagrees with
  the rendered component style.
- Application geometry exists only when current code consumes it.
- Runtime consumers use canonical published token names directly. The build
  does not generate compatibility aliases.

The current resolved inventory is 183 primitives, 43 semantic color tokens,
52 published typography variables, and 14 local text styles. Figma’s published
spelling `tittle-*` is retained for provenance.

Light and Dark in Brand Context are brand-palette datasets. They are not Clue
application themes.

Future syncs replace these resolved files after count verification. Never add a
second source or override layer to the generator.
