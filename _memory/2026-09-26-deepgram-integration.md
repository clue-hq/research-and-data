# 2026-09-26 Deepgram research-media integration

User authorized adopting the standalone Deepgram trial for research podcasts/interviews/video.
Read supplied trial transcript, trial/hard-case notes, script and media pipeline. Implemented
shared Nova-3/v2 diarization client through ProviderCaller; whole-recording preparation shared
with standalone script; current read_media routes Deepgram for both account/person research.
Publisher transcripts/reuse and Gemini embeddings remain. Legacy v1/v2 tools retain old client.

Preserve raw words/utterances, word-speaker changes, fractional timing, uncertainty, checksums;
no inferred named-speaker identity or new verification/display gates. No automatic paid retries.
Provider seconds/unpriced USD and raw receipt recovery use existing operation/trace/ledger seams.
Secrets supports CLUE_DEEPGRAM_API_KEY and existing DEEPGRAM_API_KEY alias. Language defaults en.
Locked yt-dlp/EJS; invoke installed module, not global executable. ffmpeg/ffprobe + Deno/Node
are host prerequisites. No paid calls/workers launched.

Intermediate checks found an incorrectly placed key-forwarding argument in ToolRuntime;
corrected it to _LiveClients.for_job and added clone coverage. Publisher search assertion was
assuming a single unpaginated receipt; updated to follow next offsets and prove matching text
remains accessible. Initial uv lock required sandbox escalation for dependency cache/network.

Parent-account dossier mount and dispatch-after-save remain separately pending; not included.
Closing: 133 offline + 14 isolated DB checks passed, Ruff and targeted mypy clean. Four saved
trial responses replayed through production parser with all spans valid, no paid/network calls.
Local credential and ffmpeg/ffprobe/Node/Deno availability confirmed without secret output.
Local checkpoint contains this integration only; unrelated pre-existing changes left untouched.

## Paid provider smoke, founder requested

Ran live `_LiveClients.for_job().transcription()` with shared preparation/parser and standard
raw/ledger sinks, configured Langfuse, using the retained public 42:49 interview. Isolated files;
no fleet jobs, application DB writes, claims or additional research providers.
First test-only sink incorrectly implemented persist instead of save; provider response reached
but was not retained. Fixed harness by removing wrapper; offline-tested FileRawSink/export;
deliberate run-02 submission succeeded. Two submissions overall, first billing/outcome unknown.
Production application code unchanged. No automatic retries.
Success: 6846 words, 575 segments, 3 voice clusters, no missing word times/speakers, checksum
matched, ledger 2570 media seconds, USD unknown, 5.4 seconds elapsed. Prior trial 6850 words/576
segments; same last-word timing. Confidence metrics are not accuracy measurement.
Review and files: `.artifacts/deepgram-integration-live-20260926/REVIEW.md`.
Live provider/client/parser now checked; full fleet execution/listening accuracy still separate.
