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

## Second onboarding — live proof of the three fixes (traced 17:05 UTC)
Stack up 14:45 UTC on the fixed code (all lane ports, 4 workers, ingestion pool). Conduit AI
onboarded again: workspace `ws_3c96440b557a413fa02bda3fbf90cc5e`, brand
`brd_ec0a9b5ddb734491af0e4f76bed3737b`, run `5856ce0f-1033-4600-b75c-ba15768aa393` (fleet task
`0396160f-52fd-4225-ba3b-d93780e00fe8`), 16:18:24 → **completed** 16:26:30 (8m06s), all 15 steps
completed. Website ingestion `ingest_c162dc8c5b99418284b42a21a7a80298` succeeded 16:34:36 (kit v1;
560 assets, 402 described / 67 failed); ad harvest `ingest_4e6face312df4a7187151eb63433a861`
succeeded with 0 ads kept (`advertiser_mismatch`).
- **Exa ledger fix — proven.** 241 agent-poll rows, 232 NULL-USD, 9 priced (= the 9 terminal
  bodies) summing $1.30 = the steps' own cost; `make cost-report` total now $7.41, not inflated.
- **Fan-out fix — proven.** Same shape as run 1 (10 lineup entries, Inbox/Workflows/Operator
  `model_reused`) → 7 product-research steps, run completed.
- **Describer cap — proven, but runaways remain.** 0 calls above 32,768; 77 of 607 calls hit
  exactly 32,768 ($0.034 each, $2.59 = 62% of the $4.19 describe spend; would have been ~$12 at
  131k). Every capped answer is truncated JSON, so it is waste; 22 assets failed that way after
  both attempts. Legitimate answers stop below ~17k (nothing between 17k and 32k).
- **New findings (not fixed):** (1) persona `exa_search_evidence@1` asks for 6 results at $0.015,
  which `is_thin_deep_response` (≤9 results and ≤$0.016) always calls thin → all 15 calls retried,
  the retry is guaranteed double spend ($0.225); (2) ad harvest: no `advertiser_name` in the request,
  so `select_creatives` took the dominant advertiser (employee "Cole Rubin") as the company, dropped
  27 other ads as `thought_leader`, then the guard refused the rest vs the resolved "conduit" —
  inferred from `onboarding.py:255` + `harvest.py:192/253`; the raw vendor body was not kept, so the
  name distribution is unverified; (3) `onboarding_run.cost_usd` ($1.561) omits the grok synthesis
  ($1.43) and the thin retries; (4) the design `brief` call (grok-4.5, 20.9k in / 4.4k out) is
  unpriced; (5) the ad job waited 16 min behind the website job (coordinator has 1 slot).

## 2026-09-30 — merge, brief model, ad-harvest name fix
- Merged `codex/ai-ark-committee-discovery-spec-v1` (16 commits: Head-of-ABM continuation,
  compaction, prompt caching) as `774c4d852`; clean, no migrations; 6 new `CLUE_AGENT_COMPACT_*` /
  `CLUE_HEAD_OF_ABM_CONTINUATION_ENABLED` flags copied into `.env` at their defaults.
- `bc156e5a2` founder ruling: the brand brief runs on `x-ai/grok-4.7` with its own
  `LUMEN_INGESTION_BRIEF_REASONING=medium` (it had sent no reasoning field). Its $0 ledger row is a
  separate defect: the gateway stamped `unpriced` and `lumen_api/spend.py:273` relabels that as
  `estimate`; why OpenRouter's cost did not come through is untraced.
- `e96f8ffc6` ad harvest: `select_creatives` now gets `resolution.resolved_name` instead of the
  empty request field, so the filter stops taking the most frequent advertiser (Conduit's
  executive "Cole Rubin") as the company. When nothing is kept, the advertiser check reads the
  names dropped as thought-leader, so a stranger's page still reports `advertiser_mismatch`
  (the fallback-path test pinned the weaker `empty`; updated). Ad suites: 105 passed, 2 failed —
  the same 2 fail on the unchanged code (`partial` != `ok`), stack down.
- Live re-run of Conduit's harvest (job `ingest_0daf8aa60ccb4bb59774ea916b001331`, full run,
  card allowed by founder) FAILED: Adyntel returned `402 Insufficient tokens. Please top-up` on
  page 2, twice (the job ran at 18:49 and again at 18:51 UTC). The real advertiser names are still
  unknown. OWED: top up Adyntel, re-offer the same body, check `evidence.steps.harvest`.
- Still open: the run cost total ignores `agent_model_call` and evidence retries
  (`onboarding_synthesis_wiring.py:1494`, `exa_client.py` keeps one attempt's cost); evidence
  searches always retry (6 results asked, thin rule <=9); design lane drops raw vendor bodies
  (`lumen_api/spend.py:62`, `artifacts=None`).

## 2026-09-30 — custom-domain walk: republish under a new slug left the old one live
- Founder's walk: republishing a page from `conduit-for-jw-marriot` to `conduit-jw-marriot` left
  BOTH serving. Publishes are keyed `(workspace, slug)`; `publish_web_document` replaced only the
  new slug's row. `4d9a5f469`: it now unpublishes the document's other live slugs
  (`clue_design.publishes.unpublish_other_slugs`); founder ruling: the old address 404s, no
  redirect. Test `test_republishing_under_a_new_slug_moves_the_site` (red without the fix).
- Live-proven 2026-09-30 on the lane stack: after republishing under `jw-marriot` the two older
  slugs are `unpublished` and 404 on the page origin; `jw-marriot` 200.
- GOTCHA: `dev_stack.sh restart-api` restarts ONLY the platform API (8022/8031), not the design
  API (8011). A design-API change needs the design API restarted by hand (kill its pid, relaunch
  with the `up()` env: PLATFORM_ENV + LUMEN_EMBEDDED_FLEET_WORKER=1 + LUMEN_CORE_HELPER +
  LUMEN_API_CORS_ORIGINS + PYTHONPATH, from `subsystems/clue-design`). The first "fix didn't
  work" report was this.
- Open: rolling back an unpublished slug re-activates it beside the live one (left as is).
