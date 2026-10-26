# 03a — Runtime and toolbelt mechanics the v26 redesign must work within

**Lane L4 of the v26 document set. Status: evidence record, 2026-10-07.** Read-only trace of the
deep-agent runtime and the governed toolbelt on `main` (branch
`shank-audit-account-research-cost-optimization`, same code as `496956c98` for every file cited).
Every claim carries a `path:line` into this checkout; `site-packages` paths are the installed
`.venv` (langchain 1.3.14, deepagents 0.6.12, langgraph 1.2.6, langgraph-checkpoint-postgres
3.1.0). The measured numbers come from the 2026-10-06 production Langfuse pull in
`.artifacts/account-research-cost-20261006/` (gitignored); the per-phase timings in §1.3 were
computed for this document from the raw span tree (`langfuse-observations/*.json`) with the method
in the appendix. §1–§7 describe; only §8 recommends.

**Correction round (2026-10-07, after `review-A-consistency-and-executability.md` and the
orchestrator's `RECONCILIATION-RULINGS.md`).** Every citation re-verified against `main`
`fa4bed77b` (this checkout); the two review-A items traced to this document (K2: the pre-step
cannot enqueue; K3: the extractor's raw envelope is unbound) are fixed in §7.3, §8a and §8b, and
the line numbers review A's §2.2 table gives differently are corrected throughout. §8 now records
the **adopted** mechanisms — R4 (`person_research`), R6 (clearing per 03 §5.3, acquire receipts
included), R11 (the deferred contact page is a research-kind continuation, 04 §0.5), R12/R13
(`acquire_research_evidence@2` minted once in W1 with `candidates`, extractor as a leaf call) —
each with the code that confirms it sound and the one condition under which it breaks.

What the plan (`docs/superpowers/plans/2026-10-06-account-research-v26-cost-and-speed-plan.md` §2,
§4) wants from this seam: code-driven acquisition at job start; a tool that runs a cheap-model
extraction on a provider result and returns candidate findings instead of a path; tool-result
clearing with a per-role window; per-role round/operation/context budgets; candidates files in the
job workspace; a bounded "judge + investigate" loop; a per-section parallel page writer; contacts
started at nomination with a deferred page write.

---

## §1 How a governed tool call flows end to end today

### 1.1 The graph and its middleware

A research job's agent is one `create_deep_agent` graph built per run by
`DeepAgentTurnRuntime._build_graph` (`platform/agents/clue_agents/runtime.py:625-671`), with
`system_prompt=resolved_profile.prompt_body` (`:640`) and this middleware order (`:641-666`):

1. `ToolRepairRoundsMiddleware` (`platform/agents/clue_agents/tool_recovery.py:16-62`) —
   `abefore_model` counts a *batch* whose settled `ToolMessage`s carry
   `governed_repair_budgeted: true` as one repair round in graph state (`tool_repair_rounds`,
   `tool_repair_batch`, `:28-62`); more than `MAX_TOOL_REPAIR_ROUNDS = 10` (`:12`) raises and ends
   the turn (`:58-61`).
2. `ExactAgentToolSurfaceMiddleware` (`runtime.py:139-320`) — `awrap_model_call` (`:179-233`)
   fails loudly if a declared tool is missing or an undeclared one appears (`:180-188`), appends
   the profile's generated resource map to the system prompt unless already there (`:189-194`),
   filters the tool list to the allowed set and sets `tool_choice="required"` (`:195-202`); a
   plain-text stop gets one finalize-only recovery call (`:204-233`). `awrap_tool_call`
   (`:235-245`) refuses any name outside the allowed set with an error `ToolMessage` and routes
   `finalize_turn` through `_bounded_finalize` (`:247-320`): a refused finalization is returned
   to the model as an error `ToolMessage` with contract guidance, `return_direct` cleared for that
   call, at most `_MAX_FINALIZE_REPAIRS = 2` times (`:88`; 10 on a continued research
   conversation, `:529-535`).
3. `TurnBudgetMiddleware` (`runtime.py:336-484`) — `abefore_model` increments
   `turn_budget_rounds` in graph state keyed to the turn (`:373-377`); `awrap_model_call`
   (`:379-423`) narrows the tool list to `finalize_turn` with `tool_choice=finalize_turn` from
   round `max_rounds - 2` (`_finalize_round`, `:364`), and appends a "Platform notice" human
   message for the `WRAP_UP_WARNING_ROUNDS = 3` rounds before (`:325`, `:396-399`, `:419-423`).
   Notices are appended to that call's request only, never to state (`:349-351`).
4. The bindings middleware passed by the composition root (`:661`): for research,
   `SharedResearchAllowance` (`platform/api/clue_api/arv2/quality_execution.py:228-272`), which
   `reserve`s one `model` allowance row per model call (`:244-253`) and one `tool` allowance per
   *non-domain* tool call — framework filesystem tools, delegation, `finalize_turn` (`:255-272`);
   domain tools reserve once inside their own invoke (§1.2 step 6).
5. `ClueSummarizationMiddleware` and the `compact_conversation` tool (`:664-665`; §4.1).

deepagents installs its own `PatchToolCallsMiddleware.before_agent`
(`.venv/lib/python3.12/site-packages/deepagents/middleware/patch_tool_calls.py:14-46`): on every
graph entry it scans for AI tool calls with no `ToolMessage` and, if any, rewrites the **whole**
message list (`RemoveMessage(REMOVE_ALL_MESSAGES)` + synthetic "cancelled" tool messages,
`:36-46`). It fires only on a resumed turn that died mid-batch; every 2026-10-06 run shows exactly
one `PatchToolCallsMiddleware.before_agent` observation (the fresh start, a no-op).

The LangGraph fuse is `recursion_limit = superstep_ceiling(max_rounds)` = `max_rounds × 6 + 10`
(`runtime.py:97-109`, `:545`, `:800`); the graph runs under `thread_id = execution_id`,
`checkpoint_ns = agent-turn:<turn_id>` (`:791-795`) and an optional `asyncio.wait_for` on
`max_runtime_s` (`:786-805`; `None` for research when `CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S=0`,
`quality_research_wiring.py:1093-1101`).

### 1.2 One governed call, step by step

Every governed tool the model sees is a `StructuredTool` built by
`GovernedAgentToolFactory._governed_tool` (`platform/api/clue_api/agent_runtime_wiring.py:889-1040`)
whose args schema is the tool's `input_model` with trusted authority fields removed and `retry_of`
added (`_with_trusted_runtime`, `:560-632`, `:1035-1039`).

1. **Admission.** The closure first awaits `before_work` (`:898` → `_check_work` `:860-862`); for
   research that is `resolve_authority` + `runtime_remaining` on a fresh connection
   (`quality_research_wiring.py:713-717`). The same guard also runs on every model start/end
   through `TurnWorkGuard` (`agent_runtime_wiring.py:802-822`, attached at `:1456-1457`).
2. **Plan.** `node_key = agent_<name>_<sha256(tool_call_id)[:24]>` (`:900-902`), a deterministic
   `plan_id` (`:903-906`), and a one-step `AgentPlan` whose arguments are the LangChain-validated
   kwargs re-rendered as JSON (`_json_arguments`, `:635-655`, `:907-922`).
3. **Validation** — `C5AgentExecutionAdapter.validate_plan`
   (`platform/api/clue_api/agent_execution_wiring.py:1344-1718`): package-local review
   (`review_agent_plan`, `clue_agents/execution.py:299-430` — role/workspace/node/fanout/depth and
   `tool_not_allowed` when the step's pin is not *exactly* the profile's pin, `:342-355`); the
   live C5 interaction slot's `tool_allowlist`, child and node ceilings (`:1359-1402`); the live
   descriptor's `input_schema_sha256`/`output_schema_sha256` must equal the profile pin or the
   step is `tool_schema_mismatch` (`:1420-1434`); trusted arguments merged from the constitution
   and validated into the input model (`:1436-1473`); pins (`:1484-1560`); C5 graph compilation
   and `validate_graph` (`:1562-1588`). Then **four durable writes before anything runs**: the
   proposal artifact (`:1590-1594`), one parameter artifact per step with the tool's `estimate`
   (`:1601-1627`), the budget check (`:1629-1651`), the validated-plan artifact (`:1690-1694`),
   and `DbAgentPlanJournal.record_validated` (`:1708-1714`). A rejection returns to the model as
   a `GovernedToolFailure` JSON with `error: plan_rejected` (`agent_runtime_wiring.py:936-957`,
   `:389-410`).
4. **Execution** — `execute` (`:1720-1823`) runs ready operations in batches of
   `max_parallelism` (`:1744`; a direct agent call is always one operation);
   `_execute_operation` (`:1825-1957`): `validate_interaction_repair` for each `retry_of`
   (`:1840-1848`), read the parameter artifact back (`:1849-1852`), append the C5 node
   (`append_interaction_tool`, `:1863-1877`), then `invoke_interaction_tool` (`:1878-1888`).
5. **Executor** — `RecipeExecutor.invoke_interaction_tool`
   (`platform/execution/clue_execution/executor.py:1584-1651`): refuses a recovered node
   (`:1608-1611`), resolves the durable parameter body and checks it equals the supplied inputs
   byte-for-byte (`:1614-1625`), builds the `ToolContext` — `actor="agent"`,
   `principal_kind="service"`, `actor_id="svc_execution_worker"`, the derived turn `action_ref`,
   `operation_id = node.operation_id`, execution/node ids, `conn_factory` (`:1626-1650`) — and
   calls `ToolInvoker.invoke`. `operation_id` is `operation_id_for_plan_node(execution_id,
   node_key)` (`clue_agents/execution.py:242-245`), i.e. stable across retries of the same
   LangChain tool call id.
6. **Invoker** — `ToolInvoker.invoke` (`platform/toolbelt/clue_toolbelt/invoker.py:176-215`):
   registry lookup, input validation, and the Langfuse observation `governed.<name>@<version>`
   (type `retriever` for READ tools, else `tool`; `:191-205`). `_invoke_observed` (`:217-357`):
   parameter snapshot (`:229-233`); `journal.begin` (`:234-238`) — a `COMPLETED` disposition is a
   **journal replay** (the stored result is validated and returned with `replayed=True`,
   `:239-245`), `BLOCKED` raises `PreconditionFailed` (`:246-261`); the A9 idempotency key is
   always `execution:<execution_id>:operation:<operation_id>` (`:273`); then the pure runner
   `invoke_tool` (`:284-293`). Failures are journaled by class — blocked / awaiting input /
   failed — and re-raised (`:308-342`); cancellation leaves the attempt visibly abandoned
   (`:303-307`); success calls `journal.completed` (`:343-347`) and stamps the observation output
   with references and `replayed` (`:348-355`).
7. **Runner** — `invoke_tool` (`platform/toolbelt/clue_toolbelt/runner.py:115-217`): validate the
   body against `input_model` (`:152`; `ToolInput` is `frozen, extra="forbid"`,
   `envelope.py:69-74`), hash the validated dump as the body key (`:156`), `estimate` (`:159`),
   idempotency lookup → replay or conflict (`:169-175`, `_replay_or_conflict` `:72-87`),
   `preconditions` (`:177-179`), reserve (`:181-199`), **`tool.invoke`** then
   `validate_tool_result` (`:201-208`; a failed invoke releases the reservation), stamp
   `meta.estimated_cost_cents` (`:210-212`), store the response (`:214-216`).
8. **The tool body** returns a `ToolResult(tool, version, references, replayed, meta)`
   (`envelope.py:317-336`): `references` must validate in JSON mode against the tool's
   `output_model` (`runner.py:90-112`; `ToolOutput` is `frozen, extra="forbid", strict=True`,
   `envelope.py:77-80`; `UntypedToolOutput` allows extras but is not recipe-safe, `:83-90`,
   `:218-220`).
9. **Result persistence** (back in `_execute_operation`): `validate_tool_result` again at the
   JSON boundary (`:1894-1897`), persist the canonical result as an
   `application/vnd.clue.agent-tool-result+json` artifact with subject bindings (`:1910-1915`),
   `record_tool_result` into `agent_tool_result` (`:1916-1922`, `:642-700`), resolve `retry_of`
   failures (`:1923-1938`), and build the `GovernedOperationReceipt` (`:1944-1957`).
10. **Receipt to model.** The closure then calls `self._execution.recover(...)` (`:995-997`) —
    which re-reads **every** receipt of the execution (`load_receipts`, `:703-760`) and
    re-hydrates each one's `reference_values` from its result artifact
    (`_hydrate_tool_reference_values`, `:2195-2241`) — picks the receipt for this operation
    (`:1004-1013`) and returns `receipt.model_dump_json(exclude_none=True)` (`:1024`). That JSON
    is the `ToolMessage` content.

### 1.3 What the model actually sees, and the size rules

- **A receipt-only tool** (every `WRITE`/`SPEND` tool, e.g. `acquire_research_evidence@1`): the
  `GovernedOperationReceipt` fields `node_key, operation_id, kind, address, status, replayed,
  artifact_refs[{workspace_id, artifact_key, sha256, media_type, byte_count}], reference_values`
  (`clue_agents/execution.py:144-156`). For the acquire tool `reference_values` is the
  `AcquireResearchReceipt` dict — `operation_id, status ∈ {completed, refused, outcome_unknown},
  result_path, error_code, recovery, replayed` (`platform/api/clue_api/arv2/quality_provider_tools.py:68-74`,
  `:316-324`) — a few hundred bytes, no content. The content is one `read_file` away at
  `/research/operations/<operation_id>/0.json` (`:320`).
- **A content tool** (the READ tools): `reference_values` rides inline up to
  `SPILL_THRESHOLD_BYTES = 12 KiB` of canonical JSON (`execution.py:57`); past that the adapter
  writes the bytes to the thread's `reads/<operation_id>.json` and the receipt carries a
  `spill_stub` — `spilled_to, count, summary[:300], tool` (`:212-239`,
  `agent_execution_wiring.py:1959-1992`; `workspace.py:969-1000`). The hard bound on any receipt
  is `RECEIPT_REFERENCE_VALUES_MAX_BYTES = 16 KiB` (`:50`, validator `:170-178`), and the spill
  applies identically on recovery (`:2225-2229`).
- **A refusal**: `GovernedToolFailure` JSON — `governed_repair_budgeted, error ∈ {plan_rejected,
  operation_failed}, address, node_key, recorded: false, reasons[], guidance`
  (`agent_runtime_wiring.py:389-410`, `:1068-1098`). A READ tool refused only by preconditions
  is not budgeted (`:978-994`); everything else counts toward the 10 repair rounds.
- **Framework tools** (`read_file`, `ls`, `glob`, `grep`, `write_file`, `edit_file`,
  `write_todos`, `compact_conversation`; `runtime.py:64-76`) never enter the governed path: their
  `ToolMessage` is deepagents' own (§3.1).
- **Over-size tool messages**: deepagents evicts any `ToolMessage` whose text exceeds
  `tool_token_limit_before_evict = 20000` tokens (≈ 80,000 chars at 4 chars/token) to
  `/work/large_tool_results/…` and replaces it with a reference
  (`deepagents/middleware/filesystem.py:831`, `:2007-2050`; the `/work` root is
  `research_backend`'s `artifacts_root`, `quality_views.py:497`, and `HistoryPathBackend` remaps
  deepagents' root-level folders there, `clue_agents/compaction.py:67-104`).

### 1.4 The per-call overhead, measured (210 `acquire_research_evidence` calls, 12 runs)

The span tree is `acquire_research_evidence` (LangChain tool run) → `governed.acquire_research_evidence@1`
(the invoker's observation) and, beside it, the inner provider tool run (`search_web`,
`fetch_page`, …) → `exa.search` / `exa.contents` / `ai_ark.…` (the `ProviderCaller`
observation) → `provider.http_attempt`. Medians (p25–p75), seconds:

| Phase | What runs there | All 210 | 21 solo calls | 128 batched (≥ 4 at once) |
|---|---|---|---|---|
| a. tool start → governed start | §1.2 steps 1–3: `before_work`, `validate_plan`'s four artifact persists + `record_validated`, through the driver's single `_db_lock`ed connection (§6.3) | **2.96** (2.72–3.33) | 2.87 | 3.04 |
| b. governed start → inner tool start | step 6–7 preamble + the tool's own `resolve_authority`, `reserve`, `operations.begin` (`quality_provider_tools.py:140-153`) | **0.70** (0.62–0.82) | 0.66 | 0.70 |
| c. inner start → provider request | provider semaphore wait (§6.2), `job_available` read, thread hop (`account_research_tools.py:500-532`) | 7.05 (0.08–19.9) | 0.21 | 11.14 |
| provider | Exa / AI Ark wire time | 1.62 | 1.84 | 1.62 |
| d. provider end → inner end | `_drain`: ledger + raw artifacts, `index_provider_artifacts`, `operations.finish`, `index_acquisition`, then `recover_acquisitions` + `operations.body` (`:550-565`, `:596-687`, `:721-728`) | **28.05** (7.75–43.2) | 5.06 | 33.68 |
| e. inner end → governed end | result artifact + subject binding + derivation + operation update (`quality_provider_tools.py:259-315`) | **0.55** (0.46–0.75) | 0.46 | 0.60 |
| f. governed end → tool end | step 9–10: result artifact, `record_tool_result`, `recover()` re-reading every prior receipt's artifact | **1.59** (1.11–2.25) | 2.43 | 1.30 |
| total | | 50.4 | 17.2 | 56.0 |

So the fixed platform cost of one governed call is ≈ **3.3 s before** the tool body
(a + b, ≈ 3.0 s of it `validate_plan`'s writes behind `_db_lock`) and ≈ **0.7–1.8 s after** it
(e + f), independent of the provider; phase f grows with the number of prior calls because
`recover()` is O(receipts) storage reads per call (solo-call medians 1.1 s at calls 0–4, 2.7 s at
calls 15–19, 6.1 s past call 30). The 20–40 s the audit attributed to "before dispatch / after
the answer" (`.artifacts/…/CALL-LOG.md:36`) is phases c and d — contention on the per-job
provider semaphore held across `_drain`, and the drain itself — not the governed envelope.
Everything in a, b, e and f is per-call fixed cost that a **code pre-step issuing operations
through `ToolRuntime.operate` does not pay** (§7.3).

---

## §2 What it takes to add or change a tool

### 2.1 Versions, pins and re-mints

- A tool is a class with `name`, `version` (ClassVar, default `"1"`), `input_model`,
  `output_model`, `replay`, `effect_class` (`envelope.py:339-365`). Its descriptor hashes the
  JSON schema of both models (`_schema_sha256`, `:168-170`, `:378-379`). Changing the input or
  output *shape* changes a sha; **the profile pins both shas per tool**
  (`platform/agents/catalog/research-quality/profiles/quality-account-research/v25/profile.yaml:24-64`)
  and `validate_plan` refuses a mismatch (`agent_execution_wiring.py:1420-1434`), so a shape
  change is either a new `version` (`@2`, registered beside `@1`) or a re-mint of every profile
  that pins it. `model_description` is deliberately outside the schema so wording changes do not
  invalidate pins (`envelope.py:350-352`).
- Research tools are registered in `quality_tools` (`platform/api/clue_api/quality_research_wiring.py:211-252`);
  `make_default=tool.version == "1"` (`:249-251`), and `AcquireResearchTool` is constructed with
  the job's `ToolRuntime` (`:251`, `:1231`). Which role may call which tool is the authority map
  in `quality_profiles` (`:255-300`), and which profile version a recipe version selects is the
  ladder at `:312-349` (`v25` / `v25-person` for `version >= 25`).
- The recipe allowlist is `platform/agents/catalog/research-quality/recipe-v25.json`
  (`graph.nodes[1].dynamic_tool_allowlist`, the `research_interactions` node); a tool absent from
  it is `c5_tool_not_allowed` at validation (`:1393-1402`). `CURRENT_RECIPE_VERSION = 25`
  (`platform/api/clue_api/arv2/quality_catalog.py:14`); the job's pinned version rides
  `input_refs.quality_recipe_version` and selects everything (`quality_research_wiring.py:537-540`).
- The catalog is immutable: a change is a new folder version with new shas (prompt `v25` sha at
  `profile.yaml:7-10`, skills `:11-23`), per `docs/agents/skill-and-profile-authoring.md`
  ("Never edit a runtime workspace…", the `profile.yaml` pin list). The test that pins the shape
  is `tests/arv2/test_quality_json_dossier.py:16-60` (tool names, no delegation, recipe allowlist
  membership, `CURRENT_RECIPE_VERSION == 25`, every skill path mounted) and `:86` (the
  `SaveSectionInput` contract refuses unknown keys). Per R2 there are **two** mints — r26, the
  week-1 mint (the W1 tool-shape and prompt changes force it), and r27, the W3 pipeline — and each
  needs: `recipe-v<N>.json`, `profiles/quality-account-research/v<N>/profile.yaml` and
  `quality-person-research/v<N>-person/profile.yaml`, the prompt/skill folders they pin, the
  ladder entry at `:312-349`, `CURRENT_RECIPE_VERSION` (26 at the W1 mint, 27 at the W3 mint),
  the test's constants, and the per-workspace pilot selector of 04 P5
  (`CLUE_ARV2_RECIPE_PILOT_VERSION` / `CLUE_ARV2_RECIPE_PILOT_WORKSPACES`; the single settings
  sheet is 03 §10, R7).
- For the Head of ABM the equivalent registry is `C6_ACTIVE_PROFILE_VERSIONS`
  (`platform/api/clue_api/agent_registry_wiring.py:40`) and `build_agent_profile_registry`
  (`:960-1021`), which refuses at boot if the live tool registry differs from the audited
  authority or a profile's pins differ from the role's admitted tools.

### 2.2 Roles and models

- `AgentRole` is the enum at `platform/agents/clue_agents/contracts.py:220-236`
  (`head_of_abm, research, content_drafter, reviewer, account_research, research_claims,
  research_narrative, design, onboarding_synthesis`). **Both** research profiles declare
  `role: account_research` (`v25/profile.yaml:6`; `v25-person/profile.yaml:6`), and the runtime
  resolves `AgentRole.ACCOUNT_RESEARCH` for both (`quality_research_wiring.py:785`).
- Model selection: `_env_model_policy` reads `<ROLE>_AGENT_MODEL` at profile resolution
  (`clue_agents/registry.py:375-410`, env read `:395`), but the research driver then overrides
  the model id per lane with `ARV2_ACCOUNT_AGENT_MODEL` / `ARV2_PERSON_AGENT_MODEL`
  (`platform/api/clue_api/arv2/account_research_driver.py:129`, `:135`, `:2445`, `:2481`,
  `:1405`) and the runtime applies it (`quality_research_wiring.py:786-794`). Reasoning effort is
  read at the gateway from `<role>_AGENT_MODEL_EFFORT` where `role` is what `_build_model` is
  given (`clue_gateway/agent_model.py:1229`) — and the governed runtime passes
  `profile.role.value` (`runtime.py:606-617`), i.e. `account_research` for **both** lanes. The
  driver's `_PERSON_MODEL_ROLE = "arv2_person"` (`account_research_driver.py:280`) reaches only
  the legacy `run_account_agent` path (`:1233-1240`), so on v25 `ARV2_PERSON_AGENT_MODEL_EFFORT`
  (`.env.example:419`) is dead and `ACCOUNT_RESEARCH_AGENT_MODEL_EFFORT` (`:406`) governs both.
  The same `role` string becomes `attribution_role` → the `clue_role` stamp →
  `agent_model_call.role` (`agent_model.py:474`; `agent_runtime_wiring.py:120-134`, `:231-233`).
- The person lane's role is **`person_research`** (R4; 04 W3-26's `contact_research` spelling
  is superseded, user-facing text still says "contact"). Adding it means: a new `AgentRole`
  member; a profile whose `role:` is that member; `quality_profiles` resolving it for person
  scopes — the authority map (`:261-290`) and `active_roles` (`:260`) are keyed on
  `ACCOUNT_RESEARCH` today, as are `resolve(...)` (`:785`), the constitution (`:888`),
  `bind_execution(role=…)` (`:707`) and the dossier-middleware check (`:729`); the **five** DB
  CHECKs that enumerate roles — `agent_turn_role`, `agent_plan_role`, `agent_delegation_roles`
  (widened the same way for `onboarding_synthesis` in
  `alembic/versions/000b9d8bb17b_arv2_onboarding_synthesis_role.py:39-57`),
  `agent_model_call_role` (`65880921cd52…py:36-40`) and the `quality_execution_role` root
  predicate `parent_execution_id IS NULL AND role='account_research'`
  (`f4b30cb3d088…py:70-72`; review A W1/W2 — the first governed call of a person turn would fail
  the `agent_plan` insert without it); and every hard-coded `authority.role != "account_research"`
  refusal a person judge would hit — above all the acquire tool
  (`quality_provider_tools.py:142`, which otherwise raises "specialists request acquisition
  through their parent" on the first evidence call), `quality_json_dossier.py:198`,
  `quality_views.py:210,215,308` (operations, capabilities and context views) and
  `quality_tools.py:89`. `quality_committee_tool.py:88` stays account-only;
  `quality_dossier.py:168` and `quality_owned_narrative.py:174,225` guard pre-25 surfaces a r27
  judge does not use. Then its `PERSON_RESEARCH_AGENT_MODEL` / `_EFFORT` lines in the single
  "Agent model configuration" block (`.env.example:365-425`) with a context-window entry
  (`CLUE_AGENT_MODEL_CONTEXT_WINDOWS`, `:388`; guard test
  `tests/test_agent_model_context_windows_settings.py` per
  `_memory/2026-10-05-stranded-research-jobs-lease-takeover.md`), and the driver's model-id
  override (`ARV2_PERSON_AGENT_MODEL`) left as the model source. **Sound**, provided 04 W3-26's
  list is completed with the `agent_model_call_role` CHECK and the root predicate; without those
  two the lane fails at its first model-call record and its first plan.

### 2.3 A model call inside a tool's `invoke` — the precedent

Yes, it exists, and it never goes through the governed chat model.

- **`structure_material`** (`platform/api/clue_api/arv2/account_research_tools.py:2135-2200`)
  calls `runtime.call_provider("openrouter", hop)` (`:2196`); the hop is
  `StructuringClient._structure` (`platform/api/clue_api/arv2/structuring_client.py:1173-1227`):
  an `openrouter_chat_request` (`:1191-1199`) sent through `ProviderCaller.call(CallSpec(
  provider="openrouter", operation="chat/completions", label=…, estimate=…,
  cost_reader=openrouter_cost_reader, halt_rule=openrouter_halt_rule))` (`:1202-1211`). Model
  from `settings.arv2_structuring_model` (`libs/clue-config/clue_config/settings.py:405-406`,
  default `openai/gpt-5-mini`).
- **Media first pass / transcription** (`gemini_media_client.py:1062-1092`, `:1211-1230`) and
  the **page writer** (`platform/api/clue_api/arv2/page_writer_runtime.py:109-173`: a
  `ProviderCaller` per call, `asyncio.to_thread(caller.call, spec)` `:153`, drained into the
  ledger with the job stamp `:163-173`; model from `RESEARCH_NARRATIVE_AGENT_MODEL` falling back
  to `arv2_display_model`, `:98-106`) follow the same shape; the display module's
  `_write_section` likewise runs `runner.write_section` on a thread under a semaphore
  (`platform/api/clue_api/arv2/display/page.py:233-296`).
- **Mechanics.** `call_provider` wraps the hop in a shielded task (`account_research_tools.py:433-453`);
  `_perform_hop` takes the per-provider semaphore (`:500`, `_semaphore` `:567-575`: 1 for
  `ai_ark`/`media`, else `arv2_account_provider_concurrency`), checks `job_available`
  (`:521-528`), runs the **synchronous** httpx call on the worker thread pool
  (`asyncio.to_thread(fn, caller)`, `:532` — not on the event loop; the pool is
  `CLUE_FLEET_THREAD_POOL_SIZE=128`, `fleet_main.py:848`), latches halts on both the label and
  the wire provider (`:534-543`), and always drains (`:547-565`).
- **Attribution.** Each call writes an estimate row and a result row to `provider_call_ledger`
  with `provider='openrouter'`, `label`, `extras` (`libs/clue-spend/clue_spend/calls.py:965-1009`),
  stamped by `_drain` with `workspace_id, project_id, project_run_id, job_id` (`LedgerStamp`,
  `account_research_tools.py:612-617`; column `entity_research_job_id`,
  `libs/clue-spend/clue_spend/ledger.py:59-71`). `cost_usd` is what `openrouter_cost_reader`
  read (`CostReading`, `calls.py:111-130`). The job meter sums these rows by job
  (`quality_meter.py:39-48`). Langfuse gets one observation `openrouter.chat/completions`
  typed `generation` (`calls.py:246-260`, `:390-400`) with usage from the reader's extras
  (`:299-317`). There is **no** `agent_model_call` row, no `role`, no fallback chain, no
  `cache_read` accounting and no `Allowance.model_calls` reservation for such a call.

---

## §3 How tool results and files enter the model context

### 3.1 deepagents' filesystem tools

`read_file(path, offset=0, limit=100)` (`deepagents/middleware/filesystem.py:257-258`,
`:1154-1155`) returns `cat -n`-style line-numbered text (`format_content_with_line_numbers`,
`deepagents/backends/utils.py:119-139`; lines over 5,000 chars are split with `5.1, 5.2`
continuation rows, `filesystem.py:435`), truncated at `NUM_CHARS_PER_TOKEN × 20000 = 80,000`
chars with a reformatting notice (`:272`, `:1053-1065`). `ls`/`glob`/`grep` truncate at
`TOOL_RESULT_TOKEN_LIMIT = 20000` tokens (`utils.py:68`, `:387-397`).

### 3.2 The research mounts

`research_backend` (`platform/api/clue_api/arv2/quality_views.py:482-506`) is a
`CompositeBackend` over the thread workspace with `artifacts_root="/work"` and two read-only
routes: `/research/` and `/evidence/` → `ResearchViewMount` (`:60-130`), which re-authorises on
every read (`:84-95`). Views are rendered by `render_view` — `json.dumps(indent=2)`, whole when
the framework's default `limit=2000` or a non-positive limit is passed, else a line window
(`quality_workspace.py:43-55`). Operation bodies are served as `_passage` objects whose text is
cut into 256-char `text_segments` (`quality_views.py:45-57`, `:225-237`); evidence originals
likewise (`quality_workspace.py:77-83`). `grep` on either mount is refused (`:131-135`), `ls`
only knows `/research/context.json` and `/evidence/index.json` (`quality_views.py:436`). This is
the "two hops and inflated" reading the plan measures (§0 item 3).

### 3.3 The thread workspace

Layout `(.deepagent, inputs, context, scratch, reads, work, outputs)`
(`platform/agents/clue_agents/workspace.py:105`); `.deepagent, inputs, context` are materialised
read-only from the context bundle (`:110`; seeds from `assembled.materializations`,
`quality_research_wiring.py:973-979`); `reads/` is the spill folder — model-readable, writable
only by the runtime (`:111-113`, `write_spill` `:969-1000`); the v25 profile reads
`.deepagent, inputs, context, work, outputs, research, evidence, reads` and writes `work,
outputs` (`v25/profile.yaml:82-93`). `outputs/` is frozen and emptied at finalization
(`snapshot_outputs(empty_after=True)`, `agent_runtime_wiring.py:1351`).

### 3.4 Where a "candidates" file can live, and what each choice costs

| Channel | Mechanism | Durability / journal | Replay | Clearing (§4.2) | Trace size |
|---|---|---|---|---|---|
| Inline in the `ToolMessage` (`reference_values`) | ≤ 12 KiB or it spills (`execution.py:57`) | result artifact + `agent_tool_result` row (`agent_execution_wiring.py:1910-1922`) | `recover()` re-hydrates it (`:2195-2241`) | cleared once outside the keep window | every later generation re-sends it until cleared |
| `reads/<operation_id>.json` (spill) | automatic past 12 KiB; stub names the path (`:1984-1992`) | same artifact; the file is the thread's, rewritten on replay (`workspace.py:986-999`) | yes | the stub is tiny; the `read_file` result is what gets cleared | only the read |
| `/research/…` view | DB-backed, authority-checked per read (`quality_views.py:85-95`) | the artifact behind it | yes | as above | as above |
| Materialised `inputs/<file>` | a `ContextCandidate(materialized_path=…)` from the turn's assembler (`clue_agents/context.py:144-158`, `:949-957`) | in the context receipt with sha (`:965-975`), verified on resume (`quality_research_wiring.py:973-979`) | byte-identical | never (not a message) | only when read |
| The L7 task message (`agent-turn-input`) | the task artifact body becomes the user message (`quality_research_wiring.py:867-879`; `context.py:800-803`) | journaled as L7 | yes | **never** (`ClearToolUsesEdit` touches only `ToolMessage`s) | once per generation, in the cached prefix |

The Langfuse ceiling is real: each generation records its full input (the SDK handler,
`clue_gateway/langfuse_handler.py:38-83`; `DEFAULT_MASK_LIMIT = 8_000` chars applies per string
field, `clue_obs/langfuse.py:74`, not per prompt), and a trace over 100 MB cannot be read back
(`_memory/2026-10-03-production-research-slowness.md:91-94`). Since R3 every job is its own
trace (`_memory/2026-10-03-agent-scoped-tracing.md`), so the budget is per job: at ~200k-token
contexts a 60-call run already approaches it. Anything that lowers per-call context (clearing,
smaller files) lowers trace size one for one.

---

## §4 Context management available today

### 4.1 Compaction

`ClueSummarizationMiddleware` is deepagents' `_DeepAgentsSummarizationMiddleware` under our own
class (`platform/agents/clue_agents/compaction.py:59-65`; deepagents' default removed by exact
class through the harness profile, `:136-141`). Thresholds (`build_compaction_middleware`,
`:107-133`): with a known window, trigger = `window × trigger_fraction` and keep =
`window × keep_fraction` tokens (`:113-115`; settings `agent_compact_trigger_fraction=0.90`,
`keep_fraction=0.10`, `settings.py:477-478`), else 170k tokens / 6 messages (`:54-56`). The
window comes from `compaction_for` (`platform/api/clue_api/agent_compaction.py:16-28`):
`CLUE_AGENT_CONTEXT_WINDOW_TOKENS` override → the registry (`x-ai/grok-4.6=500000`,
`.env.example:388`; `settings.py:698`) → catalogue; so Grok 4.6 compacts at **450k** and keeps
~50k, which no 2026-10-06 run (peak 205k) reached. `trim_tokens_to_summarize=None` (`:129`) so
the summary sees the whole evicted part. Trigger logic: langchain `_should_summarize`
(`langchain/agents/middleware/summarization.py:583-623`) fires when the counted tokens **or the
last reported usage** exceed the threshold; `_determine_cutoff_index`/`_find_token_based_cutoff`
keep the suffix that fits the keep budget and never split an AI/Tool pair (`:625-700`). It runs
in `before_model` and **rewrites state**: the evicted messages are replaced by a summary message
and offloaded to `/work/conversation_history/<thread>.md` (deepagents `summarization.py:613-614`
+ the `/work` remap). The `compact_conversation` tool (`SummarizationToolMiddleware`,
`compaction.py:133`, with `system_prompt=None` so the prompt stays byte-identical) lets the agent
trigger the same thing. Tests: `tests/agents/test_compaction.py:46-110`.

### 4.2 `ContextEditingMiddleware` / `ClearToolUsesEdit` (installed, unused)

`.venv/lib/python3.12/site-packages/langchain/agents/middleware/context_editing.py`:

- `ClearToolUsesEdit(trigger=100_000, clear_at_least=0, keep=3, clear_tool_inputs=False,
  exclude_tools=(), placeholder="[cleared]")` (`:58-77`). `apply` (`:79-156`): if the
  approximate token count of the messages exceeds `trigger`, every `ToolMessage` except the last
  `keep` whose tool name is not excluded is replaced by a copy with `content=placeholder`,
  `artifact=None` and `response_metadata.context_editing.cleared=True` (`:129-142`; excluded tools skipped at
  `:126`); with `clear_tool_inputs` the originating AI message's `args` are emptied too
  (`:143-147`, `:158-185`).
- `ContextEditingMiddleware.awrap_model_call` (`:257-292`) deep-copies `request.messages`
  (`:288`), applies the edits, and calls the handler with `request.override(messages=…)`
  (`:292`). **It edits the request only.** Graph state, and therefore the checkpoint, keep the
  original tool results; nothing is persisted about the edit except that the *sent* prompt is
  smaller — and the sent prompt *is* what `DurableAgentModelCallHandler.on_chat_model_start`
  persists as the call's input artifact (`agent_runtime_wiring.py:163-196`) and what Langfuse
  records. Consequences:
  - Replay/continuation/redelivery re-send the originals and re-clear identically
    (deterministic given the same messages), so a resumed turn is byte-equivalent after its first
    call.
  - The context receipt is unaffected (it records assembly, `clue_agents/context.py:965-975`).
  - `ToolRepairRoundsMiddleware` and `TurnBudgetMiddleware` read graph state, not the request —
    unaffected; `ToolRepairRounds` parses the *original* `ToolMessage` JSON for
    `governed_repair_budgeted` (`tool_recovery.py:32-46`), which a placeholder would hide, so
    clearing must stay request-only (it is).
  - The summariser counts tokens on state **but also** honours the last reported usage
    (`summarization.py:561`, `:598-603`), and the reported usage after clearing is the cleared
    size; so once clearing is on, token-based compaction effectively never fires on these runs
    (the plan's W1-1 note is correct).
- Where to install it: the bindings middleware tuple (`quality_research_wiring.py:743-751`),
  which lands after `TurnBudgetMiddleware` and before the summariser (`runtime.py:656-665`).

### 4.3 The duplicated opening prompt (L1)

`IdentityLayerSource.load` emits the profile's `system_prompt` as a `role="system"` candidate
(`clue_agents/context.py:275-299`), where `system_prompt = prompt_body + "\n\n" +
generated_resource_map` (`clue_agents/registry.py:348-349`); the assembler turns it into a
`SystemMessage` in `context.messages` (`context.py:800-801`, `:964-966`), and the runtime seeds
the graph state with those messages (`runtime.py:733-734`). Separately, `create_deep_agent`
receives `system_prompt=resolved_profile.prompt_body` (`:640`) and `ExactAgentToolSurface`
appends the resource map (`:189-194`). Every call therefore carries the prompt twice: as the
request's system message and as the first conversation message. The research assembler budgets
L1 at 24,000 bytes (`quality_research_wiring.py:376-383`). A continued Head-of-ABM turn skips
re-sending L1 (`context.py:900`; `_memory/2026-09-29-continuation-and-compaction.md`).

### 4.4 Prompt caching on OpenRouter / xAI — what the data says

The gateway sends no `cache_control`; it only reads `input_token_details.cache_read` back
(`clue_gateway/agent_model.py:976-987`; `usage: {include: true}` on the request, `:1131-1132`).
Caching is therefore the provider's implicit prefix cache: a call is cheap exactly when its
messages are a byte-prefix-extension of a recent call. On the 2026-10-06 runs
(`model-calls.csv`, 604 calls): after each run's first call, **13 of 592 calls were full misses**
(cached < 20 % of the previous call's context; e.g. Emily Wall round 7, 76,881 new / 128 cached
at 72k context; Alex Pace round 14, 103,305 new / 0 cached) and none were partial. Those 13 calls
re-billed 1.21 M of the 3.29 M "new" input tokens after round 1 (≈ $2.41 of $6.58 new-input
spend, ≈ 5 % of the $47.88 total). None was caused by an edit (nothing edits history on v25);
they cluster after long tool waits, i.e. provider-side eviction. Clearing arithmetic follows from
the prefix rule: the first call past `trigger` replaces every `ToolMessage` except the last
`keep`, so its prefix diverges at the **earliest cleared message** — one full-miss call at the
new-input rate (≈ `trigger × $2/M`, ≈ $0.20 at 100k on Grok 4.6) — and from then on each new call
only re-bills the suffix after the message that just left the keep window (the last `keep` tool
results plus the AI turns between them, a few thousand tokens), because the cleared view is
otherwise stable. Compaction is worse: it rewrites state once into a summary (one full miss of
the kept suffix) — acceptable, but it is why the plan prefers clearing. Nothing re-clears a
message that is already a placeholder (`context_editing.py:104-105`), and the placeholder text
is deterministic, so two workers computing the same request produce the same bytes.

---

## §5 Execution, replay and continuation semantics

### 5.1 Checkpointing a turn

`postgres_agent_checkpointer` yields an `AsyncPostgresSaver` per run
(`agent_execution_wiring.py:196-208`; tables owned by migration `4a94970221e9`, `:211-235`).
LangGraph checkpoints every superstep under `thread_id = execution_id`, `checkpoint_ns =
agent-turn:<turn_id>` (`runtime.py:791-795`), so the full message list, the constitution, the
context manifest and the middleware counters (`ClueDeepAgentState`,
`platform/agents/clue_agents/state.py:20-31`) are durable after each model call and each tool
node. A research execution id is `uuid5("research-quality:<job_id>")` and its turn id
`uuid5("research-quality-turn:<execution>")` (`quality_research_wiring.py:509-516`, `:881`), so
a re-driven job addresses the same thread. On redelivery `_run_turn` finds `current.values` and
resumes with `state=None` instead of re-inserting history (`runtime.py:742-752`; proven at the
runtime level by `tests/agents/test_runtime_continuation.py`); a job whose turn already committed
short-circuits on `load_committed_outcome` (`quality_research_wiring.py:902-908`).

### 5.2 What "replay" means for a tool

Three independent layers, innermost first:

1. **Domain idempotency** declared by `ReplaySafety` (`envelope.py:120-148`): policy
   (`effect_free | domain_idempotent | operation_idempotent | at_least_once | uncertified`), a
   stated durable identity, `operation_id_required` (mandatory for `operation_idempotent`,
   `:133-134`), and the external boundary. Uncertified tools cannot enter a recipe (`:218-220`).
   `acquire_research_evidence@1` is `DOMAIN_IDEMPOTENT` with `operation_id_required=True`
   (`quality_provider_tools.py:82-86`); its body keys the paid operation on
   `uuid5("arv2-operation:v1:<ws>:<job>:<kind>:<sha(request)>")` with `ON CONFLICT DO NOTHING`
   and a 2-hour lease (`research_operations.py:57-98`); losing the insert (`won=False`) runs the
   recovery path — re-index saved originals, serve the stored outcome, never re-purchase
   (`quality_provider_tools.py:154-187`).
2. **Journal replay**: the invoker's `journal.begin` returning `COMPLETED` serves the stored
   result with `replayed=True` without running the body (`invoker.py:239-245`); the runner's
   A9 store does the same within its TTL on the stable key (`runner.py:169-175`, `invoker.py:273`).
3. **Receipt recovery**: `recover()` rebuilds every receipt from `agent_tool_result` + the
   result artifacts (`agent_execution_wiring.py:2148-2241`), so a resumed graph can continue from
   the receipts it already has; a recovered failed node cannot be re-invoked (`executor.py:1608-1611`).

### 5.3 How a crashed run resumes

Fleet leases are 30 s (`platform/fleet/clue_fleet/lease.py:23`) renewed every 10 s
(`work_worker.py:157`, `_heartbeat` `:552-597`); a task is stale after 60 s
(`queue.py:51`). The takeover is fenced by `begin_job` (`account_research_store.py:309-337`):
the new lease holder claims `in_progress` too and bumps `attempt`; `finish_job`/`suspend_job`
write only `WHERE attempt = :attempt AND status = 'in_progress'` (`:339-404`), and the driver
turns a lost fence into `_JobSuperseded` → `WorkResult("superseded", requeue=True)`
(`account_research_driver.py:343`, `:1869-1882`). A superseded zombie's **non-status** writes
(claims, stage stamps, workspace files, provider ledger rows) are not fenced
(`_memory/2026-10-05-stranded-research-jobs-lease-takeover.md:55-56`). The research unit also
takes its own C5 work lease per execution (`quality_research_wiring.py:622-640`) and binds the
job's shared allowance idempotently (`bind_execution`, `quality_execution.py:37-146`: the saved
limits must equal the requested ones, `:102-118`).

### 5.4 What a code pre-step (A0 / A1 acquisition before the agent) must write

Trace of where it sits: `_run` claims the job (`account_research_driver.py:1161`), composes
(`:1173`), stamps stage `deep_research` (`:1177`), builds the `ToolRuntime` (`:1179`,
`:1257-1271`) and, inside the `_jobs` semaphore, calls the quality runner (`:1183-1190`), which
runs `ResearchUnitRuntime.run` (`quality_research_wiring.py:781-1140`): `install`/`prepare`
(execution row + recipe start, `:782-784`, `:586-621`), profile and model (`:785-794`), lease
(`:823-830`), the card/budget/manifest/task artifacts (`:845-879`), the turn row (`:900`),
bindings (allowance, authority, `:901`, `:688-755`), the committed-outcome short-circuit
(`:902-908`), `begin_runtime` (`:958-961`), context assembly and materialisation (`:962-979`),
the adapter and tools (`:1002-1078`), then the graph (`:1088-1118`).

For replay and resume to stay correct, a pre-step must:

1. **Issue every paid operation through `ToolRuntime.operate`** (`account_research_tools.py:698-728`):
   `operations.begin` makes the pair `(job, kind, request)` single-purchase, `_drain` lands the
   ledger rows, raw artifacts, evidence index and `operations.finish` in the hop's own
   transactions (`:596-687`), and a replayed call returns the stored body (`:721-728`). The
   request mapping must be byte-stable (canonical JSON fingerprint, `research_operations.py:27-30`).
2. **Persist its derived output (candidates, the acquisition ledger) as content-addressed
   artifacts bound to the subject** — `ResearchArtifacts.persist_body` with
   `subject_bindings` and `project_bindings` as the turn's own artifacts are (`:772-779`) — and
   record `artifact_derivation` rows from each evidence source to the candidates artifact, as the
   acquire tool does for its result (`quality_provider_tools.py:292-300`), so privacy erasure
   invalidates them (§7.3).
3. **Write a durable completion marker before the agent starts**, so a re-driven job (new
   `attempt`) neither re-extracts nor races: the natural one is `retain_artifact(reference_kind=
   "research_candidates", reference_id=f"{job_id}:{plan_sha}")` on the candidates artifact
   (the pattern `mark_account_import_ready` uses, `quality_person_release.py:51-56`), read back
   before the step and skipped when present. `set_job_stage` (`account_research_store.py:408`)
   gives the progress stamp (`acquiring` → `deep_research`).
4. **Run after `begin_job` and under the job's lease** (so the attempt fence and the lease
   heartbeat cover it) and **inside `async with self._jobs`** (`:1183`) so it counts as a research
   slot; its provider calls already ride the per-job semaphores and the AI Ark pacing lock
   (`:462-492`).
5. **Feed the turn, not the checkpoint.** The candidates reach the agent through the turn's
   context (§8c), which is assembled once per turn and verified on resume
   (`quality_research_wiring.py:962-979`); a resumed graph never re-assembles, so the pre-step's
   output must be final before `AgentTurnRequest` is created (`:880-899`).

### 5.5 `finalize_turn` and `check_finalizable`

`finalize_turn` (`agent_runtime_wiring.py:1287-1401`): validate the model's shape
(`ModelFinalizeRequest`, `:413-463`), then — in this order, deliberately —
`check_finalizable(status)` (`:1294`; `agent_execution_wiring.py:2096-2109`: only for
`completed`, refuses while `unresolved_interaction_failures` exist and asks for `retry_of`),
the required output file (`:1295-1303`), the surface's `CompletionGuard` (`:1304-1305`; for
research the guard builds `outputs/research.json` from the JSON dossier and the user message,
`quality_research_wiring.py:1013-1062`), persist message/assumptions/next actions
(`:1306-1350`), **freeze and empty `outputs/`** (`snapshot_outputs(empty_after=True)`, `:1351`),
build the envelope and commit it through `AgentFinalizationAuthority.finalize`
(`:1373`; `:676-750`, single-flight on `agent_finalization_commit`, `:752-799`). The 2026-10-03
McKee defect — a refusal after the snapshot — is why every refusable check now precedes it
(`_memory/2026-10-03-production-research-slowness.md:182-205`). The tool is `return_direct`
(`:1400`), so a committed finalization ends the graph; the runtime then trusts only `recover()`'s
`finalization_ref` (`runtime.py:832-856`, `missing_finalize` otherwise).

### 5.6 Attaching a deferred page write to a job

The continuation substrate is `quality_generation.py`: one `arv2_account_research_generation`
per account/context (`ensure_generation`, `:79-115`), children registered per person job
(`register_child`, `:185-212`), monotonic `signal`s with reasons `initial_settled | person_result
| claim_changed | media_changed | manual_refresh` (`:24-26`, `:215-265`), child results recorded
once per `(job, result digest)` (`record_child_result`, `:268-318`), and `pending_continuations`
(`:390-434`) which, for recipe ≥ 20, waits until every child is terminal or import-ready and no
newer generation exists (`:408-421`). The driver's `sweep_quality` runs every
`arv2_quality_reconcile_interval_s = 10` s (`settings.py:400`; loop `fleet_main.py:800-809`;
body `account_research_driver.py:907-1005`): it delivers claim invalidations, records missing
child results, releases `ready_person_jobs` (`:951-975`), and offers one continuation per account
lease with `only_if_work_idle=True` (`:983-1003`). Today the contact page is written inline by the
contact job before it settles (`_write_pages`, `:1796-1832` → `write_job_pages`,
`page_writer_runtime.py:618-664`), and `_account_dossier_for_person` → `read_parent_dossier`
raises when the parent has no `arv2_research_import_ready` row (`page_writer_runtime.py:405-416`;
`quality_person_release.py:107-179`), so a contact that finishes first ends `needs_review`
(`:1826-1831`). The per-page fleet kind `arv2_display_page`
(`platform/api/clue_api/arv2/display/fleet_handler.py:106-195`) has the right *properties* for a
deferred page — `reopen_terminal=True`, dedup per subject/page
(`account_research_driver.py:2046-2095`), priority −80 (`arv2/fleet_task.py:69`) — but the wrong
*writer*: its handler is `ensure_page`, the claim-driven Luna block writer (`:132`), and the
frontend read never serves Luna blocks for a subject that has a quality context — it reads the
quality page and, failing that, composes an empty block rather than fall through
(`frontend_read/display_pages.py:349-375`). The research kind's own `handle()` already dispatches
on `payload["continuation"]` (`account_research_driver.py:518-519`), which is where R11 puts the
deferred write (§8f).

---

## §6 Budgets and limits — what is global, per job, per role

| Limit | Where | Scope |
|---|---|---|
| Model rounds | `Allowance.model_calls = CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS` (350, `settings.py:447`) → `arv2_quality_allowance.max_model_calls` (`quality_execution.py:86-100`) and `TurnBudgetMiddleware(max_rounds=limits.model_calls)` (`quality_research_wiring.py:1102`, `:753`); ceiling `MAX_RUNTIME_MODEL_ROUNDS = 500` (`execution.py:62`) | **per job**, one setting for account and person; the profile's `max_model_rounds: 100` (`v25/profile.yaml:101`) is carried by the registry (`registry.py:647`) but not read by the research runtime |
| Tool calls | `Allowance.tool_calls = rounds × CLUE_ARV2_ACCOUNT_MAX_TOOL_CALLS_PER_ROUND` (350 × 50, `:1235-1236`; `settings.py:450`), reserved per call (`quality_execution.py:147-227`) | per job |
| Runtime | `Allowance.runtime_ms = CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S × 1000` (0 = none, `settings.py:454`); `runtime_remaining` checked at every admission (`:275-294`) | per job |
| Finalize repairs | 2, or 10 on a continued conversation (`runtime.py:88`, `:529-535`) | per turn |
| Tool repair rounds | 10 batches (`tool_recovery.py:12`) | per turn (graph state) |
| Plan shape | `AgentPlanPolicy.from_profile`: `max_fanout=8`, `max_parallelism=8`, depth 16 (`execution.py:94-115`); `max_plan_nodes: 64` (`profile.yaml:99`); the recipe slot's `max_children` | per execution |
| Provider concurrency | `_semaphore(provider)`: 1 for `ai_ark`/`media`, else `CLUE_ARV2_ACCOUNT_PROVIDER_CONCURRENCY` (4) (`account_research_tools.py:216`, `:567-575`; `settings.py:459`); held across the whole hop **including `_drain`** (`:500-565`) | per job, per provider |
| AI Ark pacing | `pg_try_advisory_xact_lock("ai-ark:<token>")` + `sleep(CLUE_ARV2_AI_ARK_MIN_GAP_S = 10.5)` inside the lock (`:462-492`; `settings.py:403`) | **global per API token**, cross-process |
| Jobs per process | `_jobs = Semaphore(CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS)` (4) = `max_in_flight` (`account_research_driver.py:505-512`), honoured by the worker (`work_worker.py:282-287`) | per process |
| DB connection | `_db_lock` — one data connection for **every job in the process** (`:504`, `:1017-1019`; module docstring `:20-26`) | per process |
| Worker slots | `CLUE_FLEET_WORKER_CONCURRENCY` (3 in `.env.example:334`; 10 on the VM chat worker, `deploy/vm/compose.yaml:57`); 3 `batch` processes (`:66-68`) | per process / fleet |
| Thread pool | `CLUE_FLEET_THREAD_POOL_SIZE=128` (`settings.py:270`; `fleet_main.py:848`) — every sync provider call runs here | per process |
| DB pool | `pool_size=5`, `max_overflow=10`, `pool_timeout=30` (`libs/clue-db/clue_db/engine.py:101-106`; `.env.example:20-22`); pgbouncer **transaction** mode in front (`compose.yaml:25-28`) | per process |
| Context | compaction at `window × 0.90` (§4.1); no per-role window, no clearing | per model |
| Head of ABM rounds | `CLUE_HEAD_OF_ABM_MAX_MODEL_ROUNDS` (350, `settings.py:469`) | per turn |

**What has to change for per-role budgets:** `build_quality_job_runner` builds one `Allowance`
from the account settings regardless of `scope.subject_kind` (`quality_research_wiring.py:1233-1238`);
the allowance table is already per job, so a person lane only needs its own settings pair
(03 §10's `CLUE_ARV2_V26_PERSON_MAX_MODEL_ROUNDS` / `…_MAX_OPERATIONS`, with `.env.example` parity) chosen by
subject kind at `:1233`. `TurnBudgetMiddleware` and the DB allowance then follow. There is no
"operations" budget today: the tool allowance counts framework reads and dossier writes alike;
a provider-operation cap must count `arv2_research_operation` rows (`research_operations.py:260-270`
is the per-job state read) or add a column to `arv2_quality_allowance`. A per-role context cap
needs `compaction_for` to accept the role (today `model_id` only, `runtime.py:515`, `:619-623`;
`agent_compaction.py:16-28`) and the clearing trigger to be set per bindings (§4.2).

---

## §7 Cost accounting and telemetry for a new sub-call

### 7.1 What exists

- **`agent_model_call`** — one row per governed model call, written by
  `DurableAgentModelCallHandler` (`agent_runtime_wiring.py:137-290`): the full input message
  list is persisted as an artifact on start (`:163-196`), the output on end (`:241-245`), with
  `input_tokens, cache_read_input_tokens, cache_creation_input_tokens, output_tokens, cost_usd,
  cost_source, role, langfuse_trace_id/observation_id, latency_ms` (`:198-262`; insert
  `agent_turn_wiring.py:689-740`). `role` = the gateway's `clue_role` or the constitution role
  (`:120-134`).
- **`provider_call_ledger`** — estimate + result rows per provider call (`calls.py:965-1009`),
  drained by `drain_provider_calls` with the job stamp (`ledger.py:233-287`, columns `:59-71`).
- **Langfuse** — one `fleet.task` root trace per job (R3), generations from the SDK handler with
  the gateway's cost stamp (`langfuse_handler.py:38-83`), `governed.<tool>@<v>` spans from the
  invoker (`invoker.py:191-205`), `<provider>.<operation>` spans/generations from
  `ProviderCaller` (`calls.py:390-400`).
- **The job meter** — `quality_meter.usage` sums `provider_call_ledger.cost_usd/credits/
  media_seconds` by `entity_research_job_id` (`quality_meter.py:39-48`) and `agent_model_call`
  via `arv2_quality_execution` (`:49-58`), reads the allowance counters (`:59-65`), and the
  driver stamps the result on the job row and the finalization (`account_research_driver.py:1842`,
  `:1866`, `:1869-1881`).

### 7.2 How a new sub-call would be seen

| Mechanism | `agent_model_call` | `provider_call_ledger` | Langfuse | Meter / spend cap | Allowance |
|---|---|---|---|---|---|
| Extraction via `ProviderCaller` inside a tool (`structure_material` precedent, §2.3) | no | yes, `provider='openrouter'`, job-stamped, `cost_usd` metered | generation `openrouter.chat/completions` under the tool span | counted (provider sum, `quality_meter.py:39-48`) | not a model call; the enclosing governed tool reserved one `tool` |
| Extraction via a second `GovernedAgentChatModel` (a sub-graph) | yes, role-attributed, cache tokens | no | generation under the graph | counted via `arv2_quality_execution` only if the sub-call runs under the job's execution id (`:49-58`) | reserves `model` allowance only if `SharedResearchAllowance` wraps it |
| Code-issued acquisition via `ToolRuntime.operate` (A0/A1) | no | yes (`_drain`) | provider spans only — inside the job trace because the fleet task root is open | counted | **nothing** — no `governed.*` span, no `agent_plan_operation`, no `agent_tool_result`, no `arv2_quality_activity` reservation |

### 7.3 Operations issued outside the governed journal — consequences, verified

`ToolRuntime.operate` writes `arv2_research_operation` (`begin` `:708`, `finish` inside
`_drain` `:661-670`), the provider ledger and raw artifacts (`:607-618`), and the evidence index
(`index_acquisition`, `:681-687`). It does **not** write `agent_plan`/`agent_plan_operation`/
`agent_tool_result`/execution node events, does not open a `governed.*` observation, does not
reserve the tool allowance, and does not bind a tool-result artifact to the subject or record
derivations from the sources to a derived result (the acquire tool does both,
`quality_provider_tools.py:271-300`).

- **Replay:** still single-purchase per `(workspace, job, kind, request_sha)`
  (`research_operations.py:64-66`, `:76`); a re-driven pre-step re-issues the same requests and
  reads the stored bodies (`:170-206`). Anything derived (candidates) must carry its own
  idempotency (§5.4 item 3) — the journal would not do it.
- **DSAR / privacy stop:** `stop_contact_jobs` marks the operation artifacts erased by job
  (`:302-314`) and evidence rows are job-keyed, so acquisition is covered; a candidates artifact
  holding quoted personal text is covered **only** if it is recorded with `artifact_derivation`
  from its sources (the acquire tool's rule, `quality_provider_tools.py:292-300`) and a subject
  binding — otherwise it is the same class of residue as the `faithfulness_verdict.rationale`
  gap in `CLAUDE.md` ([M10.5×M9.3]). The same holds for an extractor call made through
  `call_provider` with no operation of its own (review A K3): `drain_provider_calls` persists its
  raw request/response envelope as an artifact (`ledger.py:258-266`), `index_acquisition` skips
  `openrouter` rows by design (`quality_acquisition.py:53`), and nothing binds that envelope —
  whose *request* carries the source text, quoted personal text included — to the subject. §8b
  makes the `acquire_research_evidence@2` body bind it.
- **Cost attribution:** complete in the ledger and the meter; Langfuse provider spans attach to
  the job trace because the pre-step runs inside the fleet task; what is lost is the per-call
  `governed.*` disposition and the tool card stream (`agent_runtime_wiring.py:923-930`,
  `:1014-1023`), neither of which the judge needs.
- **The agent's view:** `recover()` rebuilds receipts from `agent_tool_result`, so pre-step
  operations never appear as receipts; the judge must be told about them through the acquisition
  ledger file the plan already specifies (§2 C-account), which is also where "not found" items
  cite their operation ids.

---

## §8 Design constraints and the mechanism for each v26 need (recommendations)

Each item names the mechanism that fits the runtime, what must be re-minted, and the test that
proves it. Where this document and 03/04 diverged, the orchestrator's `RECONCILIATION-RULINGS.md`
decided; the adopted mechanism is recorded here with the ruling, the reason, and the code that
confirms it sound. Settings are named only by reference to 03 §10's single sheet (R7); recipe
integers follow R2 (r26 = week-1 mint, r27 = pipeline).

### (a) Acquisition pre-step in the driver (A0 committee, A1/A2 acquire, A3 follow-ups)

**Mechanism.** A new `arv2/acquisition_plan.py` executed from `ResearchUnitRuntime.run`
*between* `bindings` (`quality_research_wiring.py:901`) and the task artifact (`:867-879`,
moved after it), not from `_run` in the driver: at that point the job is claimed and fenced
(`account_research_driver.py:1161`), the `ToolRuntime` exists (`:1179`), the execution, lease
and allowance exist (`:782-784`, `:823-830`, `:901`), and the turn has not been assembled, so
the candidates can still enter the opening context (§5.4 item 5). Operations go through
`ToolRuntime.operate` — one `asyncio.gather` per subject bounded by the existing per-provider
semaphores and the AI Ark lock — with the journal bypass recorded (§7.3) and mitigated by
subject-bound, derivation-linked artifacts (§5.4 item 2) and the `retain_artifact` completion
marker (§5.4 item 3; two markers per R5 — the first pool after A1+B, the final pool after the
gap round — named per C9 `research_candidates…:<job>:<plan_sha>`). A0 reuses
`NominateCommitteeTool`'s body — `submit_proposal`, `link_selection_claim`, `save_person_brief`,
`create_job`, `register_child` (`arv2/quality_committee_tool.py:158-222`) — as a plain function
called with the service authority, so the person job rows exist before the account turn starts.
**They are born `not_started` and offered by the driver's 10 s sweep** (`ready_person_jobs` →
`enqueue_launched_jobs`, `account_research_driver.py:951-975`), not by the pre-step:
`ResearchUnitRuntime` is composed with `connections=transaction` and no queue
(`fleet_main.py:790-792`); the queue belongs to the driver (`account_research_driver.py:2490`)
(review A K2/C38; 04 W3-21). *Why not the governed invoker for the pre-step:* it would need an
appended C5 node per operation (`executor.py:996`) and a plan per call, i.e. the ≈ 3.3 s +
0.7–1.8 s envelope of §1.4 on ~100 operations with no model in the loop to benefit from the
receipts.

**Re-mint:** none for the pre-step itself; the r27 profile/recipe (§2.1) for the judge that
consumes it. **Settings:** 03 §10's sheet and 04 P5's pilot selector (C2); this document names
none of its own.

**Test.** An offline driver test in the `tests/arv2/test_account_research_driver.py` style with
`ScriptedTransport` (`clue_api/arv2/transport.py`, as used by
`tests/arv2/test_quality_provider_db.py:13-24`): drive once → N `arv2_research_operation` rows
`succeeded`, one candidates artifact with `artifact_derivation` rows from every source, the
`research_candidates` reference; kill and re-drive with a bumped attempt → zero new transport
calls, identical candidates sha, the agent turn starts once; the person rows exist
`not_started` and one sweep offers each exactly once.

### (b) Extraction inside the acquire tool, returning candidates

**Mechanism (adopted: R12, R13).** `acquire_research_evidence@2`, **minted once, in W1 (r26),
with the r27 shape already present**: `AcquireResearchReceipt2` adds `candidates:
list[Candidate]` — empty until W3-23 fills it — and `ledger: {operation_id, kind, result_count,
http_status, error_code}` (R13). Its `invoke` keeps every step of `@1`
(`quality_provider_tools.py:124-315`) and, on r27, after `tool.ainvoke` (`:202`) and before the
result artifact (`:259`), runs the extractor through the **same** hop path as the structuring
pass: `runtime.call_provider("extract", hop)` where `hop` builds an `openrouter_chat_request`
and sends it with `ProviderCaller.call(CallSpec(provider="openrouter",
operation="chat/completions", label="extract-<op>", estimate=…, cost_reader=
openrouter_cost_reader, halt_rule=openrouter_halt_rule))` exactly as
`structuring_client.py:1191-1211`. The hop runs on the thread pool, off the loop
(`account_research_tools.py:532`); the `"extract"` semaphore key gives extraction its own
per-job concurrency, and 03 §10 / 04 §9's one table (C19) adds the per-process semaphore and
bounds that §6 shows are otherwise missing (6 jobs × 8 would be 48 OpenRouter streams); the
wire-provider halt latch still propagates through `self.halted.setdefault(halted.provider, …)`
(`:542`). The candidates are stored **inside the operation's result value**
(`value["candidates"]`, `:259-270`) so the `won=False` replay path serves them unchanged
(`:165-178`), and surface in `reference_values` capped by count (03 §3.6.3: ≤ 20 items, ≤ 20
candidates, ≤ 10 KiB) to stay under the 12 KiB spill line (`execution.py:57`) — the full list is
the result artifact, read by an r27 judge at `/research/operations/<id>/candidates.json` (03 §3.6.1). Each candidate's quote is checked by `substring_verdict`
(`arv2/text.py:44-67`, extended per R8) against the stored source text (`exa_source_texts`,
`quality_acquisition.py:269-281`) before it is returned; a failed quote becomes a dropped
candidate, never a raised error (a raise is a failed node that blocks `check_finalizable`, §5.5).
**The extractor's raw envelope must be bound** (review A K3): `drain_provider_calls` persists it
as an unbound artifact (`ledger.py:258-266`) and `index_acquisition` skips `openrouter` rows
(`quality_acquisition.py:53`), so the acquire body inserts, in the same transaction as its own
bindings (`:271-300`), an `agent_artifact_subject` row for the envelope and `artifact_derivation`
rows from the source artifact → envelope → operation result; otherwise the request body (the
source text) is a DSAR residue of the `[M10.5×M9.3]` class. *Why not a new `AgentRole` for the
extractor (R12):* `AgentRole` is the deepagent registry's key (profiles, authority audit
`agent_registry_wiring.py:960-1021`, attribution); the extractor is a leaf call in Doc A's sense
(§1.5 "LLM leaf calls inside engines"). Model and effort follow the page writer's precedent —
`RESEARCH_EXTRACT_AGENT_MODEL` / `_EFFORT` read like `page_writer_runtime.py:98-106`, falling
back to `CLUE_ARV2_EXTRACT_MODEL` with 04's documented default (C18, D4) — with a context-window
entry in `CLUE_AGENT_MODEL_CONTEXT_WINDOWS` so the guard test passes. Cost lands in
`provider_call_ledger` with the job stamp and in the meter (§7.2); Langfuse shows it as a
generation under the `governed.acquire_research_evidence@2` span.

**Why R13 is sound in this runtime.** `ToolOutput` is `frozen, extra="forbid", strict=True`
(`envelope.py:77-80`) and the references are validated in JSON mode (`runner.py:53-69`), so a
defaulted empty `candidates` list validates on r26 exactly as a filled one does on r27; the
output sha is computed from the model's JSON schema (`envelope.py:168-170`, `:379`) and pinned
once by the r26 profiles, and r27 re-pins the same sha because the shape does not move. The one
condition: the `Candidate` model — with R9's `entities[]` and the `follows` operation id — must
be **final at the r26 mint**; a later field changes the sha, which r27 would absorb (it is its own
mint) but RC-1 on r26 would then be measuring a receipt shape r27 changes. On r26 the receipt
stays a few hundred bytes (empty list); on r27 the inline cap keeps it under the spill line.

**Re-mint:** `@2` registered beside `@1` in `quality_tools` (`:249-251`), pinned by the r26
profiles and `recipe-v26.json` (W1), carried unchanged into r27;
`tests/arv2/test_quality_json_dossier.py:16-60` updated for each mint.

**Test.** `tests/arv2/test_quality_provider_db.py` pattern: `ScriptedTransport` with one Exa
`search` response and one OpenRouter extraction response → the receipt's
`references["candidates"]` each pass `substring_verdict` against the indexed source; one
`provider_call_ledger` row `provider='openrouter'` with `entity_research_job_id`; the extractor
envelope artifact carries a subject binding and a derivation from the source; a second `invoke`
with the same arguments makes no transport call and returns `replayed=True` with the same
candidates; a candidate whose quote is not in the source is absent and counted in
`ledger.dropped`; on r26 (extraction off) the same receipt validates with `candidates == []`.

### (c) Candidates in context vs file — both, deterministically

**Mechanism.** The opening pool (A1/A2 candidates + the acquisition ledger) rides the **L7 task
message**: the `agent-turn-input` artifact (`quality_research_wiring.py:867-879`) carries the
candidates JSON inline, and the same bytes are materialised read-only as
`inputs/candidates-<kind>.json` through a `ContextCandidate(materialized_path=…)` emitted by
`_Contexts.assemble`'s L5 source (`:353-388`; `clue_agents/context.py:144-158`, `:949-957`), so
`grep`/`read_file` work without a second copy (names per C9: `inputs/candidates-<kind>.json`;
per R5 the contact judge waits on the account's *first* pool marker and the account judge on the
children's, receiving the people slice). Follow-up candidates (the judge's own
`acquire_research_evidence@2` calls) arrive as `ToolMessage`s under 12 KiB — and, per R6, are
cleared like any tool result once outside the keep window (§8d). *Why the task message
and not a file the judge reads:* a message in the opening prefix is cached after the first call,
never cleared by `ClearToolUsesEdit` (it only edits `ToolMessage`s, §4.2), journaled as L7 with
its sha, byte-identical on resume, and costs one read of ≈ 12–20k tokens instead of a `read_file`
round whose result is line-numbered, 80k-char-capped and then cleared. The 100 MB trace ceiling
is served by the smaller per-call context, not hurt: the pool is sent once per generation inside
the prefix, the same as any system/user text.

**Test.** `tests/agents/test_context.py` style: the assembled research context for a job with a
candidates artifact contains one L7 human message whose body embeds the artifact bytes and one
L5 materialisation at `inputs/candidates-account.json` with the same sha; `materializer.verify_
materialized` on a second lease passes.

### (d) Tool-result clearing + per-role window

**Mechanism (adopted: R6 = 03 §5.3; this document's earlier exclusion of the acquire tool is
withdrawn).** Append `ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=T_role,
keep=4, clear_tool_inputs=False, exclude_tools=("submit_brief", "finalize_turn"),
placeholder="[cleared — candidates remain citable by id; full list at
/research/operations/<op>/candidates.json]")])` to the bindings middleware in `bindings()`
(`quality_research_wiring.py:743-751`) so it runs after `TurnBudgetMiddleware` and before the
summariser (`runtime.py:656-665`); `T_role` = 03 §10's `CLUE_ARV2_V26_ACCOUNT_CLEAR_TRIGGER_TOKENS`
(45,000) / `…_PERSON_…` (42,000), keep = `CLUE_ARV2_V26_CLEAR_KEEP_RESULTS` (4), chosen by
`scope.subject_kind` at `:743`. **Acquire receipts are cleared like any tool result; the
candidates pool is never cleared** because it is not a `ToolMessage` (§8c). *Why acquire
receipts must be clearable (03 §5.3's arithmetic):* with the pool in the L7 prefix, 20
investigative rounds × ~3k tokens of receipts that can never leave is 60k on top of a 36k
opening — past the 60k cap by round 9; cleared, the steady state is opening + 4 kept receipts +
AI turns ≈ 56k worst case. The per-role **context cap** is applied where compaction is sized:
wrap `compaction_for` at `:1090` so the window handed to `CompactionSettings` is `min(model
window, CLUE_ARV2_V26_<ROLE>_CONTEXT_CAP_TOKENS)` — the runtime's seam already takes any
callable (`runtime.py:515`, `:619-623`) — and the settings comment states that, with clearing
on, the summariser is a backstop that will not fire on reported usage (§4.2). Nothing is
re-minted: operator settings, not profile content (the comment at `settings.py:465`).

**Confirmed sound from the code — clearing acquire receipts cannot break replay or the context
receipt.** (1) `ClearToolUsesEdit.apply` considers only `ToolMessage`s (`context_editing.py:89-94`)
and matches `tool_message.name or tool_call["name"]` against `exclude_tools` (`:126`), so
acquire receipts are cleared and the L7 pool is untouched. (2) The edit is applied to a **deep
copy** of the request and handed to the model through `request.override` (`:288-292`); graph
state — and therefore every checkpoint — keeps the originals, so a redelivered or continued turn
(`runtime.py:742-752`) re-sends the originals and re-clears to the same bytes (the placeholder is
constant, the candidate set is a pure function of the message list). (3) Tool replay never reads
messages: `operation_id` derives from the LangChain `tool_call_id` (`agent_runtime_wiring.py:902`,
`execution.py:242-245`), journal replay and the A9 key are keyed on it (`invoker.py:239-245`,
`:273`), and `recover()` rebuilds receipts from `agent_tool_result` plus the result artifacts
(`agent_execution_wiring.py:2148-2241`). (4) The context receipt is written at assembly, before
the graph runs, and records the L1–L7 candidates — never tool results — so it is unaffected
(`context.py:965-975`). (5) `ToolRepairRoundsMiddleware` parses the *state* `ToolMessage`s for
`governed_repair_budgeted` (`tool_recovery.py:24-46`), `_bounded_finalize` reads
`request.state` (`runtime.py:268-276`) and `PatchToolCallsMiddleware` reads state
(`patch_tool_calls.py:14-17`) — none sees the placeholder. (6) The `agent_model_call` input
artifact records the **cleared** request (`agent_runtime_wiring.py:163-196`), so "what did the
model see" stays truthful, and Langfuse generations shrink accordingly. **What it does change,
and what covers it:** the judge can no longer *see* a cleared receipt's candidates, so
`submit_brief@1` (R3) must resolve candidate ids server-side from the stored operation results
(03 §5.3 (a)) and the placeholder must name the view path (03 §5.3 (b)); the reasons of a cleared
*refused* call are out of view too, while the repair budget is still counted from state. Neither
touches replay or the receipt.

**Test.** `tests/agents/test_compaction.py` harness (`:21-45`): a graph with a
`FakeMessagesListChatModel` and seven tool results past the trigger, three of them acquire
receipts → the request the model receives shows `[cleared …]` on all but four (acquire receipts
included) and the L7 message intact; `graph.aget_state` still holds the originals; the
`agent_model_call` input artifact for that call contains the placeholders;
`ToolRepairRoundsMiddleware` still counts a budgeted failure in the cleared window; a second
invocation on the same checkpoint produces a byte-identical request.

### (e) Per-role budgets (rounds 20/12, operations 30/15)

**Mechanism.** Two `Allowance`s built from subject-kind settings at
`quality_research_wiring.py:1233-1238` (03 §10: `CLUE_ARV2_V26_ACCOUNT_MAX_MODEL_ROUNDS` 20 /
`…_PERSON_…` 12, `…_MAX_OPERATIONS` 30 / 15); the DB
allowance and `TurnBudgetMiddleware` follow without further change (§6). The operation budget
is enforced **inside `acquire_research_evidence@2`** as a durable, non-spending refusal value
(`{"state": "refused", "code": "operation_budget_exhausted"}`, the shape the tool already uses
for `invalid_acquisition_arguments`, `quality_provider_tools.py:191-199`) after counting the
job's `quality_tool:*` rows in `arv2_research_operation` (`research_operations.py:260-270`)
under the same transaction as `operations.begin` (`:151-153`). *Why a returned refusal, not a
raise:* a raise is a failed node — it costs a repair round and blocks finalization until
`retry_of` (`agent_execution_wiring.py:2096-2109`); a refusal value is a completed operation the
judge can read and move on from. *Why not a new allowance column:* no migration, and the
count is the ledger the judge already cites.

**Test.** Extend `tests/arv2/test_quality_provider_db.py`: with the cap at N, the (N+1)-th
acquire returns `status: refused, error_code: operation_budget_exhausted`, makes no transport
call, writes no `arv2_research_operation` row with a new request, and `check_finalizable`
accepts a later `completed` finalization.

### (f) Deferred contact page write (P1 / W1-8)

**Mechanism (adopted: R11 = 04 §0.5 / P1; this document's display-kind task is declined).**
Release contacts at nomination for recipe ≥ 26 (a `TRUE` branch in `ready_person_jobs`'s
`CASE`, `quality_person_release.py:88-92`). A contact job's settle no longer writes its page
(`_write_pages`, `account_research_driver.py:1796-1832`, returns early for `defers_contact_page
(scope)`); instead `_settle_quality` offers, **only when** the parent's
`arv2_research_import_ready` row exists, one task on the **research** kind:
`enqueue(kind=ARV2_ACCOUNT_RESEARCH, work_id=WorkId(job_id), dedup_key=
f"arv2:contact-page:{job_id}:{ready_version}", priority=-80, payload={"continuation":
"contact_page", …}, reopen_terminal=True)`; when the parent is not ready, nothing is enqueued and
the 10 s sweep (`sweep_quality`, `:907-1005`) gains a `contact_pages_due` selection beside
`ready_person_jobs` that offers the same task once the parent's `READY_KIND` reference exists and
no current contact page does. `handle()` gains `continuation == "contact_page"` →
`_contact_page_continuation`, which composes from the pins, checks readiness, and runs
`page_writer_runtime.write_job_pages` under `_jobs`. *Why not the display kind:* its handler is
`ensure_page`, the claim-driven Luna writer, whose blocks the frontend read never serves for a
quality subject (`frontend_read/display_pages.py:349-375`; §5.6), and the recipe-25 page writer
is composed only in the research handler (`account_research_driver.py:2482-2484`).

**Confirmed sound from the code.** (1) *Idempotent per subject/page with `reopen_terminal=True`:*
`enqueue_task` is `ON CONFLICT (kind, work_id, dedup_key) DO NOTHING` (`queue.py:184`; the
constraint is `fleet_task_dedup UNIQUE (kind, work_id, dedup_key)`,
`alembic/versions/d9b39fb407ed_c5_3_generic_work_fleet.py:48`); with `reopen_terminal=True` the
statement is `_ENQUEUE_REOPEN_SQL`, which re-opens only a `done`/`failed` row on the same key and
leaves a queued/claimed one alone (`:195-213`, `:460`). A repeated offer of the same
`ready_version` is therefore a no-op while the task is live and a re-open once it is terminal —
which is exactly why 04 P1 step 4's `contact_pages_due` must exclude subjects whose page is
already current (it does), or every sweep tick would re-open a done task. (2) *The dispatcher:*
`handle()` branches on `payload["continuation"]` before it parses the job scope
(`account_research_driver.py:518-519`), and its work-id check (`:534-545`) requires
`work_id == job_id`, which P1 keeps; the existing `quality_reconciliation` continuation is the
precedent (`:579-716`). (3) *Lease and slot:* the page task shares the contact job's work id, so
it shares its lease and its `max_in_flight` slot (`work_worker.py:282-287`): a re-driven research
task and the page task serialise (correct), and the page occupies one of the four research slots
for its ~1–2 min (04 accepts this). (4) *No interference with the other sweep offers:*
`only_if_work_idle` cannot be combined with `reopen_terminal` (`queue.py:458-459`) and P1 does
not combine them; the reconciliation offers use `only_if_work_idle` on a different work id
(`continuation_work_id`, `quality_generation.py:43-49`). (5) *Readiness and failure:*
`read_parent_dossier` raises without the parent's `READY_KIND` reference
(`quality_person_release.py:107-179`); the continuation checks readiness first and returns
`failed/parent_not_ready` with `requeue=False`, leaving the re-offer to the sweep — no requeue
storm. (6) *Priority:* −80 (`fleet_task.py:69`) sorts after research's −100 (`:39`; lower is
sooner), so pages yield to research. **Residual (recorded, not fixed):** the page's ledger rows
are job-stamped but land after `finish_job` wrote `cost_usd`, so the meter's ledger sum carries
them and the job row does not (04 P1 says so; the same as today's rewrites).

**Test.** As 04 P1: extend `tests/arv2/test_quality_person_release_db.py:103` — at r26 a child
that settles before `FinishDossierTool` on the parent produces **no** `arv2:contact-page:*`
task; after the parent's `finish_dossier`, `contact_pages_due` returns the child, one sweep
offers exactly one task, a second sweep offers none, and after the page is published a third
sweep re-opens nothing. Offline (`tests/arv2/test_account_research_driver.py` style): a
`continuation == "contact_page"` payload with a missing parent-ready row returns
`failed/parent_not_ready` without calling the writer; with it present, calls `write_job_pages`
once and returns `completed`.

### (g) Per-section parallel page writer

**Mechanism.** Keep `page_writer_runtime` as the owner (its views, `write_checked` repair loop,
`publish_written`), but change `write_account_pages`/`write_contact_page`
(`page_writer.py:300-356`) from one request for all sections into one `write_checked` per
section over `display/recipes.PAGES`' section recipes (`display/recipes.py:18` and the per-page
recipe rows), gathered under `asyncio.Semaphore(settings.arv2_display_max_parallel)` exactly as
`display/page.py:417-421` and `_write_section` (`:233-296`) do, each section fed its per-section
slice of the brief. Publish per section with `publish_page(... sections=(section,))`, the
single-section draft shape `quality_pages.py:460-463` already uses, so a stale-input refusal
(`:288`) and the "skip when `page_inputs().sha256` is unchanged" check of W1-10 stay per section.
The model call stays the `ProviderCaller`-on-a-thread `ModelCall` (`page_writer_runtime.py:109-173`),
so every section is a ledger row and a Langfuse generation under `research.page_writer`
(`:633-641`). *Why not move pages wholesale to the display module:* its recipes write from
claims, the v26 brief is dossier JSON with interpretations; the display module's concurrency
pattern is what to reuse, not its inputs.

03 §6 aligns with this; the contact page reaches the same writer through (f)'s continuation.

**Test.** `tests/arv2/test_page_writer_runtime_db.py:210` pattern: an account with the brief
→ N section drafts, N `publish_page` calls, a changed single section republishes only that
section; replay through `scripts/trial_page_writer.py` (the 2026-09-26 trial, `:285-300`) for
the timing claim.

---

## Appendix — how the §1.4 numbers were produced

For each `langfuse-observations/*.json` (12 runs, 603–1,300 observations each), build the
parent→children map from `parentObservationId`; for every `acquire_research_evidence` TOOL
observation take its child `governed.acquire_research_evidence@1` (the invoker observation,
`invoker.py:191-205`) and its other child (the inner provider tool run), and the inner run's
children (`exa.*`, `ai_ark.*`, `greenhouse.*`, `live_http.*`, `public_media.*` — the
`ProviderCaller` observations, `calls.py:390-400`); phases are the start/end deltas between
those four spans. "Solo" = no other acquire call started within 2 s in the same run; "batched"
= at least four did. 210 of 225 calls had all four spans with end times. Cache-miss counts are
from `model-calls.csv` (`new_input_tokens`, `cached_input_tokens` per call) with a miss defined
as cached < 20 % of the previous call's `context_tokens`.
