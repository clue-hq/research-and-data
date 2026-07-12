---
name: brand-imagery
description: Make the explicit imagery decision for a create-turn — kit asset, generate, or deliberately none — kit-first, looking at real candidates before choosing, and honest when imagery is warranted but unachievable. Use on the first authoring pass whenever a surface might carry a photo, texture, or brand image.
---

# Brand Imagery — Decide, Then Source It Honestly

Every create-turn makes an **explicit imagery decision** and records it — you do
not drift into "no image" by omission, and you do not sprinkle a photo for vibes.
The three legitimate outcomes are: **place a kit asset**, **generate an image**, or
**deliberately none**. This skill is the decision + sourcing procedure; for whether
a surface earns an image see `knowledge/images/decide`, for prompt craft
`knowledge/images/prompts`, for placement + the scrim rule `knowledge/images/placement`.

The baseline sweep shipped **0/7 runs with any non-logo imagery** even with a fully
described kit — imagery was skipped by silent omission, not by decision. That is the
failure this skill exists to break.

## 1. Decide — one explicit call, every create-turn

Run the decision from `knowledge/images/decide` and state the verdict in your
direction notes: **which archetype**, and **the imagery decision** with its reason.

- **Deliberately none** is a valid, common answer for data/type surfaces — but say
  so ("type-led numeral-hero, no photo: the metric is the hero"). Silence is not a
  decision.
- **Kit asset** when the card's `images` inventory already has what the surface
  needs (§2).
- **Generate** when the content is genuinely photographic/painted and the kit lacks
  it (§3).

Archetypes that usually earn imagery: **image-hero** (full-bleed photo + scrim) and
**split-panel** (image column). Emblem can sit over a photo field. Numeral-hero,
banded, and vertical-poster are usually type-led — but a texture/wash still counts
as a deliberate surface decision (`skills/effects`).

## 2. Kit-first — look before you choose

When a Brand Kit is in play, the kit is the FIRST source. Do not generate what the
kit already supplies.

- **Read the card's `images` inventory** — each entry carries `title`,
  `description`, and `usage_note`. Match the surface's need (hero, texture, product,
  portrait) against those fields.
- **Look at the real candidates before committing.** `view("asset:<asset_id>")`
  returns the asset's preview thumbnail — inspect 2–3 plausible candidates and judge
  by the pixels, not the metadata. Pick the one whose subject, crop, and tone fit.
- **Place it** by referencing `image asset(<asset_id from the card>)` in the DSL, or
  author a placeholder frame and call `asset(action="use_brand_asset",
  asset_id=<from the card>, node_id=<frame>)` for explicit fit/slot control
  (`knowledge/design-systems/brand-application`). Never invent an `asset_id`; never
  draw a logo from shapes.

## 3. Generate — only what the kit can't supply, art-directed to the brand

When the kit lacks a needed photographic image:

1. **Read the brand card** — palette, `tone` words, any imagery `description`s that
   establish the visual language.
2. **View 2–3 kit images first** (`view("asset:<id>")`) even when you'll generate —
   they teach you the brand's actual subject style, crop, and color so your prompt
   echoes it instead of producing generic stock.
3. **Write the 5-component prompt** (`knowledge/images/prompts`): subject, medium,
   composition, lighting, quality. The prompt describes the *scene*; pass palette +
   mood as `brand_notes` (e.g. `["deep green + gold palette", "field-tested,
   dependable", "editorial, uncluttered"]`) — brand tone rides `brand_notes`, not
   the prompt string. End with *"no text, no words, no letters, no logos."*
4. **Generate onto the target frame** — `asset(action="generate_image",
   target_node_id=<frame>, prompt=…, brand_notes=…, alt=…)`. The aspect comes from
   the frame's geometry; compose for any overlay (negative space in the lower third).
   - **Turn references ride as image conditioning, automatically.** If the user
     attached reference images this turn, generation is style-conditioned on them by
     default (palette/texture/mood/edge) — `brand_notes` stays the *prose* channel and
     the prompt stays about the subject; don't restate the reference style in words.
     Only pass `condition_on_references=false` when the brief wants imagery that
     deliberately diverges from the references.
5. **Place + scrim** per `knowledge/images/placement`: text over a photo ALWAYS gets
   a scrim beneath it, and a full-bleed-photo artboard is a **dark** surface so brand
   type tokens resolve to light ink.

## 4. Honesty — record the gap, never fake it

If imagery is genuinely warranted (an image-hero brief, a testimonial that needs a
portrait) but you cannot achieve it — no matching kit asset AND generation is
unavailable or keeps failing — **`record_gap`** describing what was needed and why it
couldn't be produced. Do not ship a black frame, a stretched logo standing in for a
photo, or a generic placeholder pretending to be brand imagery. A recorded gap is an
honest, reviewable outcome; a faked image is a silent quality failure.

## Checklist

- [ ] Imagery decision stated in the direction notes (kit / generate / deliberately none) with a reason.
- [ ] Kit `images` inventory read; candidates `view()`-ed before choosing a kit asset.
- [ ] Generated images: brand card read, 2–3 kit images viewed, 5-component prompt, tone in `brand_notes`, no in-image text.
- [ ] Placement follows the scrim rule; one hero image per surface; nothing stretched.
- [ ] Warranted-but-unachievable imagery → `record_gap`, never a faked stand-in.
