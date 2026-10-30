# Richer reference ads for the ad agent — design

Date: 2026-10-30. Branch: `fix/design-reference-ads` (from `main` at `bc8cc30dc`).
Status: approved by the founder 2026-10-30.

## 1. Why

The ad (scene) design agent's reference ads feel thin and repetitive. Today:

- Automatic onboarding asks Adyntel for up to **50** ads over 8 pages
  (`CLUE_BRAND_AD_ASSETS_AUTO_MAX_CREATIVES=50`, `_AUTO_MAX_PAGES=8`); the design API's own
  onboarding route defaults to **15** over 3 pages (`lumen_api/models.py:609-610`, and
  `harvest.py` `DEFAULT_MAX_CREATIVES = 15`).
- A vision model sorts them into at most **6 style groups** (`distill.py` `MAX_STYLE_GROUPS`).
- Each ad turn, a small text-only model call picks ONE group from its name, and at most **4**
  of that group's ads are attached to the turn as reference images
  (`ad_runtime.py` `select_reference_asset_ids` / `choose_style_group`, `AUTO_REFERENCE_MAX`).
  With 15 ads in 6 groups a group often holds 1–3 ads, so the agent keeps seeing the same few.
- The describing step that analyses every library asset may answer `creative_type = "ad"`
  for anything, with no definition of an ad, so the library shows a loose "Ad" type.
- When a person uploads an image to the brand's asset library and sets its type to "Ad"
  (stored in `design_asset_description.overrides_json.creative_type`), nothing in the ad
  agent's reference step reads it.

What the founder wants: the agent sees the brand's whole set of ads, chooses which to look at
itself, and doesn't keep repeating the same handful.

## 2. Goals

1. **No style groups.** The ad style card keeps its prose description of how the brand's ads
   look, but no longer sorts ads into groups, and no group names reach the agent.
2. **No automatic attaching.** No ads are attached to a turn by the system. The agent gets the
   full list of the brand's ads and opens the ones it wants. Ads the person attaches
   themselves still work exactly as today ("manual references always win" stays).
3. **The full list, searchable.** The agent sees every ad of the brand in one list, each with:
   its asset id, where it came from (LinkedIn ad, or marked as an ad by the person), the ad's
   headline and post copy when known, its title and one-line description, and its size. It
   can open any ad with `view("asset:<id>")`, which already returns the full per-ad analysis,
   and `search_assets` finds ads too.
4. **Each ad keeps its own layout description.** Every harvested ad keeps the per-ad analysis
   it already gets at ingestion (composition, text read from the image, typography, logo
   placement, visual hierarchy, design patterns, messaging, tone, CTA). Nothing about that
   analysis is removed. (Founder, 2026-10-30.)
5. **Only code says "ad".**
   - Every asset that came from the Adyntel harvest is an ad, set by code.
   - The describing model may no longer answer "ad".
   - A person's own choice of type in the library still counts: a person can mark any asset
     as "Ad", and can mark a harvested ad as something else.
   - Assets the model already labelled "ad" that did not come from the harvest are shown as
     "Other" from now on.
6. **The person's "Ad" assets join the list** in goal 3.
7. **50 ads per harvest** (founder, 2026-10-30: "50 is better").
8. **No frontend change.** On the brand-context Assets page, choosing type "Ad" shows exactly
   the ads harvested from Adyntel plus the assets a person marked "Ad" (founder, 2026-10-30).
   This falls out of §5.2: the page already filters on the `creative_type` the backend
   returns.
9. **3–4 ready-made backgrounds per brand, each made from a different one of the brand's
   ads** (founder, 2026-10-30), replacing two per style group.

## 3. Non-goals

- The site and web agents. They have no ad list today and get none here.
- The payer-name question (PeopleDataLabs has no payer field; the founder's 4th observation
  is still to come and is not part of this document).
- Video, carousel and document ads (still out of scope, as today).
- A per-session "already used" tracker. The agent's own session memory already records which
  ads it opened in earlier turns; the full list is what lets it choose different ones.
  (My call — see §7.)

## 4. Anti-goals

- The agent's opening context must not swell with 50 images. The list is text; pixels are
  opened one at a time on demand.
- A turn must never fail because the ad list can't be read. An unreadable list means the turn
  runs without it, as a turn with no harvest does today.
- No second definition of "ad". One rule, in one place, decides an asset's type.

## 5. How it works (decided)

