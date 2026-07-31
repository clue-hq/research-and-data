# Clue Trial Sumble canary — 2026-07-31

## Final state

- Branch: `platform/clue-trial`.
- T0–T5 of `docs/superpowers/plans/2026-07-31-clue-trial-sumble-only.md` are implemented.
- The CLI is HTTP-only. The local server composes production Stage 0, direct-account M6 admission,
  Sumble receipt acquisition, project phases, and canonical C7 reads.
- Organizations and Jobs have a three-credit aggregate hard cap. Confirmed Tech Stack remains
  default-skipped because its credits scale with results and needs a separate explicit opt-in.
- Paid responses are archived before resolver use and replay through the durable idempotency
  ledger. Unknown spend remains pending for manual reconciliation.
- Human tier approval now re-enters the real tier-checkpoint handler, persists tier claims, and
  then advances to DEEP. The old path advanced without tiers and selected no accounts.
- Inspection exports live under `.context/sumble-trials/<trial-id>/` and are non-authoritative;
  Postgres and artifact storage remain authoritative.

## Verification

- Clean dedicated DB: migrations through single head `6a7f8eed5b23`.
- 33 DB-backed Sumble/scoring/checkpoint/C7/spine tests passed.
- 81 HTTP/Stage-0/Sumble/durable/composition tests passed (83 collected; two expected skips).
- Ruff and focused mypy passed.
- Real loopback smoke passed: server startup, C7 startup check, trial create, status, exit, and
  fresh-process resume. No model or Sumble request was made.

## Manual canary prerequisite

- Redis, OpenRouter, and `CLUE_SUMBLE_API_KEY` were detected by the live doctor.
- Start with `uv run python -m clue_api.trial_main`, then
  `uv run python scripts/clue_trial.py doctor`; proceed only when doctor reports `ready: true`.

## Clean-slate reset

- Before the first manual canary, the configured local `clue` database was deliberately reset and
  migrated to `6a7f8eed5b23`; generated Stage-0 and Sumble trial directories were removed.
- No backward-compatibility path was retained for the pre-Sumble field definitions. A clean
  database seeds the current field contracts directly, which is appropriate before first testing.
- The field registry remains fail-closed: redefining a field key with a different contract is still
  rejected instead of silently mutating the contract.

## Stage-0 first-turn repair

- The first manual turn failed before model execution because the trial used private labels
  (`stage0_user_turn` / `stage0_context`) where the durable artifact schema accepts the canonical
  binding kinds `conversation` / `context`. The production call sites now use frozen constants,
  with a real-Postgres constraint regression.
- The CLI/API boundary now records every incoming human turn as an idempotent `user_turn`
  onboarding input before the agent runs and passes that exact id to the Stage-0 context. The
  trial uses the schema-valid actor `human`; target-ICP/campaign choices are explicitly routed as
  project state rather than invented claim fields.
- OpenRouter GPT-4.1 can return a plain-text stop despite mandatory durable finalization. The exact
  tool middleware now requests tool use and permits one bounded, finalize-only recovery call. A
  second plain stop still fails closed. If an `awaiting_input` response omits the redundant
  `next_actions` array, the finalizer reuses the exact durable user-facing message as its action
  reference instead of inventing content.
- Isolated live verification crossed the same HTTP route successfully: `awaiting_input` response,
  one human onboarding row, committed finalization, user+assistant thread history, and the complete
  `requested -> context_ready -> running -> awaiting_input` event sequence. No Sumble call ran.
- Focused unit, database, governed Stage-0, Recipe-0, HTTP, and tool-contract regressions passed.
  One toolbelt matrix test is feature-flag-sensitive and passed when run with its expected C7 read
  flag disabled.
