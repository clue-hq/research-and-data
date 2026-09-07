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
