# R2 — Recordings review (trial/research-quality, dd9a7d74a..HEAD)

Scope: podcast/video discovery, transcription coverage, speaker check (Jev), transcript quotes -> claims.
Method: read diffs + full current files; offline repro scripts in this folder (repro_*.py); `uv run pytest tests/footprint -q --ignore-glob='*_live.py'` and `tests/arv2/test_transcript_quotes.py` pass (no DB suites run).

---

## F1 — CRITICAL: YouTube re-ask breaks the paid-transcript recovery path (wrong timestamps, a missing window saved as "full")

- Where: `platform/api/clue_api/arv2/media_acquisition.py:618-645` (recovery) together with the new `covered_window` at `platform/api/clue_api/footprint/gemini_media_client.py:716-738` and its use at `media_acquisition.py:671`.
- What is wrong: the recovery branch (operation exists but no saved transcript, e.g. after a Gemini 503 or a crash) still assumes **one 2xx Gemini body per window**: `if len(bodies) == len(windows)` then `zip(windows, bodies, strict=True)`. Since this branch added `covered_window`, a window that stopped early produces **two** bodies (the original plus the re-ask from the last timestamp). The body count no longer maps to windows.
- Failure scenario (reproduced): 3 windows of 40 min. Window 0 stops early at 16:40 and is re-asked (2 bodies). Window 1 is fine (1 body). Window 2 gets a Gemini 503, so the hop raises and the op becomes `unknown`. That is 3 bodies, which equals 3 windows, so the next `read_media` "recovers": the re-ask body is placed at offset 2400 s instead of 1000 s, window 1 is placed at 4800 s, and window 2 (4800-7200 s) **is never transcribed but the joined transcript says `finish_reason=STOP`** (coverage looks full). Timestamps for two thirds of the recording are wrong by 23-40 min. Quotes then cite the wrong times, and the transcript is saved as a complete version.
  Output of `repro_recovery.py`: lines at 0, 1000, **2400** (should be 1000), **3780**, **4800** (should be 2400), **7190**; `finish_reason: STOP`.
- Second shape: when every window succeeded but saving failed, `len(bodies) > len(windows)` after any re-ask, so recovery returns `acquisition_not_ready_no_automatic_repurchase` for good. The recording is paid for and can never be read for that item.
- Also lost on recovery: the `STOPPED_EARLY_AT_mm:ss` marking (re-parsed from the raw body, which says STOP).
- Verified: code reading plus `repro_recovery.py`, which simulates the recovery zip with the real `covered_window` and `join_windows`. Gemini 503 ending as `unknown` is a known occurrence. This defect is different: it is what happens afterwards.
- Confidence: high.

## F2 — IMPORTANT: speaker check averages windows, so a person who speaks in only part of a long recording is judged absent or a namesake

- Where: `platform/api/clue_api/footprint/jev_client.py:166-221` (`_combine`, `check_speaker`). The window size is `arv2_speaker_check_max_chars=120_000`, so recordings of about 2 hours or more split: long podcasts, conference streams, panels.
- What is wrong: per-window probabilities are combined as a **length-weighted mean**. "Does X speak in this recording?" is true if X speaks in **any** window, but a mean dilutes a confident yes from one window with "no" from the windows where X is absent. The headline `presence`, `is_speaking` and `label` are argmaxes of those means.
- Failure scenario (reproduced, `repro_jev_windows.py`): 3 windows, the person speaks only in window 3 (Speaker 2, p=0.95, is_speaking 0.97). Result: `presence=different_person` (0.65), `is_speaking=0.36`, `label=none` (0.68). The agent is told by the model it was asked to trust that the person is a namesake, and drops real first-person quotes. The reverse also happens: a label picked in one window is used for the whole recording (see F3).
- Confidence: high on the mechanics. How Jev answers windows without the person (`different_person` or `unclear`) only changes the size of the dilution, not the direction.

## F3 — IMPORTANT: speaker-check input is primed with the person's name, and Gemini labels are per window

- Where: `gemini_media_client.py:513-563` (prompts) feeding `media_speaker.diarised_lines` and `jev_client._labels`.
- What is wrong:
  (a) The Gemini YouTube prompt tells the model "The subject is <name>" and asks for labels like `S2 (<name>)`. The long-audio prompt labels lines `<name>:` directly. So for Gemini-made transcripts the transcriber has already put the subject's name on a speaker label. Jev then gets a label list containing the person's name. The check is no longer independent, and the namesake/absent case (the worst failure) is the one it is least able to catch: Gemini, primed with the name, labels someone with it.
  (b) YouTube windows (and now the `covered_window` re-ask) are separate Gemini calls, and their `S1/S2` labels are **not consistent across windows**. `join_windows` does not reconcile them. Jev returns one label for the whole recording, and the agent is told "label S2 is this person". In another window S2 may be a different voice, which invites misattributing that window's quotes.
