# 2026-09-14 — Lane 3 slice 1: the cost read — proven on the lane database (paid turn owed)

Branch `lane3/slice1-cost-read` (off `research-streaming` at `5010db4f6`; picked up in the
`semarang` conductor workspace after the original worktree was removed). Plan:
`docs/superpowers/plans/2026-09-14-lane3-slice1-cost-read.md`. Commits: `b80681bd1` (plan + design
note + rulings), `27d02433c` (T1 migration `d36bc7d32c9a`), `ff1c65491` (T2 shared stamp reader),
`80239d174` (T3 receipt records cost), `82875e5b9` (T4 `clue_projections.cost`), `738a5c4fd` (T5
`GET /cost/report`), `97d136a3c` (T6 `cost_cli` + `make cost-report`), `52353d260` (T8 docs) and
this note's own commit. Pushed 2026-09-14 as `origin/lane3/slice1-cost-read`; PR #55 onto
`research-streaming` (https://github.com/clue-hq/research-and-data/pull/55). Until the local
`research-streaming` (139 commits ahead of origin) is pushed, that PR's diff also shows lane 1 and
lane 2's changes; it collapses to the nine lane 3 commits once the base is pushed. The SDD ledger (git-ignored, removed at close-out) held every ruling; they are repeated below.

## What landed
- `agent_model_call.cost_usd numeric(12,6)` + `cost_source text` (CHECK metered/estimate/unpriced;
  migration `d36bc7d32c9a`, reversible — proven by `make db-smoke` on a fresh empty DB). The
  conversation-turn recorder (`agent_runtime_wiring.py::on_llm_end`) stamps them from the gateway's
  `clue_cost_cents` / `clue_cost_source` through the one shared reader
  `clue_gateway.metadata.cost_cents_from_metadata`; the ARV2 agent's `_cost_cents` delegates to it.
  `cost_millicredits` untouched (still 0; credits milestone). Replay compares the two columns;
  failed and unpriced calls record a blank, never a zero.
- `clue_projections.cost.cost_report()` — one workspace-scoped read over `provider_call_ledger`
  (`phase='result'` only) and `agent_model_call` ⋈ `agent_turn`, with provider / model / job /
  project lines, four cost_source labels counted per line, project / run / job / thread / time
  filters (a filter a ledger cannot honour empties that half and says so in `notes`), and a constant
  `not_covered` list on every report.
- `GET /cost/report` on the projections router (`X-Workspace-Id` seam; 422 on an inverted or naive
  window) and `python -m clue_projections.cost_cli` / `make cost-report ARGS="--workspace …"`.

## Proof (zero spend, lane database)
The lane's throwaway DB `clue_lane3-cost-read` (server `clue-pg-istanbul`, port 55040) was
re-created as a `pg_dump` copy of `clue_san-salvador` (5,958 ledger rows, 387 receipts, 64 turns,
three workspaces) and migrated `639d081ad799 → d36bc7d32c9a` on those real rows.
- Function, endpoint and CLI agree on every workspace: `ws_869a9f51…` 15.601460 USD (credits 90.4),
  `ws_2875e9e3…` 15.320425 (credits 347.2, 3046 media-seconds), `ws_arv2_answer_key` 12.860410
  (credits 42.0, 9747 media-seconds); provider lines ordered by spend (openrouter agent_completion,
  exa search / contents / deep-reasoning / answer, exa_websets items, gemini transcribe, ai_ark
  credits-only, ashby / live_http / rss free); jobs largest-first (26 / 13 / 16); per-project split.
- Job filter `5d3275d6…` → 1.203330 with the turn-receipts note (all three surfaces); thread filter
  → 43 head_of_abm receipts and the ledger note; inverted window 422, naive `since` 422, no header 401.
- Every existing receipt is `unpriced` (written before the columns existed) — the honest path.
- Probe scripts and outputs: `.context/lane3-slice1-proof/` (git-ignored).
- Test evidence on the lane DB: tasks 1–3 neighbours 367 green; `tests/projections` 65 green;
  endpoint 2 green; CLI 2 green. Gates: ruff clean; lint-imports 26 kept / 0 broken; mypy exactly the
  4 pre-existing errors (ad_assets.py:149, account_research_claims.py:1387,
  account_research_driver.py:181-182 — none in lane files).

## Discovered, recorded, not done here
- **Slice 1b — JSONL ledgers onto Postgres.** The onboarding lane (`arv2/onboarding_driver.py:281-295`
  via `fleet_main.py:720`), the display prewrite (`arv2/display/page.py:100-118`) and the
  persona-evidence tool (`onboarding_evidence_tools.py:228-245`) ledger through `ProviderCaller` to
  JSONL files. Mechanics: `LedgerStamp` gains optional `project_id` / `project_run_id`; the onboarding
  driver already holds a `conn_factory` and an `ArtifactSink`, so it swaps `JsonlLedger`/`FileRawSink`
  for `BufferedLedger`/`BufferedRawSink` and drains after each step under its own connection with
  `job_id = run_id` (discovery's pattern, `discovery_driver.py:1221-1225`); the reconciler builds its
  own caller per run and needs the same; the evidence tool runs inside a chat turn with no connection
  in hand and needs a drain seam. On the real rows every `prj_onb_*` project reads 0/0/0 today.
- **Doubled `answering_model` on streamed head-of-ABM receipts — FIXED 2026-09-15 (e9b6262a4).**
  ("x-ai/grok-4.6x-ai/grok-4.6", 356 rows; onboarding_synthesis receipts clean.) NOT a lane 1
  defect: the doubling exists in every lane DB from 2026-08-27, the day head-of-ABM moved from
  `openai/gpt-5.6-terra` to `x-ai/grok-4.6` (clue_nashville/clue_colombo have it; the lane DB only
  dates from 09-11). Two mechanisms, one cause — LangChain's chunk merge (`merge_dicts`,
  langchain-core 1.5.1) concatenates equal string metadata: (1) OpenRouter repeats
  `finish_reason`/`model` on its usage chunk, so langchain-openai sets `model_name` on two chunks
  and the runtime's `on_llm_end` (which read `model_name`) saw it twice — the persisted LLMResult
  artifact also shows `finish_reason: "tool_callstool_calls"`; (2) the gateway stamped
  `clue_answering_model` on EVERY chunk (41 copies on one real turn), unread on this path. Fix: the
  gateway stamps the usage chunk only (`_carries_usage`; streams always ask `stream_usage=True`),
  and the turn runtime reads `ANSWERING_MODEL_KEY` before `model_name`, as the research agent's
  rounds already did. Tests: `tests/gateway/test_agent_model.py::test_the_merged_stream_carries_the_answering_model_exactly_once`,
  `tests/api/test_agent_runtime_wiring_answering_model.py`. **The 356 stored rows stay doubled**:
  `agent_model_call` is append-only by trigger and that invariant was not bypassed; the cost read
  still groups by the stored string, so pre-fix history shows under the doubled label.
- **`chat/completions` ledger rows carry no model or usage extras — FIXED 2026-09-15 (e9b6262a4).**
  The 107 `structure-*` and 7 `media.mine_quotes` result rows stamped only `cost_source`. Fixed at
  the one seam all five OpenRouter writers share: `openrouter_cost_reader` now returns `model`,
  `prompt_tokens`, `completion_tokens`, `cached_prompt_tokens` in `CostReading.extras` (the wrapper
  merges them into the result row), under the `round-*` keys the per-model breakdown reads. The
  114 stored rows were backfilled on `clue_san-salvador` from their saved response bodies
  (`response_artifact_key`), so the breakdown reads them as `openai/gpt-5-mini` with tokens now.
- `tests/api/conftest.py::FLAG_ENV_VARS` neutralises only bool settings, so this checkout's
  `CLUE_CHAT_REASONING_TRACE_MODE=raw` fails `test_production_app_construction_requires_authenticated_principal_service`
  locally (passes with the variable unset; CI has no .env). Unowned.
- Design subsystem spend (R12 hold) stays outside the read; `not_covered` says so.

## Rulings taken this session (also in the SDD ledger)
1. `.env` NOT repointed — a live semarang stack (:8070/:3040) uses `clue_semarang`; every DB command
   derives the lane URL (`${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read`).
2. The lane DB was dropped and re-created from a container-side dump of `clue_san-salvador` (it held
   0 ledger rows / 0 receipts / 0 turns before); `make db-smoke` cannot run on it (the M8D R2
   downgrade guard refuses over `entity_research_job` fleet tasks) so the smoke ran on a fresh empty
   `clue_lane3_smoke`, dropped afterwards.
3. The WIP commit 454dadbd1 was amended in place to the plan's Task 3 message (content unchanged).
4. Task 4's test helper repair (a filter must be built from the same seeding — the plan's helper
   filtered a second seeding by the first seeding's ids) accepted; assertions verbatim.
5. Task 5 constructs `CostFilters` before comparing the window (a half-aware window is 422, not 500).
6. Task 6's CLI opens `clue_db.db_lifespan()` around the read (the plan's `main` would have raised
   "no active database engine").
