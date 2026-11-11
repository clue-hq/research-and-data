# R5 — Branch integrity review (trial/research-quality, dd9a7d74a..HEAD, 125 commits)

Read-only. No edits, commits, paid calls or DB writes. Throwaway scripts in this folder.

## Test runs (offline)

- Requested set: `uv run pytest tests/footprint tests/arv2/test_acquire_v3.py tests/arv2/test_page_writer.py tests/arv2/test_quality_recipe_43.py tests/arv2/test_transcript_quotes.py --ignore-glob='*_live.py'` → **144 passed, 0 skipped** (21.6 s). Note: the repo's addopts print nothing under `-q`; I ran with `-o addopts=""` to see the summary.
- Extra, non-DB: recipe 40/41/42 tests, committee seat labels, import guard → 32 passed.
- Extra, the old-path (`clue_api.arv2.<moved>`) suites: test_media_sources, test_media_research, test_media_resolution_fixes, test_deepgram_media_client, test_media_source_links, test_gemini_media_client, test_text, test_openrouter, test_media_recording, test_media_feeds_client, test_media_feed_transcripts, test_account_research_tools, test_person_continuation_preview, test_account_research_agent → 344 passed.
- No `*_db.py` or `*_live.py` run.

## 1. Moves (arv2 → footprint)

**Result: no unintended behaviour change; shims are complete.**

- All ten moved modules (gemini_media_client, media_resolution, media_sources, media_feeds_client, media_recording, media_types, media_telemetry, openrouter, text, deepgram_media_client) diffed against `dd9a7d74a` with import lines stripped. Only differences besides docstring path strings:
  - `gemini_media_client`: new `covered_window` + `COVERAGE_SLACK_*` (a deliberate feature, founder 2026-11-09; used by `media_acquisition.py:671`, tested by `tests/footprint/test_youtube_coverage.py`). The import block moved `calls/errors/sinks/transport` from `clue_api.arv2.*` shims to `clue_spend.*` directly — same objects (the arv2 versions are `from clue_spend.X import *` shims).
  - `media_sources`: `podcast_index_headers` extracted from the inline signing code (identical computation; now also used by podcast_search).
  - The other eight: byte-identical apart from import paths/docstrings.
- Shims are `sys.modules[__name__] = <footprint module>` aliases, so every name (including `_private` ones) re-exports. 64 old-path references across tests/scripts/trial (list in `old_path_refs.txt`) all resolve; `test_old_paths_are_the_same_module` asserts identity; the 344 old-path tests pass.
- Monkeypatch targets: because old and new paths are the same module object, a test patching `clue_api.arv2.X.attr` patches the object the runtime uses. No test patches one path while the code reads a separately bound copy *because of the move* (the usual `from m import f` binding caveat is unchanged from before the move). No vacuous patches found.

### Finding M-1 (important) — "footprint never imports arv2" holds only syntactically
- Files: `tests/footprint/test_footprint_imports.py:24-36`, `platform/api/clue_api/footprint/__init__.py:3`, root cause `platform/api/clue_api/__init__.py` (pre-existing) → `agent_runtime_wiring.py:66` → `chat/__init__.py:31` → `chat/router.py:66`.
- What: importing ANY footprint module (`clue_api.footprint.text`, `.media_types`, `.openrouter` …) loads ~50 `clue_api.arv2.*` modules (calls, errors, sinks, transport, display.*, discovery_*, onboarding_*, quality_generation, research_operations …) through the `clue_api` package `__init__`. The guard walks only footprint's own AST for absolute `clue_api.arv2…` names; it also ignores relative imports (`from ..arv2 import x` → `module="arv2"`, `level=2`).
- Consequence: the docstring's promise ("Nothing here imports clue_api.arv2; … later, the gift agent wrap[s] these functions") is false at runtime; a separate consumer (gift agent) importing footprint would pull the whole ARV2 lane and its import-time side effects. The test cannot catch this.
- Verified: `python scratchpad/review/trace.py clue_api.footprint.text` prints `arv2 loaded: True` with the stack above; `clue_spend.calls` alone does not load arv2.
- Confidence: high (behaviour); the root import is pre-existing, the claim/guard are new.