- Scenario: a 90-minute YouTube panel in 3 windows. Gemini's window 2 "S2" is the moderator. Jev (window-averaged) says S2 is the person, and the agent attributes the moderator's window-2 lines to the person.
- Verified: by reading the prompt text and the window/join code. Not run against a live model.
- Confidence: medium-high (a design defect in what the check is fed; prompts are pre-existing, the dependency on them is new).

## F4 — IMPORTANT: one Exa credit halt disables the free podcast/video searches for the whole job and discards results already fetched

- Where: `footprint_operations.py:278-322` (`_exa_podcasts`, `_find_podcasts`) and `:343-358` (`_find_videos`); latch in `account_research_tools.py:~588-600`.
- What is wrong: Exa search uses `exa_halt_rule`. A 402/credit body raises `ProviderHalted`, which is **not** caught by `_exa_podcasts` (it catches only `ProviderTransportError, RawParseError`) or by the `_find_videos` Exa lambda. It escapes the hop, and `_perform_hop` latches `self.halted["podcast_index"]` (or `"youtube_data"`) as well as `"exa"`.
- Scenario: Exa runs out of credit (or was already latched by another tool; the fresh caller in this hop does not know about that and calls Exa again). find_podcasts loses the Apple and Podcast Index results it already had. Every later find_podcasts/find_videos in the job is refused pre-dispatch as `provider_halted:podcast_index` or `provider_halted:youtube_data`, although those providers are free and healthy. This contradicts the module's rule that "a source that fails is reported as a gap and the others still answer".
- Verified: by reading the class hierarchy (`ProviderHalted` and `ProviderTransportError` are siblings under `SpendError`) and the latch code.
- Confidence: high.

## F5 — IMPORTANT: find_videos throws away all paid results on any single YouTube error, and rate limits are not surfaced as such

- Where: `platform/api/clue_api/footprint/video_search.py:156-188`.
- What is wrong:
  1. A `ValueError` from **any** search or from `videos.list` returns `[], [str(exc)]`, dropping the results of searches that already succeeded (each cost 100 of the 10,000 shared daily quota units).
  2. YouTube's per-user/rate limits come back as 403 `rateLimitExceeded`/`userRateLimitExceeded` (also `dailyLimitExceeded`). Only the literal `quotaExceeded` is recognised, so these become a generic `youtube_data HTTP 403`, with no Exa fallback and everything dropped.
  3. When quota runs out at search k, the results of searches 1..k-1 are dropped and **all** searches are re-run on Exa (paid again).
- Reproduced (`repro_videos.py`):
  - 500 on the 2nd search gives `0 leads ['youtube_data HTTP 500']`.
  - rateLimitExceeded on the 2nd gives `0 leads ['youtube_data HTTP 403']`, and the Exa fallback is never asked.
  - quota on the 2nd gives `[]` (VID1 from search 1 lost) and Exa asked `['a','b']`.
  - `videos.list` 500 gives 0 leads.
- Confidence: high.

## F6 — IMPORTANT: a provider failure reaches the agent as status "empty"

- Where: `quality_provider_tools.py:430-505` (`receipt_preview`) with the bodies from `_find_podcasts` and `_find_videos`, whose `report` line never mentions `gaps`.
- What is wrong: with `n_results == 0` the receipt is `status: "empty"`, and the tool's own description says "status empty means nothing came back". The gaps (YouTube 403/500, Exa HTTP 429, Podcast Index down) live only in the saved file. The report text says "0 video results from 2 searches…".
- Scenario: F5's YouTube 500, or a 429 on every Exa search, tells the agent "there are no videos of this person". The agent records an absence that was really an outage.
- Reproduced (`repro_receipt.py`): `empty: True`, and the preview holds only the report line.
- Related: the Exa fallback in `_find_videos` (`footprint_operations.py:347-354`) never checks `hits.status`. `ExaClient.search` returns HTTP errors (429/5xx) as a result with an empty list, so an Exa outage during fallback becomes 0 results with gap `youtube_quota_exhausted_used_exa`, which suggests Exa answered. `_exa_podcasts` does check status. A transport error from that lambda is not caught either, so the whole job fails.
- Confidence: high.

## F7 — IMPORTANT: a failing speaker check is re-paid and re-waited on every transcript page

