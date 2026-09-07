# `clue_api.arv2` — the ARV2 research lane

Master plan §9 Track R. Two rules bind every module here: it **imports nothing quarantined**
(Global Constraint 7, enforced by `tests/arv2/test_import_guard.py`), and **every provider call
goes through `ProviderCaller`** — no module opens a socket of its own.

## Step 0 — the shared foundation (this task)

| Module | What it owns |
|---|---|
| `errors.py` | The lane's typed failures: `Arv2Error`, `ProviderHalted`, `ProviderTransportError`, `RawParseError`. |
| `transport.py` | The HTTP boundary — `HttpRequest` / `HttpResponse`, `HttpxTransport` (live), `ScriptedTransport` (the lane's one test double), `json_request`, `BROWSER_USER_AGENT`. |
| `sinks.py` | Where a call's evidence goes — header/URL redaction, `RawRecord` + `RawSink` (`FileRawSink`, `MemoryRawSink`), `LedgerRow` + `LedgerSink` (`JsonlLedger`, `MemoryLedger`), `SpendTotals`. |
| `calls.py` | **The wrapper.** `ProviderCaller.call` implements Appendix A laws 1 and 2 once: estimate row before the wire, raw record before any parse, `Retry-After` / `12·(n+1)` s / `2·(n+1)` s backoffs, halt latching, the result row. |
| `text.py` | Verbatim-matching primitives (`normalize_for_match`, `substring_verdict`) shared by the media and structuring clients — Appendix A law 6. |
| `openrouter.py` | The thin OpenRouter HTTP helpers both LLM clients share: request builders, the cost reader, the message-text reader. No SDK. |

## The six provider clients (Tasks 2–7)

| Module | Provider |
|---|---|
| `ai_ark_client.py` | AI Ark — company and people enrichment, paced by `arv2_ai_ark_min_gap_s`, credit-metered. |
| `exa_client.py` | Exa — search, contents and deep research; cost from `costDollars.total`. |
| `ats_client.py` | The ATS job boards (Ashby and kin) — open requisitions, read from the careers page's own slug, never guessed. |
| `media_feeds_client.py` | Podcast RSS and YouTube discovery — resolving an episode or video to a fetchable media URL and its duration. |
| `gemini_media_client.py` | Native Gemini media understanding and transcription — the one ARV2 call that bypasses OpenRouter. |
| `structuring_client.py` | The OpenRouter structuring pass: prose → claims against the field catalog, one subject per call. |
| `exa_client.py::ExaClient.agent_run` | Exa Agent (`/agent/runs`) — async deep research: create, poll every 4 s, settle on the completed body; fixed-effort prices reserved on the create leg; failures/timeouts returned, never raised. |

## Where the output goes

Raw records and the ledger are written under `Settings.arv2_raw_root` (default `.artifacts/arv2`,
git-ignored): raw records in `.artifacts/arv2/raw/<provider>/`, the ledger in
`.artifacts/arv2/ledger.jsonl`. Nothing under `.artifacts/` is ever committed.

The `provider_call_ledger` table and the `artifact`-backed raw sink land with D1/A7; R1 ships the
sinks' protocols and the file/memory implementations.

## Cost per request

**Every value a client method returns carries `cost: CallCost` for the request that produced it.**
Cost tracking is not a per-client courtesy; it is a uniform provision, so no caller ever has to
ask "did this one report its cost?".

`CallCost` (`calls.py`) is the settled money view of one request: `cost_usd`, `credits` and
`media_seconds` **as the ledger holds them** (the estimate has already stood in for anything the
provider did not report), plus `cost_source`, `provider`, `operation`, `raw_ref` and
`ledger_row_id`. `cost.ledger_row_id` is that request's `result`-phase ledger row — the join back
to the full trail. `ProviderCaller.totals()` is the running sum across every call one caller made.

`cost_source` labels how well the numbers are known, and it is written on **every** result row's
`extras["cost_source"]` as well as onto the `CallCost`:

| value | meaning | where it appears |
|---|---|---|
| `metered` | the provider's own metering answered — the cost reader supplied at least one number | every paid call: AI Ark, Exa, OpenRouter, native Gemini `generateContent` |
| `free` | nothing was ever going to be charged — the spec declared no cost reader **and** reserved nothing | the public sources: ATS boards, careers pages, RSS feeds, YouTube watch pages, enclosure `GET`/`HEAD`, the Files API upload/poll legs |
| `estimate` | a cost reader existed but reported nothing, so the pre-spend estimate stands in | the fallback only — this is the one value that means *we do not actually know* |

The `free`/`estimate` split is the point of the change: before it, a free ATS fetch and a paid call
whose provider went silent were both unlabelled, so "what did this account really cost" could not
be answered without knowing which providers meter. The test is on the **spec**, not on the amounts
— a metered call that happened to cost zero is still `metered`.

A `cost` field typed `CallCost | None` means the value can also be built **without a call**, and
`None` says so honestly rather than fabricating a ledger reference:

- pure mappers and parsers — `company_from_record`, `email_export_from_record`, `parse_feed`,
  `parse_structured_transcript`, `read_structured_reply`;
- `YouTubeWords.cost`, because the page text comes from a caller-supplied `PageTextFetcher`: only
  the caller knows what its own provider charged, so `youtube_words` takes `cost` as a kwarg and
  passes it through;
- `EmbeddedTranscript.cost`, in the one case where a transcript has no lines to chunk and **no
  call is made at all**.

Calls that return a *set* carry the cost on the set, never on each member — one request bought the
whole page, so charging it per item would multiply the run's real spend. That is why
`people_by_name` returns `AiArkPeople`, `mine_quotes` returns `MinedQuotes` and `embed_chunks`
returns `EmbeddedTranscript`; all three iterate and `len()` like the lists they replaced.
`Transcript.upload_costs` keeps the long path's free Files API legs as their own rows rather than
summing them into `Transcript.cost`, because three or four requests were made and the ledger has
three or four rows.

The D1/A7 `provider_call_ledger` table receives exactly these rows — `cost_source` included — when
the database `LedgerSink` lands; nothing above the sink protocol changes then.

## Onboarding templates and mappers (O2)

`onboarding_requests.py` holds the fixed request templates of ARV2-ONBOARDING-PLAN.md §4 —
company overview (contract-verbatim, live-validated), customer reviews, per-product research
(Agent requests) and persona evidence (a `/search` deep-reasoning request within the depth-2 /
ten-property limits). Behaviour is in the system prompt, shape in the schema; the driver never
authors a schema.

`onboarding_documents.py` turns a response into a `KnowledgeDocument` (YAML front matter = the
machine contract; markdown body under fixed headings; `not_found` always rendered). The mappers
are pure, so `KnowledgeDocument.cost` is the settling call's `CallCost` when built from a call and
`None` otherwise — the guard's documented exception.

The Agent surface is synchronous like the rest of R1: the onboarding driver (O3) calls
`agent_run` through `asyncio.to_thread`, one `ProviderCaller` per worker task.

## Notes recorded at R1 integration (2026-09-07)

- **The one native call.** `gemini_media_client.transcribe_long` is the only ARV2 call that bypasses
  OpenRouter (founder ruling): OpenRouter serves neither `gemini-3.5-transcribe` nor a file upload.
  It reads `Secrets.gemini_api_key`, sends it as `x-goog-api-key` (never `?key=`), and its cost is
  computed from `usageMetadata` with the proof-of-concept price sheet. Short items and embeddings go
  through OpenRouter like every other model call.
- **`ffmpeg` is a test-only dependency**: the Gemini live suite cuts a 180 s clip for the short path
  and skips when `ffmpeg` is absent. Production never cuts audio.
- **Two `AudioFile` types exist** — `media_feeds_client.AudioFile` (a downloaded enclosure: path,
  bytes, sha256, duration, content type, the last two optional) and `gemini_media_client.AudioFile`
  (a transcription input: path, duration, mime type, container format, all required). The
  conversion between them ships here as `gemini_media_client.transcription_input_from_enclosure`,
  which **raises** on an unknown duration or an unrecognised content type rather than defaulting:
  a `0`-second reservation would silently disarm the lane's one enforced money control, and an m4a
  labelled `mp3` is a wrong transcript.
- **The package `__init__` exports the value types as well as the client entry points** — R2 needs
  them to annotate anything, and a rule that forces submodule imports is a decorative boundary.
  The one exception is `AudioFile`: the two collide by name, so each is imported from its own
  module.
- **Every client keeps its own typed failures** (`BoardNotFound`, `UnsupportedMediaHost`,
  `MediaCeilingExceeded`, …) subclassing `Arv2Error`; consolidation into `errors.py` is deferred.
- **Halt rules are per provider, but one latch key has exactly one rule.** The wrapper latches on
  the `CallSpec.provider` string, so every spec that latches `openrouter` — the structuring call
  and the media client's short transcription, quote mining and embeddings — shares
  `openrouter.openrouter_halt_rule`. The native Gemini endpoints latch `gemini` and use
  `gemini_media_client.gemini_native_halt_rule`. Exa's ignores 2xx bodies (a successful dossier
  about a fintech names "credit" constantly); AI Ark's checks any 4xx/5xx body.
