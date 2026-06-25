---
assumes: images/decide, assets/asset-placement
---
# Imagery — Placement & the Scrim Rule

How a generated or library image goes into a design. Two non-negotiables: an image is
placed **onto a target frame** (the frame's geometry drives the aspect, the image is
cropped to fill — never stretched), and **text over an image always gets a scrim**
beneath it for legibility. Both examples below were run through `.context/p02-validate.py`
and return `{"ok": true}` (only the platform-font warnings `LUMB0613`/`LUMB0614`).

Builds on `knowledge/images/decide` (decide *whether* a surface earns an image first)
and `knowledge/assets/asset-placement` (the asset-registry rules + the
`place_asset_in_node` / `place_asset_in_slot` op contract this placement compiles to).

## Place onto a target — cover + focal, never stretched

- The image fills a frame whose **aspect comes from the frame**, not the image. The
  agent tool `asset(action="generate_image", target_node_id=…)` derives the ratio from the
  target's geometry; `asset(action="place", node_id=…/slot_id=…)` then drops the asset in.
- **Default `fit:cover` + a focal point.** Cover crops to fill the frame at the image's
  natural ratio; the focal point (0..1, default centered) keeps the subject in view —
  raise it for faces/upper subjects, bias it toward the busy side. Never `fill`-stretch
  a photo (distorts), never letterbox a hero (dead bands).
- Always set **alt text** describing the image.
- Clip the frame (`clip(true)`) and round it (`rd($radius.card)`) when the design wants
  rounded imagery; the image is clipped to the frame.

## The scrim rule — text over image is ALWAYS scrimmed

A scrim is a semi-transparent rectangle **between the image and the text**, using the
`$opacity.scrim` (0.56) or `$opacity.overlay` (0.88) token. Dark scrim
(`$surface.inverse`) under **light** text (`$text.inverse`); or a light scrim under
dark text. Without it, text on a photo is illegible the moment the photo is busy —
this is the single most common imagery failure the critic rejects.

**Make the artboard a dark surface (`fill($surface.inverse)`).** Brand tokens resolve
*relative to their container's surface*: on a dark artboard `$text.inverse` and the
`$type.*` roles resolve to **light** ink (legible over the scrim); on a light
`$surface.page` artboard the *same* tokens resolve **dark** and the headline goes invisible
against the photo. So a full-bleed-photo surface is a **dark** surface — and the dark fill
doubles as the fallback colour if the image fails to load.

### Idiom A — full-bleed image + scrim + text (the hero)

Image fills the artboard; a scrim sits on top; text is anchored at the bottom over the
scrim. Declaration order is z-order: image, then scrim, then text.

```text
page hero size(1080,1350,px)
  artboard fr p(0,0) s(fill,fill) fill($surface.inverse) clip(true)
    photo image asset(hero_photo) p(0,0) s(1080,1350)
    scrim r p(0,0) s(1080,1350) fill($surface.inverse) o($opacity.scrim)
    content al(v,x(s),y(e),g($space.stack.tight),pad($space.card.padding)) p(0,0) s(1080,1350)
      kicker text "CASE STUDY" p(0,0) s(936,40) style($type.label) fill($text.inverse) wrap_text(true)
      headline text "Faster triage, calmer clinics" p(0,0) s(936,240) style($type.headline) fill($text.inverse) wrap_text(true)
```

### Idiom B — split: image region + text on its own surface (no scrim needed)

When text sits on its own band rather than on the photo, **no scrim is needed** — the
text is on a solid surface, not the image. Safer than a scrim when legibility is
critical. Image hero on top, a brand band below absorbs the slack and centers its copy.

```text
page hero size(1080,1350,px)
  artboard al(v,x(s),g(0),pad(0)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    photo image asset(hero_photo) p(0,0) s(1080,810)
    band al(v,x(s),y(c),g($space.stack.tight),pad($space.card.padding)) p(0,0) s(1080,fill) fill($surface.brand)
      kicker text "CASE STUDY" p(0,0) s(936,40) style($type.label) fill($text.inverse) wrap_text(true)
      headline text "Faster triage, calmer clinics" p(0,0) s(936,200) style($type.headline) fill($text.inverse) wrap_text(true)
```

## Checklist

- [ ] Image placed onto a frame, aspect from the frame, `fit:cover` + focal point.
- [ ] Text over the image? A scrim rect sits beneath the text (Idiom A) — or move the
      text to its own surface (Idiom B).
- [ ] Text color contrasts the scrim/surface (`$text.inverse` on a dark scrim).
- [ ] Alt text set; one hero image per surface; nothing stretched.
