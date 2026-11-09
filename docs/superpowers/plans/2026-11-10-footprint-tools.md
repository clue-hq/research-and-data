# Footprint tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Person and account research can find and read a person's or company's public footprint (podcasts,
videos, LinkedIn, X, public Instagram and Facebook), with a Jev speaker check replacing the
self-introduction check, shipped as trial recipe 43.

**Architecture:** A new package `platform/api/clue_api/footprint/` holds the provider clients and plain
search/read functions that know nothing about research jobs (so the gift agent can use them once it joins
the platform). ARV2 exposes them as new jobs of `acquire_research_evidence` version 3; each job runs its
`footprint/` function inside `runtime.operate`, and the wrapper keeps doing permission, allowance, saved
record and saving to `/research/operations/<id>/`. `read_media` runs Jev after a transcript is saved and
shows the answer to the agent; nothing in code gates on it.

**Tech Stack:** Python 3.12, pydantic v2, SQLAlchemy async, `clue_spend` (`CallSpec`, `ProviderCaller`),
pytest; providers: treg (fetchinio, TikHub, ScrapeCreators), YouTube Data API, Podcast Index, Apple,
Deepgram, Gemini via OpenRouter, Jev via OpenRouter's Decisions API, PDL.

**Spec:** `docs/superpowers/specs/research-quality/2026-11-09-footprint-tool-set-design.md` (sections 1–9) and
the founder decisions in section 0 of `docs/superpowers/specs/research-quality/media-and-social-sources-ledger.md`.

## Global Constraints

- Design agents are not touched. Research decisions (which recording, which handle, is this the person,
  what to quote) are the agent's, by prompt; code supplies data and machinery only. No rule-based or
  string-matching identity checks anywhere (ledger decisions 3 and 5).
- Metadata confirms when it clearly names the person; only clear proof of a namesake rules a recording out;
  unclear means transcribe and let the model judge (ledger decision 3). This lives in the prompt.
- Jev picks the speaker label; every line under that label counts as the person's. No code threshold blocks
  a recording or a quote (ledger decision 5).
- Quotes: the saved proof line is the transcript's text; the page writer may fix spelling and punctuation;
  no code compares the page quote with the proof line (ledger decision 4; design section 9).
- YouTube order: podcast version of the same episode first, then Gemini on the public link with the
  coverage check; treg captions are not used (ledger decision 8). Model from `CLUE_ARV2_MEDIA_VIDEO_MODEL`.
- Jev: model `typesafe/jev-1.14`, endpoint `POST https://openrouter.ai/api/alpha/decisions`, body
  `{model, state, questions}`; the three questions' wording is copied verbatim from ledger section 4.1.
- Spotify, LinkedIn comments, voice matching, conference sites, Wayback: not built.
- Heavy posters: the whole history is fetched and saved; no page cap (founder rule: no pre-emptive caps).
  The agent reads its saved files itself.
- Every new env setting goes into `.env.example` (and the local `.env`) with its default in the same commit.
- `clue_api.footprint` imports nothing from `clue_api.arv2`.
- Profiles and tool versions already pinned are never edited; old runs replay unchanged.
- Never push. Commit locally, no AI attribution in commit messages (project CLAUDE.md).
- Tests: unit files by name with `--ignore-glob='*_live.py'`; DB tests only on the lane's throwaway test
  database, never the stack database `clue_research_trial`. Live provider calls only where a step says so,
  and report their cost.
- Prompt, skill and operation-description wording is shown to the founder in chat and approved before it is
  written (Task 11).

## Review Focus

1. A private Instagram or Facebook account, or a handle that does not exist: the job returns state
   `private`/`not_found` with no posts and no error, and nothing is charged by us twice — Task 4.
2. A provider failing on page 7 of a 12-page history: the pages already fetched are kept and returned with a
   gap saying where it stopped — Task 4.
3. A recording whose transcript is longer than Jev accepts in one call, and Jev being unreachable: the
   transcript still comes back, with the answer combined over windows or marked unavailable — Task 7.
4. A recording read twice in one job, and the same recording read by two people's jobs: Jev is paid once per
   (recording version, person); each person gets their own answer — Task 8.
5. The YouTube Data API quota running out mid-run: `find_videos` falls back to the Exa search supplied by
   the caller and says it did — Task 5.

---

