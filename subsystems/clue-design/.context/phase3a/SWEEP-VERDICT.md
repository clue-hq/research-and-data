# Phase 3a — imagery baseline sweep verdict (2026-07-05, tag `3a-sweep`)

12 briefs targeted (10 new + canary + prior customer_story under `3a-flow-fix`), all live
(deepagent, Opus 4.8 via OpenRouter; image = gemini-3-pro-image; judge = Opus 4.8 vision,
shared IMAGERY_RUBRIC). Captures: `apps/agent_runtime/evaluation/imagery_fixtures/<brief>/3a-sweep/`.
Skipped by user's 10-brief scope: platform_pillars (SHIP in June DoD), hiring_role, big_stat,
pricing_packaging (decline-discipline duplicates).

## Scoreboard — 7 SHIP / 5 REDO (accept 58%)

| Brief | Expected | Tier | wm | Failure mode |
|---|---|---|---|---|
| gtm_conf_poster_photo (canary) | photo | **SHIP** | 3.00 | — (former 1.37M-token crash) |
| founders_dinner_poster_photo | photo | **SHIP** | 3.00 | — (other poster class) |
| customer_story_linkedin_photo | photo | **SHIP** | 2.87 | — (former LUMV0100 crash) |
| collab_feature_social_illustration | icon | **SHIP** | 3.00 | — (library glyphs, correct) |
| gtm_conf_social_none | none | **SHIP** | 3.00 | — declined imagery correctly |
| qbr_business_review_none | none | **SHIP** | 3.00 | — declined imagery correctly |
| pipeline_data_slide_none | none | **SHIP** | 3.00 | — declined; crashed 1st try (record_gap bug, fixed dd5216e) |
| product_feature_card_photo | photo | REDO | 2.80 | **baked-in text**: generated screen shows garbled UI/specimen text; in-loop reviewer accepted (geometry-only), judge caught it |
| how_it_works_onepager_icons | icon | REDO | 2.62 | **icons unused**: numbered circles instead of icon row |
| security_trust_linkedin_icons | icon | REDO | 2.49 | **icons unused**: pure text grid; library also lacks domain icons (shield/lock) |
| gtm_conf_deck_band | photo | REDO | 1.72 | **decide-miss**: zero image events in trace; type-only slide where image band expected |
| testimonial_portrait_photo | photo | REDO | 1.33 | **decide-miss**: no portrait generated for portrait-frame role |

## What the sweep proves

1. **Context fix live-proven** (c30c121): both former blowup briefs complete and SHIP at 3.0.
2. **Primary photo roles work**: full-bleed hero+scrim and image-band+type-panel = 3/3 SHIP,
   legibility 3 everywhere → the scrim IDIOM is sufficient. **Step-10 scrim grammar sugar: closed, skip.**
3. **Decline discipline is perfect**: 3/3 none-briefs SHIP at 3.0. The "default to NO image" brief
   works — in fact it over-fires (see 4).
4. **Decide-miss on secondary photo roles** (image_band_clean_type on decks, portrait_frame_pull_quote):
   the coordinator never generates. `knowledge/images/decide` + step-3 prompt bias ("Default to NO")
   suppresses legitimate secondary roles. 3a's exit criterion — "reaches for imagery when the brief
   calls for it" — is NOT yet met for these roles. → Fix is prompt/knowledge-level.
5. **Icon adoption fails 2/3**: authors substitute numbered circles/text instead of `svg(icon:…)`;
   the curated library (bolt/check/plus/arrow-down + a few) lacks domain icons (shield, lock, steps).
   Step-8 residue: knowledge push + library expansion.
6. **In-loop vision gap now has hard evidence**: product_feature_card — excellent composition, but
   the generated image carries garbled baked-in text; the geometry-only in-loop reviewer accepted
   it and only the offline judge rejected. Cheapest remedy when scheduled: run `judge_imagery`
   (already has real vision) as a mid-loop check after generation. Slot per discussion: 3c.

## Recommendations (pending user go-ahead)

- **(a) Decide-tuning for secondary roles — do inside 3a** (it's the exit criterion): teach
  decide.md + coordinator step 3 the two secondary roles (image band on title/deck surfaces,
  portrait frame for testimonials) as legitimate "yes" cases; re-run the 2 failed briefs (~2 runs).
- **(b) Icon adoption + library expansion — 3a-adjacent fast-follow** (Step-8 residue).
- **(c) Mid-loop vision check — 3c**, now evidence-backed.
- **Quality-loop generate path: keep deepagent as the imagery path** (proven e2e); leave
  quality-loop DSL-only; revisit only if the quality loop becomes the primary runtime.
