# Podcast identity merge (review finding I14) — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `find_podcasts` merges two results only when the publisher's own identifiers prove they
are the same episode (or show), so one result never carries another episode's audio, description or
guests, and no episode silently disappears.

**Architecture:** every lead keeps the identifiers its source gave (episode GUID, show id, feed,
audio file, each source's own id). After all searches, results are grouped by proof
(union-find over identity buckets, so the outcome does not depend on arrival order), each group
becomes one lead built only from its own members, and results that look alike without proof stay
separate lines. All changes are inside `platform/api/clue_api/footprint/podcast_search.py`.

**Tech stack:** Python 3.12, pydantic v2, pytest; no new dependency.

**Spec:** review finding I14 in
`docs/superpowers/specs/research-quality/review-2026-11-11/README.md` and `r2_recordings.md` F8;
design agreed 2026-11-12 in chat (founder) with the main session's review (sections below record
it). Data checked 2026-11-12 on the r44a trial DB (every stored Apple and Podcast Index reply and
the 8 saved `find_podcasts` results).

## What the data showed (2026-11-12)

| Field | Apple episodes (565) | Podcast Index episodes (561) |
|---|---|---|
| Episode GUID (`episodeGuid` / `guid`) | 100% | 100% |
| Feed (`feedUrl`) | 100% | 100% |
| Audio file (`episodeUrl` / `enclosureUrl`) | 100% | 100% |
| Show id (`collectionId` / `feedItunesId`) | 100% | 88% |
| Duration (`trackTimeMillis` / `duration`) | 98% | 100% |
| Source's own id (`trackId` / `id`) | 100% | 100% |

- 37 episodes appear in both sources: same GUID, same audio file, durations within 1 s.
- The same source's own id repeats across searches (16 Apple, 231 Podcast Index): the commonest
  real duplicate.
- Cleaning tracker prefixes never joined two different GUIDs across 816 real audio links.
  Real shapes: `dts.podtrac.com/redirect.mp3/…`, `www.podtrac.com/pts/redirect.mp3/pdst.fm/e/…`
  (chained), `chrt.fm/track/<id>/…`, `pdst.fm/e/…`, `mgln.ai/e/<n>/…`, and anchor.fm's
  percent-encoded `…/podcast/play/<id>/https%3A%2F%2F<cdn>/…`. 249 of 816 carry a query
  (`?updated=…`).
- Apple lists one feed under two show ids (Inspired Execution), so "same show" must mean same show
  id **or** same feed.
- One GUID appears under 8 pairs of different feeds (host moves, syndication), so a GUID proves
  nothing without the same show.
- Today's show+title key merged two real pairs. One is Ann's Citi "The Cyber World", the same
  recording published in two feeds (Kaltura and an anchor.fm mirror with no show id), dates 10 min
  apart, durations 1 s apart. Under the new rules it stays two lines with the "may be the same"
  note (rule 3 needs the same show).
- Exa: 4 of 563 Exa leads merged with a feed result today; no Exa lead shared an exact title with
  an unmerged feed lead. The strict Exa rule loses almost nothing.

## Design (decided)

**Same episode** (two `kind="episode"` leads), any one of:

- **R0** the same source's own id (`apple:<trackId>`, `pi:<id>`, `exa:<exa_url>`);
- **R1** the same GUID (exact string, whitespace trimmed) **and** the same show;
- **R2** the same audio file (`audio_key`, below);
- **R3** the same show, the same title (case and spacing ignored), both dates present and at
  most 1 day apart, and both durations present and at most 60 s apart;
- **RX** (an Exa lead, which has no feed, GUID or audio) the same show name and the same title
  (case and spacing ignored), and both dates present and at most 1 day apart. No fuzzy matching.

**Same show** (two `kind="show"` leads, and the "same show" inside R1 and R3): both show ids present
and equal, or both feeds present and equal after `feed_key`. A show never merges with an episode.

**Missing is never equal:** every rule needs the compared values present on both sides.

**Grouping:** union-find over buckets (one bucket per R0 id, per GUID+show, per audio key, per
R3 key and per RX key), so A~B by GUID and B~C by audio make one lead whatever the order. Output
order is the order in which each group's first member was found (the overview's "order found" stays
true).

**Building one lead from a group:** identifiers, links, dates and duration are taken in a fixed
source order (podcast_index, apple, exa_podcasts), not arrival order. The description is the
longest among the members (all proven the same episode). `sources`, `found_by`, `links` and
`passages` are the union in order found. `heard_hosts` and `heard_guests` are Exa's only.

**Normalisers:**

- `audio_key(url)`: percent-decode once; take host+path; start from the last path segment that
  looks like a host name (`[a-z0-9-]+(\.[a-z0-9-]+)+`, not ending in an audio extension), applied
  to the whole chain; lower-case; drop a leading `www.`; drop the query and fragment **unless** the
  last path segment has no file extension (then the query is kept: some hosts serve every episode
  from one path).