### Task 1: Move the job-agnostic media code into `footprint/`

**Files:**
- Create: `platform/api/clue_api/footprint/__init__.py`
- Move (git mv, then leave a one-line re-export shim at the old path, like `arv2/calls.py`):
  `arv2/media_types.py`, `media_recording.py`, `media_feeds_client.py`, `media_sources.py`,
  `media_resolution.py`, `deepgram_media_client.py`, `gemini_media_client.py`, `media_telemetry.py`,
  `openrouter.py`, `text.py` → `footprint/` with the same file names
- Modify: the moved files' imports (`clue_api.arv2.calls|errors|transport|sinks` → `clue_spend.*`;
  `clue_api.arv2.<moved>` → `clue_api.footprint.<moved>`)
- Modify: `tests/arv2/test_import_guard.py` (`ALLOWED_INTERNAL_PREFIXES` gains `clue_api.footprint`),
  root `pyproject.toml` import-linter (new contract: `clue_api.footprint` forbids `clue_api.arv2`)
- Test: `tests/footprint/test_footprint_imports.py`

**Interfaces:**
- Produces: `clue_api.footprint.<module>` for every moved module, same public names as before.

- [ ] **Step 1: Write the failing test** — `test_footprint_imports_nothing_from_arv2` walks every `.py`
  under `platform/api/clue_api/footprint/` with `ast` and asserts no `Import`/`ImportFrom` names a module
  starting `clue_api.arv2`; `test_old_paths_still_resolve` asserts
  `clue_api.arv2.media_sources.podcast_twin is clue_api.footprint.media_sources.podcast_twin` (and the same
  for one public name of each moved module).
- [ ] **Step 2: Run it** — `uv run pytest tests/footprint/test_footprint_imports.py -v`. Expected: FAIL
  (`ModuleNotFoundError: clue_api.footprint`).
- [ ] **Step 3: Move the files and add the shims.** If a moved file needs something from arv2 that is not a
  `clue_spend` shim, move that too or stop and record a ruling; do not import arv2 from footprint.
- [ ] **Step 4: Run** the new test plus the existing media suites:
  `uv run pytest tests/footprint tests/arv2/test_media_*.py tests/arv2/test_gemini_media_client.py tests/arv2/test_deepgram_media_client.py tests/arv2/test_import_guard.py --ignore-glob='*_live.py'`
  and `uv run lint-imports`. Expected: all pass, no test changed except the import guard's allow list.
- [ ] **Step 5: Commit** — "Footprint: move job-agnostic media code into clue_api.footprint".

### Task 2: treg client and settings

**Files:**
- Create: `platform/api/clue_api/footprint/treg_client.py`
- Modify: `libs/clue-config/clue_config/settings.py`, `.env.example`, `.env`
- Test: `tests/footprint/test_treg_client.py`, fixtures under `tests/footprint/fixtures/treg/`

**Interfaces:**
- Produces:
  - `class TregReply(BaseModel): body: JsonValue; cost_usd: float; call_id: str | None; status: int`
  - `def treg_call(caller: ProviderCaller, token: SecretStr, tool_id: str, query: dict[str, str | int], *, base_url: str = "https://treg.to") -> TregReply`
    — one `CallSpec` with provider `"treg"`, label `f"treg.{tool_id}"`, cost read from the
    `X-Treg-Cost-Micro` response header (micro-USD → USD). A 4xx from the provider is returned (not raised)
    with `cost_usd` from the header (normally 0); a 5xx or transport error raises `ProviderTransportError`.
  - Settings: `treg_api_key: SecretStr | None = None` (env `CLUE_TREG_API_KEY`),
    `treg_base_url: str = "https://treg.to"` (env `CLUE_TREG_BASE_URL`).

- [ ] **Step 1:** Confirm the HTTP call form against treg's docs (`https://treg.to/llms.txt`): catalog tool
  URL and the `X-Treg-Token` header. Record one live call per tool used in Tasks 4 and 6 as a fixture
  (response body + headers, token stripped): `fetchinio.linkedin.user.posts`,
  `fetchinio.linkedin.user.reactions`, `tikhub.x.user.posts`, `scrapecreators.instagram.user.posts`,
  `scrapecreators.instagram.user.profile`, `scrapecreators.x.v1-facebook-profile-posts`,
  `scrapecreators.x.v1-twitter-tweet`, `scrapecreators.x.v2-instagram-media-transcript`, plus both company
  candidates `tikhub.x.linkedin-web-v2-get-company-posts` and `scrapecreators.x.v1-linkedin-company-posts`
  on two companies (U.S. Bank, Illumio). Expected spend under $0.10; report it.