## 2. Agent-facing text vs code

Pinned for recipe 44: account prompt v42 + profile v42 (skills: governed-evidence v5, account-dossier v19, person-research-briefing v7, claim-ready-account-dossier v4, account-review v2); person prompt v31-person + profile v31-person (person-dossier v7, person-depth-charter v3, claim-ready-person-dossier v6). acquire_research_evidence v3 = v2 operations minus `discover_media` plus the eight footprint jobs.

### T-1 (important) — page guide v4 tells the writer to fix recording quotes; the code rejects fixed quotes
- Text: `skills/research-page-writing/v4/SKILL.md:106`: "When you quote a recording, write the person's words as the transcript has them. Fix only spelling and punctuation the transcription got wrong."
- Code: `platform/api/clue_api/arv2/page_writer.py:229-234` — every quoted span (≥12 chars inside “ ” or "…") must be a substring of the cited findings' text after `_norm` (`page_writer.py:163-167`: NFKC, curly→straight quotes, dashes, whitespace, lower-case only). A corrected spelling ("Venkateshwari"→"Venkatachari") or changed comma fails with `quote not in cited findings`. The person prompt (v31, line 50) makes the researcher store the transcript line verbatim "transcription mistakes included", so the finding always holds the misspelling.
- Consequence: following the guide produces a check failure; `write_checked` (`page_writer.py:254-291`) allows one repair, then raises `PageWriterError` and the page set is not written. Only bites when `CLUE_ARV2_PAGE_GUIDE_VERSION=v4` (code/.env.example default is v2; the trial uses v4 per HEAD commit `0046cd6de`).
- Verified by reading both; `tests/arv2/test_page_writer.py::test_guide_v4_is_v3_plus_the_recording_quote_line` only asserts the line exists; no test runs `check_pages` on a spelling-fixed quote. Confidence: high.

### T-2 (minor, pre-existing wording carried into v42) — `search_web (type=auto)`
- Text: account v42 SYSTEM.md "…ordinary search_web calls (type=auto)…"; account-dossier v19:39 "Ordinary search_web (type auto)".
- Code: `SearchWebArgs` (`account_research_tools.py:1184-1189`) has `query, num_results, include_domains, start_published_date, end_published_date`, and `_Args` is `extra="forbid"` (`:1157-1160`). An agent that sends `"type": "auto"` gets the durable refusal `invalid_acquisition_arguments` (`quality_provider_tools.py:236-247`).
- Confidence: high that the argument does not exist; whether the model actually sends it is unobserved.

### T-3 (minor) — X video: docs/law-11 text says it is never read; the branch reads it
- Code: `media_tools.py:256-275` `_x_video_link` turns an X status link into its MP4 (`footprint/social_video.py`, ScrapeCreators via treg) before `read_media` resolves it; X post `video_urls` also come back from `x_posts`.
- Text still saying otherwise: `footprint/media_feeds_client.py:512-519` ("LinkedIn and X serve their video only to their own player; there is no artifact to download and no lawful way to take one"), `media_tools.py:74` (`_walled`: "LinkedIn and X: read_media never reads them"), `docs/superpowers/specs/research-quality/media-and-social-sources-ledger.md:130` ("LinkedIn and X video are never read").
- Consequence: the policy statement (law 11 walled-media clause) and the behaviour now disagree; worth a founder ruling either way. Confidence: high.

### T-4 (minor) — person prompt sends "the posts you read" to read_media; LinkedIn post links are refused
- Text: v31-person "Follow relevant recordings from find_podcasts, find_videos and the posts you read with read_media".
- Code: a linkedin.com URL is walled (`WALLED_MEDIA_HOSTS`, `media_feeds_client.py:54`) and refused; only the file link in the post's `video_urls` works. Neither the read_media capability description (`account_research_tools.py:3350-3357`) nor the prompt says to pass `video_urls` rather than the post link. X post links do work (T-3).
- Confidence: medium (depends on what the model passes).