- **403 is a per-provider decision, not a lane-wide one.** OpenRouter's 403 is a *moderation
  verdict on the input*, so it does **not** halt: one flagged bundle would otherwise latch
  `openrouter` process-wide and take the whole run's model calls down. AI Ark's 403 (Cloudflare
  denial) and Exa's (auth) do halt, because for them it really is a refusal to serve.

## R2 composition constraints

R1 is entirely synchronous and single-threaded by design; these are the conditions R2 must compose
it under, not defects in it.

- **Every entry into this lane from the fleet's `async def handle` goes through
  `asyncio.to_thread`.** `ProviderCaller.call` blocks — on `Transport.send` (Exa deep reasoning
  gets 1200 s, long transcription 3000 s), on the AI Ark client's pacing sleep (up to 10.5 s per
  call), and on the retry backoff (up to 12+24+36 s). Calling it directly from an async handler
  repeats the recorded Stage-0 incident ("sync LLM/HTTP calls on the web process's event loop") at
  much larger magnitudes.
- **One `ProviderCaller` per worker task.** Its running totals (`_totals`) and its halt latch
  (`_halted`) are plain mutable attributes with no lock, so a caller shared across threads races on
  both the money trail and the latch. Sharing one is only safe if the sharing is serialised.
- **`reset_halt` is an operator action and needs a stated owner.** A latch survives for the process
  lifetime and there is no surface that clears it: whoever composes the lane decides who may call
  `reset_halt` (and on what evidence — credit topped up, key replaced), or the first refusal ends
  that provider for the process.
- **The `Transport` seam materialises whole bodies.** `send()` returns `HttpResponse.body: bytes`,
  so there is no streaming path: `download_enclosure` refuses an oversized enclosure by the feed's
  declared `length`, then by a `HEAD` `Content-Length`, then by the transferred size — but a host
  that lies about all three is still read into memory once. A streaming/size-capped transport
  (`send_to(request, sink, max_bytes)`) is R2 work.
