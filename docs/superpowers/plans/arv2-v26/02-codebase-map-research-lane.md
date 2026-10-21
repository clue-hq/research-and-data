# ARV2 v26 — 02. Codebase map of the account-research lane as built

**Status:** read-only map, 2026-10-07, at main `fa4bed77b` (branch
`shank-audit-account-research-cost-optimization`). Lane L3 of the v26 program. No recommendations;
every claim cites `path:line` in this repository (line numbers are at that commit). Memory notes
under `_memory/` are cited for the *why* behind a structure, never as instructions.

**How to read the citations.** `driver` = `platform/api/clue_api/arv2/account_research_driver.py`;
`qrw` = `platform/api/clue_api/quality_research_wiring.py`; `arv2/x.py` =
`platform/api/clue_api/arv2/x.py`; `RQ` = `platform/agents/catalog/research-quality`; a bare alembic
revision id (e.g. `a3602967bb73:81`) = `alembic/versions/<revision>_*.py:81`. Production timings
come from the 2026-10-03 first production run and the 2026-10-06 Dialpad/Loopio runs as recorded in
`_memory/2026-10-03-production-research-slowness.md`, `_memory/2026-10-06-account-research-cost-audit.md`
and `docs/superpowers/specs/2026-10-06-account-research-cost-and-speed-audit.md`.

**What the lane is, in one paragraph (as built).** A Head-of-ABM chat turn calls
`launch_arv2_account_research@1`; the launch writes one `arv2_research_run` and one
`arv2_research_job` per account and, after commit, offers one `arv2_account_research` fleet task per
job. A fleet worker claims the task, pins the job to the run's ICP sha and the launch's resource
bundle sha (recipe 25), and runs one governed Deep Agent turn (`x-ai/grok-4.6`, role
`account_research`) whose tools are `acquire_research_evidence@1` (13 provider operations behind
it), `search_evidence@2`, two nominate tools, six JSON-dossier tools and `finalize_turn`, over a
virtual filesystem (`/research`, `/evidence`, `/work`, `.deepagent/skills`). `finish_dossier` imports
the JSON dossier into the claim store and marks the import ready; the driver then runs the separate
page writer (one chat completion + ≤ 1 repair, `RESEARCH_NARRATIVE_AGENT_MODEL`), publishes Overview
+ Insights as `display_block` rows, settles the job (attempt-fenced), signals the account's
generation and releases the nominated person jobs. Each person job is the same machine over a
person; its settle records a child result, which the 10-second sweep turns into an account-page
rewrite continuation. The frontend reads `display_block` through the quality read path.

---

## §1 Entry points and control flow

### 1.1 Chat launch (Head-of-ABM → launch tools)

- Three governed launch tools are granted to the Head-of-ABM role only:
  `launch_arv2_account_research`, `launch_arv2_person_research`, `launch_arv2_discovery`
  (`platform/api/clue_api/agent_registry_wiring.py:507,516,523`); the Stage-0 recipe allowlist names
  them (`platform/api/clue_api/stage0_recipe.py:472-474`); the pinned versions are
  `launch_arv2_account_research@1`, `launch_arv2_person_research@1`, `launch_arv2_discovery@2`
  (`platform/api/clue_api/recipe_contracts.py:74,78,85`). Discovery is a separate lane
  (`arv2/discovery_launch.py`, `arv2/discovery_driver.py`) and is only noted here.
- `LaunchArv2AccountResearchTool` (`arv2/account_research_launch.py:1316-1345`): `effect_class = SPEND`,
  `ReplaySafety(policy=DOMAIN_IDEMPOTENT, durable_identity="workspace + project + account set + ICP
  digest + product-set version + profile digest")`. Its model description tells the Head of ABM to
  read `.deepagent/skills/account-research-briefing/v3/SKILL.md` and write the delegation brief in
  `directive_text` (`:1325-1329`). Input (`:1229-1237`): `project_id`, `account_entity_ids` (1–200),
  `icp_artifact_key`, `icp_artifact_sha256`, `product_selection_version ≥ 1`, `effort: full|…`,
  `committee_cap` 1–12 (default 5), `directive_text`. Output: `run_id, job_ids, replayed`.
- `LaunchArv2PersonResearchInput` (`:1246-1254`): `project_id`, `contact_entity_ids` (1–50),
  `directive_text`, `persona` (default `Persona.USER` — the seat written only for a person who has none).
- The launch function (`arv2/account_research_launch.py:247-413`) validates in cost order (project →
  accounts → pinned ICP → product selection), ensures a `project_run` in `ProjectPhase.DEEP` (`:286-295`),
  derives `run_id = uuid5(_RUN_NS, sha256(request + profile_sha))` (`:302-303` via `_request_sha256`
  `:694`), resolves the pinned quality `context_id` (`_quality_context_for_run`, `:304-313`), writes one
  `arv2_research_run` (`create_run`, `:314-345` — pins `icp_artifact_key/sha256`, `product_selection_version`,
  `effort`, `committee_cap`, `directive_text`, `profile_ref`, `profile_sha256`, `request_sha256`,
  `context_id`) and one `arv2_research_job` per account (`create_job`, `:361-376`; `subject_type="account"`,
  own copy of `profile_sha256`). **It queues nothing** (`:256-264`). Typed refusal codes are enumerated
  at `:190-206` (`lane_disabled`, `account_not_found:<id>`, `project_icp_not_pinned`,
  `icp_digest_mismatch`, `product_selection_version_unknown`, …).
- `DbArv2LaunchService.launch` (`:1173-1193`) runs the launch in one transaction, then — **outside the
  block, after commit** — `enqueue_launched_jobs` (`:469-509`): one `FleetTaskKind.ARV2_ACCOUNT_RESEARCH`
  task per job, `work_id = job_id` (`arv2/fleet_task.py:41-43`), `dedup_key = "arv2-account-research:<job>"`
  (`:35`), `priority = -100` (`:39`), payload `{job_id, run_id, workspace_id}`, `reopen_terminal=False`.
  Rows first, offer second is the stated safety property (`Arv2LaunchReceipt` docstring `:217-227`).
- Fleet priorities (ascending = more urgent): research −100, discovery −90, display page −80, ordinary 0
  (`arv2/fleet_task.py:39,59,69`).
- Measured in production (2026-10-06): the launching chat turn took 240 s, $0.58, 5 model calls, 9 file
  reads; chat at 17:11:27 → jobs started 17:15:25 (`_memory/2026-10-06-account-research-cost-audit.md`,
  "Deeper audit" bullet).

### 1.2 Fleet worker → driver

- The worker composes the handler only when the lane flag is on and every key is present
  (`CLUE_EXA_API_KEY`, `CLUE_OPENROUTER_API_KEY`, `CLUE_AI_ARK_API_KEY`, `CLUE_GEMINI_API_KEY`) plus the
  env `ARV2_ACCOUNT_AGENT_MODEL` (`arv2/account_research_driver.py:2437-2456`; `ARV2_PERSON_AGENT_MODEL`
  optional, falls back to the account model with an `arv2.person_model_fallback` log `:479-492`).
  Missing anything → `arv2.account_handler_not_composed` warning and **no handler**, jobs wait
  (`:2449-2457`; `platform/api/clue_api/fleet_main.py:749-797`). The quality runner is composed by
  `build_quality_job_runner` (`fleet_main.py:783-797` → `quality_research_wiring.py:1193-1262`) and the page
  writer by `page_writer_models` (`account_research_driver.py:2478-2480`).
- `fleet_main._serve` installs the shared thread pool first (`fleet_main.py:848`,
  `CLUE_FLEET_THREAD_POOL_SIZE`), registers the handler for kind `arv2_account_research`
  (`:1345-1382`), the display-page handler (`:1358-1362`), and starts `_quality_reconcile_loop`
  (`:800-811`, every `arv2_quality_reconcile_interval_s` = 10 s, `libs/clue-config/clue_config/settings.py:400`)
  which calls `handler.sweep_quality()`.
- One handler instance holds `self._db_lock = asyncio.Lock()` and `self._jobs =
  asyncio.Semaphore(settings.arv2_account_max_parallel_jobs)` (`account_research_driver.py:504-505`;
  default 4, `settings.py:456`). `max_in_flight` returns the same number (`:507-512`) — since
  2026-10-03 the worker claims only tasks it can start (`fleet_main` T7, commit `f057ce334`).
  `_connection()` = `async with self._db_lock, self._conn_factory()` (`:1016-1019`) guards the
  driver's own row transitions, the acquisition `ToolRuntime` (handed the guarded factory as
  `conn_factory`, the unguarded one only as `pacing_conn_factory`; `_tool_runtime` `:1257-1271`;
  module docstring `:19-27`) and the page writer (`write_job_pages(conn_factory=self._connection)`
  `:1819-1821`; `_rewrite_account`'s `leased()` wraps it `:866-870`). The quality runner's own
  governed tools (findings, evidence grants, dossier, nominations, the `quality_tool:` operation
  rows) are composed with `connections=transaction` and do **not** take it
  (`platform/api/clue_api/fleet_main.py:790-792`; `quality_research_wiring.py:517-567`). Nothing
  measures the wait on this lock (§8).
- `handle` (`:516-577`) never raises: a `continuation == "quality_reconciliation"` payload goes to
  `_quality_continuation` (`:518-519`); otherwise `_run`; `CancelledError` (lease lost / stop) →
  shielded `_suspend` fenced on the attempt (`:548-556`); `_JobSuperseded` → requeue (`:557-558`,
  `:1036-1046`); any other exception → `_contain` lands `needs_review` with a named `failure_code`
  (`:559-572`, `:1048-1083`).
- `_run` (`:1159-1255`): `begin_job` claims `not_started|suspended|in_progress` and bumps `attempt`
  (`arv2/account_research_store.py:309-336`; the attempt is the fence — `finish_job`/`suspend_job`
  write only `WHERE attempt=:attempt AND status='in_progress'`, `:339-405`); `None` → `_not_claimable`
  (`:1085-1155`: a finished row = redelivery → "completed", re-offering `not_started|suspended` person
  children; no row → requeue up to 12 × 5 s, `:268-269`, then fail). Then `_compose` → for a v4
  profile `_compose_quality` (`:1289-1433`): re-reads the pinned context and refuses if the context's
  ICP key/sha differ from the run's (`:1305-1309`), loads the resource bundle and refuses on pin
  mismatch (`_ProfilePinMismatch`, `:1320-1329`), stamps `input_refs.quality_recipe_version` on the job
  row (`:1333-1344`), builds the `JobScope` (`catalog_version="v4"`), `ensure_generation` (`:1385-1389`),
  and the task instruction (person brief, or the account directive with `{{account_name}}`/
  `{{account_domain}}` substituted, `:1407-1432`, `_account_directive` `:148`). The stage is stamped
  `deep_research` on the claiming connection (`:1177`; `JobStage` vocabulary `deep_research|synthesis|
  committee|member_research`, `account_research_store.py:76`).
- Under `self._jobs` the quality runner runs the deep agent, then `_write_pages` (recipe ≥ 25), then
  `_settle_quality` (`:1183-1192`). The legacy R2/R3 branch (`run_account_agent`, `_settle`,
  `_fan_out_committee`, `_offer_display_page`) is reached only for catalog versions without the
  `research_quality` capability (`:1193-1255`, `:1658-1794`).

### 1.3 The quality runner (one governed Deep Agent turn)

- `build_quality_job_runner` (`platform/api/clue_api/quality_research_wiring.py:1193-1262`) builds a
  `ResearchUnitRuntime` per job with `quality_tools(scope, storage, purge=…, acquisition_runtime=runtime)`
  (`:211-252` — 28 tool classes registered, plus `AcquireResearchTool`) and `Allowance(model_calls =
  arv2_account_max_model_rounds, tool_calls = rounds × arv2_account_max_tool_calls_per_round,
  delegations = rounds, runtime_ms = arv2_account_max_runtime_s × 1000)` (`:1233-1239`; settings
  defaults 350 / 50 / 0, `settings.py:447-454`; `Allowance` `arv2/quality_execution.py:30-34`).
- `ResearchUnitRuntime.__init__` (`:486-574`): execution id = `uuid5("research-quality:<job_id>[:unit_key]")`
  (`:509-516`); the acquisition tool's writer is replaced by a `QualityProviderWriter` bound to the
  execution (`:522-532`); `resource_version` = `input_refs.quality_recipe_version` (`:537`);
  `quality_profiles(tools, version, person)` selects profile `v25`/`v25-person` for version ≥ 25
  (`:255-351`; the active role set is only `ACCOUNT_RESEARCH` for version ≥ 20, `:258`); a
  `RecipeExecutor` with `max_concurrency=1` (`:566-574`).
- `run` (`:781-1140`): `install` seeds `recipe-v<N>.json` as a system recipe (`:576-584`); `prepare`
  starts the recipe execution with parameters `{job_id, context_id, task_sha256}` (`:586-620`) and
  `drive` takes a work lease as worker `arv2-quality-inline` (`:622-639`, `:186`). The profile is
  resolved for `AgentRole.ACCOUNT_RESEARCH` and its `model_id` overridden by the driver's env model
  (`:785-794`). A workspace lease is acquired per thread `research-quality-<execution>` (`:822-830`).
  Four artifacts seed the turn: the project card (`research-quality-card`: `context_path=/research/
  context.json`, `evidence_path=/evidence/index.json`, subject ids, `context_gaps`, the contact
  enrichment and provider policies, `:845-860`), a `record_only` budget envelope (`:861-863`), the
  resource manifest (`:864-866`) and the task (`objective` + `completion_contract` for JSON-dossier
  recipes, `:867-879`). `AgentTurnRequest` carries `actor_id="system"`, `role=ACCOUNT_RESEARCH`
  (`:880-899`). A committed prior outcome short-circuits replay (`:902-908`). `begin_runtime` registers
  the runtime owner (`:958-961`); resources are materialised or verified against the pinned snapshot
  (`:965-979`); delegation is built only when the profile declares roles (`:980-1001`; v25 declares
  none). The `completion_guard` (`:1013-1062`) — for JSON-dossier recipes — assembles
  `outputs/research.json` from storage (`build_completion_report`) rather than trusting the model's
  report (`:1033-1054`). Tools come from `GovernedAgentToolFactory` (`:1064-1078`); for JSON-dossier
  recipes `finalize_turn`'s description gains `COMPLETION_INSTRUCTIONS` (`:1084-1087`;
  `arv2/quality_completion.py:24-32`). `DurableDeepAgentTurnRunner(DeepAgentTurnRuntime(compaction_for,
  max_runtime_s = min(remaining, profile.turn_timeout_s, settings) or None when the setting is 0,
  max_rounds = limits.model_calls, middleware = bindings.middleware, …))` runs the turn
  (`:1088-1118`). Outcome → `report()` validates exactly one `research-unit-v1` report
  (`:1166-1190`; `ResearchUnitReport` `arv2/quality_results.py:16-28`).
- `bindings` (`:688-755`): `bind_execution` + `resolve_authority` per execution; `before_work`
  re-resolves authority and checks runtime remaining on every tool call (`:713-717`); the Deep Agents
  backend is `research_backend(...)` (`:733-742`) and the middleware is `SharedResearchAllowance`
  (`:745-750`).

### 1.4 Inside the turn: what the tools do to state (summary; catalog in §2)

- `acquire_research_evidence@1` (`arv2/quality_provider_tools.py:124-215`): validates the operation
  name and arguments (a bad name/args is a durable **non-spending** refusal
  `operation_unavailable_for_subject` / `invalid_acquisition_arguments`, `:134-141`, `:186-194`),
  re-resolves authority (`:142-145`), reserves a tool slot in the allowance (`:146-152`), and opens an
  `arv2_research_operation` keyed `quality_tool:<operation>` + fingerprinted args (`operations.begin`,
  `:153-155`). A lost race (`not won`) replays the saved receipt after `recover_acquisitions` +
  `index_transcripts` (`:156-185`). The provider call runs through `ToolRuntime` (`arv2/
  account_research_tools.py`): per-provider `asyncio.Semaphore` — 1 for serial providers, else
  `arv2_account_provider_concurrency` (default 4) (`:567-575`, `settings.py:459`) — and the drain
  (`_drain`, `:596+`) writes raw bodies + ledger rows **inside `self._conn_factory()`**, i.e. behind the
  driver's `_db_lock`, then indexes provider artifacts and (via `index_acquisition`, `arv2/
  quality_acquisition.py:29`) prepares/publishes evidence sources (`arv2/quality_evidence.py:136,240`).
  The model receives a receipt with `result_path="/research/operations/<operation_id>/0.json"`
  (`quality_provider_tools.py:173`), never the content.
- `nominate_committee_candidate@3` / `nominate_web_committee_candidate@3`
  (`arv2/quality_committee_tool.py`): `ensure_generation` (`:98-100`), person job id =
  `quality_person_job_id(run, account, contact)` (`:101`; `account_research_launch.py:150`),
  `create_job(subject_type="person", input_refs={parent_job_id, discovered_via, …})` (`:205-220`,
  `:303`) and `register_child` (`:222`). The person job is born `not_started` and is **not** enqueued
  here.
- `save_dossier_section@1` / `update_dossier_findings@1` / `validate_dossier@1` /
  `finish_dossier@1` / `begin_dossier_revision@1` / `discard_dossier_revision@1`
  (`arv2/quality_json_dossier.py`): writers take a per-job advisory transaction lock
  `research-dossier:<ws>:<job>` (`:152-160`). `finish_dossier` (`:470-559`) freezes the document,
  derives `import_id = uuid5("research-json-dossier:<job>:<sha256>[:revision-after:N]")` (`:502-505`)
  and imports through `import_research_dossier` (`arv2/dossier_import.py:435-485` — prefetch reads,
  `critical_section("arv2.dossier.import")`, one savepoint per reference group) → `submit_proposal`
  → the shared claim writer; the receipt (claim ids, errors, reused) persists on the dossier snapshot
  (`:530-548`) and `mark_account_import_ready` writes `arv2_research_import_ready` + an
  `artifact_reference` of kind `research_account_import_ready` (`arv2/quality_person_release.py:29-66`).
- `finalize_turn` is a separate call after sibling results settle; `check_finalizable` runs before the
  completion guard and the outputs snapshot since 2026-10-04 (T8 `9f0d8b51e`;
  `_memory/2026-10-03-production-research-slowness.md` "McKee's failure").

### 1.5 Page writing (recipe ≥ 25) and settle

- `_write_pages` (`account_research_driver.py:1796-1831`): only when `writes_pages_separately(scope)`
  (`arv2/quality_policy.py:14-21`, `SEPARATE_WRITER_RECIPE = 25`), the unit `completed` with a report;
  a missing writer → `needs_review/page_writer_not_composed`; a writer exception →
  `needs_review/page_writer_failed`. It calls `page_writer_runtime.write_job_pages` (`arv2/
  page_writer_runtime.py:618-664`): `write_pages` (`:460-497`) builds the seller brief (`seller_brief`,
  cached per context pin + guide hash as artifact `research_seller_brief`, `:230`), reads the job's
  JSON dossier, the committee (`committee_people`, `:335`) or — for a person — the parent account
  dossier and the account story (`:405,440`), and calls `write_account_pages` / `write_contact_page`
  (`arv2/page_writer.py:300,330`); then `publish_written` (`:514-588`) retains the reply as artifact
  `research_page_writer`, creates an `execution` row `page-writer:<job>:<context>:<sha>` (`:549-575`),
  and calls `publish_page` per page (`arv2/quality_pages.py:276`) with `expected_dependency_sha256`
  from `page_inputs`. Pages/sections are fixed (`page_writer.py:41-66`; the account call always writes `("overview", "insights")`, `:314`): overview 6, insights 5,
  contact 6. Checks are correctness-only — refs resolve, quotes appear in cited findings, sections
  present, private matters absent (`PRIVATE` regex `:79-86`), `send_line` only in contact openers —
  with **one** repair call (`check_pages` `:130-181`, `write_checked` `:200-237`). The writer model is
  `RESEARCH_NARRATIVE_AGENT_MODEL` (fallback `arv2_display_model`) with
  `RESEARCH_NARRATIVE_AGENT_MODEL_EFFORT` (`page_writer_runtime.py:98-106`); the call goes through
  `ProviderCaller` so it lands a `provider_call_ledger` row stamped with the job and a Langfuse
  generation (`:109-178`, docstring `:1-10`).
- `_settle_quality` (`:1833-1958`), in one guarded transaction: `usage()` meter → coverage →
  `finish_job(attempt-fenced; status completed|needs_review; model_rounds/tool_calls/cost_usd/credits/
  media_seconds; finalization_json with quality_state="provisional")` (`:1842-1882`; `_JobSuperseded`
  when the fence refuses); for an account (or an independent person) `ensure_generation` +
  `signal(reason="initial_settled")` (`:1883-1903`), `record_child_result` for an attached independent
  person (`:1904-1912`), `ready_person_jobs(generation)` → the committee's person jobs to offer
  (`:1913-1927`); for a child person `record_child_result` (`:1928-1934`); `refresh_run_status`;
  an activity-feed row (`:1942-1947`). After commit `_offer_committee` enqueues the released person
  jobs (`:1948`, `:2002-2038`). `_offer_display_page` (Luna `arv2_display_page` tasks) is called only
  from the legacy `_settle` (`:1784`), **not** from `_settle_quality`.

### 1.6 Person release, children and the account rewrite

- Person jobs are released when the parent's **import** is ready, not when its pages are written:
  `ready_person_jobs` (`arv2/quality_person_release.py:69-111`) selects `not_started` person children
  of a generation whose parent has an `artifact_reference` of kind `research_account_import_ready`
  (`:89-92`, recipe ≥ `MIN_RECIPE = 18`, `:16`). The sweep (`sweep_quality`, `:948-978`) and the parent's
  settle both call it; both enqueue through `enqueue_launched_jobs` (same work id/dedup key as the
  launch, `:954-969`). A person job reads its parent's imported dossier read-only at
  `/research/parent-account-dossier.json` (`read_parent_dossier`, `:114-184`).
- Generation state machine (`arv2/quality_generation.py`): `Generation{input_revision,
  reconciled_revision, state}` (`:29-40`); one continuation work id per
  `(workspace, project, context, account)` (`continuation_work_id`, `:43-49`); signals
  (`initial_settled|person_result|claim_changed|media_changed|manual_refresh`, `:24-26`) bump
  `input_revision` under `FOR NO KEY UPDATE` and move the state to `provisional` unless
  `suspended|privacy_stopped` (`signal`, `:215-266`); `record_child_result` derives one
  `person_result` event per distinct terminal child result and stamps `arv2_generation_child`
  (`:268-319`); `signal_subject_change` turns delivered claim-quality events into `claim_changed`
  (`:321`); `pending_continuations` (`:390-436`) lists generations with `input_revision >
  reconciled_revision`, `initial_settled_at` set, parent terminal, and — for recipe ≥ 20 — no child
  still running **unless that child already has an `arv2_research_import_ready` row** and no newer
  generation for the same account/context; `reconcile_generation` (`:437-493`) settles a revision to
  `reconciled|partial|provisional|needs_review`.
- `sweep_quality` (`account_research_driver.py:907-1003`), every 10 s on every worker: delivers claim
  invalidations, records terminal children that lack a result, releases ready person jobs, and offers
  one continuation per generation with `only_if_work_idle=True` (`:983-1002`; the 2026-10-05 fix for the
  lease spin, `_memory/2026-10-05-fleet-lease-spin-fix.md`).
- `_quality_continuation` (`:579-715`) → for recipe ≥ 20 (`owns_narrative`, `arv2/quality_owned_narrative.py:33-37`)
  `_focused_reconciliation` (`:717-848`) → for recipe ≥ 25 `_rewrite_account` (`:849-905`):
  `rewrite_account_pages` (`page_writer_runtime.py:667-729`) is a **full rewrite** of overview+insights
  from durable rows (account dossier + committee + every finished person dossier), publishing and
  settling the revision in one transaction under the lease (`write_job_pages(after_publish=settle)`,
  `:712-721`); an account whose own dossier never imported settles `needs_review` without writing
  (`:688-704`); any failure settles the revision `needs_review` so the rewrite is not bought again
  (`:890-905`). Because a child with an import-ready row no longer blocks `pending_continuations`,
  a rewrite is offered as each person's import lands — the measured "~3 rewrites per account"
  (`docs/superpowers/specs/2026-10-06-account-research-cost-and-speed-audit.md:131-137`).
- Independent person launches attach to the account's newest generation
  (`attach_to_account_research`, `quality_generation.py:118`; called from `launch_arv2_person_research`;
  founder ruling 2026-10-04 in `_memory/2026-10-04-narration-quality.md`).

### 1.7 Display blocks and the frontend read

- Written pages are `display_block` rows via `publish_page` (`arv2/quality_pages.py:276`);
  `read_page` (`:419`) is the quality read. The frontend read seam
  (`platform/api/clue_api/frontend_read/display_pages.py:346-375`) selects the quality context for the
  subject (`select_quality_context`, `arv2/quality_read.py:26`) and serves `read_page`; a stopped or
  not-yet-started generation serves an empty block and **never falls through to the unscoped Luna
  owner** (`:364-368`). The Luna `arv2_display_page` path (`PENDING_MESSAGE`, `:114`; offers at
  `:390-398`) applies only to subjects with no quality context.
- Progress card stages are milestone fractions (`compiling_findings 0.25`, `storing_claims 0.5`, …,
  `arv2/research_progress.py:161-164`); `arv2_research_job.model_rounds/tool_calls/cost_usd` are
  written only at `finish_job` (`account_research_store.py:339-388`), so they read 0 while running
  (`_memory/2026-10-03-production-research-slowness.md`, "Job counters stay at zero").

### 1.8 Sequence diagram — one account + its committee, with production timings

Timings: first production run 2026-10-03 (`_memory/2026-10-03-production-research-slowness.md`:
Mortenson, 15:25 → 16:17:44, ~53 min) and the 2026-10-06 Dialpad/Loopio runs
(`docs/superpowers/specs/2026-10-06-account-research-cost-and-speed-audit.md:91-137`,
`_memory/2026-10-06-account-research-cost-audit.md`).

```mermaid
sequenceDiagram
    autonumber
    participant U as Marketer (chat)
    participant H as Head-of-ABM turn (fleet agent_turn)
    participant L as DbArv2LaunchService
    participant Q as fleet_task queue
    participant W as Worker — Arv2AccountResearchWorkHandler
    participant A as Account Deep Agent — quality runner
    participant P as Providers (Exa / AI Ark)
    participant S as Postgres + R2 (claims, operations, evidence, artifacts)
    participant PW as Page writer (one chat completion + ≤1 repair)
    participant C as Person Deep Agents ×5
    participant F as Frontend read (/frontend/v1)

    U->>H: "research these accounts" (t=0)
    H->>H: reads account-research-briefing skill, writes directive_text (≈240 s, $0.58)
    H->>L: launch_arv2_account_research@1
    L->>S: run + N account jobs (one txn), commit
    L->>Q: enqueue N tasks (priority −100, work_id = job_id)  (t≈+4 min)
    Q->>W: claim (≤ arv2_account_max_parallel_jobs in flight)
    W->>S: begin_job (attempt+1), compose under pins, stage=deep_research
    W->>A: quality runner: recipe-v25 execution + Deep Agent turn
    loop 40–60 model rounds, context 17k→200k tokens, never compacted
        A->>A: read_file skills (2–3 chunks each), /research/context.json, capabilities
        A->>P: acquire_research_evidence (≤4 per provider in flight)
        P-->>A: Exa search ≈2.5 s / contents ≈0.3 s / deep ≈53 s; AI Ark ≈2.6 s
        A->>S: drain + index sources behind _db_lock (≈20 s before + ≈37–46 s after the answer)
        A->>A: read /research/operations/<id>/0.json and /evidence/NNNN-slug.json (100-line pages)
    end
    A->>S: nominate_committee_candidate ×5 → person job rows not_started (t≈+15 min)
    A->>S: save_dossier_section … (strict Finding schema; ≈12 min "compiling")
    A->>S: finish_dossier → import claims, import-ready marker (t≈+22–23 min)
    A->>W: finalize_turn (check_finalizable, completion guard, snapshot)
    W->>PW: write_job_pages: seller brief + overview + insights (≈3.5–5.5 min, 12–20k tokens)
    PW->>S: publish_page → display_block rows
    W->>S: _settle_quality: finish_job(attempt-fenced), signal initial_settled, ready_person_jobs
    W->>Q: enqueue the 5 person jobs (after commit)  (t≈+23 min in practice: the sweep/settle gate)
    Q->>C: claim (same handler kind, same semaphore)
    par five people in parallel (20–25 min each; 70–125 min on 2026-10-03)
        C->>P: AI Ark export/email, Exa searches, deep report
        C->>S: finish_dossier (import-ready) → record_child_result → signal person_result
        C->>PW: contact page (≈2–4 min)
    end
    W->>W: sweep_quality every 10 s → pending_continuations → one continuation task (only_if_work_idle)
    W->>PW: _rewrite_account: full overview+insights rewrite (≈260 s, ≈$0.26 each; ~3× per account)
    PW->>S: publish_page + reconcile_generation (revision settled)  (t≈+53–56 min)
    F->>S: GET account detail → select_quality_context → read_page → display_block
