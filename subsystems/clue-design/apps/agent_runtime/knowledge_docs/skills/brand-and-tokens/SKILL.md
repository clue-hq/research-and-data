---
name: brand-and-tokens
description: Interpret a Brand Kit and design tokens, and author/repair Lumen designs that are brand-resolved — choose semantic $tokens over raw values, respect modes, and fix brand-governance diagnostics. Use whenever an effective Brand Kit is in play.
---

# Brand Artifacts & Design Tokens

A Lumen scene should look brand-aligned because it **references role tokens**, not
because the model guessed nice colors. Tokens let one scene resolve correctly for
this client, in this medium, in this mode.

## Token taxonomy (use roles, not raw values)

| Group | Examples | For |
|-------|----------|-----|
| `surface.*` | `surface.page`, `surface.card`, `surface.brand`, `surface.brand.subtle`, `surface.inverse` | backgrounds |
| `text.*` | `text.primary`, `text.secondary`, `text.inverse`, `text.brand` | foreground color roles |
| `type.*` | `type.display`, `type.headline`, `type.body`, `type.cta`, `type.caption`, `type.legal` | full typography roles |
| `border.*`, `stroke.width.*` | `border.default`, `stroke.width.card` | outlines, dividers, illustration strokes |
| `space.*` | `space.stack.default`, `space.page.margin`, `space.card.padding` | gaps, padding, rhythm |
| `radius.*` | `radius.card`, `radius.button`, `radius.badge` | corner radii |
| `opacity.*` | overlays, disabled, print-safe | non-text emphasis only |
| `logo.*`, `asset.*` | `logo.primary`, `logo.reversed`, `asset.illustration.primary` | approved brand marks/imagery |

```text
fill($surface.card)
style($type.headline)
g($space.stack.default)   pad($space.card.padding)
rd($radius.card)
stroke($border.default,$stroke.width.card)
```

Avoid guessed primitives in branded designs. Prefer existing role tokens whose
resolved values fit the intended design; primitive palette stops may also exist.
Deliberate numeric typography, gaps and margins can remain under advisory
governance when no equivalent token exists. Binding is a design change whenever
the token resolves to a different value.

**Kit fonts first, library second.** The kit's declared families are the brand
voice — use a kit type role when its effective typography fits the text. The curated
font library (`knowledge/design/font-library`) is for roles the kit does NOT
cover (e.g. a poster needs a condensed impact face and the kit only ships a
text sans) — pick a library neighbor that matches the kit's tone, and say so
in your notes so the reviewer can judge the call.

## When there is / isn't a Brand Kit

- **Effective Brand Kit present** (uploaded, generated, or platform default): prefer
  appropriate `$tokens`. If a token reference appears in the scene, preflight must receive an
  effective Brand Kit; the platform default is valid when the user supplied none.
- **No Brand Kit and a neutral demo is fine**: use the platform default, or
  concrete fallback values.
- **Strong brand signals but no kit**: a draft kit can be generated from a seed
  (name, primary color, fonts, logo, tone). Generated kits are
  `generated_unreviewed` — never claim they're approved. Keep generated token names
  semantic, not artifact-specific.

## Modes

Product-ready kits declare axes — `theme` (light/dark), `density`
(comfortable/compact), `accessibility` (standard/high_contrast/large_text),
`medium` (digital/print). **Do not hard-code mode-specific values.** Author with
semantic tokens and let preflight resolve the active mode; set the scene `medium`
for print/direct-mail and let preflight choose `medium.print`. Treat mode
compatibility diagnostics as product-safety issues, not preferences.

## Logos & brand assets

Use asset *roles* (`logo.primary`, `logo.reversed`, `asset.illustration.primary`),
not arbitrary image ids. Respect each asset's rules: allowed backgrounds, min
size, clearspace, color mode. If a kit says a logo is allowed only on
`surface.brand`, do not place it on `surface.page`/`surface.card` (→ `LUMB0807`).
Never invent production asset ids; if imagery is needed and none is approved, use
the asset tool or record an `assets` gap. See
`knowledge/design-systems/logo-and-assets`.

## Repairing brand-governance diagnostics

Missing bindings are governance findings, not proof of an invalid visual
treatment. Advisory policy permits intentional literals; strict policy still
requires valid bindings and blocks unresolved violations.

| Code | Raw thing → fix |
|------|-----------------|
| `LUMB0804` | raw/off-brand color → `fill($surface.*)` / `$text.*` |
| `LUMB0805` | missing typography role binding → inspect effective role values before choosing an equivalent role or a deliberate typography revision |
| `LUMB0806` | missing spacing/radius/stroke/opacity binding → inspect existing tokens and their resolved values before binding |
| `LUMB0807` | logo on disallowed surface → move to `surface.brand` or use `logo.reversed` |
| `LUMB0811` | print transparency → remove transparency for print medium |
| `LUMB0813`–`815` | kit-version incompatibility → adopt the compatible token set |

For gaps and padding, compare the token's active-mode value to the intended
geometry. A padding token sets **all four edges** to one value; it cannot preserve
asymmetric margins. A card-padding role is not automatically a page-margin
repair, and an empty or nonstandard kit may offer no equivalent token. Preserve
intentional literals under advisory policy. Under strict policy, choose a valid
equivalent binding or explicitly review the required layout change; never invent
a token or apply an unrelated one merely to clear a finding.

For typography, compare family, weight, size, leading, tracking and any role-owned
color in the active mode. A body role or matching size alone does not establish
equivalence. Optional leading/tracking values apply only when the role declares
them; explicit authored tokens remain the canonical resolver's responsibility.
Automatic inference preserves literal size by default. A size-ramp binding can
be safe on its own when a whole role would change typography. Keep a deliberate
numeric leading or size repair when no equivalent role exists under advisory
policy; under strict policy, review the typography change needed for a valid
role. "Make it more on brand" is not a repair: name the actual mismatch and the
intended value before choosing a binding.

## Brand-fit as a quality gate

A design can compile, preflight, and export and still fail brand. Ask: does it use
role tokens; are surfaces/text/borders/accents consistent; does typography use
`type.*`; do spacing/radius read as one rhythm; is the logo on an allowed surface;
does the medium match; does it plausibly belong to *this* client? See
`knowledge/design-systems/brand-fit-critique`.
