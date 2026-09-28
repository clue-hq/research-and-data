# Deepgram standalone transcription trial

- Scope: founder requested an isolated Deepgram experiment with RSS/YouTube/other public
  media inputs, timestamps and speaker labels. No production provider switch, fleet jobs,
  database writes, claim/narrative changes, or person-identity inference.
- Added `scripts/trial_deepgram_media.py`, configuration/run documentation under
  `docs/experiments/deepgram-media-trial.md`, focused offline tests, and a standalone-only
  `DEEPGRAM_API_KEY` placeholder in `.env.example`. Actual secret stays in local `.env`.
- Reuses platform public media resolution and shared provider raw/ledger/tracing seams.
  Three explicit stages: prepare, paid transcribe, offline render. Immutable attempt marker
  and one provider attempt prevent accidental duplicate purchases after ambiguous failures.
- Batch configuration: Nova-3, diarize_model=v2 (not deprecated boolean), utterances,
  punctuation, fillers, smart_format off. Neutral speaker clusters, no fabricated names.
  Complete recording FLAC, no trimming/resampling; first audio track documented.
- Four offline tests passed; scoped Ruff passed. Initial sandbox acquisition failed DNS;
  approved network acquisition succeeded via RSS in `sanaz-02`. `sanaz-01` preserves the
  failed attempt. Results live under `.artifacts/deepgram-media-trial-20260925/`.
- Live transcription and independent public YouTube acquisition check started. Paid usage
  is unpriced in the ledger until checked against provider billing; credits are not zero cost.
- Preserve unrelated worktree changes from the main thread. No updates to global memory.

## Completion

- First FLAC upload explicitly returned HTTP 408/SLOW_UPLOAD after 345 seconds; failure
  preserved in `sanaz-02`. Added original MP3/WAV/FLAC passthrough and explicit public
  enclosure URL delivery. Error responses now retain top-level provider request IDs.
- Separate `sanaz-03` URL attempt succeeded in 13.97 seconds: 6,850 words, 558 original
  utterances, three speaker clusters, every word labelled/timed, matching file checksum,
  last word at 2569.495s against a 2569.706s recording. Dollar cost remains unknown.
- 15 provider utterances mixed different word speakers. Renderer now splits these at
  word-label transitions (576 display segments), preserving original provider objects.
  Short interjections/name spellings still warrant listening review; not an accuracy guarantee.
- Public YouTube acquisition initially failed 403 with system yt-dlp 2026.03.17. A separate
  trial-local virtualenv using yt-dlp 2026.8.19 plus EJS succeeded (`youtube-acquisition-02`).
  No global dependency updates, cookies, paid YouTube transcription, or main runtime changes.
- Local-file preparation also succeeded (`local-original-01`). Seven focused offline tests
  and scoped Ruff passed. Credentials absent from retained trial text/JSON artifacts.
- Readable results and REVIEW.md live under the ignored trial folder. Production integration,
  verified named-speaker assignment, and measured listening/alignment accuracy remain future work.