```

## §2 The tool catalog

`arv2/x.py` = `platform/api/clue_api/arv2/x.py`. Everything the v25 account and person agents can call.

### 2.1 What the model actually sees (the surface)

- Recipe-v25 allowlists eleven governed tools (`platform/agents/catalog/research-quality/recipe-v25.json:131-143`),
  but the model-facing tools are built only from `profile.tools` (`platform/api/clue_api/agent_runtime_wiring.py:864-873`)
  and the runtime's surface check admits only profile tools plus `finalize_turn`
  (`platform/agents/clue_agents/runtime.py:158-175`). So the v25 account agent sees **ten** governed
  tools and the v25 person agent **eight** (no nominate tools; §5.1). `record_research_finding@3`
  is allowlisted by the recipe but pinned by no profile after v19 — **the model never sees it**.
- Deep Agents built-ins granted: `write_todos, ls, read_file, write_file, edit_file, glob, grep,
  compact_conversation` (`runtime.py:64-76`) plus `finalize_turn` (`:158-175`). `task` is auto-added
  by deepagents but filtered from the visible tools and refuses with "Tool 'task' is structurally
  unavailable to this exact agent profile." (`runtime.py:184-195,235-242`); `execute` → RuntimeError
  (`:187-188`); no `delegate_specialist` (`delegation_roles: []`). `tool_choice="required"`; a
  plain-text stop gets one finalize-only recovery call (`:196-233`).
- Media reaches the model only as `acquire_research_evidence` operations (`discover_media`,
  `read_media`, `search_transcripts`, `open_transcript`); `arv2/quality_media_tool.py:19-22` exposes
  only `submit_transcript_claim`, which is not in v25.

**Common machinery.** Descriptor types: `ToolInput` frozen/`extra=forbid`, `ToolOutput`
frozen/strict (`platform/toolbelt/clue_toolbelt/envelope.py:69-80`); `ReplayPolicy` (`:93-100`),
`ToolEffectClass` READ/WRITE/SPEND/STEERING (`:111-117`), `ReplaySafety` (`:120-144`),
`ToolResult(tool, version, references, replayed, meta)` (`:317-336`). The research write tools share
`_ResearchWriteTool` (`arv2/quality_tools.py:70-98`): `effect_class = WRITE`; `ReplaySafety(
DOMAIN_IDEMPOTENT, durable_identity="research job + proposal/correction key + immutable request
digest", operation_id_required=True)`; `authority()` refuses "research tool requires its bound
workspace execution" / "role has no research claim authority" (`:85-90`) then `reserve(kind="tool",
activity_id=ctx.operation_id)` against `arv2_quality_allowance`/`arv2_quality_activity`
(`arv2/quality_execution.py:147-225`; a replayed activity id is a no-op `:180-191`;
`ResearchAllowanceExhausted` `:192-201`). Every governed call runs as a one-step plan
(`node_key = agent_{name}_{sha256(tool_call_id)[:24]}`, `agent_runtime_wiring.py:897-922`) and returns
`GovernedOperationReceipt{node_key, operation_id, kind, address, status, replayed, artifact_refs,
domain_refs, reference_values, failure_code}` (`platform/agents/clue_agents/execution.py:144-179`;
`agent_runtime_wiring.py:1024`); `reference_values` carries the tool's `references` inline up to
12 KiB, above which they spill to `reads/<operation_id>.json` and a stub `{spilled_to, count,
summary[:300], tool}` is returned (`execution.py:57,212-238`; `agent_execution_wiring.py:1959-1992`;
hard cap 16 KiB `execution.py:50,177-178`). The full `ToolResult` is persisted as an
`application/vnd.clue.agent-tool-result+json` artifact and journaled to `agent_tool_result`
(`agent_execution_wiring.py:1907-1918`). Any exception comes back as
`GovernedToolFailure{error: plan_rejected|operation_failed, reasons, guidance,
governed_repair_budgeted}` (`agent_runtime_wiring.py:389-410,960-994,1068-1098`); a READ tool whose
failures are all `PreconditionFailed` is not charged a repair round (`:973-993`).

### 2.2 The governed tools, one by one

| Tool | Class / cite | Input | Output | Effect / replay | Writes | Returned to the model | Refusals / idempotency |
|---|---|---|---|---|---|---|---|
| `search_evidence@2` | `SearchPathEvidenceTool` `arv2/quality_tools.py:364-384` (extends `:248-289`) | `source_path` (an `/evidence/NNNN-slug.json` path), `query` 1–500, `start ≥ 0`, `limit` 1–20 (`:357-361`) | `SearchEvidenceOutput{source_id, matches[{start,end,path}], next_start}` (`:236-245`) | READ (`:252`); DOMAIN_IDEMPOTENT inherited | only the allowance reservation | offsets + path only; the ±160-char `context` from `search_source` (`arv2/quality_evidence.py:621-628`) is dropped (`quality_tools.py:275-286`); matching is literal `str.find` (`quality_evidence.py:611-618`) | `ValueError` "invalid source search bounds" (`:607-608`); `EvidenceUnavailable` for a bad path |
| `acquire_research_evidence@1` | `AcquireResearchTool` `arv2/quality_provider_tools.py:77-329` | `{operation: Literal[13 names], arguments: dict}` (`:45-65`) + `retry_of` added by the harness (`agent_runtime_wiring.py:600-613`) | `AcquireResearchReceipt{operation_id, status: completed|refused|outcome_unknown, result_path, error_code, recovery, replayed}` (`:68-74`) | WRITE (`:81`) — **not SPEND**; `ReplaySafety(DOMAIN_IDEMPOTENT, "research job + operation + canonical arguments; uncertain dispatch stops")` (`:82-86`); `estimate` = free | outer `arv2_research_operation` (`:301-315`); the result JSON artifact + `agent_artifact_subject` + `artifact_reference(research_tool_output)` + a derivation edge from every job source (`:259-300`); inner: `provider_call_ledger` + raw artifacts (`_drain`), `arv2_evidence_source` (`index_acquisition`), deterministic claims (`QualityProviderWriter`, `arv2/quality_mapping.py:65-105`), media tables | a receipt with `result_path=/research/operations/<id>/0.json` (`:320`); the content is read as a `_passage` (256-char `text_segments`); for account `research_deep` and for search/fetch/deep on brief scopes the body carries `source_navigation` and `source_review_path` (`:233-258`; `arv2/quality_source_navigation.py:14-47`) | hard `ValueError`s: not bound (`:127-130`), "specialists request acquisition through their parent" (`:142-143`); durable non-raising refusals in the receipt: `operation_unavailable_for_subject` (`:133-134`), `invalid_acquisition_arguments` (pre-validated against the operation schema, `:136-139,191-199`), provider refusal / `error` / state in {unavailable, empty, ambiguous, not_found, refused, failed} → `refused` (`:204-224`), state in {unknown, dispatched, reserved} → `outcome_unknown` (`:205,218-219`). Identity: `uuid5("arv2-operation:v1:{ws}:{job}:quality_tool:{op}:{sha256(args)}")` (`:151-153`; `arv2/research_operations.py:27-30,57-98`); a lost race replays the saved receipt (`:154-178`) or `dispatch_outcome_unknown` with "Inspect /evidence/index.json; record the gap without repurchasing." (`:179-187`); a `running` row past its 2-hour lease becomes `unknown` (`research_operations.py:73,90-97`). Note: a `read_media` result in state `ambiguous` is classified `refused` |
| `nominate_committee_candidate@3` (account only) | `NominateBriefedCommitteeTool` `arv2/quality_committee_tool.py:434-444` | `candidate_ref` ("{operation_id}:{person_id}", `arv2/committee_discovery.py:92-103`), `persona_key="general"`, `role="other"`, `rationale`, `research_brief` (min 1) (`:374-378,410-419`) | `NominateCommitteeReceipt{contact_id, assessment_claim_id, person_job_id, generation_id, state="candidate", replayed}` (`:61-67`) | WRITE, DOMAIN_IDEMPOTENT | `arv2_research_job` row `FOR NO KEY UPDATE` (`:93-96`); contact via `resolve_provider_contact` (`:313-323`); `ensure_generation`; an `account.committee_selection` proposal claim with `JsonSupport` at the exact AI Ark row (`:341-360`; `arv2/quality_relationships.py:24`); `submit_proposal`, `link_selection_claim`, `save_person_brief` (first creation only, `:184-204`), `create_job` (person, `not_started`), `register_child` (`:158-222`) | the id receipt only | `ValueError`s: "only the account parent may nominate candidates" (`:88-89`); "committee candidate cap reached; reconcile existing candidates" (`committee_cap`, `:111-112`); "candidate proposal refused: {code}" (`:168-169`); "provider candidate lacks a stable identity or saved original" (`:311-312`); "candidate original is missing or ambiguous…" (`:358-359`); `RefusalError("invalid_arguments")` from `read_candidate` (`committee_discovery.py:96-103,380-403`). Keys: proposal `nominate:{operation_id}` (`:136`), person job id `quality_person_job_id(run, account, contact)` (`:101`), `replayed = not created` (`:241`); the brief is immutable |
| `nominate_web_committee_candidate@3` (account only) | `NominateBriefedWebCommitteeTool` `:447-458` | `name`, `linkedin_url|None`, `source_id` (UUID, not a path), `persona_key`, `role`, `rationale`, `research_brief` (`:381-387,422-431`) | same receipt | same | reads the source artifact and uses its first 8,000 chars as a `TextSupport` passage (`:258-269`); the name-in-passage / LinkedIn checks apply only when not advisory, so skipped in v25 (`:273-288`); `discovered_via: "web_gap"` (`:299-307`) | id receipt | "research run unavailable" (`:290-291`) + the tool-4 set minus `read_candidate` |
| `save_dossier_section@1` | `SaveDossierSectionTool` `arv2/quality_json_dossier.py:224-274` | `SaveSectionInput{section, findings: list[Entry]}` (`:180-182`) | `DossierReceipt{result}` — the model receives the **content dict** `{saved, path, version, section, entries}` (`:189-190,211`) | WRITE, DOMAIN_IDEMPOTENT; gate `uses_json_dossier` (v4, recipe ≥ 16, `:44-48`) and role account_research else `ValueError` (`:197-199`); per-job advisory lock `research-dossier:{ws}:{job}` (`:152-159`) | document + snapshot artifacts, `artifact_reference` kinds `research_json_dossier_document`, `research_json_dossier`, `research_dossier_progress` keyed `{job}:{version:010d}` (`_persist` `:85-149`) | the dict | soft: `{saved:false, error:"Dossier frozen; reuse or retry its import"}` (`:245-250`); `replace_section` `ValueError`s returned as `error` (`:258-259`; `arv2/dossier_json.py:73-96`); no new version if unchanged (`:260`) |
| `update_dossier_findings@1` | `UpdateDossierFindingsTool` `:277-286` | same input; `update_findings` replaces by F-ID or appends (`dossier_json.py:107-123`) | same | same | same | same | same |
| `begin_dossier_revision@1` | `:295-370` | `{expected_version ≥ 1, reason, withdrawals: dict[str,str]}` (`:289-292`) | `{started, path, version, base_version}` | same | a new draft version from the completed base | dict | raised `ValueError` "Dossier revisions require recipe 17 or newer" (`:314-315`); soft `{started:false, error:"Read latest.json; expected a completed version"}` (`:316-321`), "Use existing finding IDs and nonempty reasons" (`:323-332`) |
| `discard_dossier_revision@1` | `:377-420` | `{expected_version ≥ 1}` (`:373-374`) | `{discarded, version, path}` | same | — | dict | `{discarded:false, error:"Expected the current unapplied revision"}` (`:395-404`) |
| `validate_dossier@1` | `:452-467` | `DossierInput{}` (`:185-186`) | `{valid, entries, errors[], path, state, coverage, note}` (`validation` `:423-449`) | read-only aside from the reservation | — | dict | errors listed in `errors` |
| `finish_dossier@1` | `:470-558` | `DossierInput{}` | `{finished, path, artifact_key, document_artifact_key, claim_ids[], stored, errors, entries[], changes, reused}`; invalid shape → `{finished:false, …validation}` (`:488-490`) | same | claims via `import_research_dossier`/`import_revision` → `submit_proposal` (`arv2/dossier_import.py:300`; `:509-525`); a new snapshot (`:527-546`); `arv2_research_import_ready` + the `research_account_import_ready` reference (`arv2/quality_person_release.py:29-55`) | dict with claim ids and per-finding outcomes | `import_id = uuid5("research-json-dossier:{job}:{sha256(doc)}[:revision-after:{base}]")` (`:504-508`); per-finding key `dossier:{import_id}:{F-ID}` (`dossier_import.py:270,297`); a completed dossier replays with `entries[].replayed=True` (`:493-503`) |
| `record_research_finding@3` (allowlisted, **not exposed**) | `RecordContentResearchFindingTool` `arv2/quality_findings.py:142-184` | `{topic 1–200, finding: JsonValue, source_paths, notes}` (`:133-139`) | `ResearchClaimReceipt{operation_id, claim_id, status, error_code, replayed, assessment_id, revision, replacement_id}` (`quality_tools.py:59-67`) | WRITE, DOMAIN_IDEMPOTENT; key `"finding:"+content_address(canonical_json({topic, finding, notes, source_ids}))` → proposal id `uuid5("claim-proposal:{job}:{key}")` (`:171-184`; `arv2/quality_claims.py:204`) | a `account|contact.research_finding` claim through `LenientClaimWriter`, assessment, dispositions, `arv2_quality_proposal`, rationale artifact (`quality_findings.py:53-71`; `quality_claims.py:482-503,615-683`) | id receipt | "plain findings require research revision six" (`:48-49`) |

**`Entry` model** (`arv2/dossier_json.py:38-40` extends `Finding`, `arv2/dossier_findings.py:38-48`):
`id ^F[0-9]{3,}$`, `topic`, `claim_type ∈ {observation, reported_statement}`, `finding: JsonValue`,
`source_paths`, `attribution`, `time_context`, `qualifications`, `agent_interpretation`,
`review{status ∈ {supported, duplicate, wrong_entity, insufficient_context, potential_conflict},
reason, duplicate_of, conflicts_with, expected_entity}` with linkage rules (`dossier_findings.py:16-34`).
The 2026-10-07 audit counts 27 failed `save_dossier_section` calls over 12 runs against this strict
schema (`_memory/2026-10-06-account-research-cost-audit.md`, "Deeper audit").

### 2.3 The operations behind `acquire_research_evidence@1`

Operation sets per subject after the ACQUISITIONS filter (`arv2/quality_provider_tools.py:110`;
catalog v4 = committee_discovery + media_research + research_quality, `arv2/account_research_catalog.py:57`):
**account** — `fetch_page, search_web, read_ats_board, lookup_company, research_deep`
(`arv2/account_research_tools.py:2803-2954`), `discover_people, read_people_result`
(`arv2/committee_discovery.py:776-804`; `lookup_people` removed at `account_research_tools.py:2959`),
`discover_media, read_media, search_transcripts, open_transcript` (`:3148-3217`);
**person** — `fetch_page, search_web, lookup_person, research_deep` (`:2996-3137`), `enrich_contact`
(`committee_discovery.py:807-824`), the same four media operations. The catalogue the model reads at
`/research/capabilities/0.json` is `{operation, description, arguments_schema}` per operation
(`quality_provider_tools.py:112-122`).

| operation | provider (semaphore label) | arguments (validation) | saved | returned to the model (inside `/research/operations/<id>/0.json`) | cost class | concurrency / pacing | reuse |
|---|---|---|---|---|---|---|---|
| `fetch_page` | Exa `/contents` (`exa`) | `{url: HttpUrl, max_chars=8000 (500..20000)}` (`account_research_tools.py:1001-1003`); body `{urls:[url], text:{maxCharacters}}`, person adds `extras{links:10, imageLinks:3}` (`:1384-1395`) | inner op `account_page`/`person_page`; ledger + raw artifact; evidence `provider_record` + `web_snapshot` per text/highlight (`arv2/quality_acquisition.py:195-265`) | `{result_ref, results (full Exa results incl. text), statuses}` (`:1396-1400`) + `source_navigation` + `source_review_path` | Exa ~$0.002/URL estimate; actual `costDollars.total` (`arv2/exa_client.py:60,14-18`) | `exa` = `arv2_account_provider_concurrency` (4) | outer exact-args replay; inner `operate` reuses an identical wire body (`:698-728`) |
| `search_web` | Exa `/search` (`exa`) | `{query ≥ 3, num_results=8 (1..10), include_domains|None, start_published_date|None}` (`:1006-1010`); `includeDomains`/date sent only when supplied (`exa_client.py:435-442`); account text cap default 1500 chars (`exa_client.py:418,433`), person 10000 + extras (`:1427-1431`) | inner op `account_search`/`person_search`; same indexing (each result → a source; the audit measured ~25 sources per search, 89 % never read) | `{result_ref, n_results}` (`:1444`) + `source_navigation` (path/url/title/kind per source) + `source_review_path` | Exa ~$0.01 estimate (`exa_client.py:59`) | `exa`: 4 | same |
| `read_ats_board` | Ashby/Greenhouse/Lever public API (`ats`), no inner op (`:1331`) | `{company_url ≥ 4}` (`:997-998`); slug read from pages, never guessed (`:1322-1327`) | ledger + raw; deterministic per-posting claims through `QualityProviderWriter` (`:1337-1356`) | `{board{kind,slug,read_from,url}, postings[{title,department,location,published_at,days_open,url,description_head(600)}], claim_ids, cost}` (`:1357-1378`) | free (`arv2/ats_client.py:1`) | `ats`: 4 | outer replay only |
| `lookup_company` | AI Ark `/v1/companies` exact domain (`ai_ark`) | `{domain ≥ 3}` (`:1013-1014`) — the argument is ignored; `company_lock` uses `scope.account_domain` (`:1471-1474`; `committee_discovery.py:192-202`) | inner op `company_lock` `{domain}`; AI Ark company claims when exactly one exact-domain match (`:208-222`); `provider_record` = `enrichment_only` (prose dropped, `arv2/ai_ark_research.py:14-47`) | `{domain, company_id, operation_id, reason}` (`:223-228`) | 0.1 credit/company returned; estimate 0.2 (`ai_ark_client.py:70,757-764,401-407`) | `ai_ark`: 1 + cross-process advisory lock + 10.5 s gap | bought once per job; outer replay |
| `research_deep` (account) | Exa `/search` `type=deep-reasoning` (`exa`) | `{charter ≥ 200, same_name_exclusions, additional_queries ≤ 10, num_results=40 (10..40)}` (`:1074-1086`) → `account_exa_arguments` (`arv2/account_exa_brief.py:32-55`) | inner op `account_deep` (input = whole wire body, `:2068-2070`); evidence `research_report` (attribution `provider_synthesis`) + per-result `provider_record`/`web_snapshot` (`quality_acquisition.py:208-265`) | `{report, result_ref, n_results, source_artifact_key, source_from_saved_response}` (`committee_discovery.py:535-553`) + `source_navigation` + `source_review_path`; an empty report → `RefusalError("deep_thin_response")`, op state `empty` (`:2090-2102`) | ~$0.05 estimate (`exa_client.py:61`); actual metered (the audit saw 52–60k-char reports read in 4–11 windows) | `exa`: 4; HTTP `max_attempts=2` (`exa_client.py:79,1265`); timeout 1200 s (`:1095`); one thin-response retry (`:1081-1141`) | inner reuse on identical body; outer replay |
| `research_deep` (person) | same | `{charter ≥ 200, additional_queries ≤ 10, highlights_query="", same_name_exclusions, num_results=20 (1..40)}` (`:1089-1103`) → `person_exa_arguments` (`arv2/person_exa_brief.py:32-55`) | inner op `person_deep` | `{report, result_ref, n_results, source_artifact_key, source_from_saved_response, gaps}`; an empty report is not a refusal: `gaps:["deep_report_empty_review_returned_sources"]` (`:2017-2038`) | same | same | same |
| `discover_people` (AI Ark SMART title search) | AI Ark `/v1/people` (`ai_ark`) | `{role_key 1..120, rationale 1..2000, evidence_refs ≤ 30, titles 1..300, seniority/functions from fixed vocabularies, page ≥ 0, size 1..100, page×size < 10000}` (`committee_discovery.py:57-66`; `ai_ark_client.py:259-311`); requires an attempted `account_deep` first else `invalid_arguments` (`:244-253`; `research_operations.py:209-220`); body `contact.experience.latest.title.any.include{mode:"SMART"}` + employer from `company_lock` (`:254-269`) | inner op `people_roles`; provider subjects registered (`:136-189`); no assessment claim under research_quality (`:291-292`) | `page_result(full=False)`: `{result_ref, people[{candidate_ref, provider_subject_id, name, title, linkedin_url, current_company, current_company_domain, employment}], returned, total_elements, total_pages, page, size, has_more, track_id, source_kind}` + `company_lock` (`:293-358`) | 0.5 credit/person returned; estimate 0.5×size (`ai_ark_client.py:71,410-412,863`) | `ai_ark` serial + pacing | inner reuse of identical body; outer replay |
| `read_people_result` | local (saved op body) | `{result_ref: UUID, candidate_refs: list[str]}` (`:69-72`) | nothing new | `page_result(full=True)` with scrubbed `profile` per person (`:361-377`) | free | no hop | outer replay |
| `lookup_person` | AI Ark (`ai_ark`) | `{linkedin_url ≥ 4}` (`:1023-1032`); seeded job (`candidate_ref` in `input_refs`): no name search, returns the saved profile + `enrich_contact` (`committee_discovery.py:697-705`); unseeded: URL must fold-equal `scope.person_linkedin_url` (`:706-710`) then `people_by_name(size=3, strict)` as op `person_named` (`:711-722`) | `input_refs` merged with provider refs (`:749-765`); AI Ark person claims (`:767-769`) | `{profile (enrichment_only), channels{email:{state, operation_id}}}` (`:770-773`) | 0.5 credit/person (estimate 1.5) | `ai_ark` serial + pacing | inner reuse; outer replay |
| `enrich_contact` (email) | AI Ark `/v1/people/export/single` (`ai_ark`) | `{channels: ["email"]}` (`:75-77`); non-email refused (`:648-649`); phone unreachable | inner op `contact_email` `{id}`; a `core.work_email` claim when identity matches and the address is not free (`:662-675`) | `{email:{state ∈ succeeded/empty/unresolved/unresolved_identity/unresolved_private_email/claim_write_failed, operation_id?, reason?}}` (`:676-694`) | 1.0 credit if found, 0 if empty (`ai_ark_client.py:72-73,426-440,949`) | `ai_ark` serial + pacing | inner reuse per job; outer replay |
| `discover_media` | Exa `/search` `num_results=20` (`exa`), skipped when `known_urls` given | `{query 3..2000, purpose 1..2000, include_domains ≤ 12, known_urls ≤ 12, discovery_ref?, offset ≥ 0, page_size 1..10 (6)}` (`arv2/media_tools.py:24-31`) | inner op `media_discovery`; `arv2_media_attempt` rows (`:119-141`) | `{discovery_ref, candidates[≤10 KB: candidate_ref,url,title[:500],description[:1200],family,identity:"unverified_candidate",origin,media_url,recording_status], next_offset, total_saved, source_text_is_untrusted, coverage}` (`:142-169`) | Exa ~$0.01 | `exa`: 4 | `attempt_id = uuid5(job, "media-discovery:"+fingerprint({query, domains, urls}))`; an existing id pages the saved result (`:76-93`) |
| `read_media` | `media_public`/`media_youtube` (resolve, download), `deepgram` (ASR), `openrouter` (embeddings) | `{url | candidate_ref (exactly one), purpose, episode_hint, alternate_urls ≤ 8, repair_version?, refresh_expired}` (`:34-47`) | `arv2_media_operation` stages resolution/download/transcribe/embedding, item, transcript version, passages, embeddings (`arv2/media_operations.py:22-136`; `arv2/media_acquisition.py:167-420`; `arv2/media_retrieval.py:110-247`) | `{state:"available", item_ref, version_ref, source_url, title, quality, char_count, preview[:1200], next_offset, reused, quotes[≤6, 300 chars], quote_count, …}` ≤ 11 KB (`media_acquisition.py:443-483`) + `index` + `next_action`; or an ambiguous candidates page; or `unavailable` + gaps (`media_tools.py:172-313`) | Deepgram $0.0043/min ($0.0052 multi) (`settings.py:419-424`); media seconds reserved against `arv2_media_seconds_ceiling=9000` per job (`settings.py:430`; `media_operations.py:100-118`); embeddings `google/gemini-embedding-2` | labels not in `_SERIAL_PROVIDERS` → 4 each; per-item and per-job advisory locks around reservation (`media_operations.py:26-31`) | fingerprinted `arv2_media_operation` reuse; an uncertain paid outcome is never repurchased (`media_acquisition.py:340-370`; `media_tools.py:276-292`). In production: 0 transcripts from 17 media GETs — 2 `FileNotFoundError: ffprobe` (`arv2/media_recording.py:103`), the rest `no_supported_recording_link`/`no_exact_episode_match` (`arv2/media_resolution.py` supports YouTube/direct audio/RSS only); the governed receipt says `completed` for failed reads (`_memory/2026-10-06-account-research-cost-audit.md`, "Deeper audit") |
| `search_transcripts` | local + a query embedding (`openrouter`) | `{query 1..2000, item_refs ≤ 20, offset ≥ 0, page_size 1..8, search_ref}` (`:50-55`) | search page record | exact passage refs, quality, attribution, timing (`media_retrieval.py:342-539`; `RECEIPT_BYTES = 12 KiB` `:19`) | embedding cost only | `openrouter`: 4 | `search_ref` paging |
| `open_transcript` | local | `{version_ref, passage_ref, start ≥ 0, end > 0, neighbors 0..2, quote_index ≥ 0}` (`:58-64`) | nothing new | a passage window ≤ 2000 chars with `next_offset`/`previous_offset` (`media_retrieval.py:256-317`); quote mode ≤ 1000 chars (`:327-351`) | free | none | — |

**Wrapper behaviour** (`_governed`/`_tool`, `account_research_tools.py:2725-2800`): every operation
returns a JSON string; `RefusalError` → `{error:"governed_research_rejection", code, detail[:1000],
recoverable:true, reaction}` (`arv2/account_research_refusals.py:123-136`); `ValidationError` →
`invalid_arguments`; any other exception → `tool_error:<Type>` (`:2766-2779`); an identical-call
refusal memory `identical_call_repeated` (`:870-903`) sits behind the outer exact-args replay.

**Provider semaphore and drain.** `_perform_hop` holds `async with self._semaphore(provider)` across
the provider call **and** the `finally: await self._drain(...)` (`:500-565`); `_SERIAL_PROVIDERS =
{"ai_ark", "media"}` get 1, every other label `arv2_account_provider_concurrency` (default 4)
(`:216,567-575`; `settings.py:457-459`). `_drain` (`:596-687`) runs in one transaction under the
driver-guarded `_connection` factory: `drain_provider_calls` (ledger + raw artifacts,
`arv2/provider_ledger.py:56`), AI Ark subject registration, privacy erasure if authority was
withdrawn, media receipt attachment, `operations.finish`; then a second transaction runs
`index_acquisition` → `arv2_evidence_source` (`quality_acquisition.py:29-56`). Calls are shielded from
cancellation (`:433-460`). The audit measured ~20 s before dispatch and ~37–46 s after the provider's
answer per evidence call, with call 5 waiting 43 s and 6+ waiting 76 s behind the four slots
(`docs/superpowers/specs/2026-10-06-account-research-cost-and-speed-audit.md:100-137`).

**AI Ark pacing.** `_hop` loops on `pg_try_advisory_xact_lock(hashtextextended('ai-ark:{sha256(key)}'))`
every 0.1 s, holds it through the hop and through `asyncio.sleep(arv2_ai_ark_min_gap_s)` = 10.5 s
(`:468-492`; `settings.py:401-403`; `driver:2363-2367`), serialising AI Ark across workers per key;
the client also paces in-process per token (`arv2/ai_ark_client.py:685-721,985-997,1014-1018`). A
credit halt (`ai_ark_halt_rule`, `:331-341`) latches `runtime.halted[provider]` and later calls are
refused `provider_halted:<p>` (`:534-543,447-449,710-719`).

**Retries.** Default `max_attempts=4` on {429, 500, 502, 503, 504} with backoff `12·(n+1)` s or
`Retry-After`; transport errors `2·(n+1)` s (`libs/clue-spend/clue_spend/calls.py:76-81,420-495,431-432`).

**Exa deep-reasoning request** (`platform/agents/catalog/research-quality/provider-requests`):
account `request-config.json:1-13` = `{"type":"deep-reasoning","numResults":40,"outputSchema":
{"type":"text"},"contents":{"highlights":true,"extras":{"links":1}}}` — note **no `text`
contents**: `deep_reasoning_body` replaces the whole default `contents:{text:{maxCharacters:10000}}`
when `contents` is given (`exa_client.py:527,539-540`), so account deep results carry highlights and
one link per result, not full text; person `request-config.json:1-19` = deep-reasoning, `numResults
20`, `text.maxCharacters 10000`, `highlights.maxCharacters 2000`, `extras.links 10`, `imageLinks 3`.
`numResults` and `type` in the config files are never read (only `outputSchema` and `contents`,
`account_exa_brief.py:47-55`; `person_exa_brief.py:41-55`); `type` is hard-coded (`exa_client.py:523`).
Query = charter + "EXCLUDE SAME-NAME ENTITIES" (account `:44-46`) / "KNOWN SAME-NAME EXCLUSIONS"
(person `:51-53`); `highlights_query` → `contents.highlights.query`; `additionalQueries` when
non-empty. The silent-fail guard (`is_thin_deep_response`, `exa_client.py:859-877`): thin if
`report_chars < 3000` or (`n_results ≤ 9` and `cost ≤ $0.016`) (`:71-73`), applied when
`outputSchema.type == "text"` (`:1112-1114`); exactly one retry keeping the richer answer
(`:1115-1141,880-889`).

### 2.4 Runtime mechanics around the tools

- Graph: `create_deep_agent(model, tools=governed, system_prompt=profile prompt, middleware, backend,
  checkpointer, state_schema=ClueDeepAgentState)` (`platform/agents/clue_agents/runtime.py:625-671`,
  deepagents 0.6.12) from `quality_research_wiring.py:1088-1118`.
- Middleware order: deepagents Todo/Filesystem/SubAgent/PatchToolCalls (`deepagents/graph.py:772-802`;
  deepagents' own summariser removed `clue_agents/compaction.py:136-141`), `ToolRepairRoundsMiddleware`
  (`runtime.py:642`), `ExactAgentToolSurfaceMiddleware` (`:643-653`), `TurnBudgetMiddleware`
  (`:656-660`), `SharedResearchAllowance` (`quality_research_wiring.py:721-751`),
  `ClueSummarizationMiddleware` + `SummarizationToolMiddleware` (`compact_conversation`)
  (`runtime.py:661-665`), AnthropicPromptCachingMiddleware (`graph.py:205,815`).
- Compaction: trigger `0.90 × window`, keep `0.10 × window`; unknown window → 170,000 / 6 messages
  (`settings.py:477-480`; `clue_api/agent_compaction.py:16-28`; `compaction.py:44-56,107-133`);
  offloads under `/work/` (`compaction.py:67-104`).
- Repair rounds: `MAX_TOOL_REPAIR_ROUNDS = 10` (`platform/agents/clue_agents/tool_recovery.py:12`); a
  round counts after the whole batch settles and only if a ToolMessage carries
  `governed_repair_budgeted: true`; an 11th → `RuntimeError("governed tool repair rounds exhausted…")`
  fails the turn (`:19-62`).
- `finalize_turn`: must be alone in its batch — `ValueError("Call finalize_turn alone after reading
  the completed tool batch results…")` (`runtime.py:276-280`); `_MAX_FINALIZE_REPAIRS = 2` (`:88`),
  10 when continuing (`:529-535`).
- Turn budget: `max_rounds = 350`; finalize-only from round `max−2` with warnings in the 3 rounds
  before (`runtime.py:325,364,385-423`); no time limit when `arv2_account_max_runtime_s = 0`;
  `recursion_limit = rounds×6+10` (`:97-109`). `SharedResearchAllowance` reserves a `model` unit per
  model call and a `tool` unit per non-domain tool call (`arv2/quality_execution.py:228-272`); limits
  `Allowance(350, 17 500, 350, runtime_ms = 0 → unlimited)`.
- `read_file` paging: deepagents `ReadFileSchema` defaults `offset=0`, `limit=100` and always forwards
  `limit` (`deepagents/middleware/filesystem.py:257-258,346-357,1174,1200`); output is line-numbered;
  a result over 20,000 tokens × 4 chars is truncated (`:831,1053-1063,1140-1148`) and tool results
  over 20,000 tokens are evicted to `/work/large_tool_results/<tool_call_id>` (`:877-879`). The private
  workspace slices `lines[offset:offset+limit]` (`platform/agents/clue_agents/workspace.py:1257-1269`);
  the `/research` and `/evidence` views (`render_view`) treat only `limit == 2000` or `≤ 0` as unbounded,
  so the default 100 is a 100-line window (`arv2/quality_workspace.py:43-55`; the code comment at `:46`
  claiming deepagents supplies 2000 does not match 0.6.12).
- Workspace authorization: readable `.deepagent inputs context work outputs research evidence reads`,
  writable `work outputs`, `.json .md .txt .yaml`, 1 MiB/file, 10 MiB, 200 files (profile `:72-94`);
  refusals `permission_denied: path is outside the readable|writable workspace authority`, `… file type
  is not allowed…`, `conflict: snapshotted outputs are immutable`, `quota_exceeded` (`workspace.py:545-586,
  1235-1239`); path rules (no `..`, `//`, backslash, control chars; `clue_agents/contracts.py:182-205`);
  `edit_file replace_all` unavailable (`workspace.py:1286-1287`); private-workspace `grep` is literal
  per line over `glob("**")` (`:1318-1336`); `reads/` writable only by the trusted spill (`:969-994`).

## §3 Data model

`arv2/x.py:N` = `platform/api/clue_api/arv2/x.py:N`; a bare revision id (e.g. `a3602967bb73:81`) =
`alembic/versions/<revision>_*.py:81`. Migration legend (apply order, ARV2 chain with foundations):
`d091e3962833` b2_artifact_table · `d0c2e361f7d4` b2_artifact_lifecycle · `13cd5078d697` design key
namespace · `128c83d5e151` c5_1_execution_journal · `10642c862e43` fleet_worker_tables · `d9b39fb407ed`
c5_3_generic_work_fleet · `9aacba7cea99` fleet_task_delayed_requeue · `5330703a78a3` harden_a2 ·
`7e9269ed8a81` agent_turns · `6628a407e993` agent_plans · `65fb2128c904` arv2_d1_display_substrate ·
`a3602967bb73` arv2_r2_account_research_jobs · `60e51eba0123` arv2_r3_person_jobs · `c90aaea30a88`
job_stage · `0ab01fe27c1e` committee discovery refs · `213dea37b230` reusable media · `68e3053b58f2`
arv3 quality context/evidence · `aaae5d2e1fa4` scoped evidence grants · `8822efd6ceae` claim quality
assessments · `f4b30cb3d088` specialist roles/allowance · `c237eb027732` specialist model calls ·
`369f195d9976` generations · `d21f35762d71` runtime allowance · `4005ff9c331c` person job scope ·
`16bfa50620f4` contextual display blocks · `7d5efcd83a32` unbounded runtime · `f3eb43c7808f` focused
reconciliation + import_ready · `fd8795c4fd5a` / `2b702a116c15` / `5e1c0a9d7b24` display kind /
shared_from / drop contact-insights.

Things that do **not** exist as columns: no lease fields on `arv2_research_job` (the fence is `attempt`;
the lease is `work_lease` keyed by `work_id = job_id`); no `task_sha256`, recipe-version,
`parent_job_id` or `provider_job_id` columns (all keys inside `arv2_research_job.input_refs`); no
`abandoned` operation state (an expired `running` lease becomes `unknown`); no readable-name column on
evidence sources (derived, `arv2/evidence_paths.py:13-29`); no erasure column on evidence sources
(availability computed from `artifact`); `pending` is a read-time projection (`arv2/quality_pages.py:505-507,586`);
no dedicated committee candidate/nomination/selection tables (claims + the `provider_*` tables).

### 3.1 `arv2_research_run` — one launched request

Created `a3602967bb73:81-111`; altered: `persona_pin jsonb` (`0ab01fe27c1e:30`), `context_id uuid` +
FK `arv2_run_context_fk (context_id, ws, project) → arv2_research_context_pin` (`68e3053b58f2:95-100`),
UNIQUE `arv2_run_workspace (run_id, ws)` (`aaae5d2e1fa4:30-33`).

| col | type / notes |
|---|---|
| `run_id` | uuid PK = `uuid5(_RUN_NS, request_sha)` (`arv2/account_research_launch.py:134,309,833`) |
| `workspace_id, project_id, brand_id` | text NOT NULL |
| `project_run_id` | uuid NOT NULL FK → `project_run(id)` (`a3602967bb73:86`) |
| `icp_artifact_key / icp_artifact_sha256` | text; sha CHECK `^[0-9a-f]{64}$` (`:102`) |
| `icp_key, icp_version, product_selection_version` | CHECK selection ≥ 1 (`:107`) |
| `effort` | CHECK full/reduced/cheap-pass (`:105`); `committee_cap` CHECK ≥ 1 (`:106`) |
| `directive_text` | text default '' |
| `profile_ref, profile_sha256, requested_by_user_id, request_sha256` | sha CHECKs (`:103-104`) |
| `status` | default not_started; CHECK seam-1 set (`:108`); `created_at, finished_at` with `arv2_research_run_finished` CHECK (`:109-110`) |
| `persona_pin` jsonb, `context_id` uuid | |

Invariants: terminal ⇔ `finished_at` set — **DB CHECK**; run status derived from its jobs in one
statement, never set directly — **code** `_REFRESH_RUN` (`arv2/account_research_store.py:101-121,418-423`);
relaunch is a no-op — `uuid5(request_sha)` + `ON CONFLICT (run_id) DO NOTHING` (`:230`); the first
context pin is serialised with run creation by advisory lock `research-launch-context:{ws}:{run}`
(`account_research_launch.py:431-435`); jobs compose only against the run's pins — code re-checks ICP
sha and profile pin before any model call (`account_research_driver.py:1305-1309,1328-1329`).

### 3.2 `arv2_research_job` — one subject in a run

Created `a3602967bb73:116-150`; altered: `subject_type`, `subject_entity_id`, `profile_sha256` + CHECKs
(`60e51eba0123:55-68`); `arv2_research_job_once` UNIQUE replaced by unique index
`arv2_research_job_subject_once (run_id, subject_type, COALESCE(subject_entity_id, account_entity_id))`
(`:69-73`), rebuilt with a 4th term for `input_refs->>'subject_scope'='account'` (`4005ff9c331c:18-22`);
`stage` + CHECK (`c90aaea30a88:30-34`); `profile_ref`, `input_refs jsonb NOT NULL DEFAULT '{}'`,
`selection_claim_ids uuid[]` (`0ab01fe27c1e:31-35`); UNIQUE `arv2_media_job_scope (ws, job_id)`
(`213dea37b230:35-38`); UNIQUE `arv2_job_scope (job_id, ws, run_id, account_entity_id)` + FK
`arv2_job_run_scope (run_id, ws) → run` (`aaae5d2e1fa4:34-41`). PK `job_id` = `uuid5(_JOB_NS, run:subject)`
(`account_research_launch.py:138-147`) or, for quality persons, `uuid5(_RUN_NS,
"quality-person:run:account:contact")` (`:150-151`). FKs: `run_id → run`; `(account_entity_id, ws) →
account_entity` (`a3602967bb73:118,135-136`); `subject_entity_id` has no FK. Indexes `(run_id)`,
`(ws, account_entity_id)` (`:146-150`).

| col | notes |
|---|---|
| `status` | CHECK not_started/in_progress/needs_review/completed/suspended (`a3602967bb73:72,138`) |
| `attempt` | int default 0 — the fence |
| `started_at, finished_at, finalization_json` | |
| `failure_code, failure_message` | `arv2_research_job_failure` CHECK (`:141-142`) |
| `model_rounds, tool_calls, cost_usd numeric(12,6), credits numeric(12,3), media_seconds` | written only at finish |
| `subject_type` | CHECK account/person; `subject_entity_id` contact for persons |
| `profile_sha256, profile_ref` | the job's own pin |
| `stage` | CHECK NULL or deep_research/synthesis/committee/member_research |
| `input_refs` | keys: `subject_scope`, `requested_persona` (`account_research_launch.py:922-935`; `quality_committee_tool.py:178`); `quality_recipe_version` (`account_research_driver.py:1324-1345`); `parent_job_id`, `candidate_ref`, `version` (`committee_step.py:235-255`); `provider_job_id`, `operation_id`, `provider_subject_id`, `artifact_key` (`committee_discovery.py:115-133`); `committee_assessment_id`, `generation_id`, `person_research_brief` (`quality_committee_tool.py:178-201`); `privacy_stopped`, `blocked_channels` (`research_operations.py:287-301`); `delegation_repair` (`quality_delegation_repair.py:128-139`) |
| `selection_claim_ids` | ordered committee checkpoint (legacy v2/v3) |

Invariants: terminal ⇔ `finished_at` — DB CHECK (`a3602967bb73:139-140`); `needs_review` ⇔
`failure_code` — DB CHECK (`:141-142`; code supplies `unspecified`, `account_research_store.py:84,364`);
person has a contact, account none — DB CHECK (`60e51eba0123:65-68`); one job per subject per run,
persons scoped per account — DB unique index (`4005ff9c331c:19-22`) + `ON CONFLICT DO NOTHING`
(`account_research_store.py:292`); single-claimant takeover — only the lease holder for `work_id =
job_id` calls `begin_job` (`attempt+1`, `:309-336`; `fleet_task.py:42-44`) and the handler refuses a
payload whose job ≠ work id (`driver:534-545`); late writers cannot settle — `finish_job`/`suspend_job`
fenced on `attempt` and `status='in_progress'` (`:372,401`), a finished job is never revived (`:327-328`),
fence failure → `_JobSuperseded` (`driver:1869-1882`); counters derived at settle — legacy `job_spend`
sums `provider_call_ledger` `phase='result'` (`:516-544`), quality `quality_meter.usage` sums ledger +
`agent_model_call.cost_usd` + allowance counters (`arv2/quality_meter.py:38-75`); `selection_claim_ids`
written once (`research_operations.py:223-234` under the job row `FOR UPDATE`). Observation: status
`failed` is not in the CHECK but code filters on it (`quality_generation.py:278,412,477`; `driver:941`).
Failure codes have no DB vocabulary (`profile_pin_mismatch`, `contact_missing`, `invalid_task_payload`,
exception names, `model_error`, `provider_refused:<p>:<r>`, `quality_unit_incomplete`,
`page_writer_not_composed`, `page_writer_failed`; `driver:251-260,2134-2156,1874,1817,1830`).

### 3.3 `arv2_research_operation` — job-keyed paid-call identity

Created `0ab01fe27c1e:39-59`, never altered. `operation_id` uuid PK =
`uuid5("arv2-operation:v1:{ws}:{job}:{kind}:{sha}")` (`research_operations.py:64-66`); `workspace_id`;
`run_id, job_id, account_id` FKs (`:42-44`); `kind` text (no CHECK); `request_sha256` =
`fingerprint()` (`:27-30`); `state` default running CHECK running/succeeded/empty/failed/unknown
(`:55-56`); `owner_token`; `lease_until` = now()+2h (`:73`); `ledger_id` FK → `provider_call_ledger`;
`artifact_key` FK → `artifact(storage_key)`; `error_code, created_at, finished_at`. UNIQUE
`arv2_research_operation_once (ws, job_id, kind, request_sha256)` (`:57`); no provider column — kind
implies it. Kind vocabulary (code only): `company_lock`, `people_roles`, `person_named`,
`contact_email`/`contact_phone` (`committee_discovery.py:198-199,265-266,654,712-713`); `account_deep`,
`media_discovery`, `account_search`/`account_page`/`person_*` (`account_research_tools.py` operate
sites); `quality_tool:<op>` (`quality_provider_tools.py:151-152`).

Invariants: at most one operation per (job, kind, request) — DB UNIQUE + `INSERT … SELECT FROM
arv2_research_job … ON CONFLICT DO NOTHING` proving containment (`:68-88`); ambiguous dispatch never
auto-retried — a `running` row past its lease becomes `unknown/dispatch_outcome_unknown` (`:90-97`),
reads of a non-success operation refuse "do not repeat uncertain spending" (`:179-184`); only the owner
settles — `finish` fenced on `owner_token` and `state IN (running, unknown)` (`:150-158`), deriving state
from the ledger's http_status (404 from ai_ark → empty, `:138-149`); two unfenced overrides:
`deep_thin_response` → empty (`account_research_tools.py:2094-2101`) and the quality-tool update
(`quality_provider_tools.py:301-314`); replay reads the original verified raw artifact, refused when
job authority is withdrawn (`job_available`, `:317-344`).

### 3.4 `arv2_research_context_pin`, `arv2_context_document`

Pin created `68e3053b58f2:69-94`: PK `context_id = uuid5("arv2-context:{ws}:{project}:{sha}")`
(`arv2/quality_context.py:460`); UNIQUE `(context_id, ws)`, `(context_id, ws, project)`,
`arv2_context_identity (ws, project, manifest_sha256)`; CHECKs digest regex, `product_selection_version
> 0`; FKs project, brand, brand_knowledge_document, `artifact(manifest_key, ws)`. Document created
`:103-119`: PK `(context_id, document_id)`; role CHECK icp/persona/seller; FK pin ON DELETE CASCADE.
Pinned bytes are retained (`reference_kind='research_context'`, `quality_context.py:469-476`);
inserts idempotent (`:478-511`).

### 3.5 `arv2_evidence_manifest`, `arv2_evidence_source`, grants, dispositions

- `arv2_evidence_manifest` (`aaae5d2e1fa4:72-83`): PK `(ws, run_id, account_id)`; `revision bigint
  default 0` CHECK ≥ 0; FK `(run_id, ws) → run`. Revisions are gap-free and publication-ordered per
  account by a row lock: `SELECT … FOR UPDATE` then `revision = revision + 1 … RETURNING` per new
  source, in one acquisition (`quality_evidence.py:240-302`; lock `:257-263`); bytes are uploaded
  before the lock (`prepare_source` `:136-237`); a revision is assigned once and names the readable
  path `/evidence/NNNN-slug.json` (`evidence_paths.py:9,13-29`).
- `arv2_evidence_source` (`aaae5d2e1fa4:84-126`): `source_id` uuid PK = uuid5 over job, ledger,
  operation, original, locator, kind, url, sha, normalizer (`quality_evidence.py:165-180`); `ws, run_id,
  account_id, job_id, subject_id`; `revision` CHECK > 0; `kind` CHECK
  web_snapshot/provider_record/research_report/transcript/seller_document/acquisition_gap;
  `artifact_key, artifact_sha256` (regex), `byte_size ≥ 0`, `media_type, original_key, source_url,
  observed_at`; `ledger_id` FK, `operation_id` FK; `origin_locator, normalizer_version`; `metadata`
  jsonb (title, segments_key…). UNIQUE `(source_id, ws)` and `arv2_evidence_source_sequence (ws, run,
  account, revision)`; FK job 4-tuple → `arv2_job_scope`; `(ws, run, account)` → manifest; artifact and
  original → `artifact(storage_key, ws)`; index `(ws, job_id, revision)` (`:123-126`). Invariants:
  only trusted acquisition code creates sources, refused if the job is unavailable or privacy-stopped
  (`_subject` `:89-109`, job row `FOR SHARE`); re-draining reuses the id (`:181-183,267-271`); bytes and
  original retained (`research_source`, `:193-200`) with a derivation edge original → normalized
  (`:201-212`); readers filter on artifact availability (`erased_at IS NULL`, `NOT privacy_erased`,
  `expires_at` unset or future, `FOR SHARE`, `:444-458,541-552`) and re-verify the digest (`:561-562`);
  a grant sees only revisions ≤ its grant revision, a person subject its own + account-level sources
  (`:423-426,499-502`).
- `arv2_evidence_grant` (`aaae5d2e1fa4:127-143`): PK `grant_id = uuid5("research-grant:{job}:{consumer}:{revision}")`
  (`quality_evidence.py:362`); UNIQUE `(grant_id, ws)`; FK job 4-tuple; `revision ≥ 0`; `revoked_at`
  (refused when set, `:385-399`). The root execution re-grants at the current manifest revision on every
  authority resolve; children keep their handed grant (`arv2/quality_authority.py:68-79`, execution row
  `FOR UPDATE OF e` `:50`). No callers of `revoke_grant` found outside its definition.
- `arv2_evidence_disposition` (`:144-163`): PK `uuid5(grant:source:unit:decision:sha)`
  (`quality_evidence.py:720`); decision CHECK written/reused/conflict/excluded/gap/unprocessed; FKs
  grant, source, receipt artifact; receipt retained (`research_disposition`) with a derivation edge
  (`:730-745`); the decision mapping is `arv2/quality_claims.py:649-662`.

### 3.6 `provider_call_ledger` — the money truth

Created `65fb2128c904:203-243`; `extras_json jsonb` added (`a3602967bb73:168`). `ledger_id` uuid PK
= `uuid5("arv2-ledger:"+row_id)` (`libs/clue-spend/clue_spend/ledger.py:57,191-193`); `call_id,
workspace_id, project_id, project_run_id, entity_research_job_id` (holds the ARV2 job id,
`a3602967bb73:27-30`); `provider, operation, label, phase, http_status, latency_ms, attempts`;
`estimate_usd/credits/media_seconds`; `cost_usd/credits/media_seconds` nullable; `over_ceiling,
outcome, error_code, provider_request_id`; `request_artifact_key, response_artifact_key` text, no FK;
`recorded_at`. CHECKs phase ∈ (estimate, result), outcome ∈ (estimate, ok, client_error,
retry_exhausted, halted, transport_error) (`:232-235`). Indexes `(ws, recorded_at)`, `(call_id)`
(`:239-243`) — **no index on `entity_research_job_id`**. Invariants: a redrain is a no-op
(deterministic id + `ON CONFLICT DO NOTHING`, `ledger.py:59-71`); bytes written before the rows that
cite them (`:233-273`); spend counts only `phase='result'` (`account_research_store.py:519-532`);
`request_artifact_key` is not in the drain's INSERT — the request travels inside the response envelope
(`ledger.py:60-64,333-368`; read at `research_operations.py:190-195`); incident hook binding
`arv2/provider_ledger.py:56-114`.

### 3.7 `artifact`, `artifact_derivation`, `artifact_reference`

- `artifact` (`d091e3962833:89-104`): `artifact_id` PK; `storage_key` UNIQUE; `workspace_id` nullable
  (public); `content_sha256` regex; `size ≥ 0`; `source_key, source_url, created_at, erased_at`.
  Altered: `purged_at`, partial index `artifact_erased_unpurged`, CHECK `artifact_key_encodes_scope`
  (`storage_key = coalesce(ws,'public')/sha`) (`d0c2e361f7d4:48-65`); UNIQUE `artifact_execution_anchor
  (storage_key, ws)` — the FK target for every `(key, ws)` citation (`128c83d5e151:72-76`); `/design/`
  keys + index `artifact_content_sha256` (`13cd5078d697:45-55`); `privacy_erased boolean NOT NULL
  DEFAULT false`, `expires_at` (`0ab01fe27c1e:36-37`); `erasure_reason` (`213dea37b230:34`).
  Triggers: `artifact_erase_derivatives` AFTER UPDATE OF privacy_erased propagates to derivation
  children transitively (`aaae5d2e1fa4:56-71`); `arv2_media_artifact_erasure` (`213dea37b230:161-213`).
  Invariants: one row per bytes per workspace — DB UNIQUE; `record_artifact`
  (`libs/clue-storage/clue_storage/artifacts.py:87-176`) records the row before the blob is put, reuses
  a live identical row `FOR SHARE` (`:120-140`; the 2026-09-25 deadlock fix), upserts with
  resurrection unless privacy-erased (`:149-156,174-175`). Erasure is two-phase: `mark_erased`
  (`:249-264`; `erase_if_unreferenced` under `FOR UPDATE` counting live claims + references
  `:319-347`) then `purge_erased_artifacts` after commit (`:350-415`; expiry → `privacy_erased=true,
  erasure_reason='retention'` `:372-380`; a non-privacy erasure can be undone if references returned
  `:398-407`). Expiry: 30 days for personal and provider pages (`subsystems/research/clue_research/identity/provider.py:74-90`;
  media `arv2/media_store.py:284-289`); readers treat `expires_at <= now()` as unavailable
  (`quality_evidence.py:451,545`; `artifacts.py:286`); only an explicit media acquisition generation may
  renew retention-erased bytes (`media_store.py:595-604`).
- `artifact_derivation` (`aaae5d2e1fa4:42-55`): PK `(ws, parent_key, child_key)`; CHECK parent ≠
  child; FKs both keys; index on child. Writers: source original → normalized (`quality_evidence.py:208-212`);
  source → disposition (`:739-745`); all job sources → tool output (`quality_provider_tools.py:291-299`);
  cited claim artifacts → page (`quality_pages.py:305-312`); parents → reconciliation packet
  (`quality_reconciliation.py:157-162`); dossier (`quality_dossier.py:224`). Privacy erasure of a
  parent cascades — DB trigger.
- `artifact_reference` (`68e3053b58f2:37-52`): PK `(ws, reference_kind, reference_id, storage_key)`;
  FK artifact; CHECK lengths; index on storage_key. `retain_artifact` requires a live, unexpired,
  non-privacy-erased row `FOR SHARE` (`artifacts.py:267-299`); `release_artifacts` (`:302-316`) has no
  callers. ARV2 `reference_kind` vocabulary (code only): `research_source` (source_id),
  `research_disposition`, `research_tool_output` (operation_id), `research_generation_result`
  (`{gen}:{job}`), `research_page` (`{execution}:{page}:{sha}`), `research_reconciliation`,
  `research_context`, `claim_proposal`, `claim_assessment`, `research_json_dossier`
  (`{job}:{version:010d}`; latest = max id, `quality_json_dossier.py:62-66`),
  `research_json_dossier_document`, `research_dossier_progress` (`{job}:{ver}:{state}`),
  `research_account_import_ready` (`{job}:{ver:010d}`), `account_research_dossier`,
  `research_seller_brief`, `research_page_writer` (`page_writer_runtime.py:94-95,210`),
  `research_execution_output` (`platform/api/clue_api/quality_research_artifacts.py:150`).

### 3.8 Governed-agent execution records

There are no `agent_execution` or `agent_tool_call` tables. The actual tables: **`execution`** (C5
journal, `128c83d5e151:178`; quality execution id `uuid5("research-quality:{job}[:{unit}]")`,
`quality_research_wiring.py:512-514`; reconciliation `uuid5("reconciliation:{gen}:{rev}")`,
`quality_reconciliation.py:110`; page-writer `page-writer:{job}:{context}:{sha}`,
`page_writer_runtime.py:549-575`); **`agent_turn`** (`7e9269ed8a81:35-96`; `execution_id` UNIQUE; role
CHECK `agent_turn_role`, re-installed with research_claims/research_narrative at `f4b30cb3d088:23-26`);
**`agent_model_call`** one row per model round (`7e9269ed8a81:422-462`: turn_id, execution_id, ws,
`sequence` UNIQUE per turn, requested/answering model, status CHECK completed/failed/cancelled, tokens,
cost_millicredits, latency, error; later `role` **with the CHECK `agent_model_call_role (role IS NULL OR
role IN (…))`** (`65880921cd52:20-25`, re-installed with the widened vocabulary by
`c237eb027732:29-41`), `cost_usd`/`cost_source` CHECK metered/estimate/unpriced
(`d36bc7d32c9a:36-42`), cache tokens (`a7eb7cbbcbc2:39-47`), langfuse ids (`b7193eb28363:30-34`); writer
`agent_turn_wiring.py:699`; read by `arv2/quality_meter.py:52`). **Every agent-role vocabulary is a DB
CHECK — six of them:** `agent_turn_role` and `agent_plan_role` (`6628a407e993:59-62`; both re-installed
by the `_roles` loop at `f4b30cb3d088:23-26`), `agent_delegation_roles` (`f4b30cb3d088:27-30`),
`agent_model_call_role` (above), and `quality_execution_role`, which ties a **root** row
(`parent_execution_id IS NULL`) to `role='account_research'` and children to
research_claims/research_narrative (`f4b30cb3d088:70-72`). A new role name must be added to all six
before the first governed call of a turn under it (the `agent_plan` INSERT is the first to fail);
**`agent_tool_result`** (`6628a407e993:176-206`; PK operation_id; writer `agent_execution_wiring.py:655`);
**`tool_invocation`** idempotency receipts (`49911e6aac37:57-84`; `DbIdempotencyStore`,
`quality_research_wiring.py:553`); **`arv2_quality_allowance`** (`f4b30cb3d088:41-55`; PK job_id; CHECK
`0 ≤ used ≤ max` per counter; `max_runtime_ms`/`runtime_used_ms`/`runtime_started_at`/
`runtime_owner_token` + CHECK (`d21f35762d71:18-25`), relaxed so 0 = unbounded (`7d5efcd83a32:18-22`));
**`arv2_quality_execution`** (`f4b30cb3d088:56-74`; root role account_research, children
research_claims/research_narrative — DB CHECK `quality_execution_role`, `:70-72`); **`arv2_quality_activity`** (`:75-85`; kind CHECK
model/tool/delegation). Invariants: allowance limits cannot be reset on recovery (code,
`quality_execution.py:86-118`); one execution per (ws, job, context, role, parent) (`:119-145` + DB);
no overspend — DB CHECK + `FOR UPDATE OF a` with activity_id as replay key (`:147-225`); runtime
charged across crashes, fenced by owner token (`:296-339`); model spend lives in `agent_model_call`,
acquisition spend in `provider_call_ledger`, never copied (`:1-6`).

### 3.9 Claim-quality tables and the ARV2-era `claim` columns

- `arv2_quality_proposal` (`8822efd6ceae:30-48`): PK `operation_id = uuid5("claim-proposal:{job}:{key}")`
  (`quality_claims.py:204`); `ws, job_id, subject_id, proposal_key` (FK artifact), `request_sha256`,
  `claim_id`; status CHECK supported/qualified/unresolved/invalid/refused; insert serialised by
  advisory lock `quality-proposal:{oid}` (`:205-208,665-681`).
- `claim` gains UNIQUE `claim_quality_scope (id, ws)` (`8822efd6ceae:49`); ARV2-era columns
  `signal_priority smallint NOT NULL DEFAULT 3` CHECK 1..3, `outreach_safe boolean NOT NULL DEFAULT
  true`, `write_markers jsonb` CHECK object-or-null, partial index `claim_live_unsafe`
  (`65fb2128c904:100-116`), excluded from the immutability guard (`:20-23`); media index on
  `write_markers->'media'->>'version_ref'` (`213dea37b230:155-159`); `source_url` nullable since
  creation (`0002_claim_table.py:95`); `artifact_key` FK + scope CHECK (`d091e3962833:116-125`).
  `write_markers` keys used by ARV2: `quality_required`, `quality_advisory` (`quality_claims.py:544,550`),
  `media` (`claim_writer.py:171`), `identity_binding_defaulted`, `use_class_defaulted`,
  `source_missing`, `proposed_field`, `schema_valid` (`claim_writer.py:213-258`).
- `claim_quality_assessment` (`:50-72`; PK `uuid5("quality-assessment:{op}")`; UNIQUE `(claim_id,
  revision)`; conclusion CHECK supported/qualified/unresolved/invalid; `rationale_key` FK artifact;
  `context_id`); `claim_quality_current` is a VIEW `DISTINCT ON (claim_id) ORDER BY revision DESC`
  (`:73-76`); `claim_quality_support` (`:77-92`); `claim_quality_operation` kind CHECK
  assessment/withdrawal/correction/conflict (`:93-113`); `claim_dependency_revision` PK `(ws,
  entity_id)` (`:114-122`); `claim_quality_event` UNIQUE `(ws, entity_id, revision)` with a partial
  pending index (`:123-140`). Append-only triggers reject UPDATE/DELETE on assessment, support,
  operation and proposal (`:141-154`).
- Invariants: history append-only — DB trigger; optimistic revision — code requires expected ==
  current under `claim FOR UPDATE ORDER BY id` (`subsystems/research/clue_research/claimstore/quality.py:122-144,244-246`),
  replays idempotent per `claim-quality:{op}` advisory lock + digest (`:201-230`); withdrawal and
  correction must conclude `invalid`, conflict `unresolved`, only a correction carries a replacement
  (`:174-179`); a replacement must be a different live `supported` claim (`:264-296`);
  project-relative fields require the same pinned context (`:252-255`); every assessment bumps
  `claim_dependency_revision` and emits `claim_quality_event` in the same transaction (`:340-367`);
  delivery `FOR UPDATE SKIP LOCKED`, acknowledged in the caller's transaction (`:441-480`); ordinary
  readers see only `supported` (or legacy unassessed) claims with no erased/expired support and a
  recursively eligible derivation chain (`eligible_sql` `:49-87`), qualified research via
  `inspectable_sql` (`:90-106`); the proposal conclusion from five semantic axes — any `contradicted`
  → invalid, any `uncertain` → unresolved, qualifications → qualified, else supported
  (`quality_claims.py:91-103`). Relationships and conflicts are **claims, not tables**:
  `contact.employment_assessment`, `account.committee_assessment`, `account.committee_selection`
  (`quality_relationships.py:22-24`, 30-day freshness `:103-145`); `account.committee_candidate`
  (`account_research_claims.py:108`).

### 3.10 Generation tables (the quality continuation lane)

- `arv2_account_research_generation` (`369f195d9976:18-46`): `generation_id` PK =
  `uuid5("research-generation:{ws}:{job}")` (`quality_generation.py:82`); `ws, project_id, context_id,
  run_id, account_id`; `initial_job_id` UNIQUE, FK job 4-tuple; `input_revision bigint default 0`;
  `reconciled_revision default -1` CHECK `-1 ≤ reconciled ≤ input`; `state` default researching CHECK
  researching/provisional/reconciled/partial/needs_review/suspended/privacy_stopped;
  `initial_settled_at, created_at, updated_at`; UNIQUE `(generation_id, ws)`; FK context pin; indexes
  `quality_generation_account (ws, project, account, context)` and partial `quality_generation_pending
  WHERE input_revision > reconciled_revision`.
- `arv2_generation_child` (`:47-73`): PK `(generation_id, job_id)`; FKs generation, `(job_id, ws) →
  job`, `(contact_id, ws) → contact_entity`, `receipt_key → artifact`; `terminal_status` CHECK NULL or
  completed/needs_review/failed; `result_sha256`; indexes `(ws, contact, generation)`, `(ws, job_id)`.
- `arv2_generation_signal` (`:74-84`): PK `(generation_id, event_id)`; UNIQUE `(generation_id,
  input_revision)`; reason CHECK initial_settled/person_result/claim_changed/media_changed/manual_refresh.
- `arv2_narrative_reconciliation` (`f3eb43c7808f:39-54`): PK `(generation_id, input_revision)`; state
  CHECK prepared/generated/completed/failed; `packet_key/response_key` FK artifact.
- `arv2_research_page_current` (`16bfa50620f4:44-59`): PK `(ws, project, context, subject_kind,
  subject_id, page)`; CHECK account pages ∈ overview/insights, contact pages = contact.
- Invariants: one generation per initial job, context never changes — DB UNIQUE + code
  (`quality_generation.py:79-115`; only account jobs or parent-less persons create one `:92`);
  monotonic replay-safe revisions — `signal()` locks `FOR NO KEY UPDATE`, a replayed event returns its
  prior revision and must carry the same reason, new events get `input + 1` (`:218-246`), backed by the
  UNIQUE; deterministic event ids (`quality-initial:{job}` `driver:1901`; `research-child-result:{job}:
  {digest}` `:289-290`; the claim_quality_event id `:380-387`); signals commit with their source
  effects (`driver:1869-1935`); writers — `initial_settled` (driver), `person_result` (`:296`),
  `claim_changed` (`:386`); **no writer found for `media_changed` or `manual_refresh`**; `suspended`
  and `privacy_stopped` are only ever read — the only UPDATEs (`:248,483`) never set them; child
  containment (`register_child` `:185-212`; `attach_to_account_research` `:118-182` admits only an
  independently launched person of the same account/project/context into the newest recipe ≥ 25
  generation); reconcile idempotent and ordered under the lock (`:446-458`), state derived from child
  statuses (`:471-481`); continuation lease `continuation_work_id` per `(ws, project, context,
  account)` (`:43-49`), offered only while idle (`driver:984-1001`); the page pointer is upserted with
  the new blocks in one transaction after locking inputs (`quality_pages.py:280-405`;
  `page_inputs(lock=True)` locks the generation and `claim_dependency_revision` `FOR SHARE`,
  `arv2/quality_page_inputs.py:53-114`; publishing refused for a stopped or superseded generation
  `:56-77`).

### 3.11 Person release marker and dossier snapshot state

`arv2_research_import_ready` (`f3eb43c7808f:30-38`): PK `(job_id, dossier_version)`; FK job ON DELETE
CASCADE; `dossier_version > 0`; `artifact_key` FK. Written by `mark_account_import_ready` inside the
import transaction for any recipe ≥ 18 job whose snapshot is complete, plus the
`research_account_import_ready` reference for account jobs (`quality_person_release.py:29-63`); read by
`ready_person_jobs` (`:66-104`, gate `:89-92`), `pending_continuations` (`quality_generation.py:408-421`),
`read_parent_dossier` (`:107-170`). Dossier snapshots: artifacts retained as `research_json_dossier`
under `{job}:{version:010d}` (`quality_json_dossier.py:85-150`); states code-only `draft` →
`import_pending`/`draft`/`complete` (`:70,412-413,535-539`); version +1 at `:266,352,413,534`; writers
serialised by `research-dossier:{ws}:{job}`, imports by `dossier-import:{job}:{import_id}`
(`dossier_import.py:164-167`).

### 3.12 `display_section_recipe`, `display_block`

- `display_section_recipe` (`65fb2128c904:141-167`): PK `(page, section_key, workspace_id)` ('' =
  system row); `h1, position ≥ 0, allowed_field_keys text[], restricted, default_open,
  instruction_version`; page CHECK overview/insights/contact; `shared_from_page/_section_key` + pair
  CHECK (`2b702a116c15:35-41`); seed row deleted/repositioned (`5e1c0a9d7b24:34-46`); system upsert
  `arv2/display/recipes.py:314-333`; a `shared_from` recipe owns no blocks (`display/blocks.py:337-341`;
  `display/page.py:358-361`); unsafe claims only in restricted sections (`display/floor.py:56-62`;
  `display/gather.py:396,482`).
- `display_block` (`65fb2128c904:169-201`): PK `display_block_id`; `ws` FK; `subject_kind` CHECK
  account/contact; page CHECK; `body_json` object CHECK; `cited_claim_ids uuid[]`; `model,
  prompt_version, recipe_version, generated_at, superseded_at`; indexes `display_block_live` (partial
  unique) and `display_block_subject`. Altered (`16bfa50620f4:16-43`): `project_id, context_id,
  generation_id, dependency_manifest, output_artifact_key` (FK artifact), `execution_id` (FK execution);
  CHECK `display_quality_shape` (all six NULL = legacy Luna block, all six non-NULL = contextual);
  `display_block_live` redefined for `context_id IS NULL` and a new unique `display_block_context_live
  (ws, project, context, kind, subject, page, section) WHERE superseded_at IS NULL`. Legacy writer
  `display/blocks.py:125-172`; contextual writer `quality_pages.py:351-394`.

### 3.13 Media tables (all `213dea37b230`)

`arv2_media_item` (`:39-51`; PK `(ws, item_id)`, `item_id = uuid5("arv2-media:{ws}:{key}")`
`media_store.py:52`; UNIQUE canonical_key; `expires_at` default now()+30d; `erased_at, privacy_erased,
acquisition_generation`; FK `current_version`); `arv2_media_alias` (`:52-62`); `arv2_media_transcript`
(`:63-84`; version `uuid5(op, "canonical-transcript-v1")`; `text_key/segments_key` FK; `char_count >
0`; expires 30d; `supersedes` self-FK with UNIQUE `arv2_media_repair_once` — repaired at most once);
`arv2_media_index` (`:90-102`; state CHECK lexical/partial/ready/unavailable); `arv2_media_passage`
(`:103-116`; bounds CHECK; generated tsvector + GIN); `arv2_media_operation` (`:117-136`; owner job
FK via `arv2_media_job_scope`; `fingerprint, stage, seconds ≥ 0, owner_token, lease_until 2h`; state
CHECK reserved/dispatched/succeeded/failed/unknown/unavailable; UNIQUE `(ws, item, stage,
fingerprint)`; stages code-only resolution/download/transcribe/query_embedding); `arv2_media_attempt`
(`:137-154`; kind/outcome code-only). Trigger `arv2_media_artifact_unavailable` (`:160-213`) scrubs the
item, deletes passages, marks indexes/operations unavailable, expires transcripts and privacy-erases
siblings when an artifact is erased. Invariants: source ownership and the per-job seconds allowance
serialised by advisory locks `media-source:{ws}:{item}`, `media-job:{ws}:{job}`
(`media_operations.py:28-31`; `media_store.py:192-195`); an expired `reserved` op is reclaimable, an
expired `dispatched` becomes `unknown` (`:51-79`); the seconds ceiling is enforced in code
(`:103-108`); privacy-erased media never refreshed (`media_store.py:581-582`); attempt detail visible
30 days (`:176`).

### 3.14 `fleet_task`, `work_lease`

`fleet_task` (`10642c862e43:87-149`): `task_id` PK; `kind` (enum `fleet_task_kind`); `work_id`
(renamed from `project_run_id`, `d9b39fb407ed:46`); `dedup_key`; `priority`; `status` (enum
queued/claimed/done/failed); `attempts ≥ 0`; `payload/result` jsonb; `claimed_by/claimed_at` with
stamp CHECKs; `enqueued_at`; `enqueue_seq` identity; `available_at` (`9aacba7cea99:30`). UNIQUE
`fleet_task_dedup (kind, work_id, dedup_key)` (`d9b39fb407ed:47-49`); indexes `fleet_task_claim_next
(kind, priority, enqueue_seq) INCLUDE (available_at) WHERE status IN (queued, claimed)`
(`9aacba7cea99:36-41`), `fleet_task_work` (`d9b39fb407ed:50`). `work_lease` (originally `run_lease`
`10642c862e43:66-78`; renamed with `generation ≥ 1` `d9b39fb407ed:33-41`): acquire takes over only an
expired lease or the same worker, bumping generation (`platform/fleet/clue_fleet/lease.py:51-73`);
renew/release fenced on (worker, generation) (`:75-92`). Invariants: idempotent enqueue — DB UNIQUE +
`ON CONFLICT DO NOTHING` (`clue_fleet/queue.py:177-187`); `only_if_work_idle` serialised by advisory
lock `fleet-offer:{kind}:{work}` (`:220-237,455-463`); claim order `(priority, enqueue_seq)` with
`available_at <= now()`, `SKIP LOCKED`, takeover after 60 s staleness (`:51,257-292`);
finish/touch/requeue fenced on the holder (`:294-326`).

### 3.15 Committee rows, project bindings, privacy reach

- `provider_identity` (`0ab01fe27c1e:60-73`; PK `(ws, provider, subject_id)`; `contact_id` FK;
  `evidence_artifact_key`; `erased_at`), `provider_artifact_subject` (`:74-89`; `expires_at` now()+30d),
  `provider_selection_claim` (`:92-100`). Legacy selection (`finalize_committee`,
  `committee_discovery.py:406-532`) writes `account.committee_candidate` claims + selection rows under the
  job row `FOR UPDATE`; v4 nomination is `NominateCommitteeTool` (`quality_committee_tool.py:69-230`).
  Seeds: person `input_refs {version: 1, candidate_ref = "{operation_id}:{provider_subject}",
  parent_job_id, [provider_job_id]}` (`committee_discovery.py:92-133`); `load_person_seed` verifies and
  rebinds identity (`:556-612`); identity locks `provider:{ws}:{p}:{s}`, `linkedin:{ws}:{url}`
  (`subsystems/research/clue_research/identity/provider.py:113-120`).
- `agent_artifact_project` (`5330703a78a3:136-162`; PK `(ws, project, artifact_key)`; project FK ON
  DELETE RESTRICT; `binding_kind`; scope CHECK). ARV2 inserts `research_page` (`quality_pages.py:334-339`),
  the page-writer kinds (`page_writer_runtime.py:213-217`), `research_reconciliation`
  (`quality_reconciliation.py:169-173`) **without** taking the project lock; the lock
  `agent-project-artifacts:{ws}:{project}` (`agent_turn_wiring.py:91-95`) is SHARED in the agent store's
  `_bind_projects` (`:343-350`) and EXCLUSIVE in `erase_project` (`:1842-1849,1878-1885`) — the 2026-10-04
  T3 change. `agent_artifact_subject` (`7e9269ed8a81:177-206`), `agent_artifact_tombstone`
  (`:210-235`), `agent_privacy_event` (`:521-555`); tombstoned keys cannot be resurrected through the
  agent store (`agent_turn_wiring.py:292-300`).
- Privacy stop: `DurableContactResearchPrivacyStopper.stop` takes `contact-research:{ws}:{contact}`
  (`platform/api/clue_api/storage_wiring.py:69-103`; DSAR `subsystems/research/clue_research/compliance/dsar.py:944-947`;
  claim writer `claim_writer.py:135-157`); `stop_contact_jobs` sets `input_refs.privacy_stopped` /
  `blocked_channels` and privacy-erases operation artifacts (`research_operations.py:273-314`).
  **Observation:** both the flag write (`:292-293`) and the claim-writer block (`claim_writer.py:142-146`)
  filter `profile_ref IN ('agent-profile:arv2-person:v2', '…:v3')`, while quality person jobs carry
  `…:v4` (`quality_committee_tool.py:219`, pinned from the parent's recipe at `:213-218`; `account_research_launch.py:915`). Readers of the flag:
  `job_available` (`:317-344`), evidence `_subject` (`quality_evidence.py:106`),
  `pending_continuations`/`ready_person_jobs`, the driver (`:632`). DSAR `erase` →
  `erase_provider_evidence` sets `provider_identity.erased_at`, privacy-erases every
  `provider_artifact_subject` artifact and nulls `linkedin_url` (`provider.py:247-303`); a provider page
  naming several people is fully erased once any registered subject is erased (`:73-90`); written pages
  are bound via `agent_artifact_subject` to every subject they describe (`quality_pages.py:323-332`;
  `page_writer_runtime.py:218-225`); `erase_subject`/`erase_artifacts` write tombstone, `mark_erased`
  and the privacy event (`agent_turn_wiring.py:1793-1822,2103-2138`); propagation by the derivation and
  media triggers.

### 3.16 What runs under the process-wide `_db_lock`

`self._db_lock = asyncio.Lock()` (`driver:504`), one handler per fleet process (`fleet_main.py:1345`),
shared by every concurrent job on that worker. **Under it** (via `_connection()`, `:1016-1019`): the
driver's row transitions (begin/finish/suspend/stage/refresh), the sweep and continuations, and every
`ToolRuntime._conn_factory` use — the acquisition path's `operate()` begin/finish/body
(`account_research_tools.py:707-724`), `_drain` and the legacy committee writes — because the runtime is
built with `conn_factory=self._connection` (`:1263`). **Not under it**: provider pacing (raw factory,
`:1264`; the AI Ark try-lock `account_research_tools.py:473-477`) and the quality runner's governed
tools (proposals, evidence grants, dossier tools, pages, nominations, the `quality_tool:` operation
rows), which use `connections=transaction` (`fleet_main.py:790-792`; `quality_research_wiring.py:517-567`).
It provides no cross-process guarantee; cross-process exclusion comes from `work_lease`, the `attempt`
fence, row locks and advisory locks.

### 3.17 Status vocabularies

PG enums: `fleet_task_kind` (`10642c862e43:62`, grown by ADD VALUE; mirror `clue_fleet/enums.py:59-77`):
drive_run, account_job, execute_graph, entity_research_job, agent_turn, stage0_recon,
official_site_crawl, design_job, onboarding_run, arv2_account_research, arv2_discovery,
arv2_display_page; `fleet_task_status`: queued, claimed, done, failed. Text + CHECK: run/job status
not_started/in_progress/needs_review/completed/suspended; subject_type account/person; stage
deep_research/synthesis/committee/member_research; effort full/reduced/cheap-pass; research operation
state running/succeeded/empty/failed/unknown; media operation state reserved/dispatched/succeeded/
failed/unknown/unavailable; media index lexical/partial/ready/unavailable; evidence source kind and
disposition decision (§3.5); context document role icp/persona/seller; ledger phase/outcome (§3.6);
quality proposal status supported/qualified/unresolved/invalid/refused; assessment conclusion
supported/qualified/unresolved/invalid; operation kind assessment/withdrawal/correction/conflict;
annotation verdicts EXACT/PARTIAL/NOT_FOUND/fetch_failed; generation state, child terminal_status,
signal reason, reconciliation state (§3.10); quality execution role and activity kind (§3.8);
`agent_model_call` status/role; display page/subject_kind. Code-only: operation kinds, media stages,
`artifact.erasure_reason` (`privacy`, `retention`), `artifact_reference.reference_kind`,
`agent_artifact_project.binding_kind`, job failure codes, dossier snapshot state, `input_refs` keys.

## §4 The virtual filesystem the agent sees

- Composition: `research_backend()` wraps the workspace lease's own backend in a Deep Agents
  `CompositeBackend(default=lease.backend, artifacts_root="/work", routes={"/research/":
  ResearchViewMount(...), "/evidence/": ResearchViewMount(..., evidence=True)})`
  (`arv2/quality_views.py:482-506`). The workspace policy (profile `v25`) allows reads under
  `.deepagent, inputs, context, work, outputs, research, evidence, reads` and writes under `work,
  outputs` (`platform/agents/catalog/research-quality/profiles/quality-account-research/v25/profile.yaml`,
  `workspace:` block). Skills are materialised read-only under `.deepagent/skills/<name>/<version>/SKILL.md`
  (resource snapshot verified or materialised at `quality_research_wiring.py:965-979`; the launch tool's
  description names `.deepagent/skills/account-research-briefing/v3/SKILL.md`
  (`account_research_launch.py:1325`). Deep Agents writes compaction archives under
  `/work/conversation_history/<thread-id>.md` (`_memory/2026-09-25-research-runtime-repairs.md`,
  checkpoint 2) and large tool results under `/work` (`artifacts_root`).
- `/research/…` is a **view, not a cache**: every read re-resolves the execution's authority
  (`ResearchViewMount.aread`, `quality_views.py:84-100`); a revoked grant or erased original turns
  into `"Research view unavailable; inspect scope or request a new authorized task."` (`:97-100`).
  Paths served by `_view` (`:102-415`):

| Path | What it serves | Cite |
|---|---|---|
| `/research/context.json` | the pinned context (ICP, personas, product set, gaps) minus the field catalog, plus a path map: `document_paths`, `catalog_path`, `claims_path`, `committee_path`, `generation_path`, `evidence_path`, `dossier_path` (`/research/dossier/latest.json`), `capabilities_path`, `selected_person` + `person_research_brief_path` + `discovery_references` + `account_research_references` for a person job, `review_policy` (advisory) | `:238-310` |
| `/research/documents/<uuid>/<offset>.json` | one pinned document body as a passage (256-char `text_segments`, `next_path`) | `:246-256`, `_passage` `:45-57` |
| `/research/catalog/<offset>.json` | field definitions for the subject's entity (`kind: field_definitions_not_evidence`) | `:316-331` |
| `/research/claims/<offset>.json` | live claims for the subject (+ account, + committee members for an account job) with `status` from `claim_quality_current`, `applicable`, a `path` per claim | `:332-415` |
| `/research/claim/<uuid>/<offset>.json` | one claim with value, span, markers, quality status | `:394-399` |
| `/research/operations/<uuid>/<offset>.json` | the saved result of one `acquire_research_evidence` call (`arv2_research_operation.artifact_key`, `kind LIKE 'quality_tool:%'`, account_research role only) rendered as a passage | `:214-237` |
| `/research/capabilities/<offset>.json` | the acquisition tool's operation catalogue (`AcquireResearchTool.capabilities()`), account_research role only | `:209-213` |
| `/research/transcripts/<uuid>/<offset>.json` | a media transcript window | `:144-150` |
| `/research/source-review/<uuid>/<offset>.json` | a source review | `:124-130` |
| `/research/person-brief/<offset>.json` | the account-authored person brief, or `no_person_specific_brief` | `:131-143` |
| `/research/coverage.json` | measured coverage | `:151-154` |
| `/research/committee.json` | committee members + `supported_count` | `:155-165` |
| `/research/generation.json` | the generation this job owns or was released into, with its person jobs | `:166-208` |
| `/research/dossier/latest.json` | the job's JSON dossier (state, version, receipt) | `:108-111` |
| `/research/account-dossier/(latest\|N).json` | the pre-JSON account dossier (older recipes) | `:112-123` |
| `/research/parent-account-dossier.json` | the parent's completed import (person jobs, recipe ≥ 18) | `:106-107` |
| `/evidence/index.json` | `list_sources` over the grant: every acquired source with readable path, availability, byte size | `arv2/quality_workspace.py:70-73` |
| `/evidence/NNNN-slug.json` | one source body as `text_segments` of 256 chars + metadata (`SOURCE_PATH` regex `arv2/evidence_paths.py:9`; name = manifest revision + sanitised title, `:13-30`) | `quality_workspace.py:74-83` |

- Rendering: `render_view` dumps the JSON with `indent=2` and treats Deep Agents' default `limit=2000`
  (and non-positive limits) as **unbounded**, otherwise slices by line (`quality_workspace.py:43-55`,
  via `deepagents.backends.utils.slice_read_response`, which adds line numbers). The 2026-10-06 audit
  measured these as "JSON inside JSON, 1.5–2.3× bigger than their content", served in 100-line pages
  (`docs/superpowers/specs/2026-10-06-account-research-cost-and-speed-audit.md:83-85`).
- `ls`: `/research` lists only `context.json, catalog/0.json, claims/0.json, dossier/latest.json`
  (+ `parent-account-dossier.json` for a released child); any other `/research/<dir>` returns
  `"Open /research/context.json or /evidence/index.json."` (`quality_views.py:417-465`); `/evidence`
  lists `index.json` + every available source (`quality_workspace.py:96-115`). `glob` filters that
  listing by file-name pattern, `..` refused (`quality_views.py:467-479`; `quality_workspace.py:117-129`).
  `grep` on `/evidence` is refused with `"Use search_evidence with the readable source path and a
  literal query."` (`quality_workspace.py:131-136`); the synchronous backend methods refuse with
  `"Use the asynchronous research runtime…"` and writes with `permission_denied` (`:138-162`).
  The 2026-10-07 audit counts 60 refused ls/glob/grep calls over 12 runs and names the grep →
  search_evidence → finalize trap (`_memory/2026-10-06-account-research-cost-audit.md`, "Deeper audit").
- Native `read_file` line windows work inside each bounded view since 2026-09-23
  (`_memory/2026-09-23-zafran-quality-live.md`: "standard read_file line windows were refused by the
  JSON view backends. They now use Deep Agents' native line slicing"); every line read rechecks the
  grant.

## §5 Profiles, prompts, skills, recipes (recipe 25)

`RQ` = `platform/agents/catalog/research-quality`. Token estimates are bytes ÷ 4.

### 5.1 The v25 profiles

| Field | Account `RQ/profiles/quality-account-research/v25/profile.yaml` | Person `RQ/profiles/quality-person-research/v25-person/profile.yaml` |
|---|---|---|
| `role` | `account_research` (`:6`) | `account_research` (`:6`) |
| prompt pin | quality-account-research v25, sha `08bceab5…` (`:7-10`) | quality-person-research v25-person, sha `4d9546cb…` (`:7-10`) |
| skills pinned (name/version/sha) | governed-evidence v4; account-dossier v9; person-research-briefing v4; claim-ready-account-dossier v3 (`:11-23`) | governed-evidence v4; person-dossier v5; person-depth-charter v1; claim-ready-person-dossier v3 (`:11-23`) |
| tools pinned | search_evidence@2, acquire_research_evidence@1, nominate_committee_candidate@3, nominate_web_committee_candidate@3, save_dossier_section@1, validate_dossier@1, finish_dossier@1, begin_dossier_revision@1, discard_dossier_revision@1, update_dossier_findings@1 (`:24-64`), each with input/output schema sha256 | the same minus the two nominate tools (`:24-56`) |
| `model.model_id` / `timeout_s` / `max_retries` | `x-ai/grok-4.6` / 120.0 / 2 (`:66-68`) | same (`:58-60`) |
| `max_output_tokens` / `temperature` | 16384 / 0.0 (`:69-70`) | same (`:61-62`) |
| `memory_policy` | `scoped-advisory-v1` (`:71`) | same |
| workspace | `virtual_mode: true`; 10 MiB total, 1 MiB per file, 200 files; `.json .md .txt .yaml`; readable `.deepagent inputs context work outputs research evidence reads`; writable `work outputs`; retention `agent-ephemeral-v1` (`:72-94`) | identical (`:64-86`) |
| delegation | roles `[]`, grants `{}`, depth 0, delegations 0 (`:95-98`) | same |
| `max_plan_nodes` / `turn_timeout_s` / `max_model_rounds` | 64 / 1800.0 / 100 (`:99-101`) | same |

Neither profile pins `record_research_finding` although recipe-v25 still allows it (asserted by
`tests/arv2/test_quality_owned_narrative.py:59`, `tests/arv2/test_quality_json_dossier.py:25`).
Each skill sha is the sha256 of the whole `SKILL.md` including frontmatter, checked by the registry
(`platform/agents/clue_agents/catalog.py:322-329`, `registry.py:549,575`).

**Which model, timeout, effort and limits actually apply** (three layers, each overriding the last):
1. the profile pin above;
2. the registry env override `{ROLE}_AGENT_MODEL` → `ACCOUNT_RESEARCH_AGENT_MODEL`
   (`platform/agents/clue_agents/registry.py:375-407`, read `:395`, applied `:634`) and
   `CLUE_AGENT_MODEL_TIMEOUT_S` replacing every profile's `timeout_s` (`:396-398`; `.env.example:378`
   = 60, bounded by `CLUE_GATEWAY_TIMEOUT_S=60` `:364`) — so the effective per-call timeout is 60 s,
   not the profile's 120 s;
3. the quality-lane override: the driver passes its own model id (`ARV2_ACCOUNT_AGENT_MODEL` /
   `ARV2_PERSON_AGENT_MODEL`) and the runner replaces the resolved profile's `model_id` with it
   (`platform/api/clue_api/quality_research_wiring.py:781-794`; `account_research_driver.py:1405,1184-1189`).
   Both are `x-ai/grok-4.6` in `.env.example:414,418`.
- The gateway role is the profile's `role` = `account_research` (`platform/agents/clue_agents/runtime.py:606-617`),
  so the effort knob that applies is `ACCOUNT_RESEARCH_AGENT_MODEL_EFFORT` (`medium`, `.env.example:406`;
  read at `libs/clue-gateway/clue_gateway/agent_model.py:1229`), **not** `ARV2_ACCOUNT_AGENT_MODEL_EFFORT`
  (`.env.example:415`), which only the legacy R2 loop's roles `arv2_account`/`arv2_person` read
  (`account_research_driver.py:276-280,1233-1240`). Person jobs share the account effort knob.
- The profile's `max_model_rounds: 100` and `turn_timeout_s: 1800` do not govern quality runs: the
  runtime uses `Allowance(settings.arv2_account_max_model_rounds=350, …, runtime_ms=
  arv2_account_max_runtime_s×1000=0)` (`quality_research_wiring.py:1232-1239`, `:754`;
  `settings.py:447,450,454`; `.env.example:181,183,186`); the generated resource map tells the agent
  "turn limits … set by the deployment" (`registry.py:340-343`).
- Fallbacks `CLUE_AGENT_FALLBACK_MODELS=x-ai/grok-4.7,meta/muse-spark-1.3` (`.env.example:383`);
  context windows `CLUE_AGENT_MODEL_CONTEXT_WINDOWS` grok-4.6 = 500000 (`:388`).

### 5.2 The v25 prompts

| | Account `RQ/prompts/quality-account-research/v25/SYSTEM.md` | Person `RQ/prompts/quality-person-research/v25-person/SYSTEM.md` |
|---|---|---|
| size | 118 lines, 10,399 B, ~2.6k tokens | 109 lines, 8,668 B, ~2.2k tokens |
| frontmatter | kind prompt, role account_research, framework deepagents `>=0.6,<0.7` (`:1-10`) | same |
| placeholders | `{{skills.claim_ready_account_dossier.path}}` (`:71`) | `{{skills.person_dossier.path}}` (`:23`), `{{skills.person_depth_charter.path}}` (`:24`), `{{skills.claim_ready_person_dossier.path}}` (`:62`) |

`{{account_name}}` / `{{account_domain}}` are not in either prompt: they live in the Head-of-ABM
directive and the driver substitutes them in the task message (`account_research_driver.py:146-149,1427-1430`);
the renderer leaves other placeholders literal (`platform/agents/clue_agents/resources.py:130-135`).

Account prompt, order of work: identity/mission/ownership incl. the committee shortlist and person
briefs (`:12-19`); evidence trust block = governed-evidence v4 `:13-19` verbatim (`:21-27`); read the
account-dossier skill before preparing Exa's assignment — main query + additional queries, no
thresholds or verdicts (`:29`); preliminary `search_web` (type=auto) before the deep call and
`/work/pre-deep-review.md` (`:31-36`); AI Ark typed enrichment and SMART discovery, work email only,
no phones (`:38`); the deep call with `additional_queries` via `acquire_research_evidence(operation=
"research_deep")`, after reading `/research/context.json` and `/research/capabilities/0.json`
(`:40-42`); review returned sources via `source_navigation`/`source_review_path`, targeted page reads
(`:43-49`); committee — four or five candidates within the job's limit, "after developing the account
picture", read person-research-briefing first and write `research_brief` yourself (`:51-61`); media
(`:63-64`); dossier formation — read the COMPLETE claim-ready skill following read continuations;
one assessable finding each; quotes preserved; `agent_interpretation` separate; open questions in
`/work/review.md` (`:66-87`); `save_dossier_section` → `update_dossier_findings` → `validate_dossier`
→ `finish_dossier`, no coverage ledger, counts are not a gate (`:89-99`); continuations/revisions
read `/research/dossier/latest.json` first (`:101-107`); **pages**: "You do not write display pages:
after you finish, a separate writer turns your imported dossier into the pages the seller reads, so
the dossier must carry every finding…" (`:108-110`); finish by writing `/outputs/research.json`
(`research-unit-v1`) then `finalize_turn` (`:111-116`).

Person prompt: identity (`:12-19`); reads `/research/context.json`, `/research/person-brief/0.json`,
`/research/capabilities/0.json`, then the complete person-dossier and charter skills (`:21-24`);
modest preliminary searches, "Do not restart committee discovery" (`:24-28`); the agent writes the Exa
assignment from the charter's subquestions plus earlier employers and interests (`:30-34`); after
Exa: `source_review_path`, `read_media`/transcripts, assess each charter subquestion as
answered/partial/unclear/unsearched/inaccessible, adaptive follow-ups (`:36-48`); no employment or
location gates (`:50-53`); no phone enrichment (`:55`); formation/JSON/finish identical to the account
prompt (`:57-109`; pages statement `:99-101`).

### 5.3 Skills (sizes, what they instruct)

Account profile skills total 66,953 B (~16.7k tokens); person profile skills 59,760 B (~14.9k tokens).

| Skill | Path | Lines | Bytes | ~Tokens |
|---|---|---|---|---|
| governed-evidence v4 | `RQ/skills/governed-evidence/v4/SKILL.md` | 24 | 1,553 | 388 |
| account-dossier v9 | `RQ/skills/account-dossier/v9/SKILL.md` | 323 | 28,690 | 7,173 |
| person-research-briefing v4 | `RQ/skills/person-research-briefing/v4/SKILL.md` | 175 | 11,265 | 2,816 |
| claim-ready-account-dossier v3 | `RQ/skills/claim-ready-account-dossier/v3/SKILL.md` | 405 | 25,445 | 6,361 |
| person-depth-charter v1 | `RQ/skills/person-depth-charter/v1/SKILL.md` | 171 | 11,436 | 2,859 |
| person-dossier v5 | `RQ/skills/person-dossier/v5/SKILL.md` | 303 | 21,448 | 5,362 |
| claim-ready-person-dossier v3 | `RQ/skills/claim-ready-person-dossier/v3/SKILL.md` | 400 | 25,323 | 6,331 |

- **governed-evidence v4**: verification deferred; trust acquired data as reported; no employment/
  location/committee proofs, no second-source requirement; never hide uncertain findings; never
  invent sources or quotes (`:13-19`); read originals via `/evidence/index.json` with native
  `read_file` pagination and cite the returned `source_paths` (`:21-24`).
- **account-dossier v9**: keep fit/threshold/role judgments; AI Ark prose excluded from inputs
  (`:19-25`); before the deep call batch reads of `/research/claims/0.json` and `/evidence/index.json`,
  several complementary `search_web` calls with no fixed count, `/work/pre-deep-review.md` (`:27-51`);
  research priorities 1 people's own statements → 2 initiatives/workflows → 3 responsibilities/tools/
  vendors → 4 financing/leadership/adverse news → 5 background (`:53-63`); discover the team then what
  its people say; per-person searches; systems through the work; excerpts as leads to read in full;
  a small number of evidence-guided follow-ups; honest "not found" (`:65-174`); eleven coverage areas
  with a nine-month recency window (`:176-192`); the five-element Exa assignment (`:194-204`);
  additional queries "usually three to five" (`:206-216`); after Exa `source_navigation`,
  `source_review_path`, `full_source_path`, `previous_capture` (`:218-252`); media via
  `/research/capabilities/0.json`, "roughly four or five useful candidates", read the briefing skill
  before nominating (`:254-271`); produce the dossier (placeholder at `:279`; "refresh your account
  narrative" `:290-293` — stale under v25); fictional Clue → Acme example (`:296-323`).
- **person-research-briefing v4**: the `research_brief` on a nomination; ~750 words, not a cap
  (`:38-41`); five-part shape (`:47-60`); required coverage incl. "seek 3–5 revealing verbatim quotes …
  with … timestamps where available" (`:64-73`, `:70`); references and the release rule (person job
  released after the account import; re-nominating reuses the job without updating its brief)
  (`:86-107`); Clue → Acme → Dana example (`:109-175`).
- **claim-ready-account-dossier v3**: faithful coverage not a claim count, no ledger (`:17-44`);
  finding vs `agent_interpretation` vs working notes; "likely" does not make an inference an
  observation; gaps go to `/work/review.md` (`:46-132`); the JSON schema `{"sections":[{"section",
  "findings":[…]}]}` with `id` F001…, `topic`, `claim_type` observation|reported_statement, `finding`
  (string or {statement, context}), `source_paths`, `attribution`, `time_context`, `qualifications`,
  `review{status, reason, duplicate_of, conflicts_with, expected_entity}`, `agent_interpretation`;
  `save_dossier_section` replaces the whole section (`:136-174`); meaningful units — "source count
  is not claim count" (`:176-202`); public statements as contiguous exact passages, omissions
  marked, host question vs guest answer apart (`:204-281`); statuses supported | duplicate |
  wrong_entity | insufficient_context | potential_conflict with precedence wrong_entity >
  insufficient_context > potential_conflict > duplicate > supported; never relabel a conflict as
  supported to pass validation (`:283-325`); a 13-row section guide from "Business and operating
  model" to "Source corrections" (`:327-346`); finish and revision workflows (`:348-400`). **Stale
  under v25**: `:369` "Continue narrative writing in this same researcher conversation after import"
  and `:402-405` naming `read_narrative_inputs`/`write_research_narrative`, tools neither pinned nor
  allowed by recipe 25.
- **claim-ready-person-dossier v3**: textually the account version with person wording;
  enrichment-provider biographies excluded (`:37-39`); personal biography kept even without seller
  relevance (`:225`); an 11-row section guide (present responsibilities … gaps and outreach ideas)
  (`:324-340`); the same stale page instructions (`:364`, `:397-398`).
- **person-depth-charter v1**: a fill-in Exa assignment template with single-brace placeholders the
  agent fills (`:18-28`); nine sections — career, background, life outside work as self-described,
  public writing/appearances, voice ("3–5 substantive verbatim quotations … an aim, not a quota",
  `:89-101`), professional identity, nine-month recent activity, distinctive findings, gaps/conflicts/
  same-name (`:40-146`); no outreach, no fit scoring (`:165-171`).
- **person-dossier v5**: do not restart discovery; AI Ark biographies excluded (`:21-31`); distinct
  preliminary angles with no mandatory count (`:33-52`); one comprehensive `research_deep` call after
  `/work/pre-deep-review.md` carrying all nine charter sections (`:62-113`); additional queries
  "usually three to five" (`:115-136`); post-Exa coverage assessment and follow-ups (`:138-226`);
  media workflow — `read_media` `ambiguous` = candidates not yet attempted, `candidate_ref`,
  `open_transcript`/`search_transcripts` (`:275-299`); stale page instructions at `:84`, `:224-225`,
  `:303`.
- **Page-writer guides** (not in the launch map; read at hard-coded `GUIDE_VERSION="v1"` with
  frontmatter stripped, `platform/api/clue_api/arv2/page_writer.py:38-39,94-108`): account system
  = research-page-writing + account-pages; contact = research-page-writing + contact-page; seller
  brief = seller-brief.

| Guide | Lines | Bytes | ~Tokens | Notable rules |
|---|---|---|---|---|
| `RQ/skills/seller-brief/v1/SKILL.md` | 83 | 3,656 | 914 | 700–1,000 words; 8 headings "What the seller sells" → "What we do not know" (`:15-83`) |
| `RQ/skills/research-page-writing/v1/SKILL.md` | 127 | 6,657 | 1,664 | 9 rules (`:38-118`); rule 8 bans private matters (`:101-106`); sentence kinds fact/quote/inference/gap with refs (`:119-127`) |
| `RQ/skills/account-pages/v1/SKILL.md` | 146 | 7,074 | 1,769 | per-section length table; items up to 3 sentences; no `send_line` on account pages (`:23-45`) |
| `RQ/skills/contact-page/v1/SKILL.md` | 96 | 4,459 | 1,115 | length table; 2–3 openers, strongest business opener first, a personal opener last only if self-published (`:24-78`) |

Retired from the v25 pins: research-narrative-editorial v1 (226 lines, 28,418 B),
account-research-narrative v2 (209 lines, 25,531 B), person-research-narrative v2 (175 lines,
20,988 B). `RQ/editorial/account-reconciliation/v1/SYSTEM.md` (19 lines) is used by
`arv2/quality_reconciliation.py:60` (recipes 20–24 continuations).

### 5.4 How skills are disclosed and read

- Not in the system prompt. The system prompt = prompt body (frontmatter stripped, skill-path
  placeholders rendered) + a generated "Resolved resource and capability map" appended on every
  model call by a middleware (`platform/agents/clue_agents/registry.py:349,673`;
  `platform/agents/clue_agents/runtime.py:189-194`). The map lists each skill as one line
  (address, summary, `open=.deepagent/skills/<name>/<ver>/SKILL.md`) plus framework tools, workspace
  limits and the model policy (`registry.py:241-258,304-345`). `create_deep_agent` is called without a
  deepagents skills middleware (`runtime.py:638-670`).
- Materialised per turn by `AgentResourceMaterializer` into `.deepagent/{profiles,prompts,skills}/…`,
  `.deepagent/manifest.json` written last as the readiness marker, then frozen read-only
  (`platform/agents/clue_agents/resources.py:117-124,330-366`). Only `{{skills.<name>.path}}` is
  rendered (`:127-155`); an unmounted or malformed placeholder fails before any model spend
  (`:146-154,184-186`); rendered files are recorded in `.deepagent/rendered-resources.json`
  (`:197-222`). Tests: `tests/agents/test_skill_references.py:20-80`,
  `tests/arv2/test_quality_json_dossier.py:52-62`.
- Read through the framework `read_file`, whose Deep Agents default is `limit=100` lines
  (`.venv/…/deepagents/middleware/filesystem.py:258`), truncated above 20,000 tokens × 4 chars
  (`:831,1051-1062`) — so a 300–405-line skill takes 3–5 reads unless the agent passes a larger
  limit; both prompts tell it to follow read continuations. Measured: skill files "read once per run
  in 2–3 chunks each (96 reads, ≈$3.53)" (`docs/superpowers/specs/2026-10-06-account-research-cost-and-speed-audit.md:78-81`).

### 5.5 Provider requests (`RQ/provider-requests`)

| File | Lines | Bytes | Contents |
|---|---|---|---|
| `account-deep/v1/exa-system.md` | 15 | 2,324 | investigative company researcher; seller context is not evidence; fit and roles left to the researcher; prioritise statements, workflows, people and tools; original sources; URLs beside findings; no outreach/schema/verdict |
| `account-deep/v1/request-config.json` | 13 | 179 | `type: deep-reasoning`, `numResults: 40`, outputSchema text, `contents.highlights true`, `extras.links 1` |
| `person-deep/v1/exa-system.md` | 45 | 3,327 | one named person; affiliation a starting point; life outside work gets genuine attention; prefer own writing/long-form; exact quotes with transcript-backed timestamps; no private inference, no relatives; searched-not-found vs not searched vs inaccessible |
| `person-deep/v1/request-config.json` | 19 | 284 | deep-reasoning, `numResults: 20`, `text.maxCharacters 10000`, `highlights.maxCharacters 2000`, `extras.links 10`, `imageLinks 3` |

Applied by `arv2/account_exa_brief.py:11-55` (recipe ≥ 7; called at `account_research_tools.py:2061-2066`)
and `arv2/person_exa_brief.py:12-58` (recipe ≥ 11; also reused for ordinary person searches `:22-27`).
The config's `numResults` is not read — `num_results` comes from the tool arguments (account default
40, range 10–40; person default 20, range 1–40; `account_research_tools.py:1086,1103`).

### 5.6 Recipes, the launch map, minting

- `RQ/recipe-v25.json` (218 lines): key `arv2-quality-unit` v25; graph barrier `research_open` → gate
  `research_interactions` (authority agent, `resume_condition: input_available`, `max_children 5000`)
  → barrier `research_complete` (`:30-130`); tool allowlist (`:131-143`) mirrored under
  `compatibility.nodes.research_interactions` (`:150-211`); `max_nodes 5003`, `max_depth 2`,
  `max_fanout 1` (`:213-215`). Versus v24: removes `read_research_page_inputs@1`,
  `publish_research_page@2`, `read_narrative_inputs@1`, `write_research_narrative@1`; nothing else.
  One recipe serves account and person jobs; the profiles narrow it.
- `RQ/launch-v4-r25.json`: `catalog_version v4`, `recipe_version 25`, `review_policy advisory`,
  21 path→sha entries (both provider-request folders; governed-evidence v3 **and** v4; the four
  skills per role; v25 profiles+prompts; `recipe-v25.json`; the quality-research-claims and
  quality-research-narrative v19 profiles / v15 prompts, still hashed though inactive at r25 —
  `tests/arv2/test_quality_owned_narrative.py:44-47`). The page-writer guides are **not** in the map.
- Loading: `CURRENT_RECIPE_VERSION = 25` (`arv2/quality_catalog.py:14`); `load_quality_resources`
  reads `launch-v4-r{N}.json`, re-hashes every listed file and raises on mismatch (`:28,32-36`); the
  bundle pin is `ResourceBundle.manifest_sha256()` (`arv2/account_research_catalog.py:97-98,132-135`);
  `expected_pin` scans r25 down to r2 to resolve historical runs (`quality_catalog.py:20-25`).
  **No env selects the recipe**: `CLUE_ARV2_RESEARCH_CATALOG_VERSION=v4` selects the catalog only
  (`.env.example:151`; `settings.py:397`); new launches get `CURRENT_RECIPE_VERSION` through
  `arv2_account_profile_sha256`/`arv2_person_profile_sha256` (`account_research_launch.py:1177-1200`);
  the driver writes `input_refs.quality_recipe_version` and runtime behaviour gates on that integer
  (`quality_research_wiring.py:537`; `quality_policy.py:15-22`; `quality_person_release.py:16`;
  `quality_json_dossier.py:47`; `account_exa_brief.py:20,28`); the profile ladder is
  `quality_research_wiring.py:312-346`.
- Minting procedure as the code requires it (commit `7559c9bca` is the template): (1) new profile
  folders `vN` / `vN-person` with matching name/version, `status: active`, prompt+skill shas (folder
  catalogs reject mismatches, `catalog.py:352-438,322-329`), new prompt/skill folders where content
  changes; (2) `recipe-vN.json`; (3) `launch-v4-rN.json` with `recipe_version N` and every file's sha
  incl. the recipe; (4) bump `CURRENT_RECIPE_VERSION`; (5) a ladder branch in
  `quality_research_wiring.py:312-346`; (6) any new behaviour behind `quality_recipe_version >= N`;
  (7) tests: `tests/arv2/test_quality_owned_narrative.py:64` and `test_quality_json_dossier.py:30`
  hard-code `== 25`, `test_quality_json_dossier.py:63-69` pins skill versions,
  `tests/arv2/test_account_research_port.py:26-27` requires the launch `recipe_version` to equal the
  newest `recipe-v*.json`, `tests/agents/test_skill_references.py:42-80` checks rendered references,
  DB tests assert `input_refs["quality_recipe_version"] == CURRENT_RECIPE_VERSION`
  (`test_quality_driver_db.py:155`, `test_quality_reconciliation_db.py:569`); (8) a model change is an
  env change, never a profile mint (`AGENTS.md:54`).

### 5.7 Version history (git log, `RQ/recipe-v*.json` + `launch-v4-r*.json`)

24 recipe versions (v2–v25) were added between 2026-09-23 and 2026-10-04 — 21 of them r5–r25.
Cadence before r25: 09-23 ×5, 09-24 ×6, 09-25 ×3, 09-26 ×4, 09-27 ×4, 09-28 ×1, then a 6-day gap.

| Rev | Commit | Date | Subject | Resource / tool change |
|---|---|---|---|---|
| r2 | 69b4c213e | 09-23 | integrate governed workers and contextual committee reconciliation | first set: account/claims/narrative v2, governed-evidence v1; submit/correct_research_claim, search_evidence@1, record_research_disposition@1, acquire@1, nominate@1 |
| r3 | 6541ecc6d | 09-23 | publish contextual evidence-backed narrative pages | +publish_research_page@1, read_research_page_inputs@1, submit_value_narrative@1 |
| r4 | 82eb90faf | 09-23 | qualify media and hiring evidence with measured coverage | +submit_transcript_claim@1 |
| r5 | 2ae21f6e2 | 09-23 | close privacy and independent contact lifecycle gaps | +nominate_web_committee_candidate@1 |
| r6 | 251ad3e82 | 09-23 | Defer research verification and keep all findings visible | governed-evidence v2; +record_research_finding@1, nominate@2, publish@2; − submit/correct/transcript/value tools |
| r7 | b587f83ea | 09-24 | Add account Exa briefing skill and targeted additional queries | +account-dossier v1; +provider-requests/account-deep/v1 |
| r8 | a854cbdb5 | 09-24 | Teach account research to review Exa sources alongside dossiers | account-dossier v2 |
| r9 | c81df3d23 | 09-24 | Add account-authored person research delegation briefs | +person-research-briefing v1; +v9-person profile; nominate@3 |
| r10 | 9b5c565da | 09-24 | Include person charter coverage in delegation briefs | briefing v2 |
| r11 | 138c5fb29 | 09-24 | Port discovery-first person research into governed Deep Agent | v11-person; +person-depth-charter v1, person-dossier v1, person-deep/v1 |
| r12 | 8ec4819ae | 09-24 | Port discovery-first account research and default new launches to v4 | account v12, prompt v10; account-dossier v3 |
| r13 | b80fed6c1 | 09-25 | Preserve account-agent dossiers before claim processing | account-dossier v4 |
| r14 | bedafc72d | 09-25 | Make research evidence navigable and preserve native compaction history | account-dossier v5, governed-evidence v3, briefing v3; search_evidence@2, finding@2, disposition@2 |
| r15 | edc62942c | 09-25 | Assign research finding write identities from canonical content | record_research_finding@3 |
| r16 | 2db722822 | 09-26 | Integrate researcher-authored JSON dossiers into account and person jobs | +claim-ready-{account,person} v1; governed-evidence v4; +save_dossier_section, validate_dossier, finish_dossier |
| r17 | c5782b32b | 09-26 | Support atomic revisions of imported research dossiers | claim-ready v2; +begin/discard_dossier_revision |
| r18 | 3cd1b7bcf | 09-26 | Release person research after committed account dossier import | recipe file only; behaviour gated in code (`quality_person_release.py:16`) |
| r19 | d1f33a42d | 09-26 | Spill oversized research receipts into readable revision 19 workspaces | all four profiles v19 (`reads` prefix) |
| r20 | 408cfd3df | 09-27 | Let account and person researchers author their own display narratives | +account/person-research-narrative v1; +read_narrative_inputs, write_research_narrative |
| r21 | c044a94b4 | 09-27 | Resolve research skill references from pinned profiles | `{{skills.*.path}}` introduced; account-dossier v8; person-dossier v4 |
| r22 | 37136cae3 | 09-27 | Introduce role and purpose in research prompt openings | v22 profiles and prompts |
| r23 | fc44754a7 | 09-27 | Promote approved account and person narrative skills for new research runs | narrative skills v2; +research-narrative-editorial v1 |
| r24 | b5f0239a1 | 09-28 | Integrate revision 24 dossier updates and reciprocal conflict imports | account-dossier v9, claim-ready v3, person-dossier v5, briefing v4; +update_dossier_findings@1; − record_research_disposition@2 |
| r25 | 7559c9bca | 10-04 | Separate page writer for research pages (recipe 25) | v25 profiles/prompts; − 3 narrative skills; − 4 page/narrative tools; +`page_writer*.py` and 4 unpinned guides; +`CLUE_ARV2_PAGE_WRITER_TIMEOUT_S=900.0` (`.env.example:279`) |

## §6 Settings and flags that govern the lane

Loaders: `libs/clue-config/clue_config/settings.py` (`class Settings` `:138`, prefix `CLUE_` `:142`,
reads `.env` `:143`, frozen `:146`); secrets in `libs/clue-config/clue_config/secrets.py` (`:59`).
Some knobs are read straight from `os.environ` (marked). Process: **W** fleet worker
(`clue_api.fleet_main`), **A** platform API (`clue_api.projections_main`), **B** both. Scope: **dep** =
deployment-wide, **role** = per agent role, **pool** = set per compose service.

**Lane enable, catalog, recipe, limits**

| env | `.env.example` | Settings field = default | scope / proc | governs |
|---|---|---|---|---|
| `CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED` | `true` (`:153`) | `arv2_account_research_enabled = True` (`:398`) | dep / B | off → no handler and no launch service (`projections_main.py:164`; `fleet_main.py:769,980-982,1342`; `account_research_driver.py:2436`) |
| `CLUE_ARV2_RESEARCH_CATALOG_VERSION` | `v4` (`:151`) | `Literal[v1..v4] = "v4"` (`:397`) | dep / B | the `profile_ref` new launches pin; v4 = committee_discovery + media_research + research_quality (`account_research_catalog.py:53-58`) |
| (quality recipe default) | none | `CURRENT_RECIPE_VERSION = 25` (`arv2/quality_catalog.py:14`) | code | pinned per job in `input_refs.quality_recipe_version` |
| `CLUE_ARV2_QUALITY_RECONCILE_INTERVAL_S` | `10.0` (`:152`) | `= 10.0` (`:400`) | dep / W | sweep cadence |
| `CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS` | `350` (`:181`) | `= 350`, ≤ 500 (`:447`) | dep / W | rounds per account **and** person job |
| `CLUE_ARV2_ACCOUNT_MAX_TOOL_CALLS_PER_ROUND` | `50` (`:183`) | `= 50` (`:450`) | dep / W | allowance tool calls = rounds × this |
| `CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S` | `0` (`:186`) | `= 0` (`:454`) | dep / W | 0 = no wall clock; else min(remaining, profile `turn_timeout_s`, this) |
| `CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS` | `3` (`:217`) | `= 3` (`:497`) | dep / W | the only `CLUE_ARV2_PERSON_*` setting |
| `CLUE_AGENT_LONG_TURN_ALERT_S` | `3600` (`:212`) | `= 3600.0` (`:490`) | dep / B | warn-only |
| `CLUE_ARV2_DISCOVERY_ENABLED` (+ `_ANSWER_MODEL`, `_POLL_INTERVAL_S`, `_WALL_S`, `_VERIFY_CONCURRENCY`, `_MAX_TOPUPS`) | `false`, `exa`, 15, 1800, 4, 3 (`:221-233`) | `:502-520` | dep / W | the R4 discovery lane |

**Parallelism and fleet**

| env | `.env.example` | Settings = default | scope / proc | governs |
|---|---|---|---|---|
| `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS` | `4` (`:190`) | `= 4` (`:456`) | dep / W | `self._jobs` semaphore and `max_in_flight` (`driver:505,507-512`; `work_worker.py:116-129,282-287,312-316`) |
| `CLUE_FLEET_WORKER_CONCURRENCY` | `3` (`:334`) | `= 1` (`:249`) | pool / W | drain slots per process (`fleet_wiring.py:533`); VM: chat 10, design 8, batch 10 |
| `CLUE_FLEET_WORKER_KINDS` | blank (`:338`) | `""` (`:255`) | pool / W | filters composed handlers (`fleet_wiring.py:365-380,516-523`); `check_prod_env.py:191-196` refuses it in the shared env file |
| `CLUE_FLEET_THREAD_POOL_SIZE` | `128` (`:762`) | `= 128`, ≥ 8 (`:270`) | dep / W only | `install_thread_pool` (`fleet_main.py:848`; `clue_fleet/runner.py:29-40`) |
| `CLUE_FLEET_POLL_INTERVAL_S` | `1.0` (`:753`) | `= 1.0` (`:242`) | dep / W | idle sleep |
| `CLUE_FLEET_LEASE_TTL_S` | `30.0` (`:755`) | `= 30.0` (`:258`) | dep / W | work-lease TTL (`clue_fleet/lease.py:23`) |
| `CLUE_FLEET_HEARTBEAT_INTERVAL_S` | `10.0` (`:757`) | `= 10.0` (`:261`) | dep / W | renew cadence; 2 × heartbeat < TTL enforced (`work_worker.py:165-170`) |
| `CLUE_FLEET_TASK_STALE_AFTER_S` | `60.0` (`:759`) | `= 60.0` (`:265`) | dep / W | a claimed row older than this can be re-claimed (`queue.py:51,266`) |
| (worker-wide DB lock) | none | `self._db_lock = asyncio.Lock()` (`driver:504`) | code / W | one per handler instance = one per worker process |

**Provider concurrency and providers**

| env | `.env.example` | source | scope | governs |
|---|---|---|---|---|
| `CLUE_ARV2_ACCOUNT_PROVIDER_CONCURRENCY` | `4` (`:192`) | `= 4` (`:459`) | per job per provider / W | `ToolRuntime._semaphore` (`account_research_tools.py:567-575`); `ai_ark` and `media` are always 1 (`_SERIAL_PROVIDERS` `:213-216`) |
| `CLUE_ARV2_AI_ARK_MIN_GAP_S` | `10.5` (`:156`) | `= 10.5` (`:403`) | dep / W | two layers: a cross-process `pg_try_advisory_xact_lock` keyed on the sha256 of the AI Ark key, held through the hop then slept `min_gap_s` (`account_research_tools.py:466-492`; `driver:2363-2367`), and the client's own in-process gap (`driver:2371`; `ai_ark_client.py:694-711,1015-1018`) |
| AI Ark halt rule | — | 402/403 or any ≥ 400 whose body says "credit" → `CREDIT_HALT_REASON` (`ai_ark_client.py:330-342,68`); latched for the job (`account_research_tools.py:521-529,447-449`); request timeout fixed 120 s (`ai_ark_client.py:58`) | code | no paid-tier setting exists; 10.5 s is "proof-of-concept pacing until the paid tier's rate is confirmed" (`.env.example:154-155`) |
| `CLUE_AI_ARK_API_KEY`, `CLUE_EXA_API_KEY`, `CLUE_GEMINI_API_KEY`, `CLUE_OPENROUTER_API_KEY` | blank (`:69,62,71`) | Secrets | dep / W | all four required or no handler (`driver:2437-2459`) |
| Exa timeouts (no env) | — | search 180 s (`exa_client.py:964`), contents 240 (`:1009`), answer 120 (`:1047`), deep_reasoning 1200 with `DEEP_REASONING_MAX_ATTEMPTS = 2` (`:1095,:79`), agent_run 900 (`:1152`) | code | deep calls at `account_research_tools.py:2024,2073` |
| `CLUE_EXA_WEBSETS_*`, `CLUE_EXA_ACCOUNT_DEEP_*` | (`:64-66,82,938,775-777`) | code defaults False (`:281-304`) | dep | none read under `clue_api/arv2/`; the ACCOUNT_DEEP knobs belong to the quarantined entity-research lane |
| `CLUE_SCRAPE_BACKEND` / `CLUE_STAGE0_PAGE_FETCHER` | `scrapling` (`:110,109`) | `"firecrawl"` (`:993,1068`) | dep | not referenced in `clue_api/arv2/` |

**Models and effort per role** (`.env.example:366-444`, the "Agent model configuration" block)

| env | `.env.example` | read by | scope | governs |
|---|---|---|---|---|
| `ARV2_ACCOUNT_AGENT_MODEL` | `x-ai/grok-4.6` (`:414`) | `os.environ` `driver:129,2445` | role / W | **required**; passed to the quality runner, replacing the profile's model (`driver:1185-1190,1405`; `quality_research_wiring.py:785-793`) |
| `ARV2_ACCOUNT_AGENT_MODEL_EFFORT` | `medium` (`:415`) | gateway role `arv2_account` (`driver:277,1239`) | role / W | legacy R2 build only; not read on the v4 path |
| `ARV2_PERSON_AGENT_MODEL` / `_EFFORT` | `x-ai/grok-4.6` / `medium` (`:418-419`) | `driver:135,2481`; role `arv2_person` | role / W | optional; blank → account model + `arv2.person_model_fallback` |
| `ACCOUNT_RESEARCH_AGENT_MODEL` / `_EFFORT` | `x-ai/grok-4.6` / `medium` (`:405-406`) | registry `registry.py:395,634`; effort `agent_model.py:1229` | role | the profile role resolved by the v4 runtime; its model is overridden, its **effort applies** (`runtime.py:615`) |
| `RESEARCH_CLAIMS_AGENT_MODEL` / `_EFFORT` | (`:408-409`) | registry | role | specialist roles active only for recipe < 20 |
| `RESEARCH_NARRATIVE_AGENT_MODEL` / `_EFFORT` | (`:410-411`) | `page_writer_runtime.py:98-106` | role | the page writer; falls back to `CLUE_ARV2_DISPLAY_MODEL` |
| `RESEARCH_AGENT_MODEL` / `_EFFORT` | `medium` (`:399-400`) | `AgentRole.RESEARCH` (`contracts.py:222`) | role | the Head-of-ABM research specialist, not the job path |
| `HEAD_OF_ABM_AGENT_MODEL` / `_EFFORT` | grok-4.6 / blank (`:397-398`) | registry | role | the chat agent |
| `CLUE_ARV2_DISPLAY_MODEL` | `x-ai/grok-4.6` (`:273`) | `arv2_display_model` (`:584`); `display/page.py:132` | dep / B | reconciliation + legacy Luna section writer; page-writer fallback |
| `CLUE_ARV2_STRUCTURING_MODEL` | `openai/gpt-5-mini` (`:158`) | `:406`; `driver:2406` | dep / W | the R2 structuring client (legacy path) |
| `CLUE_AGENT_MODEL_TIMEOUT_S` | `60` (`:378`) | `os.environ` `registry.py:396-398` | dep | overrides every profile's `timeout_s` |
| `CLUE_GATEWAY_TIMEOUT_S` | `60` (`:364`) | `= 30.0` (`:166`) | dep | the ceiling; R2 model timeout (`driver:1235`) |
| `CLUE_AGENT_FALLBACK_MODELS` | `x-ai/grok-4.7,meta/muse-spark-1.3` (`:383`) | `:688-691`; `gateway.py:182` | dep | per-call fallback chain (every call starts at the primary) |
| `CLUE_AGENT_FIRST_TOKEN_TIMEOUT_S` | `120` (`:391`) | `= 120.0` (`:707`) | dep | first-chunk deadline before falling back |
| `CLUE_AGENT_MODEL_CONTEXT_WINDOWS` | grok-4.6/4.7 = 500000, muse = 1048576 (`:388`) | `:698-702` | dep | window registry |
| `CLUE_AGENT_CONTEXT_WINDOW_TOKENS` | blank (`:201`) | `None` (`:476`) | dep | overrides every window |
| `LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S` | `300` (`:444`) | langchain | dep | stall timeout between chunks |

Max output tokens: legacy R2 `_MODEL_MAX_OUTPUT_TOKENS = 8192` (`driver:275`); v4 profiles 16384.

**Compaction** (governed deep agents, v4 included): `CLUE_AGENT_COMPACT_TRIGGER_FRACTION=0.90`,
`_KEEP_FRACTION=0.10`, `_TRIGGER_TOKENS=170000`, `_KEEP_MESSAGES=6` (`.env.example:202-205`;
`settings.py:477-480`); `compaction_for(model_id)` loads settings on each call and resolves the window
override → registry → OpenRouter catalogue (`clue_api/agent_compaction.py:16-28`), read in a thread
(`runtime.py:619-623`), wired at `quality_research_wiring.py:1090`; the middleware is
`ClueSummarizationMiddleware` (`clue_agents/compaction.py:63-64`). With a 500k window the trigger is
450k tokens, which no run reaches (audit §1).

**Media**: `CLUE_GEMINI_API_KEY` required for composition (`driver:2441`); `CLUE_DEEPGRAM_API_KEY`
optional (`driver:2468`), `CLUE_ARV2_DEEPGRAM_LANGUAGE=en`, `_USD_PER_MINUTE 0.0043 / _MULTI_ 0.0052`
(`.env.example:76-80`); `CLUE_ARV2_MEDIA_SHORT_MODEL=google/gemini-3.5-flash-lite`,
`_VIDEO_MODEL=gemini-3.5-flash-lite`, `_TRANSCRIBE_MODEL=gemini-3.5-transcribe`,
`CLUE_ARV2_EMBEDDING_MODEL=google/gemini-embedding-2` (`:160-167`); `CLUE_ARV2_MEDIA_SECONDS_CEILING=9000`
→ `MediaBudget` per job (`driver:1258,2345`); `_SHORT_MAX_SECONDS=600`;
`CLUE_ARV2_ACCOUNT_MEDIA_MAX_ENCLOSURE_MB=200` (`account_research_tools.py:1750`; `MAX_MEDIA_BYTES`
`media_resolution.py:34`); `CLUE_ARV2_RAW_ROOT` (image sets `/var/lib/clue/arv2-raw`,
`docker/backend/Dockerfile:59`). Recording shells out to `yt_dlp` (deno/node), `ffprobe`
(`media_recording.py:100-110`) and `ffmpeg` (`:126-140`).

**Claim write**: `CLUE_CLAIM_WRITE_LENIENT=true` (`:260`; `LenientClaimWriter` `driver:2486`);
`CLUE_EVIDENCE_VERBATIM_CHECK=off` (`:262`; `display/page.py:288`, `display/floor.py:183`);
`CLUE_UNEVIDENCED_ROW_PURGE_ENABLED=false` (`:265`; `account_research_tools.py:742`,
`quality_research_wiring.py:531,1230`); `CLUE_SENSITIVITY_FLOOR_ENABLED=true` (`:269`) and
`CLUE_INTERVIEW_ENTAILMENT_CHECK=off` (`:267`) have **no production consumer** (only `settings.py` and
`tests/arv2/test_settings.py`); `CLUE_VERIFICATION_ENABLED=false` (`:459`, code default True `:176`).

**Display**: `CLUE_ARV2_DISPLAY_GENERATE_ON_READ=true` (`:283`; A `display_pages.py:311,864`; W: the
`arv2_display_page` handler needs it + an OpenRouter key, `display/fleet_handler.py:213-226`);
`CLUE_ARV2_DISPLAY_TIMEOUT_S=240`, `_MAX_PARALLEL=30` (`display/page.py:133,417`);
`CLUE_ARV2_PAGE_WRITER_TIMEOUT_S=900.0` (`:279`; `page_writer_runtime.py:137`);
`CLUE_FRONTEND_CONTACT_EMAIL_LOOKUP_ENABLED=true`, `_POLL_AFTER_S=5` (`:87-88`).

**Storage / DB**: `CLUE_STORAGE_BACKEND=fs` locally, S3/R2 in production (`:34-45`;
`CLUE_STORAGE_S3_MAX_POOL_CONNECTIONS=50`, `clue_storage/factory.py:41`); `CLUE_DB_POOL_SIZE=5`,
`_MAX_OVERFLOW=10`, `_POOL_TIMEOUT_S=30` (`os.environ`, `clue_db/engine.py:60-62,104-106`);
`CLUE_DB_CRITICAL_SECTION_LOG_MS=500` (`os.environ`, `clue_obs/critical_section.py:22-34`).

**Observability**: `CLUE_LANGFUSE_ENABLED=true`, `_HOST`, `_ENVIRONMENT=lane-san-salvador`
(`:321-325`; `settings.py:236-238`), installed in W (`fleet_main.py:857-859`, service
`clue-worker-fleet`) and A (`projections_main.py:95`); Sentry off by default (`:313-317`;
`fleet_main.py:856`); `check_prod_env.py:63,124-126` requires both environment labels to be
`production`; `CLUE_LOG_MODE`/`CLUE_LOG_FORMAT` read by `clue_obs/config.py:57-70`, absent from
`.env.example`.

**The "must stay off" list — current `.env.example` values**: `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=false`
(`:570`; the `integration_pilot` overlay forces it True, `settings.py:127`); `CLUE_SUMBLE_API_KEY` blank
(`:92`) but `CLUE_SUMBLE_DISCOVERY_GAP_ENRICHMENT_ENABLED=true` and
`CLUE_SUMBLE_ACCOUNT_GAP_ENRICHMENT_ENABLED=true` (`:94-95`, code default False; `check_prod_env.py:127-137`
flags "on without key"; the runbook says production sets them false, `docs/deploy/runbook.md:125-128`);
`CLUE_MEMORY_ENABLED=true` (`:136`, code True `:351`); `CLUE_SELF_SERVE_PROVISIONING_ENABLED=true`
(`:138`; comment says default-off, code True `:922`); `CLUE_VERIFICATION_ENABLED=false` (`:459`);
`CLUE_BUDGET_CONTROLS_ENABLED=false` (`:685`, code True `:193`). Stale comments: `:933-936` claims
VERIFICATION/BUDGET are "`=true` above" (they are `=false`); the fleet header `:328-330` says the
other `CLUE_FLEET_*` knobs are undocumented (they are, `:751-764`). `CLUE_SANDBOX_ENABLED` does not
touch the research job path (no reference under `clue_api/arv2/`; sandbox workspaces go only to
`build_agent_platform_components`, `fleet_main.py:1185-1192`).

## §7 Fleet and deployment

### 7.1 `deploy/vm/compose.yaml` (worker VM, OVHcloud VPS-4)

- **Env files are not in the repo**: `/srv/clue/env`, `/srv/clue/pgbouncer.env`, `/srv/clue/compose.env`
  are referenced (`compose.yaml:2-3,12,50`) but untracked (`.gitignore:31-33`); Railway variable files
  live in `~/clue-deploy/` "outside the repo" (`docs/deploy/runbook.md:27-30`).
- Shared template `x-worker` (`:9-22`): `image: ${BACKEND_IMAGE}`, `command: ["fleet-worker"]`,
  `env_file: [/srv/clue/env]`, user `1000:1000`, `restart: unless-stopped`, `stop_grace_period: 60s`,
  `depends_on: [pgbouncer]`; mounts docker.sock, `/srv/clue/workspaces`, `/srv/clue/lumen-agent`,
  `/srv/clue/engine-cache`. `x-worker-env` (`:27-37`): `CLUE_DATABASE_URL=postgresql+asyncpg://clue_worker:…@pgbouncer:6432/railway`.

| service | lines | kinds (`CLUE_FLEET_WORKER_KINDS`) | slots (`CLUE_FLEET_WORKER_CONCURRENCY`) |
|---|---|---|---|
| `pgbouncer` | `:47-50` | `edoburu/pgbouncer:v1.23.1-p3`, env_file `/srv/clue/pgbouncer.env` | — |
| `chat` | `:52-57` | `agent_turn` | 10 |
| `design` | `:59-64` | `design_job` | 8 |
| `batch1`, `batch2`, `batch3` | `:66-68` via `x-batch` `:39-44` | `drive_run, account_job, execute_graph, entity_research_job, stage0_recon, official_site_crawl, onboarding_run, arv2_account_research, arv2_discovery, arv2_display_page` | 10 each |
| `ingestion` | `:75-88` | `ingestion-pool` | — |

- No resource limits and no `healthcheck:` keys (`:1-89`); health is `deploy.sh` restart-count
  comparison 45 s after `up` (`deploy/vm/deploy.sh:18-19,77-97`) and `watchdog.sh` (memory < 85 %,
  disk < 80 %, 7 services running, every 5 min; `systemd/clue-watchdog.timer:5`).
- Fleet-wide research capacity is documented as 3 batch × `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS` 4 =
  12 research jobs (`runbook.md:236-237`; `.env.example:187-189`), while each batch process has 10
  claim slots — the 2026-10-03 "claim-without-capacity" defect
  (`_memory/2026-10-03-first-production-research-quality-review.md`), closed by `max_in_flight`.
- PgBouncer (documented only, `runbook.md:213-225`): `POOL_MODE=transaction`,
  `MAX_PREPARED_STATEMENTS=200`, `DEFAULT_POOL_SIZE=20`, `MAX_CLIENT_CONN=200`,
  `STATS_USERS=clue_worker`, `AUTH_TYPE=scram-sha-256`, `SERVER_TLS_SSLMODE=require`,
  `LISTEN_PORT=6432`; raise 20 → 40 only after measuring (`runbook.md:241-245`). The ingestion
  controller bypasses PgBouncer (`compose.yaml:4-6,70-73`).

### 7.2 `docker/backend/Dockerfile`

Stages: `rust:1-bookworm` helper (`:7-24`), `node:24-bookworm-slim` editor (`:27-33`), runtime
`python:3.12-slim-bookworm` (`:36`) with uv 0.10, node, docker CLI 27 copied in (`:37-39`); runtime apt
installs only `ca-certificates fontconfig libfontconfig1 libstdc++6 libpq5` (`:43-46`);
`uv sync --frozen --no-dev --group deploy --all-packages` (`:50`); `playwright install --with-deps
chromium` (`:51`); `CLUE_ARV2_RAW_ROOT=/var/lib/clue/arv2-raw` (`:59`); `USER 1000:1000` (`:63`);
`ENTRYPOINT ["clue"]` (`:64`). **ffmpeg/ffprobe are not installed** by any line (whether Playwright's
`--with-deps` pulls one cannot be determined from the repo); deno is absent, node present. This matches
the production `FileNotFoundError: ffprobe` at `arv2/media_recording.py:103`
(`_memory/2026-10-06-account-research-cost-audit.md`, "Deeper audit"). Entrypoint
(`docker/backend/entrypoint.sh:9-25`): `platform-api` → uvicorn `clue_api.projections_main:app`
(`${PORT:-8020}`), `design-api` (`8010`), `fleet-worker` → `python -m clue_api.fleet_main`,
`ingestion-pool`, `migrate` (`alembic upgrade head`), `shell`.

### 7.3 Fleet worker internals

- Boot (`fleet_main.py:843-1458`): `load_settings` → `install_thread_pool` (`:848`) → preflight →
  tracing/Sentry/Langfuse (`:855-859`) → db/redis → handlers (`:1337-1386`) →
  `build_multi_work_worker` (`fleet_wiring.py:383-534`; `poll_interval, lease_ttl, heartbeat_interval,
  task_stale_after, concurrency` at `:524-534`).
- Kinds: `FleetTaskKind` has `ARV2_ACCOUNT_RESEARCH`, `ARV2_DISCOVERY`, `ARV2_DISPLAY_PAGE`
  (`libs/clue-fleet/clue_fleet/enums.py:59-79`). There is **no** person or continuation kind: person
  jobs and quality continuations share `arv2_account_research` (`driver:509-511,518-519,985-990`).
- Priorities (ascending): onboarding_run −150 (`onboarding_routes.py:45`), arv2_account_research
  −100, arv2_discovery −90, arv2_display_page −80, agent_turn 0, design_job 0. The claim filters by
  kind and orders by `priority, enqueue_seq` within it (`clue_fleet/queue.py:262,278`); workers
  rotate across kinds round-robin (`work_worker.py:299-336`).
- Claim loop: N slots run `_drain_loop` → `drain_once`, sleeping `poll_interval` when idle
  (`work_worker.py:235-265`); claim SQL = MATERIALIZED CTE `ORDER BY priority, enqueue_seq LIMIT 1 FOR
  UPDATE SKIP LOCKED` then `UPDATE … attempts = attempts + 1` (`queue.py:256-291`), taking `queued`
  rows with `available_at <= now()` **or** `claimed` rows older than `task_stale_after` (60 s) —
  the stale reclaim (`:265-266`). `InFlightLimited.max_in_flight` is reserved before the claim and
  released in `finally` (`work_worker.py:282-290,312-335`).
- Leases: `INSERT … ON CONFLICT … WHERE expires_at <= now() OR worker_id = :worker_id`, bumping
  `generation` on takeover (`clue_fleet/lease.py:52-74`); heartbeat renews every 10 s and touches the
  task, retries faster on error and sets `lease_lost` near the deadline (`work_worker.py:552-597`);
  on loss the work is cancelled and the task requeued (`:482-497`). `_wait_behind_held_lease`
  (same-process `:387-389` or foreign holder `:436-438`) requeues with delay
  `min(max(waited/2, poll), lease_ttl)` and `uncount_attempt=True` (`:396-425`; `queue.py:321-322`).
- Attempts: no generic ceiling in queue or worker; the driver uses `task_attempt` only for the
  "job row not visible" retry (12 × 5 s, `driver:262-269,1140-1155`); the job row's `attempt` is a
  fence, not a budget.
- Other background loops in the worker: orphan sweep, chat sweep, token sweep, design reaper and
  pruner, agent cleanup, Exa discovery/targeted, external research wake, quality reconcile
  (`fleet_main.py:1387-1432`).

### 7.4 Railway (documented only; variables not in the repo)

`docs/deploy/runbook.md`: **Postgres** `pgvector/pgvector:pg16`, `max_connections=200`, 4 GB
(`:39-84`); **Redis** `redis:7` (`:85-110`); **platform-api** `clue platform-api`, pre-deploy
`clue migrate`, 1 GB, `/healthz`, `api.cluehq.ai` (`:137-140`); **design-api** 1.5 GB, port 8010
(`:141-144`); **page-origin** 256 MB (`:145-146`); **frontend** `apps/frontend/Dockerfile.railway`
(`:147-157`). platform-api/design-api run the CI-built `ghcr.io/clue-hq/clue-backend:production`
image (`:129-136`); `LUMEN_EMBEDDED_FLEET_WORKER` must be 0 on Railway (`check_prod_env.py:139-142`).
The VM runs every pool, PgBouncer and the sandbox (chat 1×10, design 1×8, batch 3×10;
`_memory/2026-10-01-first-deployment.md:10-13`). No `railway.json`/`railway.toml`/Procfile in the repo.
Worker log traces carry `service.name = clue-worker-fleet` and no release tag
(`_memory/2026-10-06-account-research-cost-audit.md`).

### 7.5 `scripts/dev_stack.sh` (local)

Knobs are evaluated at script start, before `.env` is sourced (`:84-94,111,234`): `WORKERS=1`,
`WORKER_CONCURRENCY=1`, ports 3020/8010/8020/8030 (+ page origin 8040); `start_workers` launches
`$WORKERS` × `python -m clue_api.fleet_main` with `CLUE_FLEET_WORKER_CONCURRENCY=$WORKER_CONCURRENCY`
(`:179-186`) and no kind filter. The `.env.example` `DEV_STACK_*` block (`:874-903`) claims to mirror
the script's defaults but differs (3033/8013/8023/8033, 4 × 3); `DEV_STACK.md:43-44` agrees with the
script; the per-lane wrappers (`dev_stack_jerusalem.sh`, `dev_stack_lome.sh`, `dev_stack_melbourne.sh`)
decide the effective values.

## §8 Telemetry: what is recorded where, and what is not

`driver` = `platform/api/clue_api/arv2/account_research_driver.py`; `qrw` =
`platform/api/clue_api/quality_research_wiring.py`.

### 8.1 Langfuse

- Installed by `install_production_langfuse` (`libs/clue-obs/clue_obs/production.py:88-137` →
  `libs/clue-obs/clue_obs/langfuse.py:120-158`), called from the fleet at `fleet_main.py:855-858`
  with service name `clue-worker-fleet`. Environment label = `settings.langfuse_environment`
  (`langfuse.py:145`), default `"lane-san-salvador"` (`settings.py:238`; `.env.example:325`);
  `deploy/check_prod_env.py:62,124-126` insists on `production` only when the variable is present.
- **Release tag: never set.** The client is given `release=settings.release or None`
  (`langfuse.py:146`; `production.py:125`); `settings.release` defaults to `None` (env `CLUE_RELEASE`,
  `settings.py:221-225`; `.env.example:317` blank); `deploy/vm/deploy.sh` puts the git sha only into
  image tags (`:11-12,34,69`); `check_prod_env.py` does not require it.
- Export filter `should_export_span=is_default_export_span` (`langfuse.py:149-153`) keeps only
  `langfuse-sdk` and `gen_ai.*` spans and drops FastAPI, httpx and plain `clue_research` spans
  (`fleet.task`, `traced_step`, `llm.gateway_call`); the "81 raw httpx POST spans" of 2026-10-03
  predate this filter (spec `docs/superpowers/specs/2026-10-03-agent-scoped-tracing-and-one-trace-id-design.md:14-20,35-44`).
  Every exported string is truncated to 8,000 chars with secret/blob masking (`langfuse.py:74,84-114`).
- **Trace identity (since PR #90, merge `1ad82b6be`, 2026-10-03):** each fleet job gets its own
  trace. The enqueue stamps the W3C carrier into the task payload (`platform/fleet/clue_fleet/queue.py:428`);
  the worker's `fleet.task` span starts a **new** trace with a link back to the launcher and
  `launched_by_trace_id` in run context (`work_worker.py:339-370`; `libs/clue-obs/clue_obs/otel/propagation.py:61-73`;
  `langfuse.py:340-342`). The "fleet task inherits the launching turn's trace" statement and the
  100.16 MB 422 error (`_memory/2026-10-03-production-research-slowness.md`) describe behaviour
  before PR #90; whether production ran it on 2026-10-06 is unverified
  (`docs/superpowers/plans/2026-10-06-account-research-v26-cost-and-speed-plan.md:555-556`).
- **Trace name on v4:** `propagate_trace(trace_name=f"{role.replace('_','-')}.turn")` →
  `account-research.turn` for account **and** person jobs (both profiles declare
  `role: account_research`) (`agent_runtime_wiring.py:1465-1476`; `qrw:888`). Fields: `session_id =
  research-quality-<execution>` (`qrw:822`), `user_id` = workspace id, metadata `project_id, turn_id,
  execution_id, profile, actor_id`, tags `("account_research",)` only (`agent_runtime_wiring.py:1475`).
  **No `account:<domain>` tag and no job_id in trace metadata on v4** (the tag exists only on the
  legacy loop, `arv2/account_research_agent.py:430-445`; `tag_entities` is never called from a
  `quality_*` module). `job_id, run_id, workspace_id, account_id` do reach every OTel span as
  attributes (`work_worker.py:71-79,357-360`; `libs/clue-obs/clue_obs/otel/install.py:100-108`).

Observations per step on v4:

| Step | Observation | Cite |
|---|---|---|
| agent tree and model calls | `ClueLangfuseHandler` on the turn's callbacks records agent/chain/tool/generation observations; at model end it writes the gateway cost and the served model when `clue_answering_model` is present | `agent_runtime_wiring.py:1441,1458-1459`; `libs/clue-gateway/clue_gateway/langfuse_handler.py:38-107` |
| governed tool call | `governed.<name>@<version>` (type `tool`, or `retriever` for READ) | `platform/toolbelt/clue_toolbelt/invoker.py:191-214` |
| provider call | `{provider}.{operation}` (generation/embedding/tool) + `provider.http_attempt` (wire time only), `provider.retry_wait`, `provider.halt_latch`, `provider.ceiling`; ledger extras carry the Langfuse ids | `libs/clue-spend/clue_spend/calls.py:246-257,320-327,378-404,561-600,621` |
| Exa deep retry | `exa.thin_response_retry` | `arv2/exa_client.py:1137` |
| media | span `arv2.media.provider_stage`; events `arv2.media.<name>` | `arv2/media_operations.py:252-300`; `arv2/media_telemetry.py:31-37` |
| dossier import | `arv2.dossier.import` | `arv2/dossier_import.py:161` |
| page writer (recipe ≥ 25) | span `research.page_writer`; each model call an `openrouter.chat/completions` generation through `ProviderCaller` | `arv2/page_writer_runtime.py:633-655,109-176` |
| reconciliation (recipes 20–24) | `research.account_reconciliation` | `arv2/quality_reconciliation.py:556` |
| long-turn / wrap-up flags | `flag_trace("agent.long_turn")`, `flag_trace("agent.<stage>")` | `platform/agents/clue_agents/runtime.py:474-483,592-604` |

The page writer runs **after** the runner returns (`driver:1191`), outside the `propagate_trace`
block, so its spans carry no trace name/session/user/tags (they share the `fleet.task` OTel trace);
rewrites run in the continuation task's trace with no `propagate_trace` (`driver:854-906`).
`GovernedAgentChatModel` opens only `traced_step(llm.gateway_call)` OTel spans
(`libs/clue-gateway/clue_gateway/agent_model.py:542,580,618,659`), filtered out of Langfuse. The
"Langfuse was not able to parse the LLM model" warning: the chat model exposes only
`requested_model`/`fallback_model` and `ls_provider` at start (`agent_model.py:503-516`); the model is
patched in at end only when the gateway stamped it (`langfuse_handler.py:101-104`). Legacy v1–v3 for
contrast: trace `arv2.account_research`, session = run_id, metadata job_id/account_id, tags
`("arv2", subject_kind, "account:<domain>")` (`account_research_agent.py:400-475`).

### 8.2 Recorded in the database

| Store | What a row holds | Cite |
|---|---|---|
| `provider_call_ledger` | ledger_id, call_id, ws/project/project_run, `entity_research_job_id`, provider, operation, label, phase, http_status, latency_ms (wire), attempts, estimate_*/cost_usd/credits/media_seconds, over_ceiling, outcome, error_code, provider_request_id, response_artifact_key, extras_json (Langfuse ids, purpose), recorded_at | `libs/clue-spend/clue_spend/ledger.py:59-71`; `sinks.py:153-181`; `arv2/provider_ledger.py:56-114` |
| page-writer ledger rows | label `page-writer-{account|contact}-v1`; extras job_id/workspace_id/purpose; reasoning effort sent but not recorded | `page_writer_runtime.py:133-151` |
| `agent_model_call` (v4 model calls) | turn_id, execution_id, ws, sequence, requested/answering model, status, input/cache_read/cache_creation/output tokens, cost_millicredits, cost_usd, cost_source, langfuse_trace_id/observation_id, latency_ms, error_code, role, started/completed_at — **no reasoning effort, no reasoning-token column** | `agent_turn_wiring.py:688-735`; `platform/agents/clue_agents/turns.py:89-121` |
| model inputs | each call's full input messages as an `agent-model-input+json` artifact | `agent_runtime_wiring.py:163-197` |
| legacy v1–v3 rounds | `provider_call_ledger` operation `agent_completion` | `account_research_agent.py:125-142` |
| tool receipts | `agent_plan_operation` (`agent_execution_wiring.py:550-575`); `agent_tool_result` (operation_id, plan, node, tool_address, result artifact/sha, replayed, reference_count, completed_at; **no duration**; DDL `6628a407e993:176-186`); C5 `execution_node`/`execution_attempt`/`execution_event` (`platform/execution/clue_execution/journal.py:803-830`); `tool_invocation` (`clue_toolbelt/idempotency.py:137-147`); `agent_turn_event` (`agent_turn_wiring.py:149-160`) | as listed |
| `arv2_research_operation` | operation identity, state, owner_token, lease_until, ledger_id, artifact_key, error_code, timestamps | `0ab01fe27c1e:39-58`; `arv2/research_operations.py:57-90` |
| `arv2_research_job` counters | `model_rounds, tool_calls, cost_usd, credits, media_seconds` written **only** by `finish_job` at settle (`driver:1869-1880` v4; `:1741-1752` legacy; contain `:1064-1076`) — zero while running | `account_research_store.py:339-384` |
| live counters (v4) | `arv2_quality_allowance.model_calls/tool_calls` incremented per reservation, `runtime_used_ms` | `arv2/quality_execution.py:152-203,307-324` |
| stage stamps | `set_job_stage`: `deep_research` on claim (`driver:1177`); committee/member_research legacy only (`:1757-1763`) | |
| `quality_meter.usage` | known USD = ledger `phase='result'` rows for the job + `agent_model_call` via `arv2_quality_execution`; credits; media seconds; unpriced provider/model call counts; model/tool calls and runtime from the allowance; `receipt()` adds `cost_complete` | `arv2/quality_meter.py:13-75` |
| `media_telemetry` | no DB writes; logs + Langfuse events `arv2.media.*` and `tool_completed` | `arv2/media_telemetry.py:16-72` |

### 8.3 Structured log events the lane emits

Driver (`driver`): `arv2.account_invalid_payload` :524 · `arv2.account_work_id_mismatch` :538 ·
`arv2.account_job_contained_failure` :560 · `arv2.person_model_fallback` :485 ·
`arv2.quality.reconciliation_failed` :700 · `arv2.reconciliation.storage_retry` :816 ·
`arv2.reconciliation.failed` :824 · `arv2.page_writer.rewrite_failed` :892 ·
`arv2.person_research.released` :973 · `arv2.account_suspend_superseded` :1031 ·
`arv2.account_suspend_failed` :1034 · `arv2.account_job_superseded` :1041 ·
`arv2.account_contain_failed` :1081 · `arv2.account_job_not_claimable` :1137 ·
`arv2.account_job_row_not_visible` :1142 · `arv2.account_job_row_missing` :1153 ·
`arv2.person_seed_unavailable` :1229 · `arv2.account_persona_unreadable` :1635 ·
`arv2.account_persona_missing` :1640 · `arv2.account_job_finished` :1786 ·
`arv2.page_writer_not_composed` :1816 · `arv2.page_writer_failed` :1829 ·
`arv2.quality.job_settled` :1950 · `arv2.committee_step_failed` :1999 ·
`arv2.committee_jobs_not_enqueued` :2017 · `arv2.committee_jobs_enqueue_failed` :2038 ·
`arv2.display_page_not_enqueued` :2060 · `arv2.display_page_enqueue_failed` :2091 ·
`arv2.account_handler_not_composed` :2450.

Other v4 modules: `arv2.quality.unit_finished` (`qrw:1122`); `arv2.quality.allowance_exhausted` /
`activity_reserved` / `runtime_started` / `runtime_settled` (`quality_execution.py:194,220,317,335`);
`arv2.quality.generation_created` / `generation_signalled` / `generation_reconciled`
(`quality_generation.py:110,259,488`); `arv2.quality.page_published` (`quality_pages.py:407`);
`arv2.quality.finding_recorded` (`quality_findings.py:84`); `arv2.quality.candidate_nominated`
(`quality_committee_tool.py:224`); `arv2.quality.dossier_saved` (`quality_dossier.py:236`);
`arv2.context_pinned` (`quality_context.py:515`); `arv2.evidence_recorded` /
`evidence_grant_revoked` / `evidence_disposition` (`quality_evidence.py:294,382,762`);
`arv2.dossier.import_started` / `finding_imported` / `finding_import_failed` / `import_completed`
(`dossier_import.py:162,357,377,385`); `arv2.dossier.snapshot_saved` (`quality_json_dossier.py:142`);
`arv2.dossier.revision_not_applied` / `revision_applied` (`dossier_revision.py:175,188`);
`arv2.page_writer.published` (`page_writer_runtime.py:657`); `arv2.account.person_research_ready`
(`quality_person_release.py:59`); `arv2.reconciliation.completed` (`quality_reconciliation.py:731`);
`arv2.provider_pacing_acquired` with `wait_ms` (`account_research_tools.py:482`);
`arv2.claim_write_failed` :797, `arv2.stage_stamp_failed` :858, `arv2.verify_links_fetch_failed`
:2455, `arv2.account_tool_failed` :2771 (`account_research_tools.py`);
`arv2.account_research_launched` / `enqueue_failed` / `enqueued`, `arv2.person_research_launched`
(`account_research_launch.py:393,496,503,979`); `arv2.media.*` (`media_retrieval.py:138,233`;
`media_tools.py:258`; `media_operations.py:109,142,201,263,286,297`; `media_telemetry.py:59`);
`arv2.quality.continuations_offered` / `continuation_sweep_failed` (`fleet_main.py:807,809`).

Shared seams: `db.critical_section` (`libs/clue-obs/clue_obs/critical_section.py:38-47`; threshold
`CLUE_DB_CRITICAL_SECTION_LOG_MS` default 500 ms `:22-35`) at `research_artifacts.persist_body`
(`quality_research_artifacts.py:43`), `arv2.evidence.publish` (`quality_evidence.py:248`),
`arv2.dossier.import` (`dossier_import.py:453`); `toolbelt.<tool>_started/_completed/_failed` with
`duration_ms` (`clue_toolbelt/runner.py:139-150`; `clue_obs/spans.py:37-67`; refusals at warning);
`model_call_usage` with prompt/completion/cached tokens, cost and duration
(`libs/clue-gateway/clue_gateway/tracing.py:142-175`; emitted `agent_model.py:561,599,641,682`);
`provider.attempt.started/finished` (`calls.py:575,591,599`); `worker.lease_held_requeue` at **DEBUG**
(`work_worker.py:415-425`; root logger INFO, `clue_obs/config.py:136-139`); `worker.work_error`
(`work_worker.py:499-506`); `agent.long_turn` / `agent.<stage>` (`runtime.py:474,592`).

### 8.4 Metrics and Sentry

- OTLP metrics exporter `platform/api/clue_api/production_metrics.py:19-52`; defined metrics
  `research.claims.*`, `research.verification.*`, `research.cost.*`, `research.phase.progress`
  (`libs/clue-obs/clue_obs/otel/metrics.py:30-41`) are used by the old lanes and C7 only. **No metric
  calls exist in `clue_api/arv2/` or `qrw`.** The only counter the v4 harness touches is
  `agent.context.tool.outcomes` (address, outcome, replayed; counts, no durations;
  `context_observability.py:24-28,75-90`; `agent_execution_wiring.py:1773,1792`).
- Sentry: installed only with `CLUE_SENTRY_ENABLED` (default False, `settings.py:223`) and a DSN
  (`production.py:64-85`); `traces_sample_rate=0.0`, PII off (`libs/clue-obs/clue_obs/sentry.py:92-101`);
  `before_send` attaches run-context tags, the OTel trace id and a Langfuse URL (`:44-73`). Reporting
  paths: `capture(exc)` on `worker.work_error` (`work_worker.py:499-506`) and quality sweep failures
  (`fleet_main.py:808-810`); long-turn warnings (`runtime.py:599-604`). The ARV2 driver contains every
  exception (`driver:558-571`), so its failures reach Sentry only through error-level log lines.

### 8.5 What is NOT recorded (evidence of absence)

1. **Wait time on `_db_lock`** — created `driver:504`, acquired at `:1016-1019`; nothing measures the
   wait; `critical_section` times only the code inside its block (`critical_section.py:38-47`).
   Contrast: the AI Ark advisory-lock wait *is* logged (`account_research_tools.py:478-487`).
2. **Code version / release / commit sha** — none in traces (release unset), in the OTel resource
   (`service.name` only, `install.py:217`), in log processors, or in job rows (`a3602967bb73:116-143`
   has no version column; the finalization stores only `profile_ref` and `manifest_sha256`,
   `driver:1857-1858`).
3. **Build or image a job ran under** — the image sha exists only in `CLUE_SANDBOX_IMAGE` /
   `BACKEND_IMAGE` (`deploy.sh:34,69`); no telemetry or row reads it.
4. **Extraction sub-calls** — no extractor exists on v4; `arv2/quality_extract.py` is absent (proposed
   in the v26 plan item 23); the gpt-5-mini `StructuringClient` is unreachable on v4 (§9).
5. **Time a tool spends after the provider answered** — `_perform_hop` holds the semaphore through
   `_drain` (`account_research_tools.py:500,548-565`); `_drain`/`index_acquisition` (`:596-688`) and
   `recover_acquisitions` (`quality_acquisition.py:74+`) have no timer and no log;
   `provider.http_attempt` and ledger `latency_ms` cover wire time only (`calls.py:420-425,561-600`);
   only the tool's total time is visible (`governed.*` span; `toolbelt.*_completed duration_ms`);
   `arv2.evidence.publish` logs only when ≥ 500 ms.
6. **Per-section page-writer timings** — there are no per-section calls: one call writes Overview +
   Insights with at most one repair (`page_writer.py:200-237,300-327`); recorded are per-call ledger
   latency, one `research.page_writer` span and `arv2.page_writer.published` (pages/blocks/attempts,
   no duration; `page_writer_runtime.py:656-663`).
7. **Reasoning effort** — in no table (`agent_model_call` columns; page-writer extras
   `page_writer_runtime.py:147-151`).
8. **Live job counters on the job row** (§8.2).
9. **Post-settle rewrite spend on the job row** — `rewrite_account_pages` bills the account job id on
   the ledger (`page_writer_runtime.py:159-169,667-729`) but `_rewrite_account` never calls
   `finish_job` again (`driver:854-906`), so `arv2_research_job.cost_usd` excludes it.
10. **v4 trace-level `account:<domain>` tag and job_id metadata** (§8.1).

## §9 Dead, quarantined or superseded code adjacent to the lane

### 9.1 How the catalog version and recipe select a path

The launch writes `profile_ref = agent-profile:arv2-{account|person}:{settings.arv2_research_catalog_version}`
(`arv2/account_research_launch.py:336,388,860,919`). Capability map (`arv2/account_research_catalog.py:53-58`):
v1 none · v2 `committee_discovery` · v3 + `media_research` · v4 + `research_quality`; legacy rows
with no profile resolve to v1 (`:84-95`). What each `CLUE_ARV2_RESEARCH_CATALOG_VERSION` value
selects: **v1** the legacy R2 LangGraph loop (`driver:1233-1255`; catalog
`platform/agents/catalog/entity-research/arv2-{account,person}/v1`; legacy `_settle` runs the
committee step from the finalization's candidates `driver:1960-1990` and offers Luna display pages
`:1784`); **v2** v1 + persona pin at launch (`launch.py:341-353`), person seed (`driver:1193-1231`),
operation authority (`account_research_tools.py:520-528`), committee from selected operations
(`driver:1974-1979`); **v3** v2 + media receipts/finalization (`account_research_tools.py:650-669`;
`driver:1703-1712`); **v4** the quality context pin at launch (`launch.py:426`), `_compose_quality`
(`driver:1281-1284`), the `QualityJobRunner` (`driver:1180-1192`), evidence indexing
(`account_research_tools.py:672-688`) and the governed resources (`account_research_catalog.py:157-162`).
Inside v4 the recipe integer (pinned at `driver:1318-1342`; `quality_catalog.py:14-40`) decides
behaviour through `uses_account_dossier` ≥ 13 (`quality_dossier.py:38-43`), `uses_json_dossier` ≥ 16
(`quality_json_dossier.py:44-48`), `owns_narrative` ≥ 20 (`quality_owned_narrative.py:33-37`),
`writes_pages_separately` ≥ 25 (`quality_policy.py:14-22`) and the profile ladder (`qrw:255-349`).
`CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED` is forced true by `CLUE_PRODUCT_PATH=integration_pilot`
(`settings.py:120-127`; `.env.example:926` = `default`).

### 9.2 Status table

| Module / path | Status | Selector or evidence |
|---|---|---|
| M8D entity-research runtime: 39 `*entity_research*`/`*research_view*` files, ~29.7k LOC; `clue_api/deep/` 2,710 LOC | **quarantined** | boundary + 9 replay-only tool addresses `platform/api/clue_api/entity_research_quarantine.py:1-15,48-60`; flag default off (`settings.py:388`); the fleet still composes it (`fleet_main.py:398-400,895-921`); no Langfuse handler (tracing spec `:103-106`) |
| `tests/arv2/test_import_guard.py` | guard (live) | allowlist of internal prefixes `:20-69`; forbidden SDKs openai/google/exa_py/firecrawl/sumble `:72-74`; 0 offenders at HEAD; scans only `clue_api/arv2/` (so `quality_research_wiring.py` is not guarded) |
| `tests/api/test_frontend_read_arv2_only_guard.py` | guard (live) | forbids `entity_research_`, `account_run`, `research_view`, `read_governed_committee`, `ContactEligibilityResolver`, `display_allowed` in `arv2/` and `frontend_read/` (`:24-37`); only allowed substring `entity_research_job_id` (`:43`); 0 offences at HEAD |
| `docs/specs/ARV2-PHASE6-LEGACY-DELETION-INVENTORY.md` | inventory only, not executed | "Nothing … has been deleted" (`:3-5`); 327 tables, 155 to drop / 172 kept (`:34-37,248-253`); 40 files / 29,778 LOC + ~8,500 quarantined + 19,419 LOC legacy tests (`:39-41`); deletion order `:403-422` |
| `arv2/account_research_agent.py` (R2 LangGraph loop) | live-only-for-v1–v3 | called only at `driver:1242`, after the v4 branch returned (`driver:1180-1192`) |
| `ARV2_ACCOUNT_AGENT_MODEL` / `ARV2_PERSON_AGENT_MODEL` | **model id live on v25**; gateway roles `arv2_account`/`arv2_person` v1–v3 only | env read `driver:2445,2481` → `composition.model_id` (`:1406`) overrides the profile model (`qrw:786-794`); the roles (`driver:277-280`) are used only at `:1233-1240`; on v4 the effort knob is `ACCOUNT_RESEARCH_AGENT_MODEL_EFFORT` (`agent_model.py:1229`) |
| catalogs `entity-research/arv2-{account,person}/{v1,v2,v3}` | superseded; kept for pinned rows | `account_research_catalog.py:66-95`; v4 loads `research-quality` (`:157-162`) |
| `arv2/structuring_client.py` (gpt-5-mini, `CLUE_ARV2_STRUCTURING_MODEL`) | `StructuringClient` superseded on v4; `FieldCatalog`/`FieldSpec` live | built at `driver:2401-2408`; called only by `_structure_material`/`_unique_insight` (`account_research_tools.py:2135-2199,2258-2297`), not in the v4 acquisition allowlist (`quality_provider_tools.py:45-59,99-110`); types used at `quality_context.py:21`, `quality_mapping.py:43` |
| `arv2/account_research_tools.py` | partially live-on-v25 | v4 wraps the legacy tools filtered to 13 acquisitions; hop/drain/operation code live; `structure_material`, `verify_links`, `finalize_research`, `write_claims` legacy-only |
| `arv2/account_research_claims.py` | partially live | `JobScope` imported by ~25 modules; provider mappers live via `QualityProviderWriter` (`quality_mapping.py:19-25,65`; `qrw:526-532`) |
| `arv2/claim_writer.py` | live (base class) | `QualityProviderWriter(LenientClaimWriter)` (`quality_mapping.py:65-77`; `quality_claims.py:617`); the driver's own writer (`driver:2486`) is replaced on v4 (`qrw:526`) |
| `arv2/committee_step.py` | partially live | `run_committee_step` legacy only (`driver:1760,1960-1990`); `CommitteeStepResult` used in `_settle_quality`; `_resolve_contact` used by `quality_committee_tool.py:256` |
| `arv2/person_compliance.py` | live-on-v25 | `apply_person_floor` via `quality_claims.py:588-590` from `dossier_import.py:24` |
| `arv2/quality_narrative.py` (`submit_value_narrative`) | recipes 3–5 only | registered for every recipe (`qrw:211-252`) but granted only in v3–v5 profiles |
| `arv2/quality_page_tools.py` (`read_research_page_inputs`, `publish_research_page`) | recipes ≤ 19 only | granted in profiles ≤ v19; `PublishPageOutput` type imported by `quality_owned_narrative.py:20` |
| `arv2/quality_owned_narrative.py` | tools recipes 20–24 only; `owns_narrative()` predicate live on v25 | tools granted in v20–v24 only; the predicate routes continuations (`driver:636-650`) and read-side logic (`quality_pages.py:511-518,596-599`) |
| `arv2/quality_shared_narrative.py` | live (read side) | `quality_pages.py:513-518` (Insights "Context only") |
| `arv2/quality_reconciliation.py` + `quality_reconciliation_routing.py` | recipes 20–24 only | recipe ≥ 25 → `_rewrite_account` (`driver:752-757`); 20–24 → `run_reconciliation` (`:758-797`); < 20 → a quality-runner reconcile unit (`:650-680`) |
| `arv2/quality_reconciliation_model.py` | superseded-uncomposed | "Historical replay helper" (`:1-4`); test-only importers |
| `arv2/quality_delegation_repair.py` | uncomposed (operator recovery) | docstring `:1-5`; imported only by its DB test |
| `quality-research-claims` / `quality-research-narrative` profiles | recipes < 20 only | `active_roles = {ACCOUNT_RESEARCH}` for ≥ 20 (`qrw:258-260,311`); delegation only if the profile declares it (`qrw:981`), v25 declares none; `launch-v4-r25.json` still hashes the v19 profiles but they cannot be resolved (`_memory/2026-09-27-research-specialists-disconnected.md`) |
| narrative skills `account-research-narrative` v1/v2, `person-research-narrative` v1/v2 | recipes 20–24 only | present only in manifests r20–r24 |
| `research-narrative-editorial` v1, `editorial/account-reconciliation` v1 | recipes 20–24 only | manifests r23–r24; read at `quality_reconciliation.py:60,67` |
| `arv2/quality_dossier.py` (markdown `AccountDossierPersistence`) | recipes 13–15 only | `qrw:722-731`, gated by `uses_account_dossier` and not `uses_json_dossier` |
| `arv2/page_writer.py`, `page_writer_runtime.py`, guides `research-page-writing`/`account-pages`/`contact-page`/`seller-brief` v1 | **live-on-v25** | `driver:1191,1796-1831`; publishes via `quality_pages.publish_page`; guides read from disk, not in launch manifests |
| display inline Luna runner (`arv2/display/runner.py:407`, `display/fleet_handler.py`, kind `arv2_display_page`, `fleet_main.py:1358`) | live only for subjects with no quality context (v1–v3 / legacy) | v4 settle enqueues no display pages (only legacy `_settle`, `driver:1784,2046-2095`); the read path serves `read_page` or an empty block whenever a quality context exists and never falls through to Luna (`frontend_read/display_pages.py:346-381`; the Luna path is labelled `qualityState: "legacy"` `:497-512`); `display/recipes.py` and `blocks.py` are live on v25 (`quality_pages.py:18-19`) |
| `arv2/answer_key.py`, `answer_key_loader.py`, `answer_key_recall.py` | script-only | importers only `scripts/load_arv2_answer_key.py`, `scripts/launch_arv2_*.py`, `scripts/arv2_answer_key_recall.py` |
| `arv2/discovery_*.py`, `arv2/onboarding_*.py` | separate lanes (note only) | — |
| `tests/arv2/quality_load_harness.py` | stale | its scripted model's tool calls fail on current contracts and every job ends `runtime_error` (`_memory/2026-10-03-production-research-slowness.md`, "R2-backed before/after benchmark"); last commit `4f997d795` (2026-09-23); hard-codes v4 (`:307,345`) |
| `.env.example` Sumble flags `CLUE_SUMBLE_DISCOVERY_GAP_ENRICHMENT_ENABLED` / `CLUE_SUMBLE_ACCOUNT_GAP_ENRICHMENT_ENABLED` | documented as quarantined, example value `true` | `.env.example:93-95`; code default False (`settings.py:316,321`); `check_prod_env.py:127-137` flags "on without key"; runbook says production sets false (`docs/deploy/runbook.md:125-128`) |

## §10 Design intent and constraints to respect

(Each is a founder ruling or master-plan rule a redesign must not silently violate.)

1. **ARV2's own rows are the only truth; the old lane is never bridged** (`docs/specs/ARV2-MASTER-PLAN.md:64-70`;
   guards `tests/api/test_frontend_read_arv2_only_guard.py`, `tests/arv2/test_import_guard.py`).
2. **A claim needs a quote and a URL or it is honestly empty; conflicts are recorded, never smoothed;
   fabrication is the only failure** (`ARV2-MASTER-PLAN.md:71-73`; Appendix A `:618-641`).
3. **Exactly two gates plus one floor; nothing mechanical blocks a store; checks are flag-controlled
   annotations defaulting off; the sensitivity floor runs by default and redacts/marks, never drops**
   (`ARV2-MASTER-PLAN.md:74-106`). "Judgment annotates; it never vetoes." Money truth blocks; money
   caps only record (`:92-93`).
4. **Factual visibility (2026-09-22)**: retain invalid observations for audit, exclude them from
   ordinary summaries, keep unresolved findings visible as uncertainty (`ARV2-MASTER-PLAN.md:3-11`);
   recipe ≥ 6 is advisory (`arv2/quality_policy.py:9-10`; the view stamps `review_policy` at
   `quality_views.py:301-307`).
5. **The claim store is the only seam; research never reads chat history** (`ARV2-MASTER-PLAN.md:96-97`).
6. **Free primary sources first; a known URL is fetched, never searched for** (`:94-95`).
7. **Launch contract (seam 1)**: human-approved cohort; `directive_text` carries effort + committee
   cap; accounts must exist; the ICP ref and the profile sha are pinned — a profile change relaunches,
   never resumes; `product_selection_version` pinned; zero yield is an honest terminal outcome; the
   research side never vetoes or reorders a launch (`ARV2-MASTER-PLAN.md:207-224`; enforced at
   `account_research_launch.py:247-413` and `account_research_driver.py:1305-1329`).
8. **Committee discovery v2 (2026-09-22)**: company-scoped AI Ark SMART title search after the
   account picture; selected profiles seed person jobs; email/phone enrichment ride person depth;
   provider facts cite saved artifacts; committee responsibility is the agent's separate assessment
   (`ARV2-MASTER-PLAN.md:13-27`).
9. **Media v3 amendment (2026-09-22)**: metadata/ASR labels never establish a person's voice;
   untimed speech is valid; empty resolution does not consume a slot; no new monetary/call-count/
   zero-yield stopping rule (`ARV2-MASTER-PLAN.md:652-676`).
10. **Researcher-owned narrative (2026-09-27) — reversed 2026-10-04**: the founder approved a
    *separate writer* "provided context transfer and output quality hold"; the short story lives in
    the existing Overview opening; seller brief must say what the research is for
    (`_memory/2026-10-04-narration-quality.md`, "Founder decisions, 2026-10-04";
    `_memory/2026-09-27-researcher-owned-narrative.md`). Recipe 25 is that cutover
    (`arv2/quality_policy.py:14`).
11. **No code that counts words/lines/items in agent prose (2026-10-04).** Code checks correctness
    only (refs resolve, quotes appear in cited findings, sections present, private topics absent,
    `send_line` only in openers), one repair attempt; "~1,500 words per page is acceptable when it
    carries valuable signals" (`_memory/2026-10-04-narration-quality.md`; implemented verbatim in
    `arv2/page_writer.py:1-11,130-237`).
12. **Instructions/references must not be tied to a dev example (2026-10-04)** — writer guides use
    neutral examples (`_memory/2026-10-04-narration-quality.md`, "Build into the pipeline").
13. **Miscellaneous / page cleanup (2026-09-29)**: per-sentence quality tags, qualification suffixes,
    gap lists and the quality banner are gone from the pages; recipes' `restricted` flags honoured
    (Watch-outs hidden on overview, Context-only under Insights' Internal notes — "keep watch-outs like
    it was before"); Contact-insights section removed; a `*.research_finding` claim no live block cites
    becomes an item in that page's Miscellaneous (`quality_presentation.uncovered_findings`); the
    custom rail excludes agent-registered fields (`_memory/2026-09-29-research-page-cleanup.md`).
    The 2026-10-07 plan records that uncited findings are dumped into Miscellaneous
    (`quality_pages.py:531+`) as a quality problem, but the ruling stands until changed.
14. **Person release after account import, not after pages (2026-09-26)**; **independent person
    launches attach to the account's research (2026-10-04)** (`_memory/2026-09-26-person-release-after-import.md`,
    `_memory/2026-10-04-narration-quality.md`).
15. **Replay / idempotency**: run id = digest of the request; job id = `uuid5(run, subject)`; the
    launch is retryable; rows first, offer second; `begin_job` attempt fence; `finish_job`/`suspend_job`
    fenced; `record_research_finding@3` identity from canonical content + resolved sources;
    `acquire_research_evidence` operation identity from `quality_tool:<op>` + fingerprinted args with
    receipt replay and "no repurchase on unknown outcome"; `finish_dossier` import id from the
    document sha; the committed turn outcome short-circuits a replayed execution
    (`account_research_launch.py:134-157`, `account_research_store.py:309-405`,
    `quality_provider_tools.py:153-185`, `quality_json_dossier.py:502-505`,
    `quality_research_wiring.py:902-908`; Doc A §2.5 `docs/architecture/clue-hq-platform-agent-runtime.md:272-295`).
16. **Tool-error recovery (Doc A §2.5, 2026-09-25)**: batches settle before the next model call; ten
    corrective rounds per turn; `finalize_turn` must be a separate call; explicit `retry_of` recovery
    (`docs/architecture/clue-hq-platform-agent-runtime.md:272-295`;
    `_memory/2026-09-25-research-runtime-repairs.md`, "Founder adjustment: ten repair rounds").
17. **Privacy / DSAR**: raw personal pages expire after 30 days; whole-page erasure overrides
    surviving citations; DSAR reaches selection copies and old job authority; late responses stay
    unreadable; `privacy_stopped` halts generations and person release
    (`_memory/2026-09-22-arv2-ai-ark-committee-implementation.md`; `quality_generation.py:144,252,405-407`;
    `quality_person_release.py:85-87`; `quality_views.py:352-356` excludes erased/expired artifacts).
    `birth_date` and kin dropped inside the provider client (`ARV2-MASTER-PLAN.md:626`).
18. **"Plain and operational first"**: no mechanical quality gates, no secondary model judges, no
    verification blockers in v1 (`docs/specs/ARV2-AGENT-BRIEFING.md` §2 item 10; `ARV2-MASTER-PLAN.md:98-106`).
19. **Doc A vocabulary**: per-account deep research is a *governed worker agent in the fleet shell*
    with limits-not-scripts (max rounds, envelope, fan-out caps); the fleet shell is never a mind;
    tools are the only write path (`docs/architecture/clue-hq-platform-agent-runtime.md:77-187`).
20. **Model choice is an env change, never a profile version** (CLAUDE.md "Environment flags — parity
    rule"; `_memory/2026-09-29-research-model-grok.md`); compaction stays sized for the currently
    selected model (`_memory/2026-10-05-stranded-research-jobs-lease-takeover.md`, context-window registry).
21. **Rulings pending / not taken that a redesign must not assume**: openers must tie to the offer and
    the reader is "a rep preparing first outreach" are working assumptions, not rulings
    (`_memory/2026-10-04-narration-quality.md`); removing sensitive data already in production and
    stopping its collection is parked (same note); the v26 plan's D1–D9 decisions are the founder's
    (`_memory/2026-10-06-account-research-cost-audit.md`).
