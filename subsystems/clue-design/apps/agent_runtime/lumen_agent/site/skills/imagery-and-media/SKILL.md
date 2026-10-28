---
name: imagery-and-media
description: "Read when a section needs an image, a logo, a product screenshot, a video or motion: which images a page may use and in what order, keeping the seller's image staging, generating an image that fits the brand, screenshots, sharpness, the account's and customers' logos, and keeping or rebuilding the seller's motion and video."
---

# Imagery and media

## The images a page may use

One list, in this order of preference:
1. the clone's own images;
2. the images in `brand/brand.md`;
3. the seller's other images (uploads, and images made for earlier pages), found with
   `search_assets`;
4. images generated for this site with `generate_image` (see "Generating an image");
5. the account's logo from `fetch_logo`, in the header only (see "Logos").

- Look at an image with `view_asset` before you use it. A description can be wrong or missing.
- The most authoritative image wins: the seller's own image in a clone beats a search result, which
  beats a generated one. A strong image the section already has is kept, not replaced.
- Check that the image fits the words beside it. A graphic with its own words baked in rarely fits a
  new heading.
- How to put an image in a slot or a section: `building-with-puck`.

## An image only for a real job

- Add an image only when it does something for the reader: shows the product, the setting, the
  proof. Never to fill a section, and never generic stock-style imagery.
- When a section must show how the product fits together and no real screenshot fits, draw it as a
  diagram in the brand's styles (a section of your own, `writing-a-section`), never a generated fake
  screen.
- One empty search does not mean there is no image: try other words. If nothing fits, use a smaller
  honest placement, or a section without an image. No image beats a weak image.

## Keeping the seller's staging

In rebuilt sections, brand sections and sections of your own, stage images the way the seller does:
- keep the crop, the focal point, the proportions and the layer order (the background behind, then
  the image, then any frame);
- know what is already inside the image: if it already has rounded corners, a shadow, a frame or a
  see-through edge, don't add another, and never put an opaque box behind a cut-out;
- never swap a photographic or illustrated background for a flat colour because the right image was
  hard to find: find it with `search_assets`, make one of the same type with `generate_image`, or use
  the clone as it is.

## Generating an image

**When**: only when a section needs an image and nothing in the list above fits.

**What**: follow the imagery type of the seller's own site and images: photographic or illustrated,
its subjects, its treatment. A setting for the audience's industry is a normal use (a warehouse floor
for freight brokers).

**Never presented as real**:
- never an image that pretends to be the seller's actual logo or the seller's actual product (a fake
  product screen);
- nothing presented as the account's own building, staff or customers;
- never an imitation of the account's logo, or a copy of anything that is the account's.

People, scenes, and elements in the style of the seller's imagery may be generated.

**How to ask**: write the prompt in five parts:
1. what the image is;
2. the style, described in plain words from the brand's own imagery;
3. the brand's exact colours;
4. the composition: where the weight sits, and where the image stays calm for text;
5. what must not appear.

Pass one to three of the brand's own photos as `style_references`. The test: would the brand's own
design team have made this?

**Then look at it.** If it is wrong, change the prompt rather than repeating it. Try once more at
most, then leave the image out. Never ship a failed or placeholder image.

**Text over it** sits on its calm area or on a scrim. One atmosphere per section.

## Screenshots

- A product screenshot must show what the words beside it say.
- A screenshot shows the product, not a result: it never stands in for a claim about integrations or
  outcomes.
- Never alter a screenshot: never redraw a dashboard, edit its figures, paint in the account's data,
  stretch it, or crop out the feature the words describe.
- Stage it the way the seller's own site stages its product images.
- On a phone, the product's interface stays visible and readable. A background with no interface
  left is a failure.

## Sharpness

- Never show an image larger than its natural size. A large image on a big screen needs about twice
  its displayed width in pixels.
- When an image is too small for its place, search for a sharper version of it (`search_assets`), or
  show it smaller, choose another, or leave it out.
- When the brand's own imagery uses blur or soft focus on purpose, that softness is the style, not a
  fault.

## Logos

- **The account's logo** goes in the header only, beside the seller's (on the kinds of page that name
  the account, `page-kinds`). It is in `brand/brand.md` under "The account's logo". If it is missing
  or does not fit, call `fetch_logo` with the account's website domain and look at what it finds. If
  it finds nothing, hide the account's logo and say so in your report.
- **Choose the right version**: the full logo where the header has room; the light or dark version
  that stays readable on its background.
- **When unsure** it is the right company's logo (an ambiguous name, a sub-brand), leave it out and
  say so in your report.
- **Never draw, recolour, retype or generate a logo**, the seller's or the account's. Logos are shown
  whole.
- **The seller's logo** is not repeated around the page as decoration or proof.
- **A row of the seller's customer logos** must not suggest the account is already a customer. Leave
  out a logo of a company with the same or a similar name as the account, or one that could be its
  parent or subsidiary. A logo wall sits beside the argument; it never replaces it.

## Motion and video

The seller's motion is part of its design. Keep it, in three steps:
1. **Keep the clone's own motion as captured**: videos, loops, animations.
2. **When a section is rebuilt, or its motion did not survive capture**, rebuild it so it moves the
   way the seller's does: a switcher, a carousel, tabs, something that appears as the visitor scrolls
   (`rebuilding-a-section`, and `making-a-section-interactive` when you have it). A switcher is one
   linked component: each control changes its own image and text.
3. **Otherwise, a clean still version**: no dead space, no controls that do nothing, nothing left
   hidden. It does not apply to ambient video, which keeps the clone.

- **No invented motion.** Brand sections and sections of your own move only through the brand's
  motion classes (`brand/brand.md`, Motion), or to rebuild something the seller's site actually does.
- **Anything that moves on its own has a still state** (a loop, a carousel that advances by itself,
  something that appears as the visitor scrolls): for visitors who ask for less motion, it stops
  moving and all its content is visible. A control the visitor drives (tabs, a switcher, an accordion)
  is not motion: it may show one item at a time for everyone. No sound ever plays on its own.
- **Video**: ambient video that belongs to the seller's design (background loops, animated heroes,
  GIFs) stays as the clone carries it; it is never removed on purpose or swapped for a still image.
  A section you write or rebuild cannot play a video yet, so when a section's video matters, keep
  that clone as it is rather than rebuilding it. An embedded press-play video (a video player, a brand film) comes
  out, unless it is a short demo that directly shows what the page argues. When a video stays, the
  headline still states the promise, and the page reads fully without pressing play.
- **Say what you could not check.** `render_page` gives still pictures, so never claim from a
  screenshot that motion works; say in your report that you could not check it.
