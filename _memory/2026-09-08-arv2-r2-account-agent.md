# 2026-09-08 — ARV2 R2 (account research agent): plan written, ready to execute

Branch `track-R2` (worktree san-salvador), rebased onto `integration/design-improvement` @ `33ab4fed1`
(O3 + O4 + D2 merged; single alembic head `9f81e5692fea`). Founder rulings today: stop policy
(100 rounds / 50 per round / 30 min, no total-call or zero-yield caps, full mode only); ICP hard gates
are lenient fit verdicts, never an early exit; negatives born `outreach_safe=false`; twelve-section
charter; structuring client gains `mode=intent_sweep`. S7 substance fully APPROVED.

## Artefacts
- Plan: `docs/superpowers/plans/2026-09-08-arv2-r2-account-agent.md` (7 tasks; Task 7 = founder-triggered
  live acceptance on Probook + Zafran).
- Facts (exact signatures, four scouts): `docs/superpowers/plans/2026-09-08-arv2-r2-account-agent-facts/facts-{fleet,jobs,agent,tools}.md`.
- Substance §7 records the implementation decisions.

## Architecture decisions (why, in one line each)
- **Own rows + own fleet kind** (`arv2_research_run/_job`, `arv2_claim_annotation`, `arv2_account_research`):
  the M8D `entity_research_job` needs `product_id NOT NULL`, a sealed discovery and an `icp_spec`-keyed
  research directive (old Stage-0 machinery; standing-rule item 5), and its kind is owned by the
  quarantined handler.
- **Own `create_agent` loop**, not the M8D runtime: `EntityResearchStopPolicy` caps rounds at 64 and
  requires zero-yield/total-call caps; the tool-surface validator hard-codes M8D tool names; caps raise.
- **One `ProviderCaller` per tool invocation** with buffered sinks drained to `provider_call_ledger`
  (+ `extras_json`) and the artifact store after each `to_thread` hop; job-level halt registry;
  AI Ark/media serialised. Known residual: a lease lost mid-hop can lose that hop's rows.
- Only the launch/read tools join the toolbelt (`launch_arv2_account_research@1`,
  `read_arv2_account_research_run@1`, HEAD_OF_ABM; authority count 120→122); the twelve agent tools are
  `StructuredTool`s inside the driver.
- Stop-policy numbers are `CLUE_ARV2_ACCOUNT_*` settings (six new fields) — a limit change is an env change.
- Two new pack keys: `account.committee_candidate`, `account.icp_fit_verdict` (40 keys).

## Pre-existing base failures (not R2's)
`tests/arv2/test_onboarding_settings.py` (`CLUE_ONBOARDING_V2_ENABLED=true` vs default False) and
`tests/arv2/test_settings.py` (quoted display pitch). Two-line fixes on the base lane.

## Next
Execute the plan (subagent-driven, Opus implementers, Fable reviews each task). AI Ark people credit
is the only external prerequisite left before Task 7.

## Execution progress (SDD, Opus implementers, Fable reviews) — 2026-09-08
- T1 cad840c68 (settings/kind/migration a3602967bb73/keys/wiring) ✓; T2 5dfac9547+ee1ac0bab (catalog files, refusals, prompt assembly) ✓;
  T3 6a7f31a96 (buffered sinks → provider_call_ledger + artifacts; store) ✓; T4 d8345bf9e+5cf692557+1a8399d37
  (mappers, intent_sweep mode, twelve tools) ✓ — review fixes: AI Ark revenue → core.revenue_band enum bucket in
  code or not claimed; intent_sweep needs its own USER prompt + code cap of 4 (live run 1 returned 17 broad rows;
  2/2 pass after fix); T5 7981af58e+0b3cb0801 (create_agent loop with cap-to-end middlewares, fleet driver) ✓ —
  review fixes: artifact sink + model provider injected from fleet_main (no second artifact write path, no
  import-linter ignore). T6 (launcher/toolbelt/CLI/fleet_main) in progress. T7 = founder-triggered acceptance.