- Where: `media_speaker.py:84-126`; `media_tools.py:482-497, 525-536` (`_with_speaker_check` on **every** `open_transcript`).
- What is wrong: only an `answered` check is saved. If Jev is down, times out, or returns a body this code cannot parse (it is an **alpha** endpoint; `KeyError`/`TypeError` are mapped to unavailable **after the call was paid**), every `open_transcript` page asks again, across all windows.
  - Timeout is 300 s with `max_attempts=2`, so up to about 10 min per window per page.
  - Agents page through transcripts 2,000 characters at a time (known cap), so a 60k-character transcript is about 30 pages. That is 30 full paid checks, or about 30 x 10 min stalls.
  - A partial success (window 1 answered, window 2 failed) re-pays window 1 every time.
  - Parallel `open_transcript` calls before the first save each pay too: the check reads, then later writes, with no lock.
- Verified: by reading. `test_jev_unavailable_is_not_saved_and_retried` confirms the retry is intended, but not that it happens per page.
- Confidence: high on the behaviour. The cost per call is small; the latency and runtime-cap exposure is the real risk.

## F8 — IMPORTANT: podcast dedup key merges different episodes and splices their fields

- Where: `platform/api/clue_api/footprint/podcast_search.py:213-239` (`_key`, `_merge`).
- What is wrong: the key is `kind|show|title`. Two distinct episodes or shows with the same show title and episode title (generic titles like "Episode 12", "Trailer", "Bonus"; or several feeds called "The Security Podcast") collapse into one. `_merge` keeps the first episode's `audio_url`/`feed_url` but takes the **longer description** from either, so one lead can pair episode B's description (naming the guest) with episode A's audio.
- Reproduced (`repro_podcast_merge.py`): two PI episodes from two different feeds (different audio, guests "Ada" and "Bob") plus two same-named shows. The 4 leads become 2. Bob's episode and the second feed disappear, which contradicts the "never dropped" rule.
- Scenario: the agent picks the lead because the description names the person, and `read_media` then transcribes the other episode's audio. Saved with that description and title, this is a misattribution.
- Confidence: high on the mechanics. Frequency is moderate (generic titles are common in Podcast Index results).

## F9 — MINOR: the X-video rewrite changes the citation source and pays treg on every read

- Where: `media_tools.py:257-293`.
- What is wrong:
  - An X post URL is replaced by its `video.twimg.com` MP4 **before** the cache lookup. The transcript item, its `source_url` and every claim citing it then point at a CDN file, not the post. The item also has no title or description for the speaker check's `what_we_know_about_the_recording`.
  - Every repeat `read_media` of the same post pays another treg lookup.
  - Errors are mishandled. A treg 4xx (402 credit, 429) yields no variants, so the call silently falls back to the walled-host refusal. A latched treg raises `RefusalError` out of `read_media` rather than falling back. A non-dict `entities` or `media` entry raises `AttributeError` in `_variants`.
- Confidence: high on the source_url change. The rest is a minor robustness issue.

## F10 — MINOR: a leftover gate refuses every contact transcript quote on pages

- Where: `platform/api/clue_api/arv2/quality_pages.py:208-217`.
- What is wrong: commit f4ed6e396 removed the speaker gates and display demotion (founder ruling 2026-11-09), and `attach` / `validate_transcript` now always write `attribution: "unverified"`. `quality_pages` still requires `attribution == "evidence_backed"` for a contact `research:transcript` quote. That condition can no longer be true, so any page sentence of kind `quote` backed by a contact transcript claim raises "primary quotes must be exact original evidence". This contradicts the display path (`display/evidence.py`), which now shows it as a quote.
- It fails closed, so it is not a safety bug, but it is dead or contradictory policy.
- Confidence: high.

## F11 — MINOR: claims cannot tell "speaker check never ran or failed" from "account job"

- Where: `media_claims.py:92-102, 116-124, 204`; `quality_media.py:205-226`.
- What is wrong: claims carry `speaker_check: None` in all of these cases:
  - Jev failed (not saved).
  - the check was never run for that version (a claim made from a version the agent never opened through read_media/open_transcript, or an older superseded version).
  - an account job.
  
  Since f4ed6e396, transcript claims on person jobs are `outreach_safe=True` with no speaker evidence at all (intended by the ruling), so this marker is the only trace a reviewer has. A missing check is indistinguishable from "not applicable".
- Confidence: high.

## F12 — MINOR: DSAR — speaker-check rows and the Jev request bodies are not covered by erasure

- Where: `arv2_media_attempt` rows of kind `speaker_check` (`media_speaker.py:113-125`).
- What is wrong:
  - Nothing in the media or contact erasure paths touches `arv2_media_attempt` (grep: only inserts and reads).
  - The saved label is the transcript's speaker label, which for Gemini transcripts embeds the person's name (F3a).
  - The Jev request (name, title, employer, LinkedIn URL, employment history, transcript excerpt) is saved inline in the raw record whenever it is under 64k characters (`MAX_INLINE_REQUEST_CHARS`).
  - The call is made with no `operation`, so the contact privacy hook (which erases artifacts through `arv2_research_operation.artifact_key`) does not reach it.