- `feed_key(url)`: drop the scheme, lower-case, drop a leading `www.` and a trailing `/`; keep the
  query.

**"May be the same" note (agent-facing wording; founder approval needed before Task 4 lands):** two
episode lines that did not merge but share show and title (case and spacing ignored) get, in the
overview, `| may be the same episode as #12 (same show and title)`. The code does not merge; the
agent judges, and is spared transcribing the same recording twice.

**Unchanged:** the receipt, the operation's output schema (recipe 44 pins), the overview's other
columns, nothing dropped or ranked, no name judgement. The saved file gains identifier fields on each
lead.

## Global constraints

- `footprint` never imports `arv2` (`tests/footprint/test_footprint_imports.py`).
- Nothing is dropped or ranked; code judges no names (founder ruling 2026-11-11).
- No new env flag; if one became necessary it goes in `.env.example` the same commit.
- Fixtures use the real URL shapes from r44a with neutral show and episode names (no prospect
  names in the repo).
- Tests offline only: `uv run pytest tests/footprint -q --ignore-glob='*_live.py'`.
- Agent-facing wording (the overview note) waits for founder approval.

## Review focus

1. A wrong merge (two different episodes become one) is worse than a duplicate line: every test of
   a rule has a near-miss case that must stay separate.
2. Missing values (no show id on 12% of Podcast Index results, no duration on 2% of Apple) never
   count as a match.
3. Order independence: the same results in any order give the same leads with the same fields.
4. Exa leads keep their heard names and passages, and only Exa supplies heard names.
5. Apple's feed lookup still fills a missing feed, keyed by the lead's show id, not by the old key.

---

### Task 1: Keep each source's identifiers on the lead

**Files:**
- Modify: `platform/api/clue_api/footprint/podcast_search.py` (`EpisodeLead`, `_apple`,
  `_pi_episodes`, `_pi_shows`, `_exa_lead`)
- Test: `tests/footprint/test_podcast_search.py`