### 5.1 Harvest
Automatic onboarding keeps its 50 ads over 8 pages (`CLUE_BRAND_AD_ASSETS_AUTO_*`, unchanged).
The design API route's defaults (`models.py` `max_creatives`/`max_pages`, and `harvest.py`
`DEFAULT_MAX_CREATIVES`/`DEFAULT_MAX_PAGES`, kept equal) move to the same **50 / 8** (~8
Adyntel credits). Only new or re-run onboardings change; existing brands keep what they have
until harvested again.

### 5.2 One rule for "ad"
In `clue_design/asset_context.py` `effective_context` (the one read seam every reader already
goes through):

| Situation | Shown type |
|---|---|
| The person set a type | the person's type (unchanged rule) |
| No person's type, and the asset came from the harvest | `ad` |
| No person's type, the model said `ad`, and the asset didn't come from the harvest | `other` |
| Otherwise | the model's type (unchanged) |

"Came from the harvest" means **the asset has a `design_ad_creative` row** in its workspace —
the table the Adyntel harvest writes, whatever the job's options. NOT the `linkedin_ad` source
occurrence: that is only written when an ad is analysed (since 2026-09-21, `9cc82d08d`), so ads
harvested earlier or by a `harvest_only` job lack it. `descriptions.get_many` (the one read
every caller, including the Assets page, goes through) checks membership in the same query and
hands it to `effective_context`. A harvested asset with no description row at all still comes
back with type `ad` (an otherwise empty context), so the Assets page's "Ad" filter shows it.
Those older ads keep no per-ad written analysis — founder, 2026-10-30: leave them as they are.

Doing it at the read seam re-labels every existing asset without a migration and without
re-running any model. `classification_origin` stays as today (`human` only when the person set
it). Separately, the describing step (`describe.py` system prompt and response schema) no
longer offers `ad` as an answer: the model's allowed types are the person's types minus `ad`.
The person's override type list (`AssetOverrides.creative_type`, the frontend's
`CreativeTypeSchema`) keeps `ad`.

### 5.3 Ad style card without groups
The distiller (`distill.py`) still writes the card's prose (the brand's ads described in the
model's own words), now over up to 50 ads (the existing 100-creative distil cap stays), but asks for no groups and stores none. Cards
already stored with groups keep working: everything that renders a card for the agent
(`frame.py`, `workspace.py` `render_ad_dna_card_text`) stops printing group names, so old
cards need no re-distilling.

### 5.4 No auto-attach
`select_reference_asset_ids`, `choose_style_group` and `resolve_auto_ad_references`
(`main.py`) are removed, along with the turn path that calls them. Turns where the person
attached references are unchanged. Turns with no attachments now carry no reference images,
and `references.md` doesn't appear for them (it appears only when references ride the turn,
as today).

### 5.5 The agent's ad list
A new section, "The brand's ads", at the top of the existing `ad-assets.md` (which already holds
the card and the backgrounds and which the prompt already points to), written by
`scaffold_workspace` whenever there is at least one ad. A separate `ads.md` beside it would be
easy to confuse with it. One row per ad:

| asset id | from | headline | post copy (first ~200 chars) | title | short description | size |

The short description is a sentence or two saying what the ad looks like, taken from the start
of the ad's own description (founder, 2026-10-30: "add a slight description of each ad"). An ad
with no description says so; the full analysis is always one `view` away.

- **Harvested ads:** the turn's ad lane — every `design_ad_creative` row of the workspace, as
  `read_ad_lane` reads today (the table has no brand column; automatic harvests run before a
  brand kit exists). Headline and copy come from the creative row. The frozen lane fleet
  turns carry (`lane_to_frozen`; frozen at `design_leg_wiring.py` and `main.py:~3532`) grows
  to hold each creative's headline, copy and created time, with the legacy shape still read.
  No cap beyond the lane's existing `CREATIVE_SCAN = 200`.
- **The person's ads:** independent of `LUMEN_BRAND_AD_ASSETS` (that flag gates the harvest
  lane, not the person's own choice). Every ready asset in the turn's pinned library snapshot whose shown
  type (§5.2) is `ad` and that isn't already in the harvested set. Headline/copy are blank.
- Ordered newest first. Assets that aren't ready or have no preview are left out, the same
  rule `source_assets.json` uses.
- Everything in the list is also in the library the agent can `view` and `search_assets`,
  so the file only lists; it never carries pixels.

`search_assets` already searches each asset's `creative_type`, so a query for "ad" finds them;
no change there beyond §5.2 making the type trustworthy.

