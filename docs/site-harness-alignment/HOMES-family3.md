# Family 3 · Step 3 — one home per rule (draft for founder review)

Homes as before (S1): **BASE** · **CASE** · **IMAGERY** (the family-3 aspect skill: today's `images-and-logos`,
rewritten and widened to imagery and media) · **COPY**/**EVIDENCE** (family 2) · **REVIEW** (family 5) · **MECH**
(`building-with-puck`, `writing-a-section`, `rebuilding-a-section`, `making-a-section-interactive`) · **SYS** ·
**TOOLS** · **CODE** (workspace and site-kit text the agent reads) · **PRODUCT** (new platform work, not a skill).

Ploy appears only where the founder asked (M5), rewritten in our own words.

## A. Each ruling's home

| Ruling | Home | Notes |
|---|---|---|
| M1.1 `brand/brand.md` motion text: keep the seller's motion | CODE (`site-kit/src/catalog.ts` `motionSection`) | "Do not imitate them" and "write no transition or animation of your own" go. |
| M1.2 the three-step ladder | IMAGERY (the ladder) + MECH (`making-a-section-interactive`: rebuilding the seller's motion; `rebuilding-a-section`: keep the original's video) | |
| M1.3 no invented motion | IMAGERY + MECH (`writing-a-section`, `making-a-section-interactive`) | |
| M1.4 a still state for every moving part; no sound | MECH (`making-a-section-interactive`) + IMAGERY (video) | |
| M1.5 honest reporting on motion | REVIEW (family 5) | |
| M1.6 clone cards list videos and motion; motion text rewritten | CODE (`catalog.ts` `cloneFile`, `motionSection`) | Same item as R11.4. |
| M1.7 carousel brand section (then tabs) | PRODUCT | When built, a new ladder step and a line in `catalog/sections.md`. |
| M1.8 strong section writing | MECH (family 6) + trials | |
| M2.1–M2.2 reuse first; follow the seller's imagery type | IMAGERY | |
| M2.3 the "must not show" line removed | IMAGERY | Deleted, not rewritten. |
| M2.4 never presented as the account's; never imitate its logo or replicate its things | IMAGERY | |
| M2.5–M2.7 prompt craft, look and retry, text on the calm area | IMAGERY | |
| M2.8 nothing generated presented as real | IMAGERY | Replaces "Anything real… Never generate them." |
| M3.1–M3.3 keep the seller's image staging | IMAGERY | |
| M4.0 the two existing lines stand | IMAGERY | |
| M4.1 a screenshot shows the product, not a result | IMAGERY (+ COPY's claim rules decide the claims) | |
| M4.2 never alter a screenshot | IMAGERY | |
| M4.3 pairing each screenshot with what it shows | CASE (product campaign) | |
| M4.6 the interface stays readable on a phone | IMAGERY + REVIEW | |
| M5.1 one image list | IMAGERY + MECH (`building-with-puck` brand sections and image slots, `writing-a-section` props) + CODE (`brand/brand.md` heading) + TOOLS (`view_asset`, `search_assets` stay as they are) | |
| M5.2–M5.5 authoritative source first; real job only; diagram not fake screen; search well | IMAGERY | |
| M6.1–M6.2 never enlarge past natural size; search for sharper; blur/bokeh exception | IMAGERY | |
| M6.3 tools report width × height | CODE (`site/tools.py` `view_asset`, `search_assets`) + TOOLS (descriptions mention it) | |
| M7.1–M7.5 logos | IMAGERY (+ MECH header lines for the seller's logo) | Placement stays R6 (CASE). |

## B. Today's site lines: where each goes

| Row | Line (short) | Fate |
|---|---|---|
| B1-04 | `view_asset` description | Keep; add that it reports size (M6.3). |
| B1-05 | `search_assets` description | Keep; add that results carry size (M6.3). |
| B1-06 | `generate_image` description | Keep. |
| D1-59 | Keep the clone's layout, images and rhythm | → IMAGERY (M3) and family 4 (layout). |
| D2-16, D2-17, D6-04 | Images only from brand.md or generated | Rewrite to the one list (M5.1). |
| D3-04, D3-07 | Brand images in brand.md; other images via search | → IMAGERY, merged into the one list (M5.1). |
| D3-05 | "Anything real… Never generate them" | Rewrite: presented-as-real (M2.8). |
| D3-06 | Image fits the words; screenshot shows what the copy says | Keep (IMAGERY, M4.0). |
| D3-08 | Generate only when needed and nothing fits | Keep (IMAGERY, M2.1). |
| D3-09 | Scene or mood; the "must not show" list | Rewrite: follow the seller's imagery type (M2.2); the list is deleted (M2.3); keep the account clause (M2.4). |
| D3-10 | Style references; one retry or leave it out | Keep and widen with the craft (M2.5–M2.6). |
| D3-11 | No image beats a weak image | Keep (IMAGERY, M5.5). |
| D3-12, D3-13 | fetch_logo; skip look-alikes | Keep (IMAGERY, M7.1). |
| D4-05, D4-06 | No broken image; same image not twice | → REVIEW (family 5). |
| D5-01 | Video → closest brand image | Rewrite: keep the original's video (R11.1, M1.2). |
| D6-05 | Seller's logo via kit.Image | Keep (MECH). |
| D7-01…D7-03 | Interactive sections; stay on the brand | Keep; add rebuilding the seller's motion, still state, no sound (M1.2–M1.4). |
| H3-02 | Clone card lists images only | CODE: list videos and motion too (M1.6). |
| H4-01 | Sections take motion from the brand | Keep (CODE). |
| H4-02 | Logos shown whole | Keep (CODE). |
| H4-03 | "the only images and logos a page may use" | CODE rewrite (M5.1). |
| H4-04, H4-05, H4-06 | Motion section; "Do not imitate them" | CODE rewrite (M1.1). |
| H4-07 | The account's logo (header only) | Keep (CODE; R6). |

## C. What this does to the skill set

- **IMAGERY** — today's `images-and-logos`, rewritten and widened (working name `imagery-and-media`): the one image
  list and source order, real job only, keeping the seller's staging, generation (when, what, craft), screenshots,
  sharpness, logos, the seller's motion and video (the ladder, still states). Built from the site skill, the
  legacy `web-media-composition`, `web-product-story`, `web-motion-fidelity` and the site-relevant craft of
  `generative-imagery`.
- **MECH**: `making-a-section-interactive` gains rebuilding the seller's motion; `rebuilding-a-section` keeps
  the original's video; image lines in `building-with-puck` and `writing-a-section` follow M5.1.
- **CODE**: `brand/brand.md` motion and asset text; clone cards list videos; image tools report sizes.
- **PRODUCT**: a carousel brand section, then tabs (M1.7).
