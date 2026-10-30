# Richer reference ads for the ad agent — 2026-10-30/31

Branch `fix/design-reference-ads` (from main `bc8cc30dc`), local commits only, not pushed.
Spec `docs/superpowers/specs/2026-10-30-design-reference-ads-design.md`; plan
`docs/superpowers/plans/2026-10-30-design-reference-ads.md`.

## What changed
- Only code labels ads: harvested (Adyntel, has a `design_ad_creative` row) → "ad"; the
  describe model can no longer answer "ad"; an old model-"ad" shows as "other"; a person's
  type always wins (`clue_design.asset_context.effective_context`).
- No style groups, no auto-attached reference ads. The card is prose only (`style_groups` stays
  in the stored payload, always empty).
- The ad agent gets every brand ad (harvested + person-marked) by value
  (`ad_runtime.context_brand_ads` → `config.brand_ads`) as a table at the top of
  `ad-assets.md` (headline, post copy ≤200 chars, title, short description, size). An
  un-overridden "ad" outside the lane is still listed as a LinkedIn ad.
- The solo prompt now says (founder-approved): "Read {workspace}/ad-assets.md with your initial
  gather. It lists every ad this brand has published or marked as an ad; open the ones that fit
  this request with `view("asset:<id>")`. Published-ad context is advisory source data."
  This supersedes harness-alignment I7's "don't read ad-assets.md" for the solo agent.
- Harvest route defaults 50 creatives / 8 pages. Pre-generation: one background from each of up
  to 4 different ads (deduped by image digest), the ad attached as the reference, approved
  "imitate that ad's background" prompt.
- A list that can't be built costs the list, never the turn; a session's stale `ad-assets.md`
  is removed when no ads remain.

## Verification
- 20 touched test files green except `test_fast_loop.py::test_flag_on_author_toolset_includes_render`
  (fails identically on base — pre-existing). Also pre-existing on base:
  `test_ingestion_ui_api.py::test_pipeline_ingested_assets_get_db_records`.
- Live (trenton, Garner Health ws_c080123a…): `/assets/descriptions` 47/47 harvested → Ad, 2
  model-"ad" → Other. Turn after the prompt fix: run_48ec81c3… read `ad-assets.md` in its first
  gather, viewed 2 listed ads, accepted in 3m06s (31 LLM calls, 2.62M input tokens).

## Open
- The agent opened only 2 of 47 listed ads, and cropped one published ad for its logo and ground.
- Not checked: the Assets page UI (founder sign-in); a fresh onboarding to see 50 ads + per-ad
  backgrounds (spends Adyntel credits — needs a go).
- Design-agent spend is not recorded in Postgres, so no dollar figure for the live turns.