### 5.6 What the agent is told (heading approved by the founder 2026-10-30)
Draft heading for the new section of `ad-assets.md`:

> # The brand's ads
> These are the brand's own published ads and any images the team marked as ads — N in all.
> Open any of them with `view("asset:<id>")` to see the picture and its full description
> (layout, text, typography, hierarchy). Look through several before you design, and pick
> ones that fit this request; you don't need to use the same ones as last time.

The ads the agent opens are inspiration it chose, not attached references: they do not switch on
the reference path (`references.md`, the "References are present…" block, prompts.py:~1382).
The `reference-conditioned-ads` skill's guidance on learning from brand ads is pointed at this
list instead. (My call.) The places that today tell the agent about auto-attached references or style groups
(`prompts.py` around the reference lines, `frame.py` card prose,
`knowledge_docs/views/scene/skills/reference-conditioned-ads/SKILL.md`) get matching one-line
changes. Each change is shown to the founder as text before it's committed.

## 6. Ready-made backgrounds (founder, 2026-10-30)

`pregenerate.py` stops making two backgrounds per style group and instead makes **one
background from each of up to 4 different ads** of the brand (3–4 when the brand has that many;
one per ad when it has fewer):

- Which ads: the 4 most recent harvested ads with a usable image. (My call.)
- Each generation gets exactly ONE reference image — its own ad — so the four come out
  different, instead of every generation seeing the same 4 ads.
- Shape: the closest of the existing shapes (16:9, 1:1, 4:5) to that ad's own aspect ratio.
  (My call.)
- The link column `visual_system` (which held the group name) holds the source ad's
  creative id; no migration.
- The prompt (approved by the founder 2026-10-30; today's text in §6.1):

> A {shape} background for {brand}'s advertising. The attached image is one of the brand's
> published ads. Imitate that ad's background: its colours, gradients, textures, shapes,
> light and mood. Leave out everything placed on top of it: its words, logo, people, product
> shots and screenshots. The brand's published ads, described: {card prose, first 900
> characters}.
> Produce a background image only. No text of any kind, no letters, no numbers, no wordmark,
> no logo, no watermark, no user interface.

(Founder, 2026-10-30: imitate the attached ad's background; drop "no charts, no people and no
faces" and "leave the composition open in the middle" from the end. `BACKGROUND_ONLY_CLAUSE`
is used only here.)

### 6.1 Today's prompt (for comparison)
Sent to the image model with up to 4 of the brand's ads as reference images:

> A {wide ground | square ground} for {brand}'s advertising. The brand's published ads,
> described: {card prose, first 900 characters} This ground belongs to the brand's
> '{style group name}' style group. Produce a background image only. No text of any kind, no
> letters, no numbers, no wordmark, no logo, no watermark, no user interface, no charts, no
> people and no faces. Leave the composition open in the middle so type and a card can be
> laid over it later.

## 7. Calls I made (check these)

- Model-labelled non-harvest "ad"s show as **Other** (not "Unknown").
- A person can mark a harvested ad as something else, and it then leaves the list.
- No "already used" tracking; the full list plus session memory is the answer to repetition.
- The ad list covers the workspace's harvested ads (as today; no brand attribution exists for
  them) plus every library asset the person marked "Ad".
- The list lives in `ad-assets.md`, not a new file.
- "From the harvest" means having a `design_ad_creative` row.
- The person's "Ad" assets are listed even when `LUMEN_BRAND_AD_ASSETS` is off.
- Ads the agent opens don't switch on the attached-references path.
- Existing brands are not re-harvested automatically to reach 50, and existing backgrounds
  stay in the library.

## 8. Done looks like

- A new onboarding keeps up to 50 ads; its card has prose and no groups; it makes 3–4
  backgrounds, each from a different ad.
- On the Assets page, type "Ad" shows the harvested ads (including ones with no description)
  and the person-marked ones, and nothing else — with no frontend change.
- An ad turn with no attachments has no reference images and an `ad-assets.md` listing every ad of
  the brand with headline/copy; `view("asset:<id>")` on one shows the per-ad analysis.
- An image uploaded to the library and set to "Ad" appears in the list on the next turn.
- A website image the model once called "ad" shows as "Other" in the library and isn't in
  the list; a harvested ad shows as "Ad" whatever the model said.
- A turn whose person attached references behaves as today.
- A live check on the trenton stack: one ad turn on a harvested brand, the trace shows the
  agent opening several ads from the list.
