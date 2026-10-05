# Brand imagery for scene ads — findings and trial plan

Date: 2026-10-05. Branch `design/linkedin-ad-skill-testing` (nashville lane). Status: findings
recorded, trials not started, **no product change made**. Every proposal below is a proposal until
a trial or a founder ruling settles it. Skill and prompt wording in §5 needs founder review before
anything is written into a skill.

Evidence comes from three Conduit → Atrium Hospitality LinkedIn ad runs (run 2
`run_37abd7d6…`, run 3 `run_fac28447…`, run 4 `run_bfcb80e9…`), Conduit's brand-kit ingestion of
2026-10-04 23:33, and the lane database `clue_nashville`.

## 1. Founder direction (2026-10-05)

- The design agent decides and generates imagery itself at runtime. Pre-generating backgrounds at
  ingestion is probably unnecessary: give the agent the context and a usable library instead.
- The image prompts the agent writes must not add detail nobody asked for and no brand reference
  shows (yellow lights, an unbranded hotel front desk).
- Sort this out with standalone trials first, then change the product.

## 2. Findings

### 2.1 The asset library and its descriptions

- Conduit's library holds 604 assets: 566 scraped from the website, 16 harvested ads, 14
  generated, 8 from Brandfetch. By type: 124 photos, 120 logos (mostly partner logos), 98 product
  screenshots, 11 backgrounds. Duplicates exist (the website hero background is stored twice, at
  1920 and 2048 wide: `asset_ing_b83ad64b…`, `asset_ing_4c652b55…`).
- Each asset's stored analysis averages ~6,900 characters (max ~17,000). Most of it is caveats,
  uncertainty lists, rights notes and all-caps restatement of the pixels.
- The facts that decide selection — does it have text, UI, people baked in; can it sit behind
  type; is it the brand's ad look or a website photo — are buried in prose, not stored as fields.
- Tags are too broad to filter on: 239 of 506 described assets carry `section_background`.

### 2.2 What the design agent sees, and how it searches

| Surface | What it carries |
|---|---|
| `source_assets.json` (opening index) | 530 entries, each a title + one description paragraph. No type, roles, avoid-when |
| `search_assets(q)` | Keyword match over title/description/usage/type/roles. No filters. Returns those fields |
| `view("asset:<id>")` | Pixels + the full analysis, including avoid-when, placement, observed colours |

- The scene prompt and scene skills never mention `search_assets`. (The web agent's prompt does:
  "search the real assets before asking for a generated image".)
- Run 3 searched 5 times, 4 of them for logos. Run 2 searched once, for a logo. Neither surfaced
  the best background in the library, `asset_ing_4c652b55…` (clean text-free blur photo, tagged
  section background + hero image, bytes present).

### 2.3 The "pick a look" call

- Before the agent starts, the design API (`main.resolve_auto_ad_references` →
  `ad_runtime.select_reference_asset_ids`) makes one Grok text call: the first 1,200 characters of
  the turn prompt plus the style-group names, "pick the one look". The chosen group's ads become
  the turn's reference attachments; on failure, the 4 newest ads.
- The 1,200 characters are the delegation brief's opening: account, ICP and product boilerplate,
  never what the ad should look like. The pick is close to a guess.
- Run 4: the call timed out (20 s), the fallback ads failed to load
  (`auto_ad_references_unresolvable`), the turn ran with 0 references, and nothing told the agent.
- The agent already sees every harvested ad, can view them, and can choose up to 4 references with
  roles itself. The separate call duplicates a decision the agent is better placed to make.

### 2.4 The ad-style card and style groups

- Grok 4.5 sees up to 12 of the harvested ads (Conduit: 12 of 16) and writes one description of
  all of them, plus named style groups with their ad ids.
- Conduit's card has 6 groups of exactly one ad each; 10 of the 16 ads belong to no group, and a
  real 3-ad look ("blurred outdoor scene, Integration label, centred logo card") has no group.
  `distill.py` keeps at most 6 groups and drops the rest silently.
