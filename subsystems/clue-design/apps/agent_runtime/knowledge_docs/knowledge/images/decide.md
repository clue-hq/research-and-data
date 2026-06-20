# Imagery — Decide First (generate only what you can't build)

The guardrail against gratuitous AI imagery. BEFORE generating or placing anything,
answer two questions: **does this surface need imagery at all**, and **if so, what
role** — which decides the *mechanism*. An image must earn its place by serving the
message; decoration that just fills space makes the design worse, not better. For how
to prompt see `knowledge/images/prompts`; for how to place + scrim see
`knowledge/images/placement`.

## The decision table — content → mechanism

Route by what the content actually is. Most of these are NOT a generated photo.

| Content | Mechanism | Why |
|---|---|---|
| Photo, product shot, portrait, food, place/scene, **texture**, raster illustration | **`generate_image`** (text-to-image) | Only a model can render real photographic/painted content. |
| **Icon, pictogram, simple flat illustration, logo glyph** | **icon/library** — `svg(icon:name)` or a brand `logo.*`/`asset.icon.*` token | A curated vector is reliable, crisp at any size, and recolorable; a model garbles small flat marks. NOT `generate_image`. |
| Abstract / decorative geometric, accents | **shapes + gradients** (`r`, `vector`, gradient fills) | Built primitives are sharper, on-brand, and free. |
| Flat color field, brand block, panel | **solid / gradient fill** (`fill($surface.*)`) | A token surface, not an image. |
| Data, comparison, timeline, process, metrics | **layout / data-display blocks**, not imagery | Information belongs on surfaces, not behind a photo. |

## Does it need an image at all? Default to NO

Most enterprise one-pagers, cards, and slides are **stronger as clean typographic
layouts** with a strong hero headline, generous whitespace, and one accent. Reach for
a photo only when it does real work:

- **Use a photo when** it sets emotional/human tone the words can't (a hero that makes
  the message felt), shows a product/place/person that must be *seen*, or gives
  editorial credibility (a case study, a story).
- **Do NOT use a photo** as wallpaper behind text "for vibes", to fill an empty band,
  to look busy, or when an icon/shape/gradient conveys the idea more crisply. A
  generic stock-style image reads as filler and fails the critic.

## Rules of thumb

- **One hero image per surface.** Like one dominant element — a single, deliberate
  image, not a scatter of photos. A second image almost always competes.
- **Icons over generated illustrations** for anything iconographic (feature rows,
  checklists, step markers): use the library — reliable and recolorable.
- **Texture/pattern** that sits *behind* content must stay subtle (low contrast,
  scrimmed) so it never fights the text — or use a gradient instead.
- Imagery that genuinely serves the message is welcome; only **gratuitous or cliché**
  imagery is penalized. If you can't name what the image *does* for the message, don't
  generate it.
