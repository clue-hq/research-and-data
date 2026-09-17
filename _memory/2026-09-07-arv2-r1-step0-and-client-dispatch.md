# 2026-09-07 — ARV2 R1: Step 0 foundation landed; six provider clients dispatched in parallel

Branch `track-R` (Conductor workspace san-salvador), cut from `integration/design-improvement`
@ `46ab5892b` (master plan v1.6). Plan: `docs/superpowers/plans/2026-09-07-arv2-r1-foundation-and-provider-clients.md`
(committed `8e2272bbb`). SDD ledger (git-ignored):
`.superpowers/sdd/2026-09-07-arv2-r1-foundation-and-provider-clients/progress.md`.

## Founder rulings taken this session (Aryan)
- R1 tests run **live against the real providers**; no replay fixtures. Tests skip with the env-var
  name when a key is unset. The wrapper's own retry/halt timing is the one place a scripted
  transport is allowed.
- Gemini `gemini-3.5-transcribe` is called on Google's **native** endpoint (OpenRouter serves
  neither that model nor a file upload) — the one exception to "OpenRouter only". Short items
  (`google/gemini-3.5-flash-lite`) and embeddings (`google/gemini-embedding-2`) go through OpenRouter.
- Keys now in the local `.env`: Exa, OpenRouter, AI Ark (`CLUE_AI_ARK_API_KEY`, paid plan; the key
  answers `POST /v1/companies`; `GET /v1/credit` returns 401 even with a valid key), Gemini
  (`CLUE_GEMINI_API_KEY`). AI Ark key source: app.ai-ark.com → Settings → API Management.

## Step 0 (Task 1) — DONE on track-R: ee6fe1c94, 3544ac9ba, ebe4f2945, fix 076f0114a
- `Settings`: `arv2_account_research_enabled=False` (flips to True after the R2 exit gate), the
  `CLUE_ARV2_*` model/ceiling/pacing knobs; `Secrets.ai_ark_api_key`, `Secrets.gemini_api_key`;
  all mirrored in `.env.example`; `httpx` declared on `clue-api`.
- `platform/api/clue_api/arv2/`: `calls.py` (`ProviderCaller` — estimate row before the wire, raw
  record per attempt before any parse, Retry-After else 12·(n+1)s / 2·(n+1)s, halt latch, result
  row; ceilings record-only; `raw_scrubber` output REPLACES the body on every path), `sinks.py`
  (`FileRawSink`/`JsonlLedger`/memory pair, redaction, `LedgerRow` = the R1 shape of
  `provider_call_ledger`), `transport.py`, `openrouter.py` (plain-HTTP builders + cost reader,
  no SDK), `text.py` (verbatim verdicts), `errors.py`.
- `tests/arv2/`: import guard (allowlist), wrapper unit tests, live foundation (Ashby GET +
  one paid OpenRouter completion). 37 green live. Raw/ledger output under `.artifacts/arv2/`.
- Docs: `provider_call_ledger` table spec added to master plan §4 and data-source map §2.2 as a
  D1 addition (raw bodies → `artifact` rows via `record_artifact`; table + artifact sink land at A7).

## Tasks 2–7 — dispatched (Opus, parallel), one worktree + branch each
`/Users/aryankeshri/conductor/worktrees-arv2/<name>` on `task/R1-<name>`, base `076f0114a`:
ai-ark, exa, ats, media-feeds, gemini-media, structuring. Each has its own `.venv` and a copy
of `.env`. Client tasks do not edit `arv2/__init__.py`, README, settings, or `.env.example`; the
controller adds exports at merge. Reports land in the SDD workspace as `task-N-report.md`.

## Open / to watch
- Merge order into track-R: any, as each passes Fable's personal review + live suite re-run.
- Live-suite spend per full `tests/arv2` run once all six merge: roughly $0.50 + ~5 AI Ark credits.
- Worktrees to remove after merge: `git worktree remove /Users/aryankeshri/conductor/worktrees-arv2/<name>`.

