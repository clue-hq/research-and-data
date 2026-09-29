# 2026-09-29 — live onboarding watch (Conduit AI) and the three cost/run defects it surfaced

Lane: `addis-ababa` (branch `website/custom-domain`), stack on 3021/8011/8022/8031/8040, lane DB
`clue_addis-ababa@55040`. The founder ran a real onboarding of conduit.ai while I watched the
platform API, design API, fleet worker and ingestion-pool logs and the money tables.

## Ids
- workspace `ws_b10206c7479643f0a6de0517693b6c0d`, brand `brd_62b817d9f0c842ad8be578357fd6e96a`,
  project `cf3ae217-b777-448d-b0d7-4d89b0294e9f`
- onboarding run `ffc93bca-4480-4a8f-b2a6-c336885717bb` (kind `full`, lane `onboarding-v2`);
  fleet task `7eee9ed8-ef4d-4004-9e25-7e36df338ea9`
- design ingestion jobs: website `ingest_939ba44d06c04108b39099b86cb5fc80`, ad assets
  `ingest_d52294c91a0e4db4a0363a9f4043614a`
- Exa agent runs: overview `agent_run_285a2c96…` (high, $0.50), reviews `agent_run_3127425405…`
  (medium, $0.10), seven product-research runs (medium, $0.10 each), three persona steps ($0.075 each)

## What was honest and what was not
- `onboarding_step.cost_usd` is the true Exa agent spend (reads the terminal body once).
- `provider_call_ledger` / `make cost-report` overstated Exa ~30× (see defect 1).
- Honest spend at 14:27 UTC: Exa agents $1.56, Exa deep-reasoning $0.49 (every
  `exa_search_evidence` call retried once under the thin-response rule — a pattern, not a defect),
  OpenRouter $7.22 (asset descriptions, dominated by runaways — defect 3), grok-4.6 synthesis
  $1.69 (23 calls, 566k input tokens, `agent_model_call`).

## Defects found and fixed (commits `f6c2a41f0`, `e818a815b`, `40c4185e9`)
1. **Exa agent ledger over-count.** Exa returns `costDollars` (the effort's fixed price) on the
   create response and on every running poll; `exa_agent_cost_reader` booked it on each leg
   (208 poll rows → $37.20 phantom). Now only a terminal body settles money; create/running polls
   are `usd_unpriced` with the quote kept as `quoted_cost_breakdown`. Residual: a `timed_out` run
   books no charge. The rows already written for this workspace were NOT rewritten (append-only
   ledger) — `make cost-report --workspace ws_b102…` stays inflated for this run.
2. **Run failed after every step completed.** Lineup had 10 entries → 7 products (3
   `model_reused`); the fan-out launched per entry, the 8th launch collided on the deterministic
   step id, the open sat outside the step's containment, `finish_run` never ran. Now
   `_one_link_per_product` + the open inside the containment (`onboarding.step_open_failed`).
   The run row `ffc93bca…` is still `failed` in the lane DB (founder's call to flip it; all steps
   are `completed`).
3. **Describer runaways.** No `max_tokens` on the describe body; deepseek-v4.1-flash looped to
   131072 output tokens at $0.157 a call (35 of 527 calls = $5.02 of $6.46). Measured legit
   output: median ~4.5k, p99 ~15k. New `LUMEN_INGESTION_DESCRIBE_MAX_TOKENS_PER_ASSET=32768`
   (× assets per call, ceiling 131072) in config + both `.env.example`s + the lane `.env`.

## Verification
- `tests/arv2/test_exa_agent.py` (10), `tests/arv2/test_onboarding_driver.py` (28; dedupe test
  proven red under the old fan-out), design `tests/test_describe_max_tokens.py` (2) +
  `test_ingestion_deployment_config.py` — all green; ruff/format/mypy clean on the changed files.
- Wider `tests/arv2` (no live/db): 3 pre-existing reds inherited from the ai-ark merge, none in
  the changed files — `test_import_guard` (quality_* files import `clue_api.quality_research_artifacts`
  / `execution_wiring`), `test_account_research_port` (recipe pin 22 vs catalog 24),
  `test_discovery_driver::…not_composed_without_the_flag_or_the_key` (only when the lane `.env`
  with a real key is sourced); 3 collection errors (`test_person_*_trial*.py` import a
  `duration_of` that `media_acquisition` no longer exports).
- Design-side ruff shows 19 findings in `describe.py` and formatting drift in `config.py` that
  predate this work (their lines untouched).

## Not done / owed
- The running stack still runs the pre-fix code (workers, design API, ingestion pool); a restart
  is needed for the fixes to take effect and would interrupt the live ingestion job — founder's call.
- Asset-description failures on this site (75 of 489 at 14:27): 6 originals unavailable, 5 image
  worker did not finish, the rest the model returning empty title/description/usage (validation).

## Closing entry (14:40 UTC)
- Founder ruling: delete the onboarding, stop everything. Stack brought down with
  `dev_stack.sh down`; leftover ingestion-pool and `next dev` processes of this worktree stopped by
  hand (the script does not own them once `up`'s trailing status hangs); all of 3021/8011/8022/
  8031/8040 free; dubai's stack untouched.
- **Lane DB `clue_addis-ababa` dropped and recreated empty, migrated to head `6eb27d45f570`**
  (one head). The Conduit AI workspace, the suites' `ws_test_*` rows and any login mapping are gone;
  `.artifacts` blobs of that workspace are orphans on disk. Sign in fresh before the next walk.
- The next stack start runs the fixed code (`f6c2a41f0`, `e818a815b`, `40c4185e9`) — the
  three defects above were never exercised live; the next onboarding is their live proof.