- [ ] **Step 2: Write failing tests** with a fake transport replaying the fixtures:
  `test_cost_comes_from_header` (`X-Treg-Cost-Micro: 1500` → `cost_usd == 0.0015`),
  `test_provider_4xx_is_returned_not_raised` (status 400 body kept, `cost_usd == 0`),
  `test_5xx_raises_transport_error`, `test_token_never_in_ledger_row` (the recorded ledger/raw row contains
  no token value).
- [ ] **Step 3: Run** — `uv run pytest tests/footprint/test_treg_client.py -v`. Expected: FAIL (import).
- [ ] **Step 4: Implement** `treg_call` and the two settings; add both env lines to `.env.example` and `.env`.
- [ ] **Step 5: Run** the tests. Expected: PASS.
- [ ] **Step 6: Commit** — "Footprint: treg client and CLUE_TREG_* settings".

### Task 3: Shared result types for social history

**Files:**
- Create: `platform/api/clue_api/footprint/social_types.py`
- Test: `tests/footprint/test_social_types.py`

**Interfaces:**
- Produces:
  - `class Post(BaseModel)`: `platform: Literal["linkedin","x","instagram","facebook"]`, `post_id: str`,
    `url: str | None`, `published_at: datetime | None`, `text: str`, `kind: Literal["own","reaction","repost","company"]`,
    `author_name: str | None`, `author_url: str | None`, `video_urls: list[str]`, `raw_ref: int` (index of
    the provider page it came from).
  - `class SocialHistory(BaseModel)`: `state: Literal["complete","partial","private","not_found","unavailable"]`,
    `posts: list[Post]`, `pages: int`, `cost_usd: float`, `earliest: datetime | None`,
    `latest: datetime | None`, `gap: str | None`.

- [ ] **Step 1: Write failing test** `test_history_dates_follow_posts`: a `SocialHistory` built by
  `SocialHistory.of(posts, pages=2, cost_usd=0.003, state="complete")` has `earliest`/`latest` equal to
  the min/max `published_at`, ignoring `None`.
- [ ] **Step 2: Run** — Expected FAIL. **Step 3: Implement** the models and the `of` classmethod.
  **Step 4: Run** — PASS. **Step 5: Commit** — "Footprint: social history types".

### Task 4: Social history readers (person and company)

**Files:**
- Create: `platform/api/clue_api/footprint/social.py`
- Test: `tests/footprint/test_social.py`

