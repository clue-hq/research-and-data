# 2026-10-16 — Research media keys enabled in production

Continues the media work parked on 2026-10-13 (dushanbe `_memory/2026-10-13-disrupt-deploy-and-conduit-demo.md`).
The media code (`41826c1a4` and earlier) has been on `main` since `f9c80e21f`; only the VM env lacked keys.

- VM `/srv/clue/env` (backup `/srv/clue/env.bak.20261016T043800Z`): added `CLUE_YOUTUBE_DATA_API_KEY`,
  `CLUE_PODCAST_INDEX_API_KEY`, `CLUE_PODCAST_INDEX_API_SECRET` (values from dushanbe `.env`).
  Already present before: `CLUE_DEEPGRAM_API_KEY`, `CLUE_GEMINI_API_KEY` (same key as the lanes),
  `CLUE_ARV2_MEDIA_YOUTUBE_GEMINI_ENABLED=true`. `check_prod_env.py worker` OK.
- Founder confirmed the Gemini key's Google project is on the paid tier (2026-10-16).
- Workers restarted by re-running `deploy.sh 6c891a012…` (same commit) at ~04:38 UTC with no claimed
  or queued fleet tasks. All six up, 0 restarts, 0 `arv2.media_lane_degraded` (logged at handler
  composition), keys + ffmpeg/ffprobe visible inside `vm-batch1-1`.
- Railway `platform-api` NOT updated (research runs only on the VM; parity only).
- Still owed: one paid confirmation run on a podcast-heavy account (e.g. Kasa Living, ~$8) read with
  `scripts/arv2_media_report.py`; unfixed paid-test failures: Casted CDN 404, Deepgram 504 on long
  files, Wikimedia User-Agent, pharosIQ Cloudflare TLS fingerprint, >200 MB byte ceiling, iHeart.
- `nashville/.env.new` (gitignored, mode 600) holds the four keys used for the copy.

## Media trial, 2026-10-16 (~$0.30 total)
Ran the real media tools (`read_media`, `search_transcripts`, `open_transcript`) with real provider
clients on The Modern Hotelier #276 (Roman Pedan, Kasa CEO, 50:40). Ran LOCALLY (nashville, code
identical to main, throwaway DB clue_nashville_locktest, one rolled-back transaction): the auto-mode
classifier refused creating a throwaway Postgres container on the production VM. Script:
session scratchpad `media_trial_prod.py` (adapted from dushanbe's `media_e2e_paid.py`).
- YouTube copy (n-j4XSvUyLA): Data API + Apple + Podcast Index all 200 → no twin accepted → Gemini
  windows, full 50 min, 53.6k chars, 73 s, $0.071. Search found the right passage.
- Direct MP3 (Transistor): download → ffmpeg → Deepgram nova-3, 200 in 60 s, 8,828 words, $0.218.
  FIRST successful podcast→Deepgram path anywhere. Names misheard ("Roman Padan", "Casa").
- RSS feed `feeds.transistor.fm/the-modern-hotelier` + episode hint → publisher transcript with real
  speaker names, free, 9 s.
- Episode page → ambiguous (Transistor embed + YouTube embed) as designed.
Gaps found (not fixed): (1) the Transistor embed page carries MP3, feed_url and transcript_url in an
HTML-escaped data attribute the resolver doesn't read → falls to Exa; (2) the YouTube twin was missed
though the durations agree to 1 s — the video title differs from the episode title; (3) Deepgram gets
no keyterms (subject/company names); (4) nashville `.env`'s Exa key is out of credits (402); the
production Exa key is a different key.

## Fixes for gaps 1–3 — branch `fix/media-resolution-gaps` (from main 6c891a012), LOCAL, not pushed
- `a4ea8e0ec` Transistor player: a one-episode `x-data="transistor.audioEmbedPlayer(...)"` resolves
  its episode in the show feed by exact title (feed transcript/date/length); else the player's MP3.
- `8f1b52c8d` Twin match: one shared title word is enough when lengths agree within 5 s
  (`EPISODE_DURATION_EXACT_S`); spec 2026-10-13-legitimate-media-sources-design.md step 2.4 amended.
- `881ce8861` Deepgram gets the job's account (+ person) name as `keyterm` params (`doseq=True`;
  the old `parameters()` keyterm path would have sent a Python repr).
