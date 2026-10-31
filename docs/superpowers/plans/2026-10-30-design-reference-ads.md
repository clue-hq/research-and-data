# Richer Reference Ads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The ad agent sees every ad the brand has (harvested from Adyntel plus any library asset a person marked "Ad") as one listed, openable set, and nothing is grouped or auto-attached; only code calls an asset an ad.

**Architecture:** One read-seam rule (`effective_context`, fed a `harvested` flag by `descriptions.get_many`) decides every asset's shown type, so the Assets page, the agent's library and search all agree with no frontend change. The ad lane stops grouping and auto-attaching; it carries each creative's headline/copy instead, and the API passes a by-value `brand_ads` list that the runtime renders at the top of `ad-assets.md`. Pre-generation makes one background per ad from up to 4 ads.

**Tech Stack:** Python 3 (FastAPI, SQLAlchemy async, pytest), Postgres.

**Spec:** `docs/superpowers/specs/2026-10-30-design-reference-ads-design.md`

## Global Constraints

- No frontend change (`apps/frontend/` untouched).
- No migration. `design_ad_pregenerated_asset.visual_system` keeps its name and now holds the source ad's creative id.
- "Came from the harvest" = the asset has a `design_ad_creative` row in its workspace. Nothing else.
- Shown-type rule, in this order: person's override → `ad` if harvested → `other` if the model said `ad` → the model's type.
- Harvest defaults: `max_creatives = 50`, `max_pages = 8` on the design API route and in `harvest.py` (automatic onboarding env `CLUE_BRAND_AD_ASSETS_AUTO_MAX_CREATIVES=50` / `_AUTO_MAX_PAGES=8` unchanged).
- No per-ad backfill of older ads' descriptions.
- Pre-generation: one background per ad, from the first up to 4 harvested creatives; one reference image per generation.
- Agent-facing and model-facing copy below marked **APPROVED COPY** is founder-approved (2026-10-30) and goes in verbatim. Any other agent-facing sentence a task adds or changes must be shown to the founder before it is committed.
- The design agent always runs solo (`LUMEN_AGENT_SCENE_SOLO=1`); all runtime changes target the solo path.
- Tests run only through `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh <one file>` with a hard timeout; never a whole design test folder; never `*_live.py`.
- Commits: local only, no AI attribution trailer (repo CLAUDE.md).

## Review Focus

1. A harvested ad with no description row at all (harvested before 2026-09-21, or by a `harvest_only` job) — the Assets page's "Ad" filter must still show it. (Task 2 test.)
2. A person marks a harvested ad as "Photo" — it must leave the "Ad" filter and the agent's list. (Task 1 and Task 6 tests.)
3. A fleet turn whose frozen lane was offered before this deploy (no `creatives` key) — the list still renders, with blank headline/copy, never a failed turn. (Task 5 test.)
4. A workspace with `LUMEN_BRAND_AD_ASSETS` off (no lane) but person-marked "Ad" assets — the list is still written. (Task 6 and Task 7 tests.)
5. An ad whose headline/copy/description contains `|` or newlines — the markdown table must not break. (Task 7 test.)

---

### Task 1: One rule for "ad" at the read seam, and the model may not answer "ad"

