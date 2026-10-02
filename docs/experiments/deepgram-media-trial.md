# Standalone Deepgram media trial

This experiment acquires a public recording, submits its audio to Deepgram, and saves the
provider transcript with word timing and speaker clusters. It does not change production
research, write application database records, launch workers, or generate claims/narratives.

The research-media pipeline adopted these shared primitives on 2026-09-26; see
[production integration](../superpowers/plans/2026-09-26-deepgram-integration.md).
Running this standalone script still does not launch or mutate application research.

## Configuration and rationale

Use `.venv/bin/python scripts/trial_deepgram_media.py`. Requirements: repository Python
dependencies, `ffmpeg`/`ffprobe`, and `yt-dlp` for YouTube. Put `DEEPGRAM_API_KEY` in the
repository `.env`; the script also accepts this key from its process environment. Credentials
never appear in command-line arguments or saved requests. The existing provider wrapper
redacts authorization and saves the raw response/ledger. Configured production tracing and
Langfuse are used for the transcription call, with linkage saved locally.

| Setting | Trial choice | Reason |
|---|---|---|
| Endpoint/model | `POST /v1/listen`, `nova-3` | Batch transcription of complete recordings |
| Speaker separation | `diarize_model=v2` | Pin the current batch diarizer for comparison; omit legacy `diarize` |
| Segments | `utterances=true`, `utt_split=0.8` | Timestamped utterances with word-level detail |
| Wording | `punctuate=true`, `filler_words=true`, `smart_format=false`, `profanity_filter=false` | Readable punctuation while retaining fillers and avoiding smart-format substitutions |
| Language | `en` default; `--language auto` or `multi` available | Use known language, dominant-language detection, or supported code-switching deliberately |
| Channels | `multichannel=false` | Treat the podcast as one conversation with speaker clustering |
| Vocabulary | Optional repeated `--keyterm`; none in baseline | Compare without seeding expected discoveries/names |

Sources: [batch API](https://developers.deepgram.com/docs/pre-recorded-audio),
[API parameters](https://developers.deepgram.com/reference/speech-to-text/listen-pre-recorded),
[diarization/versioning](https://developers.deepgram.com/docs/diarization),
[utterances](https://developers.deepgram.com/docs/utterances),
[pause splitting](https://developers.deepgram.com/docs/utterance-split),
[filler words](https://developers.deepgram.com/docs/filler-words),
[smart formatting](https://developers.deepgram.com/docs/smart-format),
[language detection](https://developers.deepgram.com/docs/language-detection),
[code switching](https://developers.deepgram.com/docs/multilingual-code-switching),
[keyterms](https://developers.deepgram.com/docs/keyterm).

Audio-only MP3, FLAC and WAV are retained byte-for-byte. Other formats/video use lossless
FLAC extraction without trimming, resampling or changing channel count. The first audio
track is selected and recorded in `source.json`. Container headers convey
encoding/sample rate; raw-PCM settings are not forced. Stereo studio tracks are not assumed
to correspond one-to-one with speakers. Truly separated speaker channels could warrant a
separate multichannel experiment. The whole recording is sent in one request so speaker
numbers share a single scope; there is no chunk-local identity stitching in this trial.

## Run in explicit stages

```sh
# Acquisition only; no paid transcription.
.venv/bin/python scripts/trial_deepgram_media.py prepare \
  --source 'https://publisher.example/podcast/feed.xml' \
  --episode 'Exact episode title, GUID, or URL' \
  --out .artifacts/deepgram-media-trial/my-episode-01

# One paid request; reads the already-prepared audio.
.venv/bin/python scripts/trial_deepgram_media.py transcribe \
  --out .artifacts/deepgram-media-trial/my-episode-01 --language en

# Rebuild human-readable files from the saved response; no network calls.
.venv/bin/python scripts/trial_deepgram_media.py render \
  --out .artifacts/deepgram-media-trial/my-episode-01
```

For a resolved public enclosure, add `--delivery url` to `transcribe`. Deepgram fetches that
recording directly, avoiding a large local upload. This sends the resolved audio URL, never
an HTML YouTube watch page or RSS document. Acquisition still retains the original bytes
and checksum for comparison. URL delivery requires one audio stream; local/YouTube recordings
use upload. The request manifest states which delivery mode was used. A remote URL could
change after preparation; compare the response's file checksum to `original_sha256` where
the provider reports it. Do not infer byte identity merely from a matching URL.

`--source` also accepts a local audio/video path, direct media URL, public YouTube URL,
or an episode page the shared resolver can follow to explicit audio/feed links. RSS and
Apple podcast resolution reuse the platform implementation. When a feed/page is ambiguous,
inspect `resolution.json` and choose an explicit candidate in a fresh output folder.
If a page resolves only to an existing text transcript, provide the recording or RSS URL:
the trial must actually test audio transcription. It does not scrape arbitrary text and
call that a transcript. Private, login-protected, DRM, unavailable or extraction-blocked
recordings cannot be guaranteed. YouTube uses public `yt-dlp` without cookies or local
downloader configuration/cache; its diagnostic files are retained. Use a current `yt-dlp`
with its EJS dependencies and a supported JavaScript runtime
([official setup](https://github.com/yt-dlp/yt-dlp/wiki/EJS)). A trial-local installation can
be selected by prepending its `bin` directory to PATH for that one command, without changing
the platform environment.

The shared public downloader limits media to 200 MiB and documents to 5 MiB. Deepgram
documents a 2 GB upload limit and a 10-minute Nova processing timeout (not a 10-minute
recording-length cap). This trial uses a 660-second socket timeout and no automatic paid
retries. For an ambiguous timeout, inspect saved raw/ledger evidence before deliberately
making another attempt. A persistent exclusive submission marker prevents accidental
repurchases. Use a fresh folder for an intentional new experiment.

## Review artifacts

- `source.json`, `resolution.json`, `media-probe.json`: recording provenance, duration,
  track selection, audio checksum and feed/page resolution.
- `request.json`: actual safe Deepgram settings; `deepgram-response.json`: exact response bytes.
- `transcript.md`: complete transcript, neutral speaker labels and start/end times. Where a
  provider utterance contains multiple word-level speakers, split it at those label changes
  rather than assigning every word to the utterance's majority speaker.
- `transcript.vtt`: playable captions for utterances with usable timing; unknown timing is
  retained in Markdown/JSON rather than invented for captions.
- `words.json`, `utterances.json`: the returned word/utterance objects including confidence.
  `segments.json` records the display segments derived from them; originals remain unchanged.
- `quality.json`: missing-field warnings, low-confidence counts, duration and last-word
  timing, model metadata. These are diagnostics, not an accuracy certificate.
- `receipt.json`, `events.jsonl`, `provider-ledger.jsonl`, `raw/`, `trace-linkage.json`:
  provider request identity, timing and traceability. Dollar cost is unknown unless read
  from billing; the script does not assume YC credits mean zero consumption.

Deepgram labels voices as Speaker 0, Speaker 1, etc.; those are not verified personal names.
Map names only after checking introductions or listening evidence. Diarization and ASR
can still confuse similar voices, overlapping speech, names and accents. Review samples
at the beginning, middle, end and speaker transitions against the audio. Check whether
important quotations retain the spoken words and whether timestamps point to those words.
No additional LLM is used to rewrite, summarize or "repair" the transcript.

Results, audio and trial logs stay under ignored `.artifacts/`. No transcription provider
has been switched in the platform. Live test findings are recorded separately in the
trial folder so offline adapter tests cannot be mistaken for measured ASR quality.
