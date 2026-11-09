# Footprint tool set: design for review

Status: **draft for the founder's review, 2026-11-09.** Nothing here is built. Sources, prices and test
results are in `media-and-social-sources-ledger.md`; the founder's rulings are its section 0.

## 1. What this is for

Person research (and account research, and later the gift agent) must find and read what a person has said
in public: podcasts, videos, LinkedIn, X, and public Instagram and Facebook. Today the agent has one Exa
search that mostly returns namesakes, cannot read LinkedIn or X at all, and a speaker check that stops a
person's own words from ever appearing on their page as a quote.

The gift pilot (`~/gift-poc`) shows what works: a few tools that each do the legwork for one job, long results
saved where the agent can page through them, and a prompt that says how to research, not just what to find.

## 2. Where the code lives

A new package `platform/api/clue_api/footprint/`, beside `arv2/`. It holds everything that does not depend on
an ARV2 research job, so the gift agent can use it later without ARV2.

**Moves into `footprint/` unchanged (research-agnostic today):** `media_types`, `media_recording`,
`media_feeds_client`, `media_sources`, `media_resolution`, `deepgram_media_client`, `gemini_media_client`,
`media_telemetry`. Old import paths in `arv2/` keep working as one-line re-exports until callers are moved.

**Stays in `arv2/` (tied to the research job, claims or quality pages):** `media_store`, `media_operations`,
`media_acquisition`, `media_retrieval`, `media_claims`, `quality_media`, `quality_media_tool`.

**New in `footprint/`:**
- `podcast_search` – Apple + Podcast Index by person and by keyword, one call (the gift agent's
  `find_podcasts`).
- `video_search` – YouTube Data API search with the quoted name, then full details of each hit.
- `treg_client` – one HTTP client for the treg tools: LinkedIn posts and reactions (fetchinio), X timeline
  (TikHub), short X and Instagram video transcripts and Instagram/Facebook posts (ScrapeCreators), tweet
  lookup for X video files. Cost read from treg's `X-Treg-Cost-Micro` header.
- `pdl_client` – person enrichment for X and Facebook handles.
- `jev_client` – the speaker check through OpenRouter's Decisions API (`typesafe/jev-1.14`).

Every provider call goes through `clue_spend` (`CallSpec` with a cost reader, `ProviderCaller.call`) so it
lands in `provider_call_ledger`, and through `runtime.operate` in ARV2 so a job never pays twice for the same
request. The arv2 import guard (`tests/arv2/test_import_guard.py`) gets `clue_api.footprint` added to its
allowed list.

## 3. What the agent sees

The quality lane gives the agent one tool, `acquire_research_evidence`, with named operations; results are
saved as files under `/research/operations/<id>/` and transcripts under `/research/transcripts/<v>/`, which
the agent reads with its file tools (`ls`, `read_file`, `grep`). That already is the gift agent's
"saved with an ID, page through it" pattern, so **no new reading tools are needed.**

My call: add the new jobs as operations of `acquire_research_evidence` version 3, not as separate tools. It
keeps receipts, replay and cost handling in one place. The agent learns each operation from
`/research/capabilities/0.json`, so each operation's description must be written as carefully as a tool's.

| Operation | Takes | Does | Gives back |
|---|---|---|---|
| `find_podcasts` (new) | name, company | Apple + Podcast Index (by person, by keyword); removes duplicates; fills missing feed links; puts episodes naming the person and company first. Never drops a result. | Show, title, date, description, links found in it, feed, audio link, publisher transcript link |
| `find_videos` (new) | name, company | YouTube search with the quoted name, then full description, tags, channel and length for each hit; Exa on youtube.com when the YouTube quota is used up | Title, channel, date, length, full description, tags, links found in it |
| `read_media` (extended) | a link or a found item | Transcribes podcasts from the publisher transcript, else Deepgram on the file. YouTube: the podcast version of the same episode if there is one, else Gemini on the link, with a coverage check (last timestamp against the video length; the missing part re-run once). Model set by `CLUE_ARV2_MEDIA_VIDEO_MODEL`, chosen by the founder. Now also reads LinkedIn, X, Instagram and Facebook video (short X/Instagram clips by ScrapeCreators, the rest by Deepgram from the file link). Runs the speaker check (section 4). | Transcript saved as files, with the speaker check's answer at the top |
| `search_transcripts`, `open_transcript` (kept) | | as today | |
| `linkedin_activity` (new) | profile link, `posts` or `reactions` | Pages through the person's whole history | Every post saved to files; a receipt with counts and date range |
| `x_posts` (new) | handle | Pages through the TikHub timeline | Same |
| `instagram_posts`, `facebook_posts` (new) | handle or profile link | Public posts only; a private account returns "private" and costs nothing | Same |
| `find_handles` (new) | name, company, LinkedIn link | PDL for X and Facebook; same-handle check for Instagram | Candidate handles, each to be confirmed by the agent from its bio and posts |