7. Task 8 makes three consistency edits in the lane index (title, intro sentence, the Lane 1 ↔ Lane 3
   bullet) beside the new Lane 3 section.
8. The paid live turn (Task 7 steps 1–4 on a running stack) is founder-triggered, as every lane's
   live gate has been; the slice's proof ran over real rows with zero spend.

## Verification owed (founder-triggered)
One real conversation turn on a stack running this branch (the semarang stack on :8070/:3040 runs
`clue_semarang`, which is BEHIND head — migrate it or point a stack at the lane DB first), then:
```
psql "$CLUE_DATABASE_URL" -c "SELECT m.sequence, m.answering_model, m.cost_usd, m.cost_source, m.cost_millicredits
  FROM agent_model_call m JOIN agent_turn t ON t.id = m.turn_id
  WHERE t.thread_id = '<thread id>' ORDER BY m.started_at DESC, m.sequence LIMIT 5;"
make cost-report ARGS="--workspace <workspace id> --thread <thread id>"
curl -s -H "X-Workspace-Id: <workspace id>" "http://localhost:<projections port>/cost/report" | python -m json.tool | head -60
```
Expected: the newest rows carry a non-NULL `cost_usd`, `cost_source='metered'`, `cost_millicredits=0`;
the thread-filtered CLI shows the same turn spend; the endpoint total equals the CLI total. If
`cost_source` reads `unpriced`, the gateway had no rate for the configured model — record it, it is
not a slice-1 defect.

## 2026-09-15 — the two findings above fixed; lane DB migrated

- `clue_san-salvador` upgraded 639d081ad799 → d36bc7d32c9a (both new columns nullable, applied under
  the running pre-merge stack; the merged code's receipt insert needs them at the next restart).
- Verified: gateway + arv2 suites green except the pre-existing `test_import_guard` failure
  (`arv2/icp_authoring.py` importing `clue_api.project_library_refresh`, from 48edda9e8 — lane 2's
  project library, unowned here); the four receipt DB suites and `tests/projections -k cost` green.
- Not done: no repair of the 356 doubled receipts (append-only trigger, see above); no live paid turn.