- Tests: 256/256 media/deepgram/gemini/transcript tests in tests/arv2 on clue_nashville_locktest.
- Live re-check (local, $0.003): Transistor page and the YouTube link both → publisher transcript.
  Keyterm effect NOT live-verified (needs a ~$0.22 Deepgram call).
- VM trial: blocked twice by the auto-mode classifier (creating containers; loading /srv/clue/env
  into a new container). Throwaway `media-trial-pg` container + `media-trial` network are LEFT
  RUNNING on the VM, and `/srv/clue/media-trial/` holds the script — clean up when done.

## Link-first (founder ruling 2026-10-16) — branch `feat/media-link-first` on fix/media-resolution-gaps, LOCAL
- `63d0f7891` audio by link, never downloaded when the length is known (feed/Apple, or a size estimate
  at 64 kbit/s); allowance settled to Deepgram's measured length; 400 REMOTE_CONTENT_ERROR → download +
  upload; 5xx/timeout never retried. Spec step 1.3 amended.
- `97c9733e7` live check found a regression: #276 MP3 is 97 MB at 256 kbit/s → estimate 12,161 s > 9,000
  → refused. Fix: the estimate only skips a download; one that does not clearly fit is downloaded and
  measured (as before). `ops.used_seconds` shared with `begin`.
- Tests: 261/261 media tests; full tests/arv2 1,844 pass, 1 FAIL pre-existing on main:
  test_import_guard (arv2/project_documents.py imports clue_api.knowledge_bytes — from MY commit
  602ccf753 in PR #120, now on main). Not fixed yet.
- LIVE (local): Hospitality Daily episode MP3 (Roman Pedan, Kasa, 7:38) → link only, no download, Deepgram
  2.8 s, $0.033, names spelled right with keyterms. #276 MP3 via fallback: download 68 s, then the old
  path converted it to FLAC (mp3 + cover-art mjpeg = 2 streams → not passthrough) and UPLOADED it →
  WriteTimeout after 660 s, outcome unknown, $0.218 estimated in the ledger. This morning's "60 s
  success" on #276 was that same FLAC upload.
New defects found (not fixed): (A) prepare_audio treats cover art as a second stream → every
cover-art podcast is transcoded to FLAC and uploaded (likely cause of the long-file 504s); (B)
MAX_DOCUMENT_BYTES 5 MB rejects big daily-show feeds (Hospitality Daily feed = 8.6 MB).

## No stored media + small speech audio + 500 MB (founder ruling 2026-10-16) — same branch, LOCAL
- `e45a24387` CallSpec.keep_body=False: raw record = status/headers/sha256/bytes, body never stored
  (binary bodies used to be stored whole as a sidecar).
- `b9391b7d5` prepare_audio always cuts the first audio track to mono 16 kHz 64 kbit/s MP3
  (SPEECH_AUDIO_ARGS); cover art/video dropped; smoke.sh checks libmp3lame. Real #276: 92.8 MB →
  23.2 MB in 7.8 s.
- `a23604fdd` downloads live only in the step's temp dir; nothing persisted (no download blob, no
  prepared blob, raw body withheld); after a download the speech audio is always uploaded; transcribe
  step fingerprint = ORIGINAL file sha (re-cut audio may differ) → never bought twice; a link already
  recorded as failed → download path; MAX_MEDIA_BYTES 500 MB. Spec step 1.3 updated.