Dropped: `discover_media` as the main route (its Exa search stays only as `find_videos`' fallback).
Not in this version: LinkedIn comments (untested), Spotify, Listen Notes, Podscan, Podchaser, Google,
conference sites, the Wayback archive.

## 4. Speaker check

- The old self-introduction check is deleted, with everything that depends on it: `SpeakerIntroduction` and
  the regex in `validate_transcript`, the `evidence_backed` attribution value, the "strong" rule in
  `media_claims`, the quote refusal in `quality_pages.py:211`, the demotion in `display/evidence.py:177`,
  and their tests.
- Gemini's YouTube transcripts carry speaker labels too, so Jev picks the label as for Deepgram. Gemini's own
  name on a label is a guess (its prompt names the subject) and is not the proof.
- After a recording with speaker labels is transcribed for a person job, `read_media` asks Jev the three
  agreed questions (present? speaking? which label is that exact person?), with what we know about the person
  and the recording. About 1 s and under $0.001 a question.
- The answer is shown to the agent at the top of the transcript, e.g. "Jev: speaking, 0.97; Speaker 1 is this
  person, 0.88". Every line under that label counts as the person's. The agent decides; there is no code
  threshold that blocks a recording or a quote.
- Metadata rule (prompt, not code): clear naming confirms; only clear proof of a namesake rules a recording
  out; anything unclear is transcribed and judged.

## 5. Quotes

The claim keeps the transcript line as transcribed (`submit_transcript_claim` already points at the saved
passage, so the agent never retypes it). The page writer is told to write the same line with spelling and
punctuation corrected and the meaning unchanged. No code compares the two.

## 6. Prompt and descriptions (content to agree with the founder before writing)

Points for the person prompt, taken from the gift pilot:
- Search the whole public footprint: podcasts, videos, own posts and likes, X, public Instagram and Facebook,
  own sites and blogs.
- Search podcasts and videos by name and company first; read the full description before transcribing.
- Read whole transcripts of the recordings where the person talks most; an episode description is not the
  episode.
- A same-name result is checked for a link to the day job before it is dismissed.
- Confirm a social handle from its bio and posts before reading it.
- If a tool is down, use the others. Stop when every source type has been searched, and say what was searched.
- Off-limits topics for each use (sales research and gifts) to be agreed separately.

## 7. Versions and rollout

New `acquire_research_evidence` version 3, person prompt and profile v31, account profile v40, recipe 43 and
its launch file (the trial harness runs `CURRENT_RECIPE_VERSION`, now 42). Order:
1. Move the agnostic files into `footprint/` (no behaviour change; existing tests green).
2. New clients and operations, each with tests against recorded responses.
3. Jev speaker check; delete the old check.
4. Prompt and descriptions, after founder review.
5. Trial on the U.S. Bank committee, then production.

## 8. Open, for the founder

1. Operations inside `acquire_research_evidence` (my call above) or separate named tools like the gift agent's.
2. ~~YouTube captions have no speaker labels.~~ Settled 2026-11-09: podcast version first, else Gemini;
   captions dropped (ledger decision 8).
3. ~~Does account research get the social operations?~~ Settled 2026-11-09 (founder): yes, account research gets them too.
4. ~~Where saved posts live.~~ Settled 2026-11-09 (founder): under `/research/operations/<id>/`, like every
   other operation's result. No `reads/` folder is added to the research agent. The shared `footprint/` code
   only returns posts; each agent saves them in its own place (the gift agent or a Head of ABM chat in its
   own workspace).
