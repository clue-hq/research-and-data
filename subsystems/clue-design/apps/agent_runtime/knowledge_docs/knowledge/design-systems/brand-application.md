# Brand Application — deciding HOW MUCH brand, and WHERE

Loaded whenever the run has an attached Brand Kit. The run context carries a
**brand context card** with the kit's ACTUAL tone words, resolved role
colors, its `accent` (the most vivid brand color), type roles, and the
logo/image inventory. Design from the card's facts; never invent token
names or values the card does not list.

## Decide brand intensity by surface archetype

| Surface archetype | Brand intensity |
| --- | --- |
| Marketing collateral: poster, social ad, invitation | FULL: brand surface for the hero field, accent CTA, logo present |
| Deck title slide / section divider | STRONG: brand surface or band, mark or wordmark, accent sparingly |
| Content/data slide, report page, pricing table | QUIET: neutral surfaces (`surface.page`/`surface.card`), brand color only as accent on key numbers/rules, mark-only or no logo |
| Email / letter / document | QUIET: neutral field, brand in header/footer marks and links |

Never more than ONE logo per page. Brand color is a voice, not a flood —
a data slide drowning in `surface.brand` reads as a mistake, and a poster
with zero brand color reads as unbranded.

## The CTA / accent rule (taste-critical)

- A CTA button, key stat, or emphasis element uses the kit's **accent**: the
  `accent` entry in the brand context card (or `surface.accent` when the kit
  defines that role). Style CTA text with `style($type.cta)`.
- Do NOT default CTAs to `surface.inverse` / ink. Ink-on-brand reads as a
  disabled button; the accent is what makes the design feel like THIS brand.
- Check contrast: accent surface + its text must read (the card lists
  resolved hex values — reason about light/dark from them). If the accent
  fails contrast on the chosen field, put the accent CTA on a neutral field
  or use `text.inverse` on the accent, whichever the values support.
- On a brand-colored field, the accent is the ONLY loud element. One accent
  moment per page beats five.

## Logo rules

- Choose the variant by the background it sits on: `reversed` on dark/brand
  fields, `full_color`/primary on light fields. The card lists each logo's
  `allowed_backgrounds` — respect them (LUMB0810 enforces this; LUMB0809
  enforces `min_size`).
- Respect `min_size`; never distort, recolor, or add effects to a logo.
- Mark-only (`logo.mark`) for tight corners and quiet surfaces; full lockup
  for hero/headers.

## Placing kit assets (logos and brand images)

- Author an image frame for the logo/brand image in the DSL (a placeholder
  asset id is tolerated until placement), then call
  `asset(action="use_brand_asset", asset_id=<from the card>, node_id=<frame>)`.
  Every logo variant and brand image in the card carries its `asset_id` —
  never invent one, and never draw a logo from shapes or text when the kit
  has the real mark.
- Logos place with fit `contain` (the default for this action) — a cropped
  logo is a brand failure. Brand images/textures may pass `fit="cover"`
  explicitly when they fill a field.
- Size the logo frame at or above the card's `min_size` for that logo.
- ONE logo per page. When the kit has no suitable asset for a need, fall
  back to the imagery decide flow (generate) or `record_gap` — do not fake
  a mark.

## Type roles

- Author text through the kit's roles — `style($type.display)` for the hero,
  `$type.headline`, `$type.body`, `$type.cta` — with `font_size($type.size.*)`
  overrides when scale demands. The card lists each role's family/weight so
  you can reason about hierarchy; the values resolve at preflight.

## Kit imagery first

- When the card's `images` inventory has an asset whose role/description
  matches the need (illustration, texture, product shot), prefer placing it
  over generating a new image. Generation remains for content imagery the
  kit cannot supply — brand `tone` words ride generation `brand_notes`.

## Tone

- The card's `tone` words shape composition: "clinical/precise" → generous
  whitespace, restrained palette; "warm/human" → imagery-forward, softer
  radii. State in your plan which tone words drove which choice.