- Confidence: medium. It depends on how generic raw records are erased elsewhere; I did not trace the full raw-artifact erasure path.

## F13 — MINOR: smaller find_* issues

- `find_podcasts`: the Apple `lookup` failure is swallowed (`except ValueError: feeds[collection] = None`, `podcast_search.py:304-305`) with no gap recorded. An Exa hit without a title is silently dropped (`_exa_lead` returns None), against "nothing dropped".
- `find_podcasts`/`find_videos`: `queries` has no maximum length (`FindPodcastsArgs`/`FindVideosArgs`). Each video search costs 100 units of a 10,000/day YouTube quota **shared by every job**, so one person job with 20 searches uses 20% of the fleet's daily quota. Noted, not a cap request (founder no-caps ruling); it should at least be visible.
- `covered_window`: the re-ask starts at the last line's start, so that line is transcribed twice (duplicate text and quote). When the first part's finish was `MAX_TOKENS`, the joined transcript stays partial even after the re-ask filled the gap (conservative, but coverage is under-reported).
- `read_media`: the speaker check runs after the paid transcription. An unexpected error there (DB, storage) fails the whole tool after the receipt was earned (the agent can re-read from cache). The receipt's 11 KB trim runs before `speaker_check` is added.
- `open_transcript` with `quote_index` returns a mined quote with no speaker check.
- `media_claims.annotate_drafts` and `guard_draft`: `speaker_for` opens a new connection per draft, nested inside an open one in `guard_draft`.

---

## Checked and fine
- Moved modules (`media_resolution, media_sources, media_feeds_client, gemini_media_client, deepgram_media_client, media_recording, media_types, media_telemetry, openrouter, text`): diffing the base `arv2/` copy with `arv2.` replaced by `footprint.` against the new copy shows only import-path changes. `clue_api.arv2.{calls,errors,transport,sinks}` were already re-export shims of `clue_spend`, so the exception classes are identical. The two real changes are `podcast_index_headers` (a pure extraction, same signing) and `covered_window` (new, see F1/F13).
- `arv2/` shims use `sys.modules[__name__] = moved`, so `import`, `from … import` and `mock.patch` on the old path all hit the same module object. 53 old-path imports still resolve; the footprint tests pass.
- Overview numbering: line N maps to `podcasts[N-1]`/`videos[N-1]` in both overviews; dedupe and order are stable; `found_by` numbers match the deduplicated search list.
- Podcast Index signing, Apple episode parsing, Exa header parsing (`_HEADER`, `_PASSAGE_HEADER`), duration parsing.
- `SpeakerCheck` is never a gate (as ruled). Account jobs skip it. A saved check is reused per (job, version) and validated back into the model.
- `arv2_media_attempt` has no CHECK on `kind`, so the `speaker_check` insert is accepted.
- `jev_client` error mapping: JSON errors are `ValueError`, a missing `answers` key is `KeyError`, a wrong shape is `TypeError`, transport errors are caught; halts become `RefusalError` through `call_provider` and are caught in `media_speaker`.
- `media_store`, `media_retrieval`, `media_tools` (other than the new code above), `quality_media` imports: path-only changes.

## Repro scripts (offline, no providers, no DB)
- /private/tmp/claude-501/-Users-aryankeshri-conductor-workspaces-research-and-data-research-trial/7b4c6fab-cdd6-4591-80a2-9a98dab021da/scratchpad/review/repro_recovery.py (F1)
- /private/tmp/claude-501/-Users-aryankeshri-conductor-workspaces-research-and-data-research-trial/7b4c6fab-cdd6-4591-80a2-9a98dab021da/scratchpad/review/repro_jev_windows.py (F2)
- /private/tmp/claude-501/-Users-aryankeshri-conductor-workspaces-research-and-data-research-trial/7b4c6fab-cdd6-4591-80a2-9a98dab021da/scratchpad/review/repro_videos.py (F5)
- /private/tmp/claude-501/-Users-aryankeshri-conductor-workspaces-research-and-data-research-trial/7b4c6fab-cdd6-4591-80a2-9a98dab021da/scratchpad/review/repro_receipt.py (F6)
- /private/tmp/claude-501/-Users-aryankeshri-conductor-workspaces-research-and-data-research-trial/7b4c6fab-cdd6-4591-80a2-9a98dab021da/scratchpad/review/repro_podcast_merge.py (F8)
Run each from the worktree root with `uv run python <script> 2>/dev/null`.