- Ledger: `.superpowers/sdd/2026-09-08-arv2-r2-account-agent/progress.md` (gitignored; rulings listed there).
- Rulings so far: T5 may extend the T3 store; Fable reviews directly (user rule); cap-ended jobs land `completed`
  with reason in receipt; parallel file-disjoint fix round was allowed once (structuring_client.py only).

## Final whole-branch review fixes — 2026-09-08
Review: `.superpowers/sdd/2026-09-08-arv2-r2-account-agent/final-review.md`; fixes report:
`…/final-fix-report.md`. Three findings closed before the Task-7 acceptance run:
- **C1** the launch no longer enqueues. `Arv2LaunchReceipt.to_enqueue` (every job of the run) +
  `enqueue_launched_jobs(queue, receipt)`, called by `DbArv2LaunchService.launch` after the
  `conn_factory` block and by the CLI after `trans.commit()` (prints `"enqueued": n`). Driver
  defence: `begin_job → None` now reads the row — absent → `job_row_not_visible` requeue after 5 s
  (12 attempts, then a loud `failed`); only an existing row is the idempotent `completed`.
- **I1** `handle` catches `asyncio.CancelledError` (lease loss), suspends the job under
  `asyncio.shield`, and re-raises — the job is re-claimable instead of stranded `in_progress`.
- **I2** `_without_nones` drops null optional properties from every mapped claim value (required
  keys stay, so a genuine mismatch still flags `schema_valid=False`).
- **I3** (context growth over a 100-round loop) is NOT fixed: it is a Task-7 live watch item —
  if a job ends `model_error`, read the worker log for a context-length error first.

## Task 7 live acceptance — 2026-09-08 (founder go) — EXIT GATE MET
Run `a0021ecf-8396-5f41-b4aa-eb8de755839a` (project_run `0a2f18b6…`), CLI launch, fleet worker from this
worktree (storage root repointed to `san-salvador/.artifacts`; answer key reloaded first).
- Probook: completed/finalized, 17 rounds, 64 tool calls, 85 claims (74 with quote+URL, 6 negatives,
  5 fit verdicts, 14 requisitions, 12 committee candidates), $0.2208 + 3.6 AI Ark cr; link audit
  EXACT 38 / PARTIAL 6 / NOT_FOUND 26.
- Zafran: completed/finalized, 12 rounds, 47 calls, 104 claims (95 quoted, 8 negatives, 4 verdicts,
  27 requisitions, 14 committee), $0.1517 + 3.6 cr; audit 39/21/27.
- Evidence: `.context/arv2-r2-acceptance/` (receipts, ledger by provider, claims by field, link audit,
  negatives+verdicts, worker log excerpt, D2 display outputs). D3 not merged → screens checked via the
  D2 CLI; the frontend screen check is OWED.
- R2-close follow-ups (observed, not fixed): unnamespaced proposed key loses a whole structuring batch
  (writer raises inside one txn); fit-verdict gate labels are paraphrased, not the ICP gate keys;
  45 claims schema_valid=false (objects in scalar core fields; vacant seats); link audit NOT_FOUND
  ~30-40% (LinkedIn/dynamic pages; separate fetch_failed); **model token spend is not in
  provider_call_ledger** (gateway logs cost_cents 0 for grok-4.6 agent completions) — money-truth gap;
  one job per worker at a time; context ~97k tokens by round 13 (no model_error).
- PR #49 MERGED into integration/design-improvement (a758b5b1f, 2026-09-08). New branch track-r2-v1 for R2 close.

## R2 close — 2026-09-08 (branch `explain-r2-close-plan-simply`, local only, nothing pushed)

The six tasks of `.superpowers/sdd/2026-09-08-arv2-r2-close/` (briefs + per-task reports there),
each closing a follow-up the Task-7 acceptance run observed. Docs updated by Task 6:
`platform/api/clue_api/arv2/README.md` (R2 section), `docs/specs/ARV2-MASTER-PLAN.md` §9 R2 row,
this file.

