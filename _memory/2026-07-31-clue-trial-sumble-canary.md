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

- Redis and OpenRouter were detected.
- `CLUE_SUMBLE_API_KEY` was not detected, so the live T6 canary was correctly not run.
- Start with `uv run python -m clue_api.trial_main`, then
  `uv run python scripts/clue_trial.py doctor`; proceed only when doctor reports `ready: true`.