**Files:**
- Modify: `subsystems/design/clue_design/asset_context.py` (`effective_context`, new `AI_CREATIVE_TYPES`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/describe.py` (`_response_schema`)
- Test: `tests/design/test_asset_context.py`, `subsystems/clue-design/apps/api/tests/test_ingestion_describe.py`

**Interfaces:**
- Produces: `effective_context(row: dict[str, Any], *, harvested: bool = False) -> dict[str, Any]`; `AI_CREATIVE_TYPES: tuple[str, ...]` (every `CreativeType` except `"ad"`, in declaration order).

- [ ] **Step 1: Write the failing tests** in `tests/design/test_asset_context.py`:

```python
from clue_design.asset_context import AI_CREATIVE_TYPES, effective_context

def _row(ai_type=None, override=None):
    return {"asset_id": "a1", "analysis": {"creative_type": ai_type} if ai_type else {},
            "overrides": {"creative_type": override} if override else {}}

def test_a_harvested_asset_is_an_ad_whatever_the_model_said():
    assert effective_context(_row("photo"), harvested=True)["creative_type"] == "ad"
    assert effective_context(_row(), harvested=True)["creative_type"] == "ad"

def test_a_model_ad_that_was_not_harvested_shows_as_other():
    assert effective_context(_row("ad"))["creative_type"] == "other"

def test_the_persons_type_always_wins():
    assert effective_context(_row("photo", override="ad"))["creative_type"] == "ad"
    ctx = effective_context(_row("ad", override="photo"), harvested=True)
    assert ctx["creative_type"] == "photo" and ctx["classification_origin"] == "human"

def test_other_model_types_are_unchanged():
    assert effective_context(_row("logo"))["creative_type"] == "logo"
    assert effective_context(_row())["creative_type"] == "unknown"

def test_the_model_may_not_answer_ad():
    assert "ad" not in AI_CREATIVE_TYPES and "other" in AI_CREATIVE_TYPES
```

And in `test_ingestion_describe.py`:

```python
def test_the_describe_schema_does_not_offer_ad():
    from lumen_ingestion.describe import _RESPONSE_SCHEMA
    enum = <the creative_type enum reached through _RESPONSE_SCHEMA["$defs"] / items.analysis>
    assert "ad" not in enum and "other" in enum
```

- [ ] **Step 2: Run both files, verify the new tests fail**

Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh tests/design/test_asset_context.py` and the same for `subsystems/clue-design/apps/api/tests/test_ingestion_describe.py`
Expected: FAIL (`ImportError: AI_CREATIVE_TYPES`, `"ad" in enum`).

- [ ] **Step 3: Implement.** `effective_context` applies the Global Constraints rule after its existing merge; `classification_origin` unchanged. `_response_schema` replaces the analysis' `creative_type` enum with `list(AI_CREATIVE_TYPES)` (wherever pydantic emitted it: inline or under `$defs`). `AssetAnalysis`, `AssetOverrides` and `CreativeType` keep `"ad"` (stored analyses and the person's choice must still validate).

- [ ] **Step 4: Run both files, verify PASS** (whole file each).

- [ ] **Step 5: Commit** — `Only code calls an asset an ad: harvested ads are ads, a model "ad" shows as Other`

---

### Task 2: The description read knows which assets were harvested