### T-5 (minor) — find_videos description vs Exa-fallback results
- Text (`footprint_operations.py` `_TEXT["find_videos"]`): "Each comes with its full description, tags, channel, length…".
- Code: without a YouTube key, or after the daily quota, leads come from Exa (`video_search.py:163-189`, `_bare`) with no title/description/length; the overview shows "(no details) <url>". Also the Exa fallback returns at most 10 hits per search vs 25 from YouTube.
- Confidence: high.

### T-6 (minor) — stale module docstring
- `footprint_operations.py:8-10`: "The descriptions below are short and functional. The wording the agent reads is agreed with the founder first (plan Task 11) and replaces them." The `_TEXT` block is already marked founder-approved 2026-11-11. Confidence: high.

### T-7 (minor) — account-review v2 brief sections vs the page writer's sections
- Text (`skills/account-review/v2/SKILL.md`, "The sections"): why they fit, why now, buying committee, how to approach, watch-outs, buying signals, money and momentum, tools they already use, how they sell, also worth knowing.
- Code (`page_writer.sections_for("v4")`): overview = why-they-fit, why-now, **what-they-do**, buying-committee, how-to-approach, watch-outs; insights = …, miscellaneous. The brief never covers `what-they-do`. Confidence: high.

### T-8 (minor) — pinned skills still carry instructions v31 deliberately removed
- `skills/person-depth-charter/v3/SKILL.md:46-47` (pinned with v31-person): "If you saw a post only in their profile's activity, search its words to find its own URL… If you can't find it, say … its own URL was not found." v31-person dropped exactly this sentence in favour of `linkedin_activity` (which returns each post's own URL). `person-dossier/v7` still says "The same search over different date windows is not a cosmetic variation" (the v30 date-window LinkedIn method).
- Consequence: conflicting guidance on how to find LinkedIn posts. Confidence: high (text), impact low.

### T-9 (minor) — briefing skill seat list predates the new seats
- `skills/person-research-briefing/v7/SKILL.md:35-38` lists what to confirm for economic buyer, champion, technical evaluator, blocker; the nomination tools and v42 prompt also have `executive_sponsor` and `user` (`test_committee_seat_labels.py`). Confidence: high.

### T-10 (minor) — receipts for social jobs hide two states the prompt relies on
- v31-person: "Personal accounts are often private. That is an answer." Code: a `private`/`not_found` history (`social.py:110`) is not in the refused set (`quality_provider_tools.py:255-263`); with `n_results=0` the receipt says `empty`, the same as an account with no posts. The agent must open the file to see `state: private`.
- Reactions: `_title` (`footprint_operations.py:186-194`) shows the liked post's text with no "liked" marker in the receipt preview; only `kind: reaction` in the file distinguishes it from the person's words.
- Confidence: high.

### Covered and matching (no finding)
Operation names, argument names and examples for all eight footprint jobs match the pydantic models (and `test_every_new_job_explains_its_arguments_and_shows_a_valid_example` validates each example); overview format claims (show/channel, title, date, length, found-by, heard guests) match `podcast_search.overview` / `video_search.overview`; saved-file key order (overview before podcasts/videos) holds because the wrapper stores `sort_keys=True` and the view re-serialises in that order (`quality_views.py:322-326`); `text_may_be_cut`, short-link addresses (`links`), reshare `shared` authorship, speaker check with per-answer probabilities (`jev_client.SpeakerCheck`), `additional_queries` on account `research_deep` and "no separate probes field" (`AccountResearchDeepArgs`), `/outputs/page-brief.md` and `/work/review/input.json` paths, `/research/person-brief/0.json`, `/research/parent-account-dossier.json`, "eleven areas" (account-dossier v19 lists exactly 11), and all `{{skills.*.path}}` placeholders resolve to skills pinned in the matching profile.

## 3. Test honesty

- **H-1 (important)** No test for T-1: the v4 page-guide test (`test_page_writer.py:493-512`) checks the guide text and loading, never that a spelling-fixed recording quote passes `check_pages`. The mismatch would have been caught by one call.
- **H-2 (important)** No test that an *account* job's `linkedin_activity`/`x_posts` of a named leader is reachable by that person's DSAR erasure (see L-2). `test_footprint_erasure_db.py` only covers a person job, where binding to the contact is automatic.
- **H-3 (minor)** `test_footprint_imports_nothing_from_arv2` cannot fail for the real risk (M-1): AST-only, absolute names only, no runtime import check.
- **H-4 (minor)** Social fixtures (`tests/footprint/test_social.py`) are hand-built dicts, not recorded treg/TikHub/ScrapeCreators bodies. In particular the company-reshare URL is built as `…/feed/update/urn:li:activity:{urn}/` (`social.py:520`) from `urn or share_urn`; the test feeds a made-up urn, so whether that produces a working link on real data is unverified. Comments say shapes were "checked 2026-11-10/11" live, but no recorded body backs the test.
- **H-5 (minor)** Missing negative paths: ProviderHalted from Exa inside `find_podcasts`/`find_videos` (L-3); YouTube quota hit on the 2nd+ search (results from earlier searches are dropped, `video_search.py:183-186`; the test only covers quota on the first call); `find_videos` with no `clients.exa`; `find_handles` with treg missing but PDL present (returns `unavailable` though PDL alone could answer).
- **H-6 (minor, trivia pins)** `test_quality_recipe_43.py::test_account_research_is_told_to_use_the_footprint_jobs` pins exact prompt/skill sentences; `test_jev_client.py::test_settings_defaults` pins `120_000`. Intentional, but they fail on approved rewording rather than behaviour.
- **H-7 (minor)** `test_transcript_quotes.py::test_only_recipes_2_to_5_fail_to_resolve` swallows any `Exception`; a recipe 2–5 failing for a new reason, or a new failure mode in those versions, is indistinguishable.
- Positive: `test_quality_recipe_43.py` really checks launch pins, profile tool-schema fingerprints for v3 against the live descriptor, and graph validation; `test_acquire_v3.py` exercises the real `_find_podcasts/_find_videos` bodies and `receipt_preview`; `test_youtube_coverage.py` exercises `covered_window` + `join_windows`. No assert-on-mock tautologies found in the offline set.

## 4. Leftovers and hygiene

### L-1 (important) — `trial/` is not excluded from ruff; the lint gate is red
- `pyproject.toml:60` `extend-exclude` has `"trials"`, not `"trial"`. `uv run ruff check trial` → 173 errors (T201 prints, E702, I001, B023 …); `ruff format --check` → 9 trial files would be reformatted. `make lint` / `make check` (`ruff check .`, `ruff format --check .`) therefore fail on this branch.
- Outside trial/: 1 E501 (`conversation_naming.py:3`, pre-existing line) and `arv2/onboarding_driver.py` would be reformatted (unformatted block around 673-690; the branch touched 1 line of the file).
- `trial/worker.py` (the person-job hold hack via `TRIAL_HOLD_PERSON_JOBS`, monkeypatching `Arv2AccountResearchWorkHandler._offer_committee`) is trial-only and not imported by platform code — fine, but it is the main lint offender. `trial/pwexp/` (real research output, 9.3 MB) is excluded via `.git/info/exclude`, not tracked — fine.
- Confidence: high.

### L-2 (important) — leaders' social histories read by the account job are not bound to the person for erasure
- Code: the evidence wrapper binds each saved result to `runtime.scope.person_subject_id or runtime.scope.account_id` (`quality_provider_tools.py` INSERT INTO agent_artifact_subject, ~line 318-327). On an account job `person_subject_id` is None (`account_research_claims.py:191-198`). `erase_subject` finds artifacts only by that binding (`agent_turn_wiring.py:1804-1827`).
- The v42 prompt now tells the account agent to "read what they post with linkedin_activity" for leaders (and reactions are available too). Those full personal post histories are saved bound only to the account; a DSAR erasure of the person does not reach them.
- Confidence: high on the binding; medium on whether another erasure path (account-level) is expected to cover it.

### L-3 (important) — an Exa halt inside find_podcasts/find_videos kills the whole job and latches unrelated providers
- `_exa_podcasts` (`footprint_operations.py:263-283`) catches only `ProviderTransportError, RawParseError`; `ProviderHalted` (Exa has `exa_halt_rule`, `exa_client.py:653`) propagates out of `find_podcasts`, so the Apple/Podcast Index results of that call are lost. `_dispatch` then latches `halted["podcast_index"]` (the hop label) and `halted["exa"]` (`account_research_tools.py:592-600`), and every later `find_podcasts` in the job is refused pre-dispatch even though Apple/PI still work. Same pattern for `find_videos` (Exa fallback inside the `youtube_data` hop, `footprint_operations.py:322-331`) and for PDL inside `find_handles` (hop label `treg`), if PDL ever halts.
- Confidence: medium (traced by reading; no test).

### L-4 (minor) — new mypy errors on branch code
`uv run mypy platform/api/clue_api libs/clue-spend/clue_spend libs/clue-config/clue_config` → 11 errors; 6 on lines added by this branch (blame vs base): `quality_markdown_dossier.py:152,252,255`, `page_writer_runtime.py:493` (Any returned as `UUID|None`), `quality_review.py:138` (JsonValue dict-item), `account_research_driver.py:1053` (false positive from conditional `**{...}` kwargs at 1052-1053). The other 5 pre-date the branch, so `make typecheck` was already red at base.

### L-5 (minor) — short-link opener follows redirects
`footprint/short_links.py:46-61` fetches t.co / lnkd.in through `HttpxTransport` (`follow_redirects=True`, `clue_spend/transport.py:90`). If either service answers with a redirect instead of its interstitial page, the worker GETs an attacker-chosen address (blind SSRF; body discarded). Media fetches use `PublicMediaTransport` for exactly this. Also `except SpendError` there swallows `ProviderHalted`. Confidence: medium (depends on t.co/lnkd.in behaviour for the browser UA).

### L-6 (minor) — env parity
`CLUE_PDL_API_KEY` (`Secrets.pdl_api_key` alias, `AliasChoices("CLUE_PDL_API_KEY","PDL_API_KEY",…)`) appears in `.env.example` only inside a comment (lines 860-862), deliberately left unset because an empty value would shadow `PDL_API_KEY`. Every other new setting (`CLUE_TREG_API_KEY`, `CLUE_TREG_BASE_URL`, `CLUE_ARV2_SPEAKER_CHECK_*`, `CLUE_ARV2_PERSON_STALL_WAIT_S`, `CLUE_ARV2_JOB_MAX_ATTEMPTS_NO_PROGRESS`, page guide v3/v4) is present with its default. Rule-strictly a gap; the reason is documented.

### L-7 (minor) — edge cases
- `covered_window` (`gemini_media_client.py:716-737`): if the first part's last timestamp is 0, `resume == start` and the identical window is bought again.
- `find_videos` quota on a later search discards the YouTube results already paid for and re-runs every search on Exa (`video_search.py:183-186`).

### Searched, nothing found
No TODO/FIXME/XXX/breakpoint/print added under platform/libs/subsystems; no `trial/` or `TRIAL_` reference from platform code; no hard-coded keys or user paths in new code; broad `except Exception` added only at `account_research_driver.py:984` (review turn; logged, retried up to `arv2_job_max_attempts_no_progress`, then pages are written with `needs_review` — documented fallback, not silent) — the gemini one is pre-existing. No unreferenced top-level functions/constants in the new footprint/arv2 modules.