**Interfaces:**
- Consumes: `treg_call`, `TregReply` (Task 2); `Post`, `SocialHistory` (Task 3).
- Produces (each pages until the provider says there is no more page, keeps every page):
  - `linkedin_activity(caller, token, profile: str, kind: Literal["posts","reactions"]) -> SocialHistory`
    (fetchinio, `count=50`, `paginationToken` while `hasMore`)
  - `x_posts(caller, token, handle: str) -> SocialHistory` (TikHub timeline cursor; retweets as `repost`)
  - `instagram_posts(caller, token, handle: str) -> SocialHistory` (ScrapeCreators posts; "Profile is
    restricted" → `state="private"`)
  - `facebook_posts(caller, token, profile: str) -> SocialHistory` (ScrapeCreators; "Profile is private" →
    `state="private"`)
  - `company_linkedin_posts(caller, token, company: str) -> SocialHistory` (the company tool chosen in
    Task 2 step 1 — the cheaper one unless its fixtures show fewer posts or missing dates; record which and
    why in the ledger section 5). The company's X account uses `x_posts`.

- [ ] **Step 1: Write failing tests** against the fixtures:
  `test_linkedin_pages_until_no_more` (two fixture pages → `pages == 2`, all posts, `state == "complete"`),
  `test_failure_mid_history_keeps_fetched_pages` (page 2 raises transport error → `state == "partial"`,
  page-1 posts kept, `gap` names the page), `test_private_instagram_is_private_not_error`
  (`state == "private"`, `posts == []`), `test_unknown_handle_is_not_found`, `test_retweet_marked_repost`,
  `test_video_links_kept` (a LinkedIn post with `videoUrl` → `video_urls == [that url]`).
- [ ] **Step 2: Run** — `uv run pytest tests/footprint/test_social.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the five readers. Each provider's field names are read from its fixture.
- [ ] **Step 4: Run** — PASS. **Step 5: Commit** — "Footprint: LinkedIn, X, Instagram, Facebook and company post readers".

### Task 5: `find_podcasts` and `find_videos`

**Files:**
- Create: `platform/api/clue_api/footprint/podcast_search.py`, `platform/api/clue_api/footprint/video_search.py`
- Test: `tests/footprint/test_podcast_search.py`, `tests/footprint/test_video_search.py`

**Interfaces:**
- Consumes: `media_sources.apple_shows`, `podcast_index_shows`, `youtube_details`, `MediaSourceKeys`.
- Produces:
  - `class EpisodeLead(BaseModel)`: `show`, `title`, `published_at`, `description`, `links: list[str]`,
    `feed_url`, `audio_url`, `transcript_url`, `episode_url`, `sources: list[str]`, `names_match: bool`
    (the description or title contains the name or company, used only for ordering).
  - `find_podcasts(caller, keys: MediaSourceKeys, name: str, company: str | None) -> list[EpisodeLead]`:
    Podcast Index `search/byperson` and `search/byterm` (quoted name) plus Apple; duplicates merged by
    episode (feed + guid, else audio URL); missing feed links filled from Apple; ordered `names_match`
    first, then newest. Never drops a result.
  - `class VideoLead(BaseModel)`: `video_id`, `url`, `title`, `channel`, `published_at`, `duration_s`,
    `description`, `tags`, `links`, `source: Literal["youtube","exa"]`.
  - `find_videos(caller, keys, name: str, company: str | None, *, exa_fallback: Callable[[str], list[str]] | None) -> tuple[list[VideoLead], str | None]`:
    YouTube `search.list` with `q='"<name>"'` (and a second query with the company when given), then
    `videos.list` for full details; on a quota error (HTTP 403 `quotaExceeded`) calls `exa_fallback` with
    the same query, reads details for the YouTube links it returns, and returns the gap
    `"youtube_quota_exhausted_used_exa"`.
- [ ] **Step 1: Write failing tests** with recorded responses (Podcast Index and YouTube calls are free;
  record them live for Ann Barron-DiCamillo and Dilip Venkatachari):
  `test_podcasts_merge_duplicates_across_sources`, `test_podcasts_naming_results_first`,
  `test_podcasts_never_dropped` (a result naming neither still returned, last),
  `test_videos_full_details`, `test_video_quota_falls_back_to_exa` (fake 403 quotaExceeded → fallback
  called once, gap returned), `test_video_quota_without_fallback_returns_gap`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — "Footprint: find_podcasts and find_videos".

### Task 6: `find_handles` and social video reading

**Files:**
- Create: `platform/api/clue_api/footprint/handles.py`, `platform/api/clue_api/footprint/pdl_client.py`
- Modify: `platform/api/clue_api/footprint/media_resolution.py` (social video links), `libs/clue-config/clue_config/settings.py`, `.env.example`, `.env`
- Test: `tests/footprint/test_handles.py`, `tests/footprint/test_social_video.py`

**Interfaces:**
- Produces:
  - Settings `pdl_api_key: SecretStr | None` (env `CLUE_PDL_API_KEY`).
  - `pdl_person(caller, key, *, name, company, linkedin_url) -> dict | None` (PDL person enrich; cost from
    PDL's reported credits at the ledger's price, about $0.28 a match; no match → `None`, not charged by us).
  - `class HandleCandidate(BaseModel)`: `platform`, `handle`, `url`, `source: Literal["pdl","same_handle"]`,
    `private: bool | None`, `bio: str | None`.
  - `find_handles(caller, token, pdl_key, *, name, company, linkedin_url) -> list[HandleCandidate]`: X and
    Facebook from PDL; Instagram by trying the LinkedIn public id and the PDL handles with
    `scrapecreators.instagram.user.profile` (gives `private` and `bio`). Every result is a candidate; the
    agent confirms it from the bio and posts.
  - Social video in `read_media`: an X post link → `scrapecreators.x.v1-twitter-tweet` → MP4 link; Instagram
    and Facebook video links come from the post readers. Clips ≤120 s use the ScrapeCreators transcript
    tools; longer ones go to Deepgram by file link (existing path).
- [ ] **Step 1: Write failing tests:** `test_handles_are_candidates_with_source`,
  `test_private_instagram_marked`, `test_no_pdl_key_returns_instagram_only`,
  `test_short_x_video_uses_scrapecreators_transcript`, `test_long_x_video_goes_to_deepgram_file`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**; add `CLUE_PDL_API_KEY` to `.env.example`/`.env`.
  **Step 4: Run** — PASS. **Step 5: Commit** — "Footprint: find_handles, PDL client, social video reading".

### Task 7: Jev client

**Files:**
- Create: `platform/api/clue_api/footprint/jev_client.py`
- Modify: `libs/clue-config/clue_config/settings.py`, `.env.example`, `.env`
- Test: `tests/footprint/test_jev_client.py`, `tests/footprint/test_jev_client_live.py`

**Interfaces:**
- Produces:
  - Settings `arv2_speaker_check_model: str = "typesafe/jev-1.14"` (env `CLUE_ARV2_SPEAKER_CHECK_MODEL`),
    `arv2_speaker_check_max_chars: int = 120000` (env `CLUE_ARV2_SPEAKER_CHECK_MAX_CHARS`).
  - `class SpeakerCheck(BaseModel)`: `state: Literal["answered","unavailable"]`, `presence: str | None`,
    `presence_probabilities: dict[str, float]`, `is_speaking: float | None`, `label: str | None`,
    `label_probabilities: dict[str, float]`, `windows: int`, `model: str | None`, `cost_usd: float`,
    `reason: str | None`.
  - `check_speaker(caller, api_key, model, *, person: dict, recording: dict, lines: list[str], max_chars: int) -> SpeakerCheck`
    — `lines` are `"[mm:ss] Speaker N: text"`; labels are read from the lines; state keys
    `person_we_research`, `what_we_know_about_the_recording`, `transcript_diarised`, `note`; the three
    questions `presence`, `is_speaking`, `speaker_label` with the exact instructions and criteria in ledger
    section 4.1. Cost from the response's `usage.cost`.
  - Long transcripts: split `lines` into consecutive windows of at most `max_chars`; ask every window;
    combine by averaging each probability weighted by window length; `presence`/`label` are the highest
    combined option. Any HTTP error, timeout or unparseable answer → `state="unavailable"` with `reason`,
    never an exception.
- [ ] **Step 1: Write failing tests** with recorded Jev responses (the five Citi/Dilip/Kuhn runs saved
  during the founder's tests; copy three into `tests/footprint/fixtures/jev/`):
  `test_request_carries_the_agreed_questions` (instructions equal the ledger text),
  `test_answer_parsed` (Citi fixture → `label == "Speaker 1"`, `presence == "speaking"`),
  `test_namesake_answer_is_none`, `test_long_transcript_split_and_combined` (fake: two windows answering
  Speaker 1 0.9 and 0.7 over equal lengths → 0.8), `test_error_returns_unavailable`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**; add the two env lines.
- [ ] **Step 4: Run** — PASS. Then the live test (`_live.py`, run by name once): a two-hour transcript
  (Deepgram an existing 2-hour episode, about $0.52, or reuse a saved one) sent whole; record whether Jev
  accepts it, its time and cost; if it refuses, set the default `max_chars` to the largest size that worked
  and note it in ledger section 4.1.
- [ ] **Step 5: Commit** — "Footprint: Jev speaker check client".

### Task 8: Speaker check in `read_media`

**Files:**
- Modify: `platform/api/clue_api/arv2/media_tools.py` (`read_media`, `open_transcript`)
- Create: `platform/api/clue_api/arv2/media_speaker.py`
- Test: `tests/arv2/test_media_speaker_db.py`

**Interfaces:**
- Consumes: `check_speaker`, `SpeakerCheck` (Task 7); `media_store.load_transcript`, `media_store.attempt`.
- Produces:
  - `async def speaker_check(runtime, version_ref: UUID) -> SpeakerCheck | None` — `None` for account jobs.
    Looks for an `arv2_media_attempt` row of `kind="speaker_check"` for this job and `version_id`; if
    present returns it; otherwise builds the person facts (name, current employer and title, career
    history from the same person record `read_person_state` serves), the recording facts (title, show or
    channel, date, description, source URL), the diarised lines from the saved segments, calls
    `check_speaker` through `runtime.operate("openrouter", "speaker_check", request, fn)` so the same
    request is paid once per job, and saves the attempt with `data=check.model_dump()`.
  - `read_media` success result gains `"speaker_check": check.model_dump()` placed before `"text"`-like
    fields; `open_transcript` result gains the same key for its `version_ref`.
  - `read_media`'s `next_action` drops "do not assign the research subject to a cluster from the episode
    title alone" and says the speaker check above is a model's answer for the agent to weigh.
- [ ] **Step 1: Write failing DB tests** (fake `check_speaker`): `test_person_read_media_carries_speaker_check`,
  `test_speaker_check_paid_once_per_job` (two `read_media` calls on the same version → one fake call),
  `test_two_people_get_their_own_answer` (two person jobs, one recording → two calls, two attempts),
  `test_account_job_has_no_speaker_check`, `test_jev_unavailable_still_returns_transcript`.
- [ ] **Step 2: Run** on the lane test DB — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS, plus
  `tests/arv2/test_media_research.py tests/arv2/test_media_store_db.py`.
- [ ] **Step 5: Commit** — "Research: Jev speaker check on every person-job transcript".

### Task 9: Delete the self-introduction check and the speaker gates

**Files:**
- Modify: `arv2/quality_media.py` (`validate_transcript`), `arv2/media_claims.py` (`attach`),
  `arv2/display/evidence.py:170-180`
- Modify tests: `tests/arv2/test_quality_media_db.py`, `tests/arv2/test_media_research.py`, and any test
  asserting `evidence_backed` on transcript claims
- Test: `tests/arv2/test_transcript_quotes.py`

**Interfaces:**
- `SpeakerIntroduction` and `TranscriptSupport.introduction` are deleted (founder 2026-11-10). This changes
  `submit_transcript_claim@1`'s fingerprint; only the recipe 4/5 profiles pin it, and recipes 2–5 already
  fail to resolve today (`nominate_committee_candidate@1` digest changed), so nothing that resolves today
  breaks. Check: resolving `quality_profiles` for every recipe 1–43, person and account, fails for exactly
  recipes 2–5 before and after the change.
- `validate_transcript` returns `attribution: "unverified"` always and adds the job's saved
  `speaker_check` (if any) as `"speaker_check"` in the claim's media marker; the warning "The quoted voice is
  not corroborated as this person." is removed.
- `media_claims.attach`: the `strong` rule and its use in `outreach_safe` are removed; `attribution` is
  `"unverified"`; the media marker carries the saved `speaker_check`.
- `quality_pages`: no change. Its quote, substring and outreach checks (`quality_pages.py:207-240`) run only
  outside advisory mode (`_validate_sections` returns early when `advisory_research(scope)`, i.e. every
  recipe ≥ 6), so they do not touch any current page. Checked on the lane DB 2026-11-10: contact pages of
  the last 10 days carry 1,086 facts and 595 quotes, all citing claims marked outreach-unsafe, including 6
  transcript quotes whose text is not a copy of the claim's line.
- `display/evidence.py`: no demotion to `source_excerpt` on attribution.

- [ ] **Step 1: Write failing tests:** `test_transcript_claim_outreach_safe_without_introduction`
  (`media_claims.attach` no longer forces `outreach_safe=False` on a person job),
  `test_display_keeps_transcript_quote_as_quote` (the evidence panel keeps `primary_quote` and the quote for a
  contact transcript claim with no `evidence_backed`),
  `test_no_introduction_field` (`"introduction" not in TranscriptSupport.model_fields`), and
  `test_only_recipes_2_to_5_fail_to_resolve` (loop over recipes 1–43 × person/account; the failing set is
  `{2, 3, 4, 5}`).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**; delete the regex and every test that pinned the old
  behaviour (list them in the commit message). **Step 4: Run** `tests/arv2/test_transcript_quotes.py`,
  `test_quality_media_db.py`, `test_media_research.py`, and `uv run pytest tests/arv2 -k "page or display or media" --ignore-glob='*_live.py'`
  on the lane test DB — PASS.
- [ ] **Step 5: Commit** — "Research: delete the self-introduction check and speaker gates".

### Task 10: YouTube coverage check

**Files:**
- Modify: `platform/api/clue_api/arv2/media_acquisition.py` (`_acquire_youtube`)
- Test: `tests/arv2/test_youtube_coverage.py`

**Interfaces:**
- After Gemini's windows return, the last line timestamp is compared with the video duration. If it ends
  more than `max(60 s, 5% of the duration)` early, the missing span is requested once more as one window
  starting at the last timestamp; the result is appended. If it is still short, `Quality.coverage =
  "partial"` with warning `"model_stopped_early_at_<mm:ss>"`. No second retry.
- The podcast version of the same episode is used before Gemini (existing `podcast_twin` in
  `resolve_youtube`); pinned by a test, not changed.
- [ ] **Step 1: Write failing tests** (fake Gemini): `test_short_transcript_rerun_once`,
  `test_still_short_marked_partial`, `test_full_transcript_not_rerun`,
  `test_podcast_version_used_before_gemini` (a video with a matching feed episode never calls Gemini).
- [ ] **Step 2: Run** — FAIL (the first two). **Step 3: Implement.** **Step 4: Run** — PASS, plus
  `tests/arv2/test_gemini_media_client.py tests/arv2/test_media_sources.py`.
- [ ] **Step 5: Commit** — "Research: YouTube coverage check, one re-run of the missing part".

### Task 11: Operation descriptions, prompts and skills — founder review first

**Files (written only after approval):**
- `arv2/footprint_operations.py` (the inner tools' `description` strings, Task 12 imports them)
- `platform/agents/catalog/research-quality/prompts/quality-person-research/v31-person/SYSTEM.md`
- `platform/agents/catalog/research-quality/prompts/quality-account-research/v42/SYSTEM.md`
- any changed skill as a new version directory (e.g. `skills/person-depth-charter/v4/SKILL.md`), never an edit
  of a pinned one; the page-writing skill's line on fixing spelling in recording quotes

- [ ] **Step 1: Draft in chat for the founder** — each new operation's description; the person prompt
  points from design section 6 (whole footprint; search by name and company; read the full description
  first; the metadata rule; read whole transcripts where the person talks most; check a same-name result for
  a link to the day job; confirm a handle from bio and posts; Jev's answer is a model's judgement to weigh;
  if a tool is down use the others; stop when every source type is searched and say what was searched);
  the account prompt's use of company pages and leaders' posts; the page writer's spelling line. Plain,
  clear wording; nothing written to files yet.
- [ ] **Step 2: Founder approves or edits.** Record the approval date in design section 6.
- [ ] **Step 3: Write the approved text** into the files above. **Step 4: Commit** — "Research: footprint prompts and descriptions (founder-approved <date>)".

### Task 12: `acquire_research_evidence` version 3 and the inner jobs

**Files:**
- Modify: `arv2/quality_provider_tools.py` (new `AcquisitionNameV3`, `AcquireResearchInputV3`,
  `AcquireResearchToolV3`), `arv2/account_research_tools.py` (`build_person_tools`, `build_account_tools`
  add the inner tools), `platform/api/clue_api/quality_research_wiring.py` (register V3,
  `make_default=False`; add it to the account-research-only authority set)
- Test: `tests/arv2/test_acquire_v3.py`

**Interfaces:**
- `AcquisitionNameV3` = version 2's names minus `discover_media`, plus `find_podcasts`, `find_videos`,
  `find_handles`, `linkedin_activity`, `x_posts`, `instagram_posts`, `facebook_posts`,
  `company_linkedin_posts`. `AcquireResearchToolV3(AcquireResearchToolV2)`: `version = "3"`,
  `input_model = AcquireResearchInputV3`, its `operations` filtered by `AcquisitionNameV3`. Version 1 and 2
  are unchanged.
- Each inner tool: args model with the inputs in Tasks 4–6, body runs the `footprint/` function inside
  `runtime.operate("treg"|"youtube_data"|"podcast_index"|"pdl", "<job name>", request, fn)` and returns the
  result's `model_dump(mode="json")`. Treg token from `settings.treg_api_key`; a missing key returns
  `{"state": "unavailable", "gap": "treg_key_missing"}`. `find_videos` passes the job's Exa search as
  `exa_fallback`.
- Person jobs get every new job; account jobs get them too (company pages via `company_linkedin_posts` and
  `x_posts`, leaders via the person jobs).
- [ ] **Step 1: Write failing tests:** `test_v2_schema_fingerprint_unchanged` (v2 input/output sha256 equal
  the values pinned in `profiles/quality-person-research/v30-person/profile.yaml`),
  `test_v3_lists_new_jobs_not_discover_media` (capabilities names),
  `test_v3_runs_linkedin_activity_and_saves_result` (fake treg; result at
  `/research/operations/<id>/0.json`; ledger row with treg cost), `test_repeat_call_not_paid_twice`,
  `test_missing_treg_key_is_a_gap`, `test_account_job_has_company_jobs`, and
  `test_saved_post_page_is_citable` (after `recover_acquisitions`, a `JsonSupport` pointing at one post's
  text in the saved page validates).
- [ ] **Step 2: Run** on the lane test DB — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS, plus
  `tests/arv2/test_quality_provider_db.py tests/arv2/test_provider_tool_schema_gate.py tests/arv2/test_import_guard.py`.
- [ ] **Step 5: Commit** — "Research: acquire_research_evidence v3 with the footprint jobs".

### Task 13: Erasure covers the new saved data

**Files:**
- Test: `tests/arv2/test_footprint_erasure_db.py`
- Modify (only if the test fails): the person erasure path that handles `arv2_media_item` and operation
  artifacts

- [ ] **Step 1: Write the test** `test_person_erasure_removes_posts_transcripts_and_speaker_checks`: a person
  job with a saved `linkedin_activity` result, a transcript and a `speaker_check` attempt; run the existing
  person erasure; assert the saved post page, the transcript and the speaker-check data can no longer be
  read.
- [ ] **Step 2: Run.** If it passes, commit the test alone. If it fails, extend the erasure to the missing
  item, run again — PASS. **Step 3: Commit** — "Research: erasure covers saved posts and speaker checks".

### Task 14: Mint recipe 43

**Files:**
- Create: `platform/agents/catalog/research-quality/recipe-v43.json`, `launch-v4-r43.json`,
  `profiles/quality-person-research/v31-person/profile.yaml`,
  `profiles/quality-account-research/v42/profile.yaml`, `tests/arv2/test_quality_recipe_43.py`
- Modify: `arv2/quality_catalog.py` (`CURRENT_RECIPE_VERSION = 43`), `quality_research_wiring.py` (version
  ≥ 43 → `v42` / `v31-person`)

Copy recipe 42's files and change only: profiles pin `acquire_research_evidence` version `'3'` with its
fingerprints; prompts and skills point at Task 11's versions; resource hashes recomputed.

- [ ] **Step 1: Write failing test** in the style of `test_quality_recipe_42.py`:
  `test_recipe_43_pins_match_files`, `test_recipe_selects_its_own_profiles` with
  `[(43, False, "v42"), (43, True, "v31-person"), (42, False, "v41"), (42, True, "v30-person")]`,
  `test_recipe_43_pins_acquire_v3`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Create the files.** **Step 4: Run** the new test plus
  `tests/arv2/test_quality_recipe_42.py` — PASS.
- [ ] **Step 5: Commit** — "Trial recipe 43: footprint jobs, Jev speaker check".

### Task 15: Trial on the U.S. Bank committee

- [ ] **Step 1:** Start the lane stack per `DEV_STACK.md` and run the U.S. Bank committee people and the
  U.S. Bank account on recipe 43 with the trial harness. Report spend before starting (estimate) and after.
- [ ] **Step 2:** For each person, compare with the hand research in `docs/superpowers/specs/research-quality/`:
  podcasts and videos found, LinkedIn/X/Instagram/Facebook read, Jev answers, quotes on the page, gaps the
  agent named, cost per person. For the account: company page posts and leaders' posts used.
- [ ] **Step 3:** Write the results into the ledger (new section) and `_memory/`; commit. Production
  rollout waits for the founder.

---

## Self-review notes

- Spec coverage: design sections 2 (Tasks 1–7), 3 (Tasks 5, 6, 12), 4 (Tasks 7–9; metadata rule in Task 11),
  5 (Task 9), 6 (Task 11), 7 (Tasks 14–15), 8 and 9 (Tasks 12, 9, 13); ledger decision 8 (Task 10).
- Not covered on purpose: the gift agent's own tools; Spotify, LinkedIn comments, voice matching.
