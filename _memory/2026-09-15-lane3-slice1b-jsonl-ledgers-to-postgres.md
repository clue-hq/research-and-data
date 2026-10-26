# 2026-09-15 — Lane 3 slice 1b: every provider call on the Postgres ledger

Branch `lane3/sice1b` (the founder's branch, rebased onto `research-streaming` after PR #55 — slice 1 —
was merged and pushed on 2026-09-14; no upstream yet, not on origin). Design: `docs/superpowers/specs/archive/2026-09-14-lane3-slice1b-jsonl-ledgers-to-postgres-design.md`
(founder decisions D1–D3). Plan: `docs/superpowers/plans/2026-09-14-lane3-slice1b-jsonl-ledgers-to-postgres.md`.
Commits: `e9fcee89e` (design), `aa7d1a8b6` (plan), `5ce794a8c` (T1 `LedgerStamp` optional
project/run/job), `74d5f5c5a` (T2 OpenRouter reader stamps model + token counts), `9f9569bae`
(T3 onboarding driver drains every provider step), `0a24a13ab` (T4 display prewrite + the
frontend read seam drain in their own transaction), `439e371da` (T5 persona-evidence tool),
`e7d44c191` (T6 cost read `not_covered` + docs), `769b368b0` (review minors), and this note. Local only
until pushed. NOTE: the base also carries a second, earlier slice 1b plan,
`docs/superpowers/plans/2026-09-14-lane3-slice1b-jsonl-ledgers-onto-postgres.md` (d097d9e6a, a different,
unapproved design: `extras_json.lane`, a generic client+spend wrapper) — not written or executed by this
session; the lane index row 1b names the executed `-to-` plan. The founder decides its fate.

## What landed
- `LedgerStamp(workspace_id, project_id=None, project_run_id=None, job_id=None)`; the drain writes NULLs.
- `openrouter_cost_reader` stamps `model`, `prompt_tokens`, `completion_tokens`, `cached_prompt_tokens`
  into every OpenRouter row through the existing `ProviderCaller._settle` merge — structuring, media,
  reconcile and display rows now join the cost read's per-model view (historical rows keep `unknown`).
- Onboarding lane: the driver owns a `BufferedRawSink` + `BufferedLedger` per provider step, hands
  them to the Exa client factory and the catalog-reconciler factory (both signatures gained the sinks),
  and drains after each step (recon and lineup in a `finally`, the catalog step on its held
  connection) through an injectable `drain`, stamped workspace + **job = onboarding run id (D1)**.
  `build_onboarding_provider_caller(raw=, ledger=)` writes nothing to disk;
  `build_onboarding_exa_client_factory(secrets)` lost its `settings` argument.
- Display prewrite: `RunnerFactory(raw, ledger)`; `ensure_page(..., artifacts=, spend_conn_factory=)`
  creates the section buffers before the gather and drains them sequentially in a `finally` under the
  injected factory with a workspace-only stamp; the script composes `DurableAgentArtifactStore` over
  `build_storage_backend` and passes `transaction`, so a `--dry-run` page rolls back but its spend
  rows commit (**D2**). The frontend read seam `DisplayPages` (a second `ensure_page` caller the plan
  had missed) takes an optional `artifacts` sink composed at `frontend_read/app.py` from the root's
  `evidence_storage`; `generates` is now a property meaning "runner AND sink", so a seam without a
  sink serves stored blocks and never spends.
- Persona-evidence tool (`439e371da`): `ExaSearchEvidenceTool` owns a buffer pair per invocation, drains
  in a `finally` under `ctx.conn_factory()` with a workspace-only stamp (the tool context carries no
  project), and refuses `artifacts_not_configured` before spend when no artifact store is composed
  (**D3**, checked after the Exa check so the keyless default composition still says
  `exa_not_configured`); `build_onboarding_evidence_tools(artifacts=)`; the toolbelt wiring passes a
  `DurableAgentArtifactStore` only when a storage backend exists.
- Cost read (`e7d44c191`): `NOT_COVERED` shrinks to the design subsystem (R12 hold) and pre-column turn
  rows; the design note (§3 row, §5.5, §9 1b DONE) and the lane index row 1b record it.

## Proof (zero spend)
- Every task's tests green on the lane DB (`clue_lane3-cost-read`, a copy of san-salvador at head):
  provider_ledger 3, openrouter 6, onboarding driver 24 offline + 2 DB, persona-run DB, fleet wiring,
  display 91 + display-pages seam 15 + contacts 15, evidence tool 20, projections 67; ruff clean;
  mypy exactly the 4 pre-existing errors; lint-imports 26/0; the display live test imports.
- `make cost-report --workspace ws_869a9f51…` now prints exactly two NOT COVERED entries
  (`.context/lane3-slice1-proof/cli_after_slice1b.txt`). No production module references
  `FileRawSink`/`JsonlLedger` any more (only the `clue_api.arv2` re-export and one docstring).
- Whole-slice run (tests/arv2 + the slice's api/agents/gateway suites): green except three attributed
  failures — the arv2 import guard (lane 1's `icp_authoring.py → clue_api.project_library_refresh`,
  48edda9e8, pre-existing on the base) and two answer-key loader tests that pass on a fresh empty DB
  and fail on the copied one because real `arv2_claim_annotation` rows reference the answer-key jobs.

## Rulings taken (all in the SDD ledger, repeated here)
1. A failing drain in the onboarding driver RAISES; the run fails loudly via `handle`'s containment
   (the catalog step's own except lands the step `failed` instead — accepted asymmetry).
2. Spec refinement: persona-only runs make no driver-side provider call, so the onboarding stamp is
   workspace + job only (no project id).
3. Exact offline labels: four drains (overview, reviews, lineup, catalog-reconcile), three rows.
4. The display live test counts `provider_call_ledger` rows instead of JSONL lines.
5. `DisplayPages` gains an optional sink composed at the root; generation needs runner AND sink;
   both seam calls pass their own connection factory as the spend transaction.
6. Four dead display-pages tests (bound-method `is True/False`) fixed in scope: `generates` became a
   property returning the combined condition.
7. The CLI render test asserts "design subsystem" instead of "onboarding" in the NOT COVERED block.
8. Three review minors (no-op `--raw-root`, the idle spend connection, the stale replay note) fixed in
   one wave after the final review.

## Pre-existing, attributed, not fixed
- Ambient `.env` values leak past `Settings(_env_file=None)` / `load_settings(_env_file=None)` and fail
  otherwise-green tests when the file is sourced: `CLUE_ARV2_DISCOVERY_ENABLED` and the Exa key
  (`tests/arv2/test_discovery_driver.py::test_the_handler_is_not_composed_without_the_flag_or_the_key`),
  the provider keys and `CLUE_FLEET_WORKER_CONCURRENCY` (two `tests/api/test_fleet_wiring.py` tests),
  `CLUE_BRANDFETCH_CLIENT_ID` (`tests/api/test_frontend_read_contacts.py` rail test),
  `CLUE_CHAT_REASONING_TRACE_MODE` (slice 1's projections-app test). Run suites with those unset.

## Deferred minors
- None open: the three review minors were fixed in the closing wave (`769b368b0`).

## Verification owed (founder-triggered, spends money)
- One real onboarding run (`POST /onboarding`) on a stack running this branch, then
  `make cost-report ARGS="--workspace <ws> --job <run id>"` should show the run's Exa rows and the
  reconcile's OpenRouter row with `model` in extras; the persona turn's evidence-tool rows appear under
  the workspace with NULL job.
- One display prewrite (`scripts/generate_arv2_display.py --dry-run`) against a real account: the page
  rolls back, the spend rows stay.