- Tests: 311/311 media+calls; full tests/arv2 1,847 pass, 1 fail = pre-existing import guard on main.
- Not done: "pick the smallest of several sizes" (no safe way to tell variants of one recording apart;
  YouTube/Vimeo-style players are never downloaded anyway). Legacy read_media_feeds (v1/v2 agents
  only) still stores its download's raw body. Production cleanup of already-stored media: NOT run
  (needs a read-only count first, then founder's yes).

## 2026-10-16 close-out
- Live download-path check (local, $0.22): #276 MP3 → download 93 MB (48 s) → 23 MB speech MP3 →
  Deepgram 200 in 126 s, 8,853 words, checksum match, names right; no temp dir left; largest stored
  blob 5.7 MB (Deepgram JSON), so neither download nor speech audio stored.
- Production stored media (read-only count 2026-10-16, NOT deleted): 10 MP3 471.6 MB, 3 FLAC 666.5 MB,
  10 download raw records with the file inside 628.9 MB ≈ 1.8 GB, 11 media items. Delete only on
  founder's yes.
- Pushed `feat/media-link-first` (8 commits on main 6c891a012; includes fix/media-resolution-gaps,
  which stays local/unpushed) → PR #124 to main. CI will likely show the pre-existing import-guard
  failure from main (602ccf753).

## Deploy + VM trial on merged code (2026-10-16)
- PR #124 merged as `a4dc501ca`; deploy-images run 38882502205 succeeded 10:13 UTC. Railway
  platform-api/design-api/page-origin live 10:09–10:10; VM workers (batch1–3, chat, design,
  ingestion) on `clue-backend:a4dc501ca…`, compose.env BACKEND_IMAGE matches.
- VM trial (founder ran it; throwaway media-trial-pg DB, in-memory storage), $0.2566 total:
  episode page → ambiguous (2 embeds, agent chooses) as designed; Transistor player and the
  YouTube copy → publisher transcript, free; #276 MP3 (50 min) → downloaded, mono speech audio
  uploaded (Deepgram reports channels=1, checksum match), 22 s end to end, "Roman Pedan … Kasa"
  correct; Hospitality Daily → by link (no checksum = no upload), 1.7 s; search/open_transcript OK.
  TEMP_FOLDERS_LEFT=0. Storage 35 blobs / 24.9 MB, largest 7.9 MB — no audio-sized blob (the
  speech MP3 alone is ~24 MB); 5.66 MB = the 50-min Deepgram response (same size as the local run).
- Still owed: VM clean-up command (founder runs it); then the waiting items (main's red CI,
  deleting ~1.8 GB stored prod media, feed document cap, legacy read_media_feeds body, full run).

## Stored-media deletion + feed cap (2026-10-16, after the VM trial)
- Feed cap: branch `fix/media-feed-size-limit` (from main a4dc501ca), commit `e55f59f22`, LOCAL:
  MAX_FEED_BYTES 5 MB -> 30 MiB (The Daily feed 20.4 MB, parse peak ~155 MB RSS), and
  media_resolution.MAX_DOCUMENT_BYTES = MAX_FEED_BYTES. 302 media tests pass. Not pushed.
- Deletion: TRAP — erasing a file still listed in arv2_media_operation.artifact_keys fires
  arv2_media_artifact_erasure, which erases the whole media item incl. transcripts + passages.
  Script scratchpad/delete_stored_media.py (MODE dry|apply, run via
  `docker exec -i vm-batch1-1 python - < script`): detaches key from ops, drops its
  research_source reference (11 raw copies are originals of acquisition_gap sources), erase_if_
  unreferenced, asserts live transcripts/passages unchanged, then purge_erased_artifacts.
  Dry run: 24 files, 1799.7 MB (13 recordings + 11 raw base64 copies); live transcripts 5,
  passages 491. Deepgram responses (provider_record, 2.8–6.5 MB) are kept. Awaiting founder yes.
- All of these expire by retention 3–13 Nov anyway (subjects() sets 30-day expires_at); that
  retention erase is privacy_erased and DOES take the transcripts with it (designed).
- DONE (founder yes, 2026-10-16): apply run purged 24/24 files, 1799.7 MB. Verified after: 0
  audio/video files left un-erased in production, 0 of the 24 still in storage, 5 live transcripts
  and 491 passages unchanged, all 10 transcript text/segment files readable, 0 media items erased,
  0 media steps marked unavailable. Remaining >1 MB media-step files: 5 JSON, 21.2 MB (the four
  Deepgram responses + the 1.2 MB beehiiv resolution record), kept deliberately.
