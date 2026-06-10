# Brand Kit Generation

Brand generation turns structured seed inputs into a draft Brand Kit. It is not
the same as writing random styles in a prompt.

## Inputs

Useful seed inputs:

- brand name
- primary color
- optional secondary, accent, and neutral colors
- preferred font families
- logo asset refs
- tone words
- website or style-guide summary
- desired default mode values

## Core Contract

The deterministic core function is:

```text
generate_brand_kit(seed: BrandSeed) -> BrandGenerationReport
```

The result should include:

- generated Brand Kit
- diagnostics
- missing-input warnings
- confidence
- source/provenance

Generated kits start as `generated_unreviewed`. Do not claim they are approved
unless a trusted workflow or user explicitly approves them.

## Agent Behavior

When the user has no Brand Kit:

1. Prefer platform default if the task only needs a neutral demo brand.
2. Generate a draft Brand Kit when the user gives enough brand signals.
3. Ask for missing brand facts only when the task cannot proceed safely.
4. Keep generated token names semantic, not artifact-specific.

When writing DSL against a generated kit, still use role tokens such as
`$surface.card`, `$type.headline`, and `$space.card.padding`.