- Nothing checks that a group is a real cluster, or that every ad belongs to one.
- `ad-assets.md` (written into the agent's workspace each turn) carries the description, the group
  names (not their ad ids) and the pre-generated backgrounds. A listed id is checked to be in the
  library and not archived; its bytes are not checked.

### 2.5 Pre-generation

- 12 backgrounds = 6 groups × square/wide. Every call got the same 4 references (the first 4
  harvested ads, full of text and UI), the same first 900 characters of the description (cut
  mid-word), the group's name and a fixed "background only, no text/UI/charts/people" clause.
- The prompt forbids everything the references show except colour, so all 12 came out as one
  generic pastel blur. Cost ≈ $1.10 per brand ingestion.
- Same faults for every seller (checked on Insight Health AI in the dubai lane: one of its 4 looks
  falls entirely after the 900-character cut).

### 2.6 Runtime image prompts: where the yellow light and the hotel desk came from

- Run 3 and run 2 used `conduit.ai/og-image.jpg` as the treatment reference. Its description reads
  "warm yellow-green and olive shapes… several soft circular bokeh highlights"; it is a website
  image tagged `reference_only`, not Conduit's ad look (pastel pink/purple/blue blur).
- The agent then amplified it: "olive, yellow-green and amber bokeh, with a few soft circular
  highlights" (run 3), "warm olive and pale gold… gentle circular bokeh" (run 2).
- "Quiet hotel front desk at first light" (run 3) and "an unbranded hotel interior" (run 2, with a
  "Hotel Lobby Interior" photo as composition reference) are the agent's own invention: the target
  is a hotel company. No Conduit asset shows a hotel, and no skill asks for the target's world.
- Today's guidance (`knowledge/scene/references.md`) asks the agent to "describe material, edge
  softness/blur, tonal range, depth and texture scale as they appear in the sources". It has one
  narrow guard ("a new subject does not authorize invented lighting or materials"). Nothing says the
  treatment must come from the brand's own ads, nor forbids adding a subject.

### 2.7 Quiet failures

- Run 3: `asset_ing_b83ad64b…` was refused as "no materialized bytes" although its bytes are on
  disk now. Cause not yet traced (the selected-reference path reads the record's preview digest).
- `auto_ad_references_unresolvable` swallows the exception without logging it.
- A failed reference costs the turn its conditioning without the agent being told.

## 3. Proposals (to be settled by trials)

**Remove**
- The pre-turn "pick a look" call.
- The 530-line asset index in the opening context.
- Pre-generation at ingestion (step, `asset_gen_*` listing in `ad-assets.md`, generation-ledger
  wiring) — if T4 confirms runtime generation does as well or better.

**Change**
- Per-asset analysis → a few structured fields plus one or two plain sentences; the long analysis
  stays available through `view` or is trimmed hard.
- Library → separate the brand-look collection (the brand's ads, text-free brand photos) from the
  rest of the website scrape; dedupe at ingestion.
- Style groups → cluster the brand's ads by visual similarity first, then let the model name and
  describe each cluster; `ad-assets.md` lists each look with its ad ids.

**Add**
- Structured fields: collection, kind, has_text, has_ui, has_people, orientation, colour family.
- Visual embeddings (e.g. SigLIP 2) in Postgres (`vector` is already installed), fused with
  keyword search (reciprocal rank fusion), behind `search_assets` with filters.
- Search results returned as one contact-sheet image of 8–12 labelled thumbnails.
- A short opening inventory ("Brand ads: 16 in N looks; text-free brand photos: …; logos: …").
- "Search the library before generating" as an explicit step of the scene workflow.
- A loud message to the agent whenever a reference fails to load.

## 4. Trials

All trials are standalone scripts under the session scratchpad or a `trials/` folder, reading the
lane DB only. Nothing in the product changes. Results go into §7 of this doc.

| # | Trial | Method | Measure | Cost |
|---|---|---|---|---|
| T1 | Search bake-off | ~20 real queries with the right assets labelled once by the founder; compare today's keyword search, filters + keywords, SigLIP 2 embeddings, hybrid | right asset in top 5; latency | ≈ $0 |
| T2 | Description diet | Re-describe 40 assets with a short structured prompt (DeepSeek v4.1 Flash vs Grok 4.5); rerun T1 on the short version | T1 score vs today; cost per asset | < $1 |
| T3 | Style groups | Cluster Conduit's 16 ads by embedding; compare with Grok's 6 single-ad groups | do real looks come out | ≈ $0 |
| T4 | Runtime generation done well | For the run-3/run-4 brief, generate backgrounds from (a) today's agent prompt + og-image, (b) the brand's ads of one look as treatment + a disciplined prompt (§5), (c) (b) + a text-free brand photo. 3 images each, judged side by side by the founder | on-brand, no invented detail | ≈ $1–2 |
| T5 | Prompt discipline | Give Grok 4.7 the run-3 brief, the chosen references and today's vs §5 guidance; have it write only the image prompt, 5 times each. Count details not traceable to a reference or the request | invented details per prompt | < $1 |
| T6 | Agent selection | Same brief, the design agent with (a) today's index, (b) inventory + filtered contact-sheet search. Compare what it picks | right references chosen | a few $ |

Order: T1 and T5 first (cheap, decide search and prompting), then T4, then T2/T3, then T6.

## 5. Image prompt discipline — proposed wording (for founder review, not yet in any skill)

Proposed to replace the "Specify the component…" paragraph of `knowledge/scene/references.md` and
to be pointed at from the `brand-imagery` and `generative-imagery` skills:

> Write the image prompt from what you saw, not from what you imagine.
>
> Every visual quality you ask for — colour, light, material, blur, texture, subject — must come
> from a reference you selected and viewed, or from what the person asked for. Describe it the way
> it looks in that reference.
>
> For an ad, take the treatment from the brand's own published ads. A website photo or a social
> preview image is a different look; use it only if the brand's ads use that look too.
>
> Do not add a subject, a place, an object or a light source that none of your references show.
> The target company's industry is not a reason to put its world into the image: a hotel company
> does not need a hotel lobby or a front desk behind the copy.
>
> Keep the prompt short: what the component is, its shape, where the copy will sit, and the
> treatment you are keeping. Leave out everything else.
>
> If no reference shows the look you need, ask the person, or use a flat brand-colour ground.

## 6. Open questions for the founder

1. Should a scene ad ever carry imagery of the target's world (their hotels, their product), or is
   the background always the seller's look? (§5 assumes the seller's look.)
2. Is the brand-look collection curated by a person at onboarding, inferred by the model, or both?
3. Switch the ad-style describer (`LUMEN_AD_DNA_MODEL`) to `deepseek/deepseek-v4.1-flash` now, or
   wait for T2? (It reads images and supports structured output; $0.30/$1.20 per M tokens vs
   Grok 4.5's $2/$6.)

## 7. Trial results

None yet.

## Evidence index

- Run 3 image calls: session `dsess_76efab4f…/turns/run_fac28447…/logs/run.jsonl` (15:55:32, 15:55:39).
- Run 2 image call: `run_37abd7d6…/logs/run.jsonl` (14:36:24).
- Run 4 opening context: session `dsess_e5d5cc37…/workspace/ad-assets.md`; selector timeout in the
  ledger (`design.ad.style_group`, 10-05 05:25:18) and the worker log.
- Pre-generation code: `lumen_ingestion/ad_library/pregenerate.py`, `onboarding.py::_pregenerate`.
- Selector: `lumen_api/ad_runtime.py::select_reference_asset_ids`, `choose_style_group`.
- Agent image route: `lumen_agent/tools/substrate.py::generate_image`, `_produce_image_asset`;
  provider `lumen_api/image_provider.py` (OpenRouter Images API, `openai/gpt-image-2.5-flare`).
- Asset context: `subsystems/design/clue_design/asset_context.py::effective_context`;
  `main.asset_metadata_entry`; `tools/asset_catalog.py::rank_assets`.