| task | what it shipped | commits |
| --- | --- | --- |
| 1 | Answer-key recall measurement: `answer_key_recall.py` + `scripts/arv2_answer_key_recall.py`; structured values graded by their leaf values, not their key names; baseline recorded | `811b25837`, fix `b3811058a` |
| 2 | The agent's model rounds are `provider_call_ledger` rows (`openrouter` / `agent_completion`, ids carry the job attempt), cost from OpenRouter's `usage.cost` or its `/generation` endpoint (`cost_source` metered\|estimate\|unpriced), receipt carries `model_spend` | `73925fb95`, `f0c4507a9`, `cf9420b10`, `cb8ece1e5` |
| 3 | Structuring hardened: `structure_material` takes `sources[]`+`notes` (notes are never evidence; the cited URL is corrected to the source block), per-draft writes with `write_failures`, proposed-key normalisation, scalar coercion with `coerced_from`, vacant committee seats; AI Ark mapper widened to every registered core/account field the record carries, HQ in the registered shape, funding as USD | `0e47f7e4c`, `e41d0b8c0` |
| 4 | The link audit records a reason per claim (`on_page`, `partial_on_page`, `page_empty`, `page_unreachable`, `not_on_page`, `second_hand_from_report`, `quoted_context`); the receipt tallies `verdict/reason` | `ce006fd97` |
| 5 | Fit verdicts keyed to the ICP's `hard_gates[].key` (unknown label refused, missing gate filled `unclear`, duplicates dropped; the keys are in the agent's context); transient `tool_error` not remembered; provider timeout ends `model_error`; malformed ICP front matter refuses `icp_front_matter_invalid`; one profile digest | `69b27e3e8`, `6ff1f6bb2` |
| 6 | Docs + memory (this entry) | this commit |

### Founder rulings taken during the close
- **Model cost comes from OpenRouter only** — its reported `usage.cost` or its `/generation`
  endpoint. We ship no price table of our own; a deployment-supplied price is labelled `estimate`,
  and an unpriced round books `cost_usd = NULL`, never an invented zero.
- **Schema-invalid claims stay visible; the shapes are fixed at the source.** Nothing is dropped
  for failing its schema — the mappers and the coercion write the registered shape instead
  (`core.hq_location`, scalar core fields, vacant committee seats).
- **AI Ark funding amounts are read as USD**, with the assumption recorded per claim
  (`markers.currency_assumed = "USD"`). `core.annual_revenue` stays unmapped: a range with no
  amount and no currency is not a fact.
- **Measurement first** — the recall baseline is taken before the fixes, so the re-run has
  something to be measured against.
- **The Exa claims-mode experiment is deferred** (not part of this close).

### Baseline recall (pre-close, `.context/arv2-r2-acceptance/recall-before/`)
```
probook recall 0.50 (exact 9 / partial 3 / field_only 9 / missing 3 of 24)
zafran  recall 0.45 (exact 16 / partial 14 / field_only 27 / missing 9 of 66)
```
Sections — Probook `core` 5/13, `account` 7/9, `account.resonance` 0/2;
Zafran `core` 16/29, `account` 13/26, `account.resonance` 1/11.

### Task 7 re-run: founder-triggered, pending
The re-run against the same two accounts, graded with the same script into a `recall-after`
directory, is the close's exit gate. Nothing in tasks 1–6 has been exercised live.

## R3 rulings (founder, 2026-09-08)
- Contact selection: every confirmed committee member gets a person agent, up to committee_cap; a human can also launch research for any particular contact on demand.
- Email export: every member.
- Media per person: on by default.

## R2 close — Task 7 re-run DONE (2026-09-08 12:05–12:24Z, run `e5c457d3-e38b-5e36-b84f-114a841045cf`)
- Both jobs completed (Probook 15 rounds / 10m13s / 97 claims; Zafran 13 rounds / 7m46s / 113 claims).
- Evidence: `.context/arv2-r2-acceptance/rerun/` (`before-after.md` is the write-up; `before/` and `after/`
  collected with the same `collect.sh`; `recall-after/` from the recall script).
