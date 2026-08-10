# 2026-08-08 — Temporary M9 runtime-verification toggle

## Outcome
- Added default-on `Settings.verification_enabled` (`CLUE_VERIFICATION_ENABLED`).
- `false` keeps the canonical `VERIFICATION` phase but skips M9.2 corroboration and M9.3
  faithfulness judging, constructs neither verifier, records `verification_enabled=false` plus
  `accounts_skipped`, incurs zero judge cost, and advances normally.
- The flag also prevents the API roots from constructing the earlier reverse-profiling M9.3 judge
  and toolbelt entailment judge. The direct `run_verification` tool no longer requires a gateway
  while verification is disabled.
- M10's use gate remains active in the disabled verification phase. Pre-spend authorization, born
  contact identity binding, freshness/retention, and strict merge exclusion of unverified tier-4
  claims remain unchanged. The toggle never promotes raw/unverified data.
- Documented the flag in `.env.example`; default `true` preserves all existing behavior.

## Verification
- Focused: `tests/test_config_settings.py`, `tests/api/test_verification_handler.py`, and
  `tests/api/test_run_composition.py` passed (one DB-gated skip).
- Ruff check + format-check over every touched Python file passed; `git diff --check` passed.
- `make typecheck`: 577 source files, no issues.
- `make contracts`: 24 kept, 0 broken.
- Full `pytest -q` completed with three unrelated existing failures: stale Stage-0 skill-v9 path in
  `test_agent_registry_wiring`, merged clue-design direct-logging findings, and a clue-design
  `.context` attachment tripping the workspace-rename token guard.
- Repository-wide `make check` stops at its first formatting gate because 21 unrelated existing
  files would be reformatted; those files were not changed.

## Operational use
- Set `CLUE_VERIFICATION_ENABLED=false` and restart the relevant API/fleet process.
- Re-enable with `CLUE_VERIFICATION_ENABLED=true` (or unset it) and restart.
- This is deployment-scoped rather than pinned per durable run; a restart with a changed value can
  change the verification mode before an uncommitted verification phase executes.
