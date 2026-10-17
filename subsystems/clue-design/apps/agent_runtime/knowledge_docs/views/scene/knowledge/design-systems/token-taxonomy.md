# Brand Token Taxonomy

Use Brand Kit semantic tokens before raw values. Lumen scenes should look
brand-aligned because they reference role tokens, not because the model guessed
nice colors.

## Required Semantic Groups

Use these groups when an effective Brand Kit exists:

- `surface.*` for page, card, elevated, brand, muted, inverse, and accent
  backgrounds.
- `text.*` for readable foreground color roles.
- `border.*` and `stroke.width.*` for outlines, dividers, focus, and
  illustration strokes.
- `type.*` for full typography roles.
- `space.*` for gaps, padding, margins, sections, and card rhythm.
- `radius.*` for cards, buttons, badges, images, and full pills.
- `opacity.*` only for non-text emphasis, overlays, disabled states, and
  print-safe rules.
- `logo.*` and `asset.*` for approved brand marks, illustrations, icons, and
  textures.

## Authoring Rules

Prefer semantic tokens:

```text
fill($surface.card)
style($type.headline)
g($space.stack.default)
pad($space.card.padding)
rd($radius.card)
stroke($border.default,$stroke.width.card)
```

Avoid primitive or guessed values in branded designs:

```text
fill(#2463eb)
font("Inter",57,791,left)
g(17)
rd(13)
```

Primitive palette stops may exist, but agents should prefer role tokens such
as `$surface.brand` and `$text.primary` unless a repair explicitly asks for a
low-level token.

## Product-Ready Minimum

A product-ready Brand Kit should include:

- surfaces: `surface.page`, `surface.card`, `surface.brand`,
  `surface.brand.subtle`, `surface.inverse`
- text: `text.primary`, `text.secondary`, `text.inverse`, `text.brand`
- type: `type.display`, `type.headline`, `type.body`, `type.cta`,
  `type.caption`, `type.legal`
- spacing: `space.stack.default`, `space.page.margin`, `space.card.padding`
- radius: `radius.card`, `radius.button`, `radius.badge`
- assets: `logo.primary`, `logo.reversed`, `asset.illustration.primary`,
  `asset.texture.subtle`, `asset.icon.primary`

If a needed token is missing, record the gap; don't invent a raw replacement.
