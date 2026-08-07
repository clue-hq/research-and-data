# Brand Kits — Using & Generating

A Brand Kit is the resolvable design system a scene references through `$tokens`.
Lumen designs look on-brand because they reference role tokens, not because the
model guessed nice values.

## Using a kit (authoring)

Use tokens when the design should adapt to an uploaded, generated, or platform
default kit:

```text
fill($surface.brand)     fill($surface.card)
stroke($border.default,$stroke.width.firm)
g($space.stack.default)  pad($space.card.padding)
rd($radius.card)
style($type.headline)    style($type.body)
```

If a scene contains token references, preflight must receive an effective Brand
Kit. The platform default kit is valid when the user supplied none. The DSL
compiler lowers token refs into scene token carriers where a precise field exists;
Brand Kit resolution and fallback happen in preflight. Avoid ambiguous tokenized
forms with no precise carrier (e.g. tokenizing only the size arg of `font(...)`) —
prefer a full `style($type.headline)`.

See `token-taxonomy.md` for the role groups and the product-ready minimum set.

## Kit status & governance

Phase C kits expose:

- approval status: `draft`, `generated_unreviewed`, `approved`, `deprecated`
- a `medium` mode for digital vs print behavior (see `modes.md`)
- logo and reusable brand-asset rules (see `logo-and-assets.md`)
- strict scene governance diagnostics (see `brand-validation.md`)
- compatibility reports between kit versions

Approved kits are stricter than draft/generated ones. When strict governance flags
raw styling, repair by choosing a semantic token — never swap one arbitrary value
for another.

## Generating a draft kit

Generation turns structured seed inputs into a draft kit. It is not the same as
writing random styles into a prompt.

Useful seed inputs: brand name; primary color (+ optional secondary/accent/neutral);
preferred fonts; logo asset refs; tone words; a website/style-guide summary;
desired default mode values.

The deterministic core function is
`generate_brand_kit(seed: BrandSeed) -> BrandGenerationReport`, returning the kit,
diagnostics, missing-input warnings, confidence, and provenance. Generated kits
start `generated_unreviewed` — **do not claim they are approved** unless a trusted
workflow or the user approves them.

Agent behavior when the user has no kit:

1. Prefer the platform default if the task only needs a neutral demo brand.
2. Generate a draft kit when the user gives enough brand signals.
3. Ask for missing brand facts only when the task can't proceed safely.
4. Keep generated token names semantic, not artifact-specific.

When authoring against a generated kit, still use role tokens
(`$surface.card`, `$type.headline`, `$space.card.padding`).