- Recall: Probook 0.50 → 0.50, Zafran 0.45 → 0.52 (all gains = widened AI Ark mapper; losses = empty media
  layer this run + agent-shaped objects). Link audit EXACT share 45% → 74% (Probook), 54% → 63% (Zafran);
  every verdict carries its reason. Schema-invalid 45 → 37, and none of the remaining are the shapes the
  close fixed — they are the agent's own `write_claims` shapes (string/list into bare-object fields; own keys
  where the field names required ones; `name: null` on vacant seats; one persona outside the enum).
  Root cause: the agent never sees `value_schema` at write time. Follow-up, not done.
- Model spend is on the ledger, all `metered`: ~$1.10 (Probook) / ~$0.98 (Zafran) for the agent's own
  completions, ~7¢ per round — 8× all provider spend combined. Total per account ≈ $1.2 + 2.6 AI Ark cr.
  No `gateway.cost_lookup_failed`.
- Defect found and fixed: the close relaxed `account.committee_candidate`'s schema in place; on a DB that
  already loaded the R2 pack the fleet worker refused to start (`FieldRedefinitionError`). Data migration
  `320e975d4c46` (303b1a084) swaps the stored schema exactly; proven by reproducing the refusal one step down.
  Lesson: a pack-row schema change ALWAYS ships with a data migration; fresh-DB suites cannot see this.
- Ops notes: this worktree needs its own fleet worker (`uv run python -m clue_api.fleet_main`, stopped after
  the run); the worker drives one ARV2 job at a time, so N accounts run sequentially.
- Exa claims-mode experiment kit for the founder's Playground run: `.context/arv2-exa-experiment/`
  (exact R2 deep-call bodies recovered from the ledger's request records, split into system prompt / query /
  schema files, plus a claims-mode output schema and `run.sh`). Not run by me.

## Exa claims-mode experiment — DONE by API (2026-09-08, 4 calls, $0.10)
- Founder's Playground runs were a third mode (free JSON sections, highlights not text): no per-assertion URL,
  NOT FOUND discipline collapsed, prompt framing echoed. `.context/arv2-exa-experiment/playground/evaluation.md`.
- Designed experiment (same bodies, only `outputSchema` differs): claims mode gives 17/20 rows vs ~60 cited
  assertions in report mode; quotes 94–95% verbatim in Exa's own retrieved text (report 56–86%) but values are
  paragraphs only half covered by their quote, one factual error (Zafran leadership titles swapped), zero
  NOT FOUND rows, half the sources. **Verdict: keep report mode**; optional prompt-only tweak ("quote first,
  one assertion per sentence"); claims mode only for narrow probes. `evaluation-claims-mode.md`.
- Ops: the Exa key env var is `CLUE_EXA_API_KEY` (an unset `EXA_API_KEY` makes Exa answer 402 x402
  pay-per-call, not an auth error). `run.sh` fixed.

## R2 follow-ups DONE (2026-09-09, plan docs/superpowers/plans/2026-09-09-arv2-r2-followups.md)
- Catalog menu renders `[shape: …]` per schema'd field; `write_claims` receipts carry `expected_shape` + a
  `corrects_claim_id` hint on a schema miss; `agent_claims` drops null optional keys (`dropped_null_keys`).
- Established block: compact JSON, 240 chars/line; `research_deep` clips it to 6k chars with an omission note.
- Deep-call EVIDENCE_RULES: one assertion per sentence, quote first; a sentence per NOT FOUND item.
- `read_media_feeds(alternate_urls=[…])` falls through on load failures; `feed_not_found` names every URL.
- AI Ark HQ shape emits `region` (state) and `country_code` when the record has one.
- Not measured live (founder ruling): folds into R3's acceptance run.
- Final review of the follow-ups (Opus, "with fixes") + one fix wave (321ebbb1c): `REACTIONS["feed_not_found"]` now
  matches the manual word for word and a test guards every row against drift; walled hosts are refused before
  any media hop is chosen; earlier load failures ride on a later refusal's detail; `expected_shape` is honest
  when the field is not in the job's catalog; candidates deduplicated. Left by ruling: type guards on
  region/country_code (M4); `schema_hint` assumes required ⊆ properties (verified across all 66 schemas, M9).
  Suite 600 passed / 76 DB-skipped; 19 pre-existing ruff findings outside the slice remain for a repo sweep.
