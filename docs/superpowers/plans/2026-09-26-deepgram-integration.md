# Deepgram integration into research media

Status: implemented locally; offline and isolated database verification below. Subsequent
founder-authorized paid production-client test passed (26 September); no fleet launch.

## Behavior

Both account and person researchers already reach the shared `read_media` pipeline. Recording
acquisition now sends the complete audio to Deepgram Nova-3, using the standalone trial's
`diarize_model=v2`, utterances, word timing, fillers, punctuation and disabled smart formatting.
There is no chunk-local speaker stitching or LLM rewriting of the transcript.

Publisher-provided transcripts remain usable without an ASR purchase. Existing stored
transcripts are reused; this change does not silently retranscribe prior runs. Older v1/v2
legacy tools and the Gemini client remain for historical callers. Current media tools no
longer select Gemini transcription based on recording length. Gemini embeddings continue
serving transcript search through the existing OpenRouter route.

- Public podcast pages/feed enclosures and directly accessible recordings use existing resolution.
- Public YouTube recordings acquire audio with the locked yt-dlp/EJS dependency. No cookies,
  login, playlists or inherited downloader configuration. Download failures remain explicit.
- MP3/FLAC/WAV audio-only files pass through unchanged. Other containers extract their first
  audio track to lossless FLAC without trimming, changing sample rate or changing channels.
- Original and prepared recording bytes remain durable artifacts. Preparation/checksum metadata
  is included in the acquisition receipt; exact provider JSON retains words, utterances,
  confidence, timing and model/request metadata.
- Resolved public audio enclosures that need no conversion use URL delivery (avoiding the
  trial's slow-upload failure). Extracted audio uses binary upload. Returned file checksum is
  compared to retained input; discrepancies remain visible warnings.
- Canonical text uses utterances, split wherever word-level speaker labels change. If utterance
  words omit channel words, preserve the full channel word stream with a diagnostic.
- Fractional start/end timestamps remain ASR alignment estimates. Speaker 0/1/etc. are voice
  clusters, not verified named people. No new attribution or presentation gate is introduced.
- Coverage remains unknown: successful JSON and confidence values are not measured ASR accuracy.

## Durability and observability

Reuse the existing media operation ownership, raw-artifact drain, provider-call ledger,
Langfuse/OTel trace tree, source bindings, erasure protection and transcript indexing.
Deepgram is recorded as a model generation. Media seconds/request IDs are recorded; USD remains
explicitly unpriced when the provider does not report it, never falsely zero/free.

A paid transcription has one wire attempt. Ambiguous dispatch does not silently retry or fall
through to a second paid source. Recovery parses the stored Deepgram response after a canonical
persistence failure. Existing transcript versions and source URLs continue through the same
claim/dossier evidence tools.

## Configuration and deployment

- `CLUE_DEEPGRAM_API_KEY` is preferred; `DEEPGRAM_API_KEY` is accepted for the existing trial key.
  Values load via `Secrets`; headers are redacted by the shared provider wrapper.
- `CLUE_ARV2_DEEPGRAM_LANGUAGE=en` preserves the English trial baseline. `auto` selects a dominant
  language; `multi` is available for supported code-switching. No names/keyterms are seeded.
- Worker image/host requires ffmpeg and ffprobe. Locked Python dependencies install
  yt-dlp 2026.8.19 and EJS 0.8.0. YouTube challenge support additionally needs Deno or Node on PATH;
  the downloader is invoked from the worker's Python, avoiding older global executables.
- API request timeout remains 660 seconds, matching the trial. Existing media byte/seconds
  allowances remain unchanged. No workers are started or restarted here.
- Missing transcription credentials do not prevent non-media research from composing; attempting
  transcription returns a configuration error. There is no paid Gemini fallback.

## Verification

Offline client tests cover exact request options, upload versus URL bodies, credential redaction,
raw-response preservation, unpriced usage, no retries, fractional alignment, word-speaker changes,
missing metadata and lossless fallback from incomplete utterances. Recording tests cover a real
synthetic WAV and mocked video/YouTube preparation. Standalone trial tests share the production
parameter/parser primitives. Driver tests check account/person composition, including per-job
credential cloning.

Isolated Postgres tests cover acquisition, long/short recordings, durable recovery without
repurchase, source ownership, cross-job reuse, source erasure, transcript reads, lexical/semantic
search and trace/ledger linkage. All external provider connections are blocked during checks.
The publisher search fixture follows continuation offsets when a rich receipt is paginated.

Final results: 133 offline tests and 14 isolated Postgres tests passed; Ruff and targeted mypy
passed. Four saved trial responses parsed successfully (576 / 241 / 145 / 1,694 segments),
with valid spans and no utterance-word fallback needed. Configured key and local ffmpeg,
ffprobe, Node and Deno availability were confirmed without printing credentials.

A subsequent paid production-client test on the retained 42:49 interview succeeded: 6,846 words,
575 segments, three speaker clusters, matching audio checksum and 2,570 ledger media seconds.
One earlier submission lost its response to a test-only sink error; the standard sink was
offline-checked before the successful deliberate retry. USD billing is unreported, including
the first attempt. See `.artifacts/deepgram-integration-live-20260926/REVIEW.md`.

Full fleet execution and listening-based ASR quality are not certified by these checks. The saved standalone benchmark
remains the evidence for acoustic performance; noisy/overlapping speech still needs review.

The separately discussed parent-account dossier reference and earlier person-job release are
not part of this provider integration.
