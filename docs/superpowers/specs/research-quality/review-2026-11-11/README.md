# Branch review — trial/research-quality (2026-11-11)

Adversarial review of the 125 commits since `dd9a7d74a`, by five independent reviewers (one area
each), every important finding re-checked by the orchestrator (reproduction re-run, code read, or
the r44a trial's stored data inspected). Detail, line numbers and reasoning live in the five
reports; reproductions are in `repro/` (run from the worktree root:
`PYTHONPATH=. uv run python docs/superpowers/specs/research-quality/review-2026-11-11/repro/<file>`).

| Report | Area |
|---|---|
| `r1_social.md` | LinkedIn / X / Instagram / Facebook readers, short links, find_handles |
| `r2_recordings.md` | podcast and video search, transcription, speaker check, transcript quotes |
| `r3_tool_surface.md` | acquire_research_evidence v3, operations, receipts, erasure, crash recovery |
| `r4_lifecycle.md` | account driver, review turn, pages, reconciliation, restarts |
| `r5_integrity.md` | code moves, agent-facing text vs code, test honesty, leftovers |

The trial-run observations (retry_of trap, uncitable social posts, hand-off paths, deadlock,
2,000-character transcript windows, short-link noise, context size) are separate and listed in the
chat of 2026-11-11; they are not repeated here.

## Status

- **I1 fixed** in `25de51b1d` (with the social part of I4, and the malformed-item crash of I7 for
  the social readers). Provider replies it relies on: sources ledger, section 0a, "What each social
  provider sends when there is nothing to read".
- **I2, I3 fixed** in `3aa7d0fcf` (podcast and video searches; search part of I4).
- **I5 and C1 fixed** in `94e07722e` (find_handles failures named; PDL record trimmed to the
  handle fields before it is stored; handles part of I4).
- **I6 fixed** in `1a81709bc` (X ownership by account id; other accounts' tweets marked `in_feed`).
- **I8 fixed** in `00eedc3af` (short links read, never followed; no spend, evidence or trace
  noise; the redirect-loop crash of I7 gone).
- **I4** is complete for every footprint job: an identical call after a failure re-runs the whole
  call (founder ruling 2026-11-11: whole call, not only the missing part).
- **Correction:** I9 is not live. The rule at `quality_pages.py:211` sits after the advisory return
  every recipe from 6 on takes (line 148); it is a leftover the spec had listed for deletion.
- **I9, I10 fixed** (review tags `review/quote-sources/start..end`). Founder ruling 2026-11-11: a
  quote on a page must cite the finding it came from; code never compares its words with the
  finding, and plain sentences are not checked for citations. `page_writer.check_pages` keeps one
  rule, "quote without a source"; the word comparison and the "uncited fact" rule are gone; the
  inactive `quality_pages` rules (every sentence cited, the recording-quote rule of I9) are deleted.
  The private-matter word list stays (founder, 2026-11-11).
- **I12 fixed** (review tags `review/speaker-names/start..end` and `review/neutral-prompt/start..end`).
  Founder 2026-11-12, after the evidence check (Google: speaker separation Experimental; a 2026 study:
  Gemini 3 Pro wrong on ~1/3 of "who said what" lines; r44a: Gemini put a Google Cloud panelist's
  lines under Ann, caught by Ann's agent): Gemini's name on a line is a strong hint, not proof; the
  agent decides with the transcript and Jev. `join_windows` writes one label per named speaker across
  parts in both the lines and the text the agent reads; an unnamed number keeps its part. The
  transcription prompts no longer say the person is present, name a speaker only when the recording
  says or shows who they are, and ask only for META and TRANSCRIPT (QUOTES and BUYING dropped).

## Critical

- **C1 Personal data stored and citable.** find_handles keeps the whole People Data Labs record.
  In r44a all 5 stored records hold personal emails and/or a mobile phone, 2 a birth date, and each
  is a `provider_record` evidence entry the agent can read and cite. Policy is work email only.
  (r3 #4, verified in the trial DB by field names only.)
- **C2 Another author's LinkedIn post filed as the person's own.** No author check; preview hides
  the author. (r1 critical, reproduced.)
- **C3 Recovered YouTube transcript misaligned.** The recovery path pairs saved Gemini answers to
  windows by position; the new re-ask breaks that: text 23–40 min off, a window missing, marked
  complete. (r2 F1, reproduced.)

## Important — failures reported as results

- **I1 Social readers turn errors into answers.** Page-1 402/401/429 or error envelope → `not_found`
  (X, company) or `complete, 0 posts` (LinkedIn, Instagram, Facebook); a failure on page 2+ →
  `complete` with no gap; `partial` reaches the agent as `completed`. (r1 #2–5, r3 #2, reproduced.)
- **I2 Recording searches lose or hide results.** One YouTube error discards every search's results;
  rate-limit 403 not recognised; Exa fallback ignores HTTP status; 0 results → receipt `empty` with
  the gaps only in the file. (r2 F5–F6, r3 #1, reproduced.)
- **I3 An Exa credit stop disables the free sources for the whole job** (podcast and video), and
  the results already fetched are thrown away. (r2 F4, r3 #6, r5 #3.)
- **I4 Wrong outcomes are permanent.** Each operation settles once per job and argument hash; an
  identical retry replays the outage. (r3 #1.)
- **I5 find_handles hides a PDL failure as "no handles".** (r1 #8.)
- **I6 Renamed X handle → every own tweet becomes a repost**, and long quotes are not read in full
  yet marked uncut. (r1 #7, reproduced.)
- **I7 Crashes after paying.** A malformed provider item, or a short-link redirect loop, raises and
  loses the whole paid result. (r1 #6 and E1, reproduced.)
- **I8 Short-link opener follows redirects to any host with no size limit** (possible SSRF); the
  safer `PublicMediaTransport` exists and is unused. (r1 #6, r5.)

## Important — quotes and the speaker check

- **I9 Contact quotes from recordings can never reach a page.** `quality_pages.py:211` requires
  `attribution == "evidence_backed"`; commit `f4ed6e396` deleted the only code that wrote it.
  (r2 F10, upgraded from minor.)
- **I10 Page guide v4 contradicts the page quote check.** The guide says fix transcription
  spelling; `page_writer.py:229-234` rejects any quote not literally in the finding. (r5 #1.)
- **I11 Speaker check averages windows**: someone speaking in only one window of a long recording
  comes out `different_person`. (r2 F2, reproduced.)
- **I12 Speaker check is fed name-primed labels** from the transcription prompt, and labels are not
  consistent across YouTube windows. (r2 F3, by reading.)
- **I13 A failing speaker check is paid again on every transcript page.** (r2 F7.)
- **I14 Podcast de-duplication merges different episodes** (show + title key). (r2 F8, reproduced.)

## Important — run lifecycle and crash recovery

- **I15 The review brief is ignored by default.** Recipe 44 pays for a review turn; the page writer
  reads the brief only for guide v3/v4; code default and `.env.example` say v2 (`.env` says v3 —
  parity broken). (r4 #1, verified.)
- **I16 A failed page step is a dead end**: generation marked `needs_review`, no requeue, job
  `completed` so the resume script cannot see it. Root of the r44a stuck pages. (r4 #3, verified.)
- **I17 A review turn can leave a draft dossier and the account gets no pages.** (r4 #2.)
- **I18 A person parked by a deploy (`suspended`) counts as finished**: the paid review and pages
  run without them, then again. (r4 #4.)
- **I19 Worker death mid-call loses the spend record and the data**: ledger rows kept in memory
  until the call ends, operation stays `running` for the 2-hour lease, agent told to look in
  /evidence where nothing is; a stopped turn never settles the operation. (r3 #5.)

## Important — erasure and gates

- **I20 Erasure misses leaders' social histories read by the account job** (bound to the account,
  not the person), and raw treg/PDL pages are never bound to the person. (r3 #3, r5 #2.)
- **I21 "footprint never imports arv2" holds only in source text**: importing footprint loads 52
  arv2 modules through `clue_api/__init__.py`. (r5 #5, verified.)
- **I22 Lint gate red**: `trial/` is not excluded (`trials` is), 173 ruff errors; 6 new mypy errors.
  (r5 #4, #8.)

## Minor

See the reports. Main ones: retweet without original keeps clipped "RT @…" text; reaction date
overwrites the post's date; company paging can stop early on an end-date tie; same long quote paid
per quoting tweet; argument variants paid twice (`@handle` vs `handle`); saved file does not open
with the overview; replayed receipt loses its preview; two identical calls in one round race; X post
link replaced by its CDN video link before caching; quote opened by `quote_index` has no speaker
check; Apple lookup failure swallowed; `queries` unbounded; re-ask transcribes the boundary line
twice; fallback page brief can be stale or unchecked; restart-fresh review continues the old
conversation; no-progress cap off by one; review-imported claims trigger a second review; trial
launcher has no DB guard; agent-facing text mismatches (search_web `type=auto`, "X video is never
read" in three places, read_media and LinkedIn post links, find_videos promise, stale docstrings,
skills v3/v7 leftovers); tests that cannot catch the defects above (hand-written fixtures, erasure
test never erases, import guard checks text only).