## Progress addendum (same day, later)
Merged into track-R after Fable's personal review + live re-run of each suite: Task 5 media feeds
(4c3c626fe), Task 4 ATS (911ec53a9), Task 2 AI Ark (39d691b05), Task 6 Gemini media (24905e90e),
Task 3 Exa (2a9a380e6 + fix 592d7f65d adding `CostReading.extras`). Consolidation commit
(f26674301): package exports for the merged clients (entry points only — two different
`AudioFile` types exist), `upload_id` added to the redacted query params, README integration
notes, product-catalog schema property count corrected to eight (the JSON was right, the prose
said nine). Task 7 structuring still in flight on `task/R1-structuring`.
Live facts learned: OpenRouter accepts `input_audio` base64 for gemini-3.5-flash-lite; native
transcribe reproduces the PoC cost ($0.0192834 for 42:49); Exa accepted the §3 schema with `enum`;
AI Ark `/v1/credit` is 401 even with a valid key; probook.ai's careers page is `/company`, reached
only via link text; the Boardroom feed has 101 episodes (the PoC's "65" was a truncated save).

## Close-out addendum
- Task 7 structuring merged (b792b5a15 + fixes 823d15a9e, 4ebcf05c5); consolidation 2
  (05b032628): exports, shared `openrouter_halt_rule` wired, person live gate counts
  evidence-bound rows (ruling).
- Final whole-branch review (Opus): 0 Critical / 7 Important / 11 Minor, "merge with fixes".
  One fix wave (4acbf578c, af394fe62, 43ed24881) applied every ruled item: header VALUES redacted
  (the Files API `x-goog-upload-url` and `x-goog-upload-control-url` carried a live `upload_id`
  token into raw records), request bodies capped at 64 000 chars inline (base64 audio no longer
  written per attempt), scrubber failures leave a body-less record + typed `RawScrubFailed`,
  OpenRouter 403 is moderation not money (no latch), `gemini_native_halt_rule` split from
  `openrouter_halt_rule`, HEAD Content-Length precheck on enclosures, `transcription_input_from_enclosure`
  ships the AudioFile conversion (raises on unknown duration), README "R2 composition constraints"
  (asyncio.to_thread at every fleet entry; one ProviderCaller per worker task; reset_halt is an
  operator action), `over_ceiling` re-evaluated against actual cost, negatives default
  outreach_safe=False, fence markers neutralised inside bundles, evidenced career links ranked first,
  media reservation released on failure, feed body cap 5 MB, deep-reasoning/transcribe max_attempts=2.
- Finding for the founders: bundle-borne prompt injection is real (reproduced live); D-track bundle
  assembly must never include prompt text.
- Live-suite mechanics: a `nohup` run from the tool shell was killed before its summary line;
  `setsid` does not exist on macOS. Run the live suite as bounded chunks (<10 min each).
- Live on the fixed head 43ed24881: Exa, Gemini, foundation, ATS, media feeds, structuring all
  green; AI Ark returned HTTP 402 "sorry, you don't have enough credit" at 12:03 UTC and the client
  latched (designed behaviour). The AI Ark account needs the paid plan / a top-up before the AI Ark
  live file can pass again; ~24 credits were recorded today across all runs.
- Founder instruction (post-close): cost tracking active on every response + a provision for the
  cost of each request. Task 8 (f8fa712b4, 7b91d6ea3, 00d4b042a): `CallCost` on every client return
  value (cost_usd, credits, media_seconds, cost_source metered|free|estimate, ledger_row_id, raw_ref,
  provider, operation); `cost_source` written on every result ledger row; README "Cost per request".
  Deferred to R2: an explicit `free: bool` on CallSpec so a forgotten cost reader cannot read as free.
- PR #45 (track-R → integration/design-improvement) MERGED 2026-09-07. Workspace san-salvador now on
  `track-R2` (59af05177) off the merged base. Founder sequencing: R2 starts only after Track O's first
  task ("O1", the onboarding/ICP lane) is done; R2 prerequisites are listed in this session's
  final answer (D1 migration + lenient write path, S3 seed rows, S7 agent content, AI Ark credit,
  seam 1 signed, an ICP artifact to read, account entities seeded, D3 read surface).