**Files:**
- Modify: `subsystems/design/clue_design/descriptions.py:44-86` (`_description_from_row`, `get_many`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/describe.py:94` (`DescriptionStore.get_many`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:~7945` (`GET /assets/descriptions`)
- Test: `tests/design/test_ingestion_descriptions_dal_db.py`

**Interfaces:**
- Consumes: `effective_context(row, *, harvested=...)` (Task 1).
- Produces: `async get_many(conn, *, workspace_id: str, asset_ids: list[str], harvested_stubs: bool = False) -> dict[str, JsonObject]`; `DescriptionStore.get_many(asset_ids: list[str], *, harvested_stubs: bool = False) -> dict[str, dict]`.

- [ ] **Step 1: Write the failing DB tests** (same fixtures as `test_get_many_returns_only_the_callers_workspace`; seed a `design_asset` + `design_ad_creative` row for `harvested_id`, a described non-harvested asset whose AI type is `ad`, and a harvested asset with no description row):

```python
def test_get_many_marks_harvested_assets_as_ads(require_design_db):
    rows = <get_many(ws, [harvested_described, plain_model_ad])>
    assert rows[harvested_described]["creative_type"] == "ad"
    assert rows[plain_model_ad]["creative_type"] == "other"

def test_a_harvested_asset_with_no_row_appears_only_when_stubs_are_asked_for(require_design_db):
    assert harvested_undescribed not in <get_many(ws, [harvested_undescribed])>
    stub = <get_many(ws, [harvested_undescribed], harvested_stubs=True)>[harvested_undescribed]
    assert stub["asset_id"] == harvested_undescribed and stub["creative_type"] == "ad"
    assert stub["status"] == "stale"

def test_another_workspaces_harvest_does_not_make_an_asset_an_ad(require_design_db):
    <same asset id harvested only in workspace B>; assert <get_many(ws A)>[id]["creative_type"] != "ad"
```

- [ ] **Step 2: Run, verify FAIL** — `pytest-keyless.sh tests/design/test_ingestion_descriptions_dal_db.py` (stack DB is the wrapper's test DB; stop the lane stack first if it holds locks).

- [ ] **Step 3: Implement.** One extra query in `get_many`: `SELECT asset_id FROM design_ad_creative WHERE workspace_id = :w AND asset_id = ANY(:ids)`. Pass `harvested=` into `_description_from_row` → `effective_context`. With `harvested_stubs=True`, a harvested id with no row gets `effective_context({"asset_id": id, "status": "stale", "revision": 0}, harvested=True)`. Default `False` keeps every enrichment caller (`describe.py:218,386`, `ingestion_tasks.py:189`, `asset_enrichment.py:112`) seeing only real rows — a stub would read as a cache hit. Only the `GET /assets/descriptions` route passes `harvested_stubs=True`.

- [ ] **Step 4: Run the DB file, verify PASS.**

- [ ] **Step 5: Commit** — `The description read marks harvested ads; the Assets page sees undescribed ones too`

---

### Task 3: Harvest 50 ads over 8 pages by default

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/ad_library/harvest.py:46-50`, `subsystems/clue-design/apps/api/lumen_api/models.py:609-610`
- Test: `subsystems/clue-design/apps/api/tests/test_ad_library_harvest.py`

- [ ] **Step 1: Failing test**

```python
def test_the_route_and_the_harvest_default_to_fifty_ads_over_eight_pages():
    from lumen_api.models import <the onboarding request model at models.py:~600>
    from lumen_ingestion.ad_library.harvest import DEFAULT_MAX_CREATIVES, DEFAULT_MAX_PAGES
    request = <Model>(<minimum required fields>)
    assert (DEFAULT_MAX_CREATIVES, DEFAULT_MAX_PAGES) == (50, 8)
    assert (request.max_creatives, request.max_pages) == (50, 8)
```

- [ ] **Step 2: Run, verify FAIL.** `pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_ad_library_harvest.py`
- [ ] **Step 3: Set both pairs to 50 / 8**; update the two comments' numbers (8 pages ≈ 200 raw ads ≈ 8 credits). `models.py` defaults reference the `harvest.py` constants if the import direction allows, otherwise the literals.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** — `Harvest up to 50 ads over 8 pages by default, matching automatic onboarding`

---

### Task 4: The ad style card is prose only — no groups

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/ad_library/distill.py` (prompts, schemas, `bounded_card`, `OpenRouterAdDnaDistiller`, `_combine`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/ad_library/onboarding.py:~881-882` (drop `ads_grouped` / `ads_left_out` evidence)
- Test: `subsystems/clue-design/apps/api/tests/test_ad_assets_distill_batches.py`, `.../test_ad_assets_distill_pregenerate.py`

**Interfaces:**
- Produces: `AdDnaCard(prose: str, model: str | None)`; `AdDnaCard.to_json() -> {"schema_version": 2, "prose": str, "style_groups": []}` (empty list kept so stored cards keep their v2 shape and the publish tool's `style_group_count` is 0).

- [ ] **Step 1: Rewrite the tests.** Delete the grouping tests (`test_a_batch_that_leaves_ads_out_is_asked_once_more_naming_them`, `test_ads_still_missing_after_the_second_ask_stay_out_and_nothing_fails`, `test_the_combining_call_must_place_every_batch_look_exactly_once`, `test_the_sorting_prompt_asks_for_every_ad_in_exactly_one_group`, `test_the_style_group_count_and_names_are_capped`, `test_unnamed_and_malformed_groups_are_dropped_without_losing_the_named_ones`, `test_a_described_card_with_no_groups_is_still_a_real_card`). Add:

```python
def test_no_prompt_or_schema_asks_for_groups():
    from lumen_ingestion.ad_library import distill
    removed = ("Then group the creatives", "exactly one group", "Then combine the batch looks",
               "its own named looks")
    for prompt in (distill._SYSTEM_PROMPT, distill._MERGE_PROMPT):
        assert not any(sentence in prompt for sentence in removed)
    batch_text = distill._batch_messages([<one CreativePreview>], None)[1]["content"][0]["text"]
    assert "then group them" not in batch_text
    assert set(distill._CARD_SCHEMA["properties"]) == {"prose"}
    assert set(distill._MERGE_SCHEMA["properties"]) == {"prose"}

def test_a_payload_carrying_groups_still_stores_none():
    card = distill.bounded_card({"prose": "x", "style_groups": [{"name": "A", "creative_ids": ["c1"]}]})
    assert card.to_json()["style_groups"] == []

def test_several_batches_are_combined_into_one_description(distiller):  # adapt the existing one
    <three batches of 12 → one merge call → card.prose is the merge answer's prose>
```

- [ ] **Step 2: Run both files, verify the new tests FAIL.**

- [ ] **Step 3: Implement.** Model-facing copy changes are **removals only**: delete the last two paragraphs of `_SYSTEM_PROMPT` ("Then group the creatives…" and "Put every creative_id…"), the last paragraph of `_MERGE_PROMPT` ("Then combine the batch looks…"), and ", then group them" from `_batch_messages` (→ "Describe what they look like."). In `_MERGE_PROMPT`, change "so each batch has its own description and its own named looks." → "so each batch has its own description." Schemas: `prose` only. Remove `StyleGroup`, `MAX_STYLE_GROUPS`, `MAX_GROUP_NAME_CHARS`, `last_ungrouped`, `_placement_gaps`, `_placement_note`, `_each_placed_once`, `_union_of_batches` (a failed merge falls back to the first batch's prose). One call per batch, no re-ask.

- [ ] **Step 4: Run both distill files and `test_ad_assets_onboarding.py`, verify PASS.**

- [ ] **Step 5: Commit** — `The ad style card describes the brand's ads without sorting them into groups`

---

### Task 5: The lane carries each ad's headline and copy; nothing is auto-attached

**Files:**
- Modify: `subsystems/design/clue_design/ad_assets.py` (`reduce_creatives`, `frozen_ad_lane`, `reduce_pregenerated`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/ad_runtime.py` (`AdLane`, `read_ad_lane`, `lane_to_frozen`, `lane_from_frozen`; delete `select_reference_asset_ids`, `choose_style_group`, `_group_named`, `AUTO_REFERENCE_MAX`, `SELECT_*`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:9622-9632` (drop the auto-reference block) and `:13391-13432` (delete `resolve_auto_ad_references`)
- Test: `subsystems/clue-design/apps/api/tests/test_ad_lane_offer_freeze.py`, `.../test_ad_assets_runtime_composition.py`

**Interfaces:**
- Produces: `reduce_creatives(rows: list[JsonObject]) -> list[JsonObject]` — each `{"creative_id", "asset_id", "headline", "commentary", "created_at"}`, rows' order, rows missing either id dropped. `AdLane.creatives: tuple[JsonObject, ...] = ()`. Frozen shape gains `"creatives": [...]`. `reduce_pregenerated` entries become `{"asset_id", "shape"}` (no `style_group`).

- [ ] **Step 1: Write the failing tests / delete obsolete ones.** Delete every selection test in `test_ad_assets_runtime_composition.py` (`test_the_auto_cap_is_the_same_four_as_the_manual_cap` through `test_an_undistilled_lane_selects_by_recency_without_a_model_call`, `test_the_selected_group_decides_which_published_ads_reach_the_run`, `test_an_unresolvable_auto_attachment_costs_the_references_not_the_turn`). Rewrite `test_a_scene_turn_with_no_attachments_gets_the_brands_own_published_ads` and `test_the_platform_design_leg_path_auto_attaches_too` as:

```python
def test_a_scene_turn_with_no_attachments_carries_no_references(...):
    <same harness as the old test> ; assert captured_config.reference_assets in (None, {})

def test_the_humans_own_attachments_are_never_overridden_or_topped_up(...):  # keep as is
```

Add to `test_ad_lane_offer_freeze.py`:

```python
def test_the_frozen_lane_carries_each_creatives_headline_and_copy():
    lane = AdLane(card=None, creative_assets={"c1": "a1"},
                  creatives=({"creative_id": "c1", "asset_id": "a1", "headline": "H",
                              "commentary": "C", "created_at": "2026-10-01T00:00:00+00:00"},))
    assert lane_from_frozen(lane_to_frozen(lane)) == lane

def test_a_legacy_frozen_lane_without_creatives_still_lists_them_blank():
    lane = lane_from_frozen({"card": None, "creative_assets": {"c1": "a1"}, "pregenerated": []})
    assert lane.creatives == ({"creative_id": "c1", "asset_id": "a1", "headline": None,
                               "commentary": None, "created_at": None},)
```

- [ ] **Step 2: Run both files, verify the new tests FAIL.**
- [ ] **Step 3: Implement** per Interfaces. `read_ad_lane` and `frozen_ad_lane` both fill `creatives` from the same `list_ad_creatives` rows via `reduce_creatives`. `main.py`: remove the `if ad_lane is not None and not reference_assets:` block (the lane is still resolved for the card/backgrounds/list); `attached_images.py` and `REFERENCE_ASSETS_MAX` stay (manual path).
- [ ] **Step 4: Run both files plus `test_ad_assets_runtime_composition.py`, verify PASS.**
- [ ] **Step 5: Commit** — `Stop auto-attaching ads; the lane carries every creative's headline and copy`

---

### Task 6: The API passes the brand's ad list by value

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/ad_runtime.py` (new `context_brand_ads`)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py:~120` (new field)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:~9754` (wire it next to `ad_pregenerated_assets`)
- Test: `subsystems/clue-design/apps/api/tests/test_ad_assets_runtime_composition.py`

**Interfaces:**
- Consumes: `AdLane.creatives` (Task 5); library entries' effective `creative_type` (Tasks 1–2, via `asset_metadata_entry`).
- Produces: `context_brand_ads(lane: Optional[AdLane], asset_library: Optional[JsonObject]) -> Optional[list[JsonObject]]` — each `{"asset_id", "from": "linkedin_ad" | "marked_by_person", "headline", "commentary", "title", "description", "width", "height", "created_at"}`; `None` when empty. `AgentRuntimeConfig.brand_ads: list | None = None`.

- [ ] **Step 1: Failing tests**

```python
def test_the_list_holds_harvested_ads_then_person_marked_ones_newest_first():
    lane = <AdLane with creatives c1→a1 (2026-10-02, headline "H1") and c2→a2 (2026-10-01)>
    library = {"a1": <entry creative_type "ad", title "T1", record dims 1200×628>,
               "a2": <entry creative_type "ad">, "a3": <entry creative_type "ad", created_at 2026-10-03>,
               "a4": <entry creative_type "photo">}
    ads = context_brand_ads(lane, library)
    assert [ad["asset_id"] for ad in ads] == ["a3", "a1", "a2"]
    assert ads[0]["from"] == "marked_by_person" and ads[1]["from"] == "linkedin_ad"
    assert ads[1]["headline"] == "H1" and (ads[1]["width"], ads[1]["height"]) == (1200, 628)

def test_a_harvested_ad_the_person_retyped_leaves_the_list():
    <library["a1"] creative_type "photo">; assert "a1" not in <ids>

def test_a_harvested_ad_missing_from_the_library_is_left_out(): ...

def test_person_marked_ads_are_listed_with_no_lane():
    assert [ad["asset_id"] for ad in context_brand_ads(None, {"a3": <ad entry>})] == ["a3"]

def test_no_ads_is_none():
    assert context_brand_ads(None, {"a4": <photo entry>}) is None
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** Harvested rows come from `lane.creatives` whose `asset_id` is in the library and whose library `creative_type == "ad"`; person rows are other library entries with `creative_type == "ad"`; sort by `created_at` descending, missing last; dims via `record_pixel_dims(entry["record"])`. In `main.py`, set `config = replace(config, brand_ads=...)` whenever the result is not `None` — independent of the lane flag.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** — `Pass the brand's whole ad list to the ad agent by value`

---

### Task 7: The agent reads the list at the top of `ad-assets.md`; no group names anywhere

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/frame.py:449-526` (new `render_brand_ads_text`, `short_description`; `render_ad_dna_card_text` drops the "looks named" line; `render_pregenerated_assets_text` drops `style_group`)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/workspace.py:362-381`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_ad_assets_workspace.py`, `.../test_ad_dna_frame_context.py`

**Interfaces:**
- Consumes: `config.brand_ads` (Task 6).
- Produces: `render_brand_ads_text(ads: list[Any], library: JsonObject | None) -> str` (empty string when no row survives); `short_description(text: str | None, limit: int = 300) -> str` (first two sentences, capped at `limit`, `""` for none).

**APPROVED COPY** — the section, verbatim, `N` = rows rendered:

```
# The brand's ads
These are the brand's own published ads and any images the team marked as ads — N in all.
Open any of them with `view("asset:<id>")` to see the picture and its full description
(layout, text, typography, hierarchy). Look through several before you design, and pick
ones that fit this request; you don't need to use the same ones as last time.

| asset id | from | headline | post copy | title | short description | size |
|---|---|---|---|---|---|---|
```

`from` renders `LinkedIn ad` / `marked as an ad`; post copy capped at 200 chars; empty cells `—`; an ad with no description renders `no description yet`; size `W×H` or `—`; every cell escapes `|` and folds newlines to spaces.

- [ ] **Step 1: Failing tests**

```python
def test_the_ad_list_opens_ad_assets_md(tmp_path, monkeypatch):
    <scaffold with config.brand_ads = 2 ads present in the library and an ad_dna_card>
    text = (workspace / "ad-assets.md").read_text()
    assert text.index("# The brand's ads") < text.index("published") and "— 2 in all." in text
    assert "`a1`" in text and "LinkedIn ad" in text

def test_an_ad_this_turn_cannot_open_is_not_listed(...)          # id not in the library → no row, N counts only rendered rows
def test_person_marked_ads_alone_still_write_the_file(...)        # no card, no grounds, brand_ads only → file exists
def test_pipes_and_newlines_cannot_break_the_table():
    row = render_brand_ads_text([{"asset_id": "a1", "headline": "A | B\nC", ...}], {"a1": ...})
    assert "A \\| B C" in row
def test_short_description_keeps_two_sentences():
    assert short_description("One. Two. Three.") == "One. Two."
def test_an_old_card_with_groups_names_no_looks(...):            # card with style_groups → "looks named" absent
def test_grounds_are_listed_without_a_group(...):                 # entry with style_group → row is "`id` — wide ground"
```

Update the existing frame/workspace tests that assert group names to assert their absence.

- [ ] **Step 2: Run both files, verify FAIL.**
- [ ] **Step 3: Implement.** In `scaffold_workspace`, `render_brand_ads_text(tools.config.brand_ads or [], library)` becomes the first section of `ad-assets.md` when non-empty, before the card and grounds; the file's existing top heading stays above it. Nothing goes into the frame payload (the list is file-only, keeping the opening context small). No prompt or skill text changes: the solo prompt already says "Read …/ad-assets.md with the initial gather" whenever the file exists (`harness.py:917`), and the `reference-conditioned-ads` skill never mentioned auto-attaching or groups.
- [ ] **Step 4: Run both files plus `test_scene_solo_prompt.py`, verify PASS.**
- [ ] **Step 5: Commit** — `Show the agent every brand ad, with a short description, at the top of ad-assets.md`

---

### Task 8: One background from each of up to 4 ads

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/ad_library/pregenerate.py`
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/ad_library/onboarding.py:885-970` (`_pregenerate`)
- Test: `subsystems/clue-design/apps/api/tests/test_ad_assets_distill_pregenerate.py`

**Interfaces:**
- Produces: `background_prompt_for(*, prose: str, shape_label: str, brand_name: str | None) -> str`; `pregenerate_for_ads(card: JsonObject, *, ads: list[tuple[str, bytes, str]], core, cache_dir, generate, brand_name=None, generation_key_for=None, find_generated=None, max_bytes=None) -> PregenerationOutcome` where each ad is `(creative_id, image_bytes, mime_type)`; `ADS_TO_GENERATE_FROM = 4`; `shape_for(image_bytes: bytes) -> tuple[str, str]` → the `(aspect_ratio, label)` of `ASSET_SHAPES` closest to the image's own ratio (`("1:1", "square")` when it cannot be read). `pregenerate_for_card`, `ASSETS_PER_SYSTEM`, `MAX_REFERENCE_IMAGES` are removed. Shape labels become `wide`, `square`, `portrait`; `clue_design.ad_assets.SHAPE_WORDS` follows (`"16:9": "wide background"`, etc.).

**APPROVED COPY** — `background_prompt_for` returns exactly (brand omitted → "a brand's"; prose cut to `PROSE_IN_PROMPT_CHARS = 900`, sentence dropped when empty):

```
A {shape} background for {brand}'s advertising. The attached image is one of the brand's published ads. Imitate that ad's background: its colours, gradients, textures, shapes, light and mood. Leave out everything placed on top of it: its words, logo, people, product shots and screenshots. The brand's published ads, described: {prose}. Produce a background image only. No text of any kind, no letters, no numbers, no wordmark, no logo, no watermark, no user interface.
```

- [ ] **Step 1: Failing tests** (replace `test_each_named_system_gets_its_own_bounded_set_of_assets`, `test_the_harvested_creatives_condition_the_generation_and_are_capped`, `test_every_prompt_is_background_only`, `test_the_prompt_is_anchored_in_the_cards_own_description`):

```python
def test_the_prompt_is_the_approved_text():
    assert background_prompt_for(prose="Bold teal.", shape_label="square", brand_name="Acme") == (
        "A square background for Acme's advertising. The attached image is one of the brand's "
        "published ads. Imitate that ad's background: its colours, gradients, textures, shapes, "
        "light and mood. Leave out everything placed on top of it: its words, logo, people, "
        "product shots and screenshots. The brand's published ads, described: Bold teal. "
        "Produce a background image only. No text of any kind, no letters, no numbers, no "
        "wordmark, no logo, no watermark, no user interface.")
    # A prose ending in its own full stop is not doubled:
    assert "described: Bold teal. Produce" in background_prompt_for(
        prose="Bold teal", shape_label="square", brand_name="Acme")

def test_each_of_four_ads_gets_one_background_from_its_own_image_only():
    calls = <recording generate>; pregenerate_for_ads(card, ads=<6 ads>, ...)
    assert len(calls) == 4 and [c["reference_images"] for c in calls] == [[(b1, m1)], [(b2, m2)], [(b3, m3)], [(b4, m4)]]

def test_fewer_ads_make_one_background_each(): <2 ads → 2 calls>
def test_the_shape_follows_the_ads_own_ratio(): <1200×628 png → "16:9"; 1080×1350 → "4:5"; 1080×1080 → "1:1">
def test_the_link_names_the_source_ad(): <outcome.links()[0]["visual_system"] == "c1">
```

The prose has one trailing `.` stripped before the sentence's own `.` is added.

Keep and adapt the ledger, failure-isolation, text-only-reply and real-dimensions tests to `pregenerate_for_ads`.

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** `_pregenerate` passes `ads=[(c.creative_id, c.image_bytes, c.mime_type) for c in creatives[:ADS_TO_GENERATE_FROM]]`; the generation-ledger key uses that ad's own digest only. Image size via Pillow. Asset label `"{creative_id} — {shape} background"`; tags `["ad-pregenerated", f"source-ad:{creative_id}"]`.
- [ ] **Step 4: Run the file and `test_ad_assets_onboarding.py`, verify PASS.**
- [ ] **Step 5: Commit** — `Make one background from each of up to four of the brand's ads`

---

### Task 9: Records and the live check

**Files:**
- Create: `_memory/2026-10-30-design-reference-ads.md`
- Modify: `docs/superpowers/specs/2026-10-30-design-reference-ads-design.md` (status line: built, with the commit range)

- [ ] **Step 1: Re-run every touched test file** through the wrapper, one at a time, with a 600 s timeout each; record results in the memory file.
- [ ] **Step 2: Live check on the trenton stack** (runbook `dev_stack_trenton.sh`, started detached; pre-approved; no new harvest — use a workspace that already has harvested ads): on the Assets page, filter type "Ad" and confirm only harvested and person-marked assets show; mark one website image "Ad"; run one ad turn with no attachments; confirm in the run view (`subsystems/clue-design/scripts/run_view.py <run_id>`) that `ad-assets.md` opens with the list including the marked image, no reference images rode the turn, and the agent `view`ed at least one listed ad. Report the turn's cost.
- [ ] **Step 3: Write the memory note** (what changed, the rulings, the live-check result, what is owed: a fresh onboarding to see 50 ads + per-ad backgrounds, which spends ~8 Adyntel credits and image-model calls and needs a founder go).
- [ ] **Step 4: Commit** — `Memory: richer reference ads built and live-checked`
