# Research media from legitimate sources only

Status: draft for founder review (2026-10-13). Nothing here is implemented.

## 1. Why

Research agents find podcasts, interviews and talks about the people they research, but almost
never get their words out of them.

* **Production never transcribes anything.** Every recording passes through `ffprobe` (and `ffmpeg`
  unless it is already plain MP3/FLAC/WAV), and the backend image (`docker/backend/Dockerfile`, on
  every branch) installs neither.
* **Locally, most reads fail before transcription.** Runs 6 and 7 (Dialpad, 2026-10-12) made 14
  `read_media` calls; about 10 failed: the page's player is built by JavaScript so a plain fetch
  finds no recording (3), a podcast episode could not be matched in its feed (2), the site refused
  the plain fetch (1), dead domains (2). Run 6 got one real transcript (the HumanX interview, six
  account findings). Run 7 got none.
* **The YouTube route breaks YouTube's terms.** It downloads audio with `yt-dlp` (YouTube allows
  downloading only where it shows a download button) and scrapes the watch page for the video's
  status and length (YouTube allows automated access only to search engines or with its
  permission). Cloud servers are also routinely blocked doing this.

## 2. Rules

1. Every source is one the publisher made available for that use: a transcript the publisher
   published, a podcast feed (built to be downloaded), a direct media file, or an official API.
2. No `yt-dlp` and no scraping of YouTube pages, anywhere (local runs behave like production).
3. LinkedIn- and X-native video stay unfetched (ruling 2026-09-03). The refusal tells the agent to
   look for the same talk elsewhere: YouTube, Vimeo, the event's own page, a podcast.
4. A third-party transcript API is not built: those services mostly scrape YouTube themselves.
5. When several episodes could match, the agent chooses from the list; the code never guesses.

## 3. The order `read_media` tries, stopping at the first that works

### Step 1 — the source itself

For any link, in this order:

1. **A transcript the publisher put out** (already supported): a transcript link (VTT, SRT, plain
   text), schema.org `transcript` data, or caption files on the page. Used as the transcript.
2. **A transcript printed in the page's text.** `read_media` cannot tell a transcript from an
   article reliably, so it says so and tells the agent to read the page with `fetch_page` (what the
   run-7 agent worked out for itself on the Twilio podcast page).
3. **A recording the page offers directly**: a direct audio or video file, an RSS feed, an `<audio>`
   or `<video>` element, schema.org `contentUrl`. Downloaded, prepared with `ffmpeg`, sent to
   Deepgram. A feed episode with a `podcast:transcript` tag uses that transcript instead.
4. **A YouTube embed on the page** goes to the YouTube path (step 2 onwards for that video).

New: when the plain fetch is refused (403) or finds no recording, the page is fetched again with
the browser-grade fetcher `fetch_page` already uses, so JavaScript-built players and protected pages
show their recordings.

### Step 2 — the same episode in a public podcast feed

Many interviews posted as video are also podcasts. For a YouTube video (or any recording step 1
could not open):

1. **Learn what it is.** For YouTube, the official YouTube Data API (`videos.list`, one quota unit):
   title, channel, publish date, duration, description, and whether it is public. This replaces the
   watch-page scrape. For other pages, the page's own title and metadata.
2. **Follow an explicit link first.** If the description or page links to Apple Podcasts, Spotify,
   an RSS feed or the show's website, follow it (a known link is fetched, never searched for).
   Spotify audio is DRM-protected and never downloaded; its public page names the show, which is
   then found through step 2.3.
3. **Otherwise search the public directories** for the show by channel or show name: Apple's
   directory (iTunes Search API, free, no key) and Podcast Index (free key).
4. **Match the episode on all of these together:** published within 7 days of the video, duration
   within 5% (or 90 seconds), and shared title words. Exactly one match: use it. Several: return
   them (title, date, duration, link) for the agent to choose with `episode_hint`. None: next step.
   (The proof of concept's word-overlap guess once returned episode 280 for episode 265; title words
   alone never decide.)
5. **From the matched episode:** its `podcast:transcript` if it has one, otherwise its audio sent to
   Deepgram, as in step 1.

### Step 3 — Gemini with the public YouTube link (YouTube only)

Google's Gemini API accepts a public YouTube link and reads the video on Google's side; we download
nothing. The client exists (`gemini_media_client.transcribe_video`).

* Only for a video the Data API reports as public, with a known duration.
* **Paid tier only** (on the free tier Google may use the content to improve its products).
* **Long videos in windows**: 40-minute back-to-back windows using the API's `start_offset` /
  `end_offset`, joined in order. Today one call is capped at 32,000 output tokens, which cuts off
  around two hours; windows remove that limit and reduce dropped passages.
* **Fewer frames** (the audio is what matters), which roughly halves the cost.
* The transcript is saved as a model transcript (`method="gemini_youtube"`): no word timings,
  speaker labels are estimates. Quotes are still checked against the transcript before use.
* Behind `CLUE_ARV2_MEDIA_YOUTUBE_GEMINI_ENABLED` (default on).

### When nothing works

`read_media` returns `unavailable` with what each step found (for example "no publisher transcript;
no podcast match for 'HumanX' on Apple or Podcast Index; Gemini off"), plus the YouTube metadata,
so the agent still learns what the video is and where else it might be.

## 4. Production and visibility

* Install `ffmpeg` and `ffprobe` in the backend image; the image smoke test fails if either is
  missing.
* Remove the `yt-dlp` dependency and the YouTube download route.
* A worker that starts without `ffprobe` or a Deepgram key logs that loudly, and `read_media` then
  reports "media lane unavailable on this worker" instead of a failure that looks like the agent's.
* Each run's report gets a media line: found, attempted, transcribed (by step), and why the rest
  failed.

## 5. Settings (all in `.env` and `.env.example`)

| Setting | Default | Notes |
|---|---|---|
| `CLUE_YOUTUBE_DATA_API_KEY` | empty | Google Cloud API key; without it YouTube links go straight to "unavailable" with a gap saying so |
| `CLUE_PODCAST_INDEX_API_KEY` / `_SECRET` | empty | Without them only Apple's directory is searched |
| `CLUE_ARV2_MEDIA_YOUTUBE_GEMINI_ENABLED` | `true` | Step 3 switch |
| `CLUE_ARV2_MEDIA_GEMINI_WINDOW_SECONDS` | `2400` | Step 3 window length |
| `CLUE_GEMINI_API_KEY` | exists | Must be a paid-tier key |

## 6. Cost per hour of recording

| Route | Cost |
|---|---|
| Publisher transcript, `podcast:transcript` | free |
| Deepgram (feed audio, direct files) | about $0.26 |
| Gemini with the YouTube link (3.5 Flash-Lite, reduced frames) | about $0.07–0.14 |
| YouTube Data API, Apple directory, Podcast Index | free within quotas |

The per-run media budget (`CLUE_ARV2_MEDIA_SECONDS_CEILING`, 2.5 hours) applies to every paid route.

## 7. Testing

* Offline, through the real resolver and stores with recorded responses: each step's success and
  each fall-through, an ambiguous episode list, a 403 page recovered by the browser fetcher, a
  feed with `podcast:transcript`, a long video split into windows, the switch off, missing keys,
  and a worker without `ffprobe`.
* A free replay of runs 6 and 7's 14 media links through steps 1–2 (directory and API lookups only,
  no Deepgram or Gemini), reporting how many each step would have resolved.
* One paid confirmation run, launched only with founder approval.

## 8. Open questions for the founder

1. YouTube Data API key and Podcast Index key and secret: created by the founder.
2. Confirm the Gemini key's project is on the paid tier.