**Interfaces:**
- Produces: `EpisodeLead.guid: str | None`, `EpisodeLead.show_id: str | None` (Apple
  `collectionId`, Podcast Index `feedItunesId` or a show's `itunesId`, as strings),
  `EpisodeLead.source_ids: list[str]` (`"apple:<trackId>"`, `"pi:<id>"`, `"pi_show:<id>"`,
  `"exa:<url>"`).

- [ ] **Step 1: Failing tests**: `test_apple_lead_keeps_guid_show_id_and_track_id`,
  `test_pi_lead_keeps_guid_show_id_and_episode_id`, `test_pi_show_keeps_itunes_id`,
  `test_exa_lead_has_its_url_as_source_id`. Each builds one reply in the existing fixture style and
  asserts the three fields (e.g. `lead.source_ids == ["apple:1000380704402"]`,
  `lead.show_id == "1201668380"`, a GUID with surrounding spaces is trimmed).
- [ ] **Step 2:** `uv run pytest tests/footprint/test_podcast_search.py -q -k "keeps or source_id"`
  → FAIL (unknown fields).
- [ ] **Step 3:** add the fields (defaults `None` / `[]`) and fill them in the four parsers.
- [ ] **Step 4:** the same command → PASS. Then `uv run pytest tests/arv2/test_quality_recipe_43.py -q`
  → PASS (the tool's output schema pins are unchanged).
- [ ] **Step 5: Commit** "Footprint: podcast leads keep their sources' identifiers (I14)".

### Task 2: Normalisers for audio and feed links

**Files:** same module and test file.

**Interfaces:**
- Produces: `audio_key(url: str | None) -> str | None`, `feed_key(url: str | None) -> str | None`
  (module-level, used by Task 3).

- [ ] **Step 1: Failing tests**, parametrized from the real r44a shapes with neutral names:
  - `test_audio_key_unwraps_trackers`: podtrac, chained podtrac→pdst, chrt.fm, pdst.fm, mgln.ai,
    and anchor.fm percent-encoded each give the same key as the plain CDN link;
  - `test_audio_key_ignores_query_on_a_file`: `…/X.mp3?updated=1` equals `…/X.mp3`;
  - `test_audio_key_keeps_query_without_a_file_name`: `host/play?id=1` differs from
    `host/play?id=2`;
  - `test_audio_key_scheme_and_case`: `http://` vs `https://` and host case are equal;
  - `test_feed_key_normalises`: scheme, `www.`, case and trailing slash are equal; a different path
    differs;
  - `test_keys_of_missing_are_none`.
- [ ] **Step 2:** run `-k "audio_key or feed_key"` → FAIL (not defined).
- [ ] **Step 3:** implement both as specified under **Normalisers**.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5: Commit** "Footprint: audio and feed link keys that see through trackers (I14)".

### Task 3: Merge on proof only

**Files:** same module and test file.

**Interfaces:**
- Consumes: Task 1 fields and Task 2 keys.
- Produces: `_group(leads: Sequence[EpisodeLead]) -> list[EpisodeLead]` (union-find; one lead per
  group in order found), `_combine(members: Sequence[EpisodeLead]) -> EpisodeLead`. `find_podcasts`
  collects every search's leads, then calls `_group`; `_key` and `_merge` are deleted. The Apple
  feed lookup is keyed by `lead.show_id` for Apple leads without a feed; the `collections` dict
  goes.

- [ ] **Step 1: Failing tests** (through `find_podcasts` with the existing scripted caller where a
  search is involved, `_group` directly otherwise):
  - `test_two_different_episode_12s_stay_two` (the reviewer's repro: two feeds, two GUIDs, two
    audio files, plus two same-named shows → 4 leads, each with its own audio and description);
  - `test_same_episode_from_apple_and_pi_is_one` (same GUID, same show id) → 1 lead,
    `sources == ["apple", "podcast_index"]`, both searches in `found_by`;
  - `test_same_source_id_found_by_two_searches_is_one`;
  - `test_same_guid_in_another_show_stays_separate` (syndication) and
    `test_same_guid_same_feed_but_two_apple_show_ids_is_one` (Apple's double listing);
  - `test_tracker_wrapped_and_plain_audio_is_one`;
  - `test_rule3_mirror_feed_merges_only_with_same_show_and_close_date_and_length`: same show, title,
    10 min, 1 s → 1; date 3 days apart → 2; one duration missing → 2;
  - `test_missing_values_never_match`: no GUID, no audio, same show and title, no durations → 2;
  - `test_exa_merges_only_on_show_title_and_date`: exact → 1 with Exa's heard names and passages;
    title differs by one word → 2; no date → 2;
  - `test_shows_merge_on_feed_or_show_id_only`: two same-named shows → 2; same `itunesId` → 1; a
    show never merges with an episode;
  - `test_merge_is_transitive_and_order_independent`: A~B by GUID, B~C by audio, A and C share
    nothing → 1; every permutation of the inputs gives equal `model_dump()` of the leads (sorted by
    `source_ids`);
  - `test_fields_never_mix_across_episodes`: in the 4-stay-4 case, each lead's `audio_url`,
    `description` and `heard_guests` come from one episode.
  - Keep and update: `test_one_episode_found_twice_is_listed_once_with_both_searches`,
    `test_exa_hit_merges_with_the_same_episode_from_apple` (needs the date now),
    `test_podcasts_never_dropped`, `test_no_ranking_by_name_order_is_as_found`.
- [ ] **Step 2:** run the file → the new tests FAIL; the kept ones may fail where their fixtures
  relied on show+title (fix the fixture, never the rule, and note each in the commit).
- [ ] **Step 3:** implement `_group` (buckets for R0, R1, R2, R3, RX and show keys; union-find; groups
  ordered by first member's position) and `_combine` (fixed source order for identifiers; longest
  description; ordered unions; Exa-only heard names). Rewire `find_podcasts`.
- [ ] **Step 4:** `uv run pytest tests/footprint -q --ignore-glob='*_live.py'` → PASS. Then run the
  reviewer's `docs/superpowers/specs/research-quality/review-2026-11-11/repro/repro_podcast_merge.py`
  → 4 leads.
- [ ] **Step 5:** replay the 8 saved r44a `find_podcasts` results' source replies through the new
  grouping (throwaway script in the scratchpad, reading the stored provider replies): report
  leads before/after, merges by rule, and that "The Cyber World" pair is two lines. Paste the
  numbers into the commit message.
- [ ] **Step 6: Commit** "Footprint: podcast results merge only when the publisher's ids prove one
  episode (I14)".

### Task 4: "May be the same" note in the overview — after founder approval of the wording

**Files:** same module and test file.

- [ ] **Step 1: Failing test** `test_overview_notes_possible_duplicates`: two unmerged episodes with
  the same show and title → each line ends `| may be the same episode as #N (same show and title)`
  naming the other; a merged lead and a unique lead get no note.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** in `overview`, group episode lines by (show, title) with case and spacing
  ignored, and append the note.
- [ ] **Step 4:** run the footprint suite → PASS.
- [ ] **Step 5: Commit** "Footprint: the podcast overview points out lines that may be one episode
  (I14)".

### Task 5: Record

- [ ] Update the module docstring (how duplicates are recognised).
- [ ] Add the I14 status line to `docs/superpowers/specs/research-quality/review-2026-11-11/README.md`
  (below the I13 line), and a short entry in
  `docs/superpowers/specs/research-quality/media-and-social-sources-ledger.md` (identifiers per
  source, coverage numbers above).
- [ ] `_memory/` note: what changed, the data numbers, open volume decision.
- [ ] Tag `review/podcast-identity/start` (before Task 1) and `review/podcast-identity/end`.
- [ ] Commit "Docs: podcast identity merge (I14)".

## Not in this plan (separate founder decision)

Volume: dropping Podcast Index `search/byterm` and capping each source per search with
"N shown, more exist" in the overview.
