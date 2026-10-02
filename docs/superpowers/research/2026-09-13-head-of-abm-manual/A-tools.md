# Head-of-ABM — the complete tool surface on the production project conversation

Read-only study, 2026-09-13, branch `research-streaming`, worktree `san-salvador`.
Everything below is read off the code, not off the docs.

## What fixes the surface

| Thing | Value | Source |
| --- | --- | --- |
| Profile pinned in production | `head-of-abm@v49` (`PROJECT_CONVERSATION_AGENT_PROFILE_ID`) | `platform/api/clue_api/chat/composer_context.py:43` |
| Profile file | `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml` | — |
| Prompt pin | `head-of-abm` `v8`, sha256 `0d942eb5…6cc3` | profile.yaml |
| Skill pin | `stage0-interview` `v26`, sha256 `0044e38d…73b5` | profile.yaml |
| Model | `x-ai/grok-4.6`, `timeout_s: 30.0`, `max_retries: 2`, `max_output_tokens: 8192`, `temperature: 0.1` | profile.yaml |
| Round budget | `max_model_rounds: 24`; LangGraph `recursion_limit = max_rounds * 2 + 4` | profile.yaml; `platform/agents/clue_agents/runtime.py:280` |
| Turn timeout | `turn_timeout_s: 300.0` | profile.yaml |
| Money budget per turn | `PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS = 1_000_000` (= $10.00) | `platform/api/clue_api/agent_turn_fleet_wiring.py:190` |
| Surface name | `project_conversation` (`PROJECT_CONVERSATION_SURFACE`) | `platform/api/clue_api/agent_registry_wiring.py:412` |
| Surface withheld tools | `frozenset()` — **nothing** is withheld from this surface at v49 | `agent_registry_wiring.py:541-565` |
| Surface withheld delegation roles | `{RESEARCH, CONTENT_DRAFTER, REVIEWER}` — i.e. **all of them** | same |
| Withheld reason code | `project_conversation_no_autonomous_research` | same |
| Max governed-tool refusals per turn | `_MAX_GOVERNED_TOOL_FAILURES = 3` (4th refusal raises and kills the turn) | `platform/api/clue_api/agent_runtime_wiring.py:92, 905-916` |
| Max finalize repairs per turn | `_MAX_FINALIZE_REPAIRS = 2` (one per independent rejector: shape contract + completion guard) | `platform/agents/clue_agents/runtime.py:57` |

The surface's own framing sentence, injected into the agent's resource map
(`agent_registry_wiring.py:557-564`):

> "This surface is the project conversation: you converse with the client, record what they tell
> you, and can draft research direction, present its confirmation gate, or launch an exact Account
> set explicitly commanded and attached by the current human turn when the pilot budget gate is
> disabled. You do not capture on their behalf, fetch external sources, delegate to a specialist,
> or widen the human's selected set."

(Quoted verbatim. See the Inconsistencies section — this framing predates the ARV2 lane and still describes the old directive/launch flow.)

## The three families of callable thing

1. **21 governed platform tools** — the `tools:` list of `head-of-abm@v49`. Each is a
   `clue_toolbelt.Tool` subclass registered at the `clue_api` composition root, wrapped per turn by
   `GovernedAgentToolFactory._governed_tool` (`agent_runtime_wiring.py:720-852`). The model sees the
   tool under its bare `name` (no `@version`), with description
   `f"{descriptor.model_description} Trusted identity, operation identity, journaling, and authority are injected."`
   and args schema `f"{input_model.__name__}AgentRuntime"`. Each call becomes a one-step `AgentPlan`
   → `validate_plan` → `execute` → durable `GovernedOperationReceipt`, returned to the model as JSON
   (`receipt.model_dump_json(exclude_none=True)`).
2. **8 deepagents framework tools** — `write_todos`, `ls`, `read_file`, `write_file`, `edit_file`,
   `glob`, `grep` (`_FRAMEWORK_TOOL_NAMES`, `runtime.py:36-46`) plus the mandatory `finalize_turn`.
   The file tools are served by the POSIX-anchored `AnchoredAgentWorkspaceBackend`.
3. **`delegate_specialist`** — **NOT installed on this surface.** `delegation_roles` in the profile
   is `[research, content_drafter, reviewer]`, but `C6_SURFACE_POLICIES` withholds all three roles on
   `project_conversation`, which empties `profile.delegation_roles` at resolution time, so
   `GovernedAgentToolFactory.build()` adds no delegation tool
   (`agent_runtime_wiring.py:695-704`: `delegation = (self._delegation_tool(),) if self._resolved_profile.profile.delegation_roles else ()`).
   The `profile.yaml`'s `delegation_tool_grants` block is therefore dead on this surface.
   `DelegationWithheld` (`conversation_turns.py:150-159`) is the "unreachable backstop, not the
   fence".

## Refusal shape every governed tool shares

When a governed call is refused, the model gets a **tool result**, not an exception
(`agent_runtime_wiring.py:300-321, 880-916`):

```
GovernedToolFailure:
  error: Literal["plan_rejected", "operation_failed"]
  address: str                 # e.g. "launch_arv2_discovery@1"
  node_key: str                # "agent_<tool>_<sha256(tool_call_id)[:24]>"
  recorded: Literal[False]     # pinned False — nothing committed
  reasons: tuple[str, ...]     # "plan_rejected" → "<location>: <code>: <message>" per review issue
                               # "operation_failed" → "<error_type>: <message>" per failure
  guidance: str = _GOVERNED_TOOL_REPAIR_HELP
```

`_GOVERNED_TOOL_REPAIR_HELP` verbatim (`agent_runtime_wiring.py:94-98`):

> "Nothing was recorded: no durable state changed and this operation did not happen. Correct exactly
> what the reasons name and call the tool again, or tell the human what is blocking you. Do not
> report this as captured."

A tool's own `PreconditionFailure(reason_code, message)` values surface inside `reasons` via the
`PreconditionFailed` error raised by the runner.

## Cards that appear in chat

Projection is `conversation_turns._project_turn_close` (`conversation_turns.py:435-497`):

- `finalize_turn`'s `open_gate_refs` → `stream.emit_gate_parts(...)` — the gate card.
- `finalize_turn`'s `domain_refs` whose `object_type` is in
  `_PLAN_OBJECT_TYPES = frozenset({"research_directive", "agent_plan", "plan", "project_document"})`
  (`conversation_turns.py:145-147`) → `stream.emit_plan_part(...)`. `project_document` is titled
  `"Plan"` with revision label `f"v{version}"`; the others are titled by
  `object_type.replace("_", " ")`.
- `stream.emit_launched_task_parts()` runs **whatever the turn's status** — "a launch is committed by
  its own transaction, so a turn that launched research and then failed to finalize still launched it".
- Each governed tool call also streams a live tool card: `tool_started` on entry, then either
  `tool_finished` (with `stream_product_tool_receipt(receipt) or stream_tool_receipt(receipt)`) or
  `tool_failed` (error code + reasons).
- **No `sources` part is ever projected** on this surface, deliberately: "the project conversation
  withholds every fetching tool by policy … projecting [domain_refs] would manufacture provenance out
  of a model's assertion" (`conversation_turns.py:458-466`).

## What the agent is actually told about its tools

The system prompt is `prompt_body` + `generated_resource_map`
(`platform/agents/clue_agents/registry.py:240-343`), and the middleware re-appends the map on every
model call if it is missing (`runtime.py:132-137`). The map is headed
`"## Resolved resource and capability map (authoritative; generated)"` — and the skill defers to it:
*"which tools exist for you is stated once, by your resolved resource and capability map, and that
map is authoritative"* (SKILL.md §82).

Its tool lines carry **only the address and the effect class**:

```
Governed platform tools available to this role:
- <name>@<version> effect=<read|write|spend|steering>
```

`model_description` is **not** in the map — it reaches the model only as the LangChain tool
description (`agent_runtime_wiring.py:840-850`). The map also emits:

- a `Surface policy:` block with `surface=project_conversation`, the framing sentence,
  `- withheld delegation: content_drafter, research, reviewer`, and
  `- reason=project_conversation_no_autonomous_research; none of the above is installed, so there is nothing here to decline`
  (no `withheld tools:` line, because `withheld_tools` is empty).
- a fixed `Framework tools available:` block: `write_todos` ("ephemeral turn planning only");
  `ls, read_file, glob, grep` ("relative reads inside authorized virtual prefixes");
  `write_file, edit_file` ("relative writes inside authorized virtual prefixes");
  `finalize_turn` ("required durable terminal action").
- `Explicitly unavailable runtime capabilities:` — framework task/subagent, execute/shell/process,
  host filesystem/repo/env/secrets/provider SDKs, arbitrary network access, and "human
  confirmation, override, budget, and checkpoint authority".
- `- delegate_specialist: unavailable on this surface` (the `withheld_delegation_roles` branch).
- `Delegation:` → `- none`.
- the workspace block (prefixes, extensions, quotas, retention class) and the model policy block.


---

# Part 1 — The reads (what the project's own rows say)


---

## `read_project_accounts@1`

- **Address**: `read_project_accounts@1` — effect class `read` (`effect_class = ToolEffectClass.READ`), replay policy `effect_free` (`ReplaySafety(policy=ReplayPolicy.EFFECT_FREE, durable_identity="current project_account rows + each account's latest ARV2 account job", external_boundary=ExternalReplayBoundary.NONE)`; `operation_id_required` is not set on this tool, so it is the envelope default `False`; an `EFFECT_FREE` policy is forbidden by `ReplaySafety.__post_init__` from declaring any external boundary other than `NONE`), pin_requirements `("project",)` — commented in code as "``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0 pin (standing rule item 5)", opens a human gate: no. Cost prior: the envelope default `Tool.estimate` → `ToolEstimate.free()` (zero cents); the tool does not override `estimate`. `audit_snapshot` is not overridden, so `has_steering_snapshot` is `False`.
- **Purpose**: It answers "which accounts are in this project, and where does each one's research stand?" by reading the project's own rows instead of the transcript. One statement returns a bounded page of `project_account` rows joined to `account_entity` (merge losers dropped) and laterally joined to each account's newest ARV2 **account** job, plus a second statement that counts the same filtered population so the model can say "showing 100 of 240". The workspace is ambient (`ctx.workspace_id`), never model-authored; a project this workspace cannot see is a typed refusal rather than an empty list, because "this project has no accounts" would be a lie about a project that is simply not ours. It changes nothing: no launch, no approval, no spend.
- **Inputs** (`ReadProjectAccountsInput(ToolInput)`, read_tools.py:893-902; the `ToolInput` base sets `model_config = ConfigDict(frozen=True, extra="forbid")`, so an unknown key is a loud `ValidationError` and the validated body is the D6 idempotency body key):
  - `project_id: str` — no `Field(...)` constraints. No field description/comment in code; what the model is expected to put there comes from the skill: "`project_id`: this project, from the project card in your context" (stage0-interview v26 §7, for the launch tool; §7c gives no separate wording) and from the tool's own `model_description`: "List the accounts in one project with each account's research status …". Checked against the ambient workspace before any row is read.
  - `limit: int = Field(default=100, ge=1, le=MAX_ACCOUNTS)` — `MAX_ACCOUNTS = 200`, whose module comment is "The hard ceiling on one read. A tool result is context the model pays for on every later turn, so the page is bounded by construction rather than by the caller's good manners." No field description on `limit` itself; the `model_description` says "page with limit and offset when total is larger than the page you received".
  - `query: str | None = Field(default=None, max_length=120)` — field comment verbatim: "A name or domain fragment, case-insensitive. Without it, an account past the first page is reachable only by paging — and a model that reads one short page and stops would tell the human their account is not in the project." Applied as a contains-`ILIKE` against `a.canonical_name` **or** `a.primary_domain`, with LIKE metacharacters neutered by `_ilike_pattern` (backslash first, then `%`, then `_`).
  - `offset: int = Field(default=0, ge=0)` — field comment verbatim: "How many rows to skip. With ``limit`` this walks a project larger than one page."
- **Preconditions and refusal codes**:
  - `PreconditionFailure(reason_code="arv2_reads_not_composed", message="the ARV2 read surface is not composed on this deployment")` — returned by `preconditions()` (which ignores both inputs and ctx) whenever the injected `Arv2ReadService` is `None`. Meaning: this deployment registered the tool but wired no service. Guidance in code (`build_arv2_read_tools` docstring): the refusal exists so "an agent that reaches for a read on a deployment without the lane gets the named ``arv2_reads_not_composed`` refusal rather than an ``UnknownTool`` it cannot explain". No agent-facing remediation guidance beyond that. In practice the service is composed wherever there is a database — `DbArv2ReadService(settings=…)` at fleet_main.py:960 and projections_main.py:157 — and unlike its launching neighbours this tool has **no** feature flag ("these three have no flag: they read rows that already exist and spend nothing to do it", read_tools.py:1162-1174).
  - `PreconditionFailure("project_not_found", "no project {project_id} in this workspace")` — raised inside `invoke` by catching `Arv2ReadRefused` and re-raising as `PreconditionFailed`. Meaning: `get_project` returned nothing, or returned a project belonging to another workspace. The code's comment: "Fail-closed and indistinguishable: another workspace's project is not 'empty', it is absent — the same answer a project id that never existed gets." What the agent should do: no guidance in code; the skill says only (§7c) "A read costs nothing and is never a launch."
  - No other `Arv2ReadRefused` code is reachable from this tool. The remaining codes listed on `Arv2ReadRefused` (`account_not_found`, `overview_not_written`, `account_not_researched`, `no_claims_under_prefix`, `discovery_run_not_found`, `no_discovery_run`) belong to the other two reads.
- **Output** (`ReadProjectAccountsOutput(ToolOutput)`, read_tools.py:904-909; `ToolOutput` base is `frozen=True, extra="forbid", strict=True`; `invoke` builds the model and returns `ToolResult(tool=…, version=…, references=output.model_dump())` — no `by_alias`, because this surface has no aliased field):
  - `project_id: str` — the project the page is about (echoed from the validated input via `ProjectAccountsPage.project_id`).
  - `total: int` — field comment verbatim (on `accounts`, covering both): "The project's accounts. ``total`` is the whole **filtered** membership; ``len(accounts)`` is the page, so the model can say 'showing 100 of 240' rather than guessing at the rest." `_COUNT_PROJECT_ACCOUNTS` repeats the listing's `merged_into IS NULL` join and its `query` filter so the two halves measure one population.
  - `accounts: tuple[ProjectAccountView, ...]` — the page, at most `limit` rows (`limit ≤ MAX_ACCOUNTS = 200`, default 100), ordered `a.created_at DESC, a.id DESC`.
  - Nested `ProjectAccountView(BaseModel, frozen=True)` (read_tools.py:121-135), docstring "One account in a project: who it is, where its research stands, and how it got here." — every field:
    - `account_entity_id: str` — `account_entity.id` as text.
    - `name: str` — `account_entity.canonical_name`.
    - `domain: str | None` — `account_entity.primary_domain`, `None` when the column is NULL.
    - `research_status: str` — field comment verbatim: "``arv2_research_job.status`` verbatim — ``not_started`` / ``in_progress`` / ``needs_review`` / ``completed`` / ``suspended``. An account with no job at all reads ``not_started``." (These are exactly `account_research_store.JobStatus = Literal["not_started", "in_progress", "needs_review", "completed", "suspended"]`.) Sourced from a LATERAL join taking the newest row with `subject_type = 'account'` ordered `created_at DESC, job_id DESC`; person jobs share the table and are excluded.
    - `refreshing: bool` — field comment verbatim: "The account has been researched before **and** is being researched again right now." SQL definition: a live job (`status IN ('not_started','in_progress')`) exists for which an earlier `completed` job exists, compared by the tuple `(created_at, job_id)` so a `created_at` tie breaks the same way the accounts screen breaks it.
    - `added_via: str` — `project_account.added_via`; observed writers in code write `"manual"` (account/person launch, answer-key loader, bulk actions, trial spine), `"discovered"` (discovery driver) and `membership_channel(EXA_WEBSETS_SOURCE_KEY)` (Exa websets materialization). No enum in this file.
    - `added_at: str` — `project_account.added_at`, ISO-8601 (`.isoformat()`).
  - Bounds, verbatim with their constant names: `MAX_ACCOUNTS = 200` ("The hard ceiling on one read…"), enforced as `le=MAX_ACCOUNTS` on `limit`; default page size 100. There is **no byte budget on this tool's `references`**: `READ_REFERENCES_BUDGET` / `READ_REFERENCES_BUDGET_BYTES` is **not found in code** — grepping the whole worktree it appears only in the unexecuted plans `docs/superpowers/plans/2026-09-13-read-tools-hotfix.md` (`READ_REFERENCES_BUDGET_BYTES = 12 * 1024`) and `docs/superpowers/plans/2026-09-13-paged-and-spilled-reads.md`. `MAX_CLAIMS` / `EVIDENCE_CHARS` / `BODY_CHARS` / `MAX_CANDIDATES` belong to the other two reads.
- **Side effects / what becomes true afterwards**: none — this is a pure read. `DbArv2ReadService.list_project_accounts` opens exactly one transaction (`ConnFactory`, default `clue_db.transaction`) and runs two SELECTs; no row is written, no run is enqueued, no gate is opened, no card appears in chat. It is journaled the way every runner-mediated invocation is: the runner wraps the call in the log_span/idempotency wrapper, and `parameter_policy = JournalParameterPolicy(safe_display_fields=("project_id", "limit", "query", "offset"))` is the allowlist of small top-level scalars that may be copied into the display-safe journal projection (the validated body itself stays artifact-backed). Registration: `build_arv2_read_tools(arv2_reads)` at toolbelt_wiring.py:2821, `registry.register(tool, make_default=True)`; authority `"read_project_accounts": (AgentRole.HEAD_OF_ABM,)` at agent_registry_wiring.py:164; withheld from the dev/trial surface (agent_registry_wiring.py:507-515) because that surface passes no `arv2_reads`.
- **Where the skill teaches it**: stage0-interview v26 **§7c "Read before you speak about accounts"** — "**How many accounts, which are researched, what joined when:** `read_project_accounts`. `status.md` carries the summary; this read is the list." (SKILL.md:218-224). Also pinned in the skill front matter tool list (SKILL.md:62-65, `input_schema_sha256: 9a7aa42aacc66b5dcf1834db46284e876e12406ecc814419b3b63d55d2275cdd`, `output_schema_sha256: b3d662ea77b66e6ed4d408e3b8c707ed2cae4efda9a3cc01b5c078a8f2cace08`) and in `head-of-abm/v49/profile.yaml:164-168`.
- **Source**: `platform/api/clue_api/arv2/read_tools.py:1-22` (module docstring), `:74-99` (`__all__`, `MAX_ACCOUNTS`), `:102-113` (`Arv2ReadRefused`), `:121-147` (`ProjectAccountView`, `ProjectAccountsPage`), `:150-208` (`_ACCOUNT_QUERY_FILTER`, `_LIST_PROJECT_ACCOUNTS`, `_COUNT_PROJECT_ACCOUNTS`), `:210-270` (`_ilike_pattern`, `list_project_accounts`), `:778-877` (`Arv2ReadService`, `DbArv2ReadService`), `:879-886` (`_not_composed`), `:893-968` (input/output models and `ReadProjectAccountsTool`), `:1162-1176` (`build_arv2_read_tools`); `platform/toolbelt/clue_toolbelt/envelope.py:1-412`; `platform/api/clue_api/toolbelt_wiring.py:75,2660,2814-2822`; `platform/api/clue_api/fleet_main.py:89,960,993`; `platform/api/clue_api/projections_main.py:12,157,163`; `platform/api/clue_api/agent_registry_wiring.py:158-166,507-515`; `platform/api/clue_api/arv2/account_research_store.py:67` (`JobStatus`); `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:62-65,218-224`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:145-168`.
- **Discrepancy**: (1) The row-order comment says "The row order is the accounts screen's own default (``created_at DESC, id DESC``), so 'the first ten accounts' means the same ten to the agent and to the marketer" — the SQL orders by `a.created_at`/`a.id` (**`account_entity`**, i.e. when the company record was created), not by `pa.added_at`, which is the field the row actually reports as "how it got here"; paging is therefore not ordered by the join date the output surfaces. (2) `model_description` enumerates research status and "how it joined the project" but never mentions `refreshing`, which the output always carries — the model is not told the field exists except through the schema. (3) `research_status=str(row["research_status"] or "not_started")` folds *any* falsy value (NULL **or** an empty string) to `not_started`; the comment justifies only the NULL/no-job case.


---

## `read_account_research@1`

- **Address**: `read_account_research@1` — effect class `read` (`effect_class = ToolEffectClass.READ`), replay policy `effect_free` (`ReplaySafety(policy=ReplayPolicy.EFFECT_FREE, durable_identity="the account's live display_block rows and its live claims", external_boundary=ExternalReplayBoundary.NONE)`; `operation_id_required` not set → envelope default `False`), pin_requirements `("project",)` — "``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0 pin (standing rule item 5)", opens a human gate: no. Cost prior: envelope default `ToolEstimate.free()`; `estimate` is not overridden. `audit_snapshot` is not overridden → `has_steering_snapshot = False`.
- **Purpose**: It serves what research actually holds about one account, in one of two shapes, so a sentence about a company carries a row behind it instead of a memory of an earlier thread. `section="overview"` returns the written overview sections exactly as the account page stores them (body JSON as text, with the claim ids each section cites), ordered by the page's own recipe order. `section="claims"` returns the account's live claims — value, source url, clipped evidence span, tier, verification status — gated predicate-for-predicate by the same display gate the account page uses, so chat can never print a fact the app deliberately refuses to print. One read never serves both halves: the unasked half comes back empty, and an unwritten overview is a typed refusal rather than an account that looks unresearched. The claims read spans every project of the workspace that researched this account ("the store holds account truth, not a per-project lens"). It writes nothing and spends nothing.
- **Inputs** (`ReadAccountResearchInput(ToolInput)`, read_tools.py:970-976; base `ToolInput` is `frozen=True, extra="forbid"`):
  - `account_entity_id: str` — no `Field(...)` constraints, no field description in code. Expected content: the account's `account_entity.id`; the tool parses it with `UUID(account_entity_id)` and a malformed value is deliberately indistinguishable from an absent one ("A malformed id is indistinguishable from an absent one on purpose: both mean 'there is no such account here', and the model does not need to learn the id format from an error"). Skill guidance (§7c): "Never state a fact about an account from memory of an earlier thread."
  - `section: Literal["overview", "claims"] = "overview"` — exactly two values; no field comment. Skill guidance (§7c) verbatim: "`read_account_research` with `section: \"overview\"` first; when the overview is not written yet, `section: \"claims\"`."
  - `field_prefix: str | None = Field(default=None, max_length=80)` — field comment verbatim: "Claims only: ``account.resonance`` narrows a researched account's claims to one family rather than making the model read all of them to find three." Applied as `claim.field_key.startswith(field_prefix)` after the claims are loaded; ignored entirely when `section="overview"`.
- **Preconditions and refusal codes**:
  - `PreconditionFailure(reason_code="arv2_reads_not_composed", message="the ARV2 read surface is not composed on this deployment")` — from `preconditions()` when the injected `Arv2ReadService` is `None` (no flag gates this tool; the service composes wherever there is a database). Guidance: the `build_arv2_read_tools` docstring only explains why it exists ("rather than an ``UnknownTool`` it cannot explain").
  - `account_not_found` — message `f"no account {account_entity_id} in this workspace"`. Raised by `_account_in_workspace` for a malformed UUID, for an id with no `account_entity` row in this workspace, **and** for a merge loser (`merged_into IS NULL` is part of the lookup: "refuses a merge loser by name rather than serving the wrong company's research under the id the caller asked about"). No agent guidance in code.
  - `overview_not_written` — message verbatim: "this account's overview has not been written yet; read section='claims' or open the account in the app". Raised when `live_blocks(...)` returns no live `display_block` rows for `subject_kind="account"`, `page="overview"`. The message itself is the guidance, and the skill repeats it (§7c: "when the overview is not written yet, `section: \"claims\"`").
  - `account_not_researched` — message verbatim: "no claims about this account yet". Raised on the claims branch when `claims_for_entities` returns nothing for this account under `WorkspaceScope.for_workspace(workspace_id)`. No further guidance in code.
  - `no_claims_under_prefix` — message `f"this account has claims, but none under {field_prefix}"`. Raised when the account has claims but none match `field_prefix`. Code rationale: "A distinct code: the account IS researched, and saying otherwise because one prefix came back empty is a false statement about the account in the machine-readable half." Implicit guidance: re-read without the prefix.
  - All four `Arv2ReadRefused` codes reach the agent the same way — `invoke` catches `Arv2ReadRefused` and raises `PreconditionFailed([PreconditionFailure(refused.code, str(refused))])`.
- **Output** (`ReadAccountResearchOutput(ToolOutput)`, read_tools.py:978-991; `ToolOutput` base is `frozen=True, extra="forbid", strict=True`; returned as `ToolResult(..., references=output.model_dump())`):
  - `account_entity_id: str` — the resolved account id (canonical `str(UUID)`), not necessarily byte-identical to the input string.
  - `account_name: str` — `account_entity.canonical_name`.
  - `section: str` — echoes the requested section.
  - `overview: tuple[AccountOverviewSection, ...]` — field comment verbatim: "The written sections when ``section='overview'``, else empty."
  - `claims: tuple[AccountClaimView, ...]` — field comment verbatim: "The account's servable claims when ``section='claims'``, else empty."
  - `truncated: bool` — field comment verbatim: "The account holds more claims than one read serves; narrow with ``field_prefix``." Set from `len(kept) > MAX_CLAIMS` on the claims branch; always `False` on the overview branch.
  - `excluded: dict[str, int]` — field comment verbatim: "What the account pages' own gate held back, by reason: ``sensitive``, ``unverified``, ``outreach_unsafe``. A non-zero count means 'there is more here, and it is not servable'." Always exactly those three keys (initialized `{"sensitive": 0, "unverified": 0, "outreach_unsafe": 0}`), all zero on the overview branch. The gate, predicate for predicate: `use_class is UseClass.SENSITIVE` → `sensitive`; `settings.verification_enabled and source_tier == 4 and verification_status is not VerificationStatus.VERIFIED` → `unverified`; `not claim.outreach_safe` → `outreach_unsafe`.
  - Nested `AccountOverviewSection(BaseModel, frozen=True)` (read_tools.py:273-286), docstring "One written section of an account's overview page, as it was stored." — every field:
    - `section_key: str` — the `display_block` section key. Ordering: the page's own recipe order (`read_recipes(conn, "overview", workspace_id=…)`), with an unknown section sorting after the known ones by key.
    - `body_text: str` — field comment verbatim: "``display_block.body_json`` as JSON text, capped at :data:`BODY_CHARS`. Text rather than a nested object because the stored body has no bound of its own — nothing in the display package limits how many items a section holds or how long one item is — and an unbounded blob is context the model pays for on every later turn of the thread." Serialized `json.dumps(block.body_json, sort_keys=True, ensure_ascii=False)`.
    - `body_truncated: bool` — field comment verbatim: "The body was longer than the cap and the tail is not here."
    - `cited_claim_ids: tuple[str, ...]` — the claim ids the stored block cites (`LiveBlock.cited_claim_ids`).
    - `generated_at: str` — ISO-8601 `display_block.generated_at`.
    - (The underlying `LiveBlock` also carries `display_block_id`, `model`, `prompt_version`, `recipe_version`; this view deliberately drops them.)
  - Nested `AccountClaimView(BaseModel, frozen=True)` (read_tools.py:288-309), docstring "One live claim about an account: the value, and what stands behind it." — every field:
    - `claim_id: str` — `claim.id`.
    - `field_key: str` — the registry field key (e.g. `account.resonance.*`).
    - `value: Any` — `claim.value_json`, verbatim.
    - `source_url: str | None` — `claim.source_url`.
    - `evidence: str` — field comment verbatim: "The evidence span, clipped — a quote is here to be *checked*, not reproduced whole. A clipped span ends in ``…`` so a partial quote is never presented as a complete one." Empty string when the claim has no span.
    - `evidence_truncated: bool` — field comment verbatim: "The span was longer than :data:`EVIDENCE_CHARS`; what is here is its opening."
    - `tier: int` — `claim.source_tier` (1–4; tier 4 is LLM synthesis).
    - `verification_status: str | None` — field comment verbatim: "``claim.verification_status`` — ``unverified`` / ``verified`` / ``rejected``. Served so the model can say *how* a fact is known, not only what it is."
    - `outreach_safe: bool | None` — field comment verbatim: "``claim.outreach_safe`` — false rows never reach here; the field carries the fact anyway so the shape does not change if the gate ever admits a restricted section."
    - `collected_at: str` — ISO-8601 `claim.collected_at`. Row order is `claims_for_entities`' own `(field_key, collected_at DESC, id)` — "one field's newest value first".
  - Bounds, verbatim with their constant names: `MAX_CLAIMS = 120` — "The hard ceiling on one claims read, for the same reason as :data:`MAX_ACCOUNTS`: a researched account can hold hundreds of claims, and the model pays for every one of them on every later turn. Over the cap the read says so (``truncated``) instead of quietly dropping the tail."; `EVIDENCE_CHARS = 240` — "An evidence span is a quotation the reader may *check*; a whole article is not. … A clipped span ends with the ellipsis and never exceeds this length, so the marker costs a character of the quote rather than adding one."; `BODY_CHARS = 6000` — "The cap on one overview section's serialized body. The stored body is ``{intro, items, checks, cited_flags, cost_usd, call:{…}}`` and nothing in the display package bounds ``items`` — so the honest answer to 'how large can a section be?' was 'unbounded' until this."; `_ELLIPSIS = "…"` — "What a clipped string ends with. One character, so the cap is the cap." There is **no** per-section count cap and **no** byte budget on `references`: `READ_REFERENCES_BUDGET` / `READ_REFERENCES_BUDGET_BYTES` is **not found in code** (searched the whole worktree) — it exists only in the unexecuted plans `docs/superpowers/plans/2026-09-13-read-tools-hotfix.md` and `…-paged-and-spilled-reads.md`. So an overview with many sections can exceed `BODY_CHARS` in aggregate (N × 6000 characters).
- **Side effects / what becomes true afterwards**: none — a pure read. `DbArv2ReadService.read_account_research` opens one transaction and performs SELECTs only (account row; then either `live_blocks` + `read_recipes`, or `claims_for_entities`). No row is written, no job or run is enqueued, no gate is opened, no card appears in chat. The invocation is journaled by the runner's log_span/idempotency wrapper; `parameter_policy = JournalParameterPolicy(safe_display_fields=("account_entity_id", "section", "field_prefix"))` is the allowlist of scalars that may also appear in the display-safe journal projection. Registered at toolbelt_wiring.py:2821 via `build_arv2_read_tools(arv2_reads)` with `make_default=True`; composed by `DbArv2ReadService(settings=…)` (fleet_main.py:960, projections_main.py:157) with no feature flag; authority `"read_account_research": (AgentRole.HEAD_OF_ABM,)` (agent_registry_wiring.py:165); withheld from the dev/trial surface (agent_registry_wiring.py:507-515).
- **Where the skill teaches it**: stage0-interview v26 **§7c "Read before you speak about accounts"** — "**What research found about one account:** `read_account_research` with `section: \"overview\"` first; when the overview is not written yet, `section: \"claims\"`. Quote a fact only with a claim behind it, and say when a field is empty. Never state a fact about an account from memory of an earlier thread." (SKILL.md:218-224). Pinned in the skill front matter (SKILL.md:66-69) and in `head-of-abm/v49/profile.yaml:145-151`.
- **Source**: `platform/api/clue_api/arv2/read_tools.py:1-22`, `:102-113` (`Arv2ReadRefused`), `:273-345` (`AccountOverviewSection`, `AccountClaimView`, `AccountResearch`, `MAX_CLAIMS`/`EVIDENCE_CHARS`/`BODY_CHARS`), `:346-360` (`_ELLIPSIS`, `_clip`), `:362-392` (`_ACCOUNT_IN_WORKSPACE`, `_account_in_workspace`), `:395-440` (`_overview_sections`), `:442-533` (`_is_sensitive`, `_is_unverified_synthesis`, `_account_claims`), `:536-584` (`read_account_research`), `:810-877` (`DbArv2ReadService`), `:879-886` (`_not_composed`), `:970-1052` (input/output models and `ReadAccountResearchTool`); `platform/api/clue_api/arv2/display/blocks.py:65-76,177-208` (`LiveBlock`, `live_blocks`); `libs/clue-core/clue_core/enums.py:57-68` (`VerificationStatus`); `platform/toolbelt/clue_toolbelt/envelope.py:1-412`; `platform/api/clue_api/toolbelt_wiring.py:2814-2822`; `platform/api/clue_api/agent_registry_wiring.py:158-166,507-515`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:66-69,218-224`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:145-151`.
- **Discrepancy**: (1) `model_description` contains a duplicated word — "section='claims' returns the the claims the account pages show" (read_tools.py:1000). (2) `model_description` states flatly that "sensitive, unverified tier-4 and outreach-unsafe claims are held back and counted in 'excluded'", but the unverified arm is conditional on deployment posture: `_account_claims` only applies it when `settings.verification_enabled` is true, so on a non-verifying deployment unjudged tier-4 syntheses are served and `excluded["unverified"]` stays 0. (3) `AccountClaimView.verification_status`'s comment enumerates "``unverified`` / ``verified`` / ``rejected``", but `clue_core.VerificationStatus` also has `FLAGGED = "flagged"`, which nothing in this path filters out — a flagged claim is servable and would render a fourth value the comment does not list. (4) `verification_status: str | None` and `outreach_safe: bool | None` are typed optional, yet `_account_claims` always writes `str(...)`/`bool(...)` — the `None` arm is unreachable in production code. (5) `ReadAccountResearchOutput.truncated`'s comment ("The account holds more claims than one read serves; narrow with ``field_prefix``") describes only the claims branch; on the overview branch it is hard-wired `False` even when a section body was clipped — an overview that lost its tail reports `truncated=False` with `body_truncated=True` on the section. (6) The tool-level docstring/description never mentions that the claims read is workspace-wide rather than project-scoped; only the internal `_account_claims` docstring says so ("The claims read spans every project of the workspace that researched this account"), while the tool declares `pin_requirements = ("project",)`.


---

## `read_discovery_run@1`

- **Address**: `read_discovery_run@1` — effect class `read` (`effect_class = ToolEffectClass.READ`), replay policy `effect_free` (`ReplaySafety(policy=ReplayPolicy.EFFECT_FREE, durable_identity="the project's latest arv2_discovery_run row and its candidates", external_boundary=ExternalReplayBoundary.NONE)`; `operation_id_required` not set → envelope default `False`), pin_requirements `("project",)` — "``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0 pin (standing rule item 5)", opens a human gate: no. Cost prior: envelope default `ToolEstimate.free()`; `estimate` is not overridden. `audit_snapshot` is not overridden → `has_steering_snapshot = False`.
- **Purpose**: It reads one verified-account-discovery run of a project — the newest by default, or one named by id — and reports what the human asked for, what the provider brought back, how many candidates the verifier actually judged against the ICP, how many were shown and how many the human approved, plus the shortlist itself (shown first, then best fit, then by name). It is the read the skill requires before proposing another discovery, so the agent answers "how did discovery go?" from the run row rather than by launching a second run. It approves nothing, starts nothing and spends nothing; the project is checked against the ambient workspace first, so "that run is not this project's" and "that project is not yours" stay two different answers.
- **Inputs** (`ReadDiscoveryRunInput(ToolInput)`, read_tools.py:1055-1062; base `ToolInput` is `frozen=True, extra="forbid"`):
  - `project_id: str` — no `Field(...)` constraints, no field description in code. Expected content: this project's id (the skill says, §7b, "call `read_discovery_run` for this project"). Resolved with `get_project` and compared to `ctx.workspace_id` before anything else is read.
  - `run_id: str | None = None` — field comment verbatim: "Omitted means the project's newest run, which is what 'how did discovery go?' means." When given it is parsed with `UUID(run_id)`; the newest run is picked by `ORDER BY created_at DESC, run_id DESC` — "the project card's own ordering (``project_status._LATEST_DISCOVERY``), so the agent and the app agree on which run is 'the' run when two were launched in the same instant".
  - `candidate_limit: int = Field(default=25, ge=0, le=MAX_CANDIDATES)` — `MAX_CANDIDATES = 50`. Field comment verbatim: "``0`` asks for the tallies alone — the shape a 'how many did we approve?' turn wants without paying for a company list it will not read."
- **Preconditions and refusal codes**:
  - `PreconditionFailure(reason_code="arv2_reads_not_composed", message="the ARV2 read surface is not composed on this deployment")` — from `preconditions()` when the injected `Arv2ReadService` is `None`. No flag gates this tool; the service composes wherever there is a database. Guidance: only the `build_arv2_read_tools` rationale ("rather than an ``UnknownTool`` it cannot explain").
  - `project_not_found` — message `f"no project {project_id} in this workspace"`. The project row is missing or belongs to another workspace. Checked first, deliberately, so a run of another project is refused by name "rather than served to a caller who happened to guess its id". No agent guidance in code.
  - `no_discovery_run` — message verbatim: "this project has not run discovery yet". Raised only when `run_id` was omitted and the project has no `arv2_discovery_run` row at all. Implicit guidance from the skill (§7b): discovery is launched with `launch_arv2_discovery`, and a read is never a launch.
  - `discovery_run_not_found` — message `f"no discovery run {run_id} in this project"` for a malformed UUID ("A malformed id and an absent one read alike"), and `f"no discovery run {run_uuid} in this project"` when the row does not exist, belongs to another workspace, or belongs to another project of this workspace. No agent guidance in code.
  - All three read refusals reach the agent through `invoke`'s `except Arv2ReadRefused` → `PreconditionFailed([PreconditionFailure(refused.code, str(refused))])`.
- **Output** (`ReadDiscoveryRunOutput(ToolOutput)`, read_tools.py:1064-1088; `ToolOutput` base is `frozen=True, extra="forbid", strict=True`; returned as `ToolResult(..., references=output.model_dump(by_alias=True))` — `by_alias` is required because `pass_` is the one aliased field on this surface):
  - `run_id: str` — the run actually read (the resolved newest run when the input omitted it).
  - `status: str` — `arv2_discovery_run.status`, one of `discovery_store.DiscoveryStatus = Literal["not_started", "in_progress", "needs_review", "completed", "suspended"]` ("The seam-1 states, verbatim — the same vocabulary the R2 runs and jobs carry").
  - `icp_key: str` — the ICP the run was pinned to.
  - `icp_version: int` — that ICP's version.
  - `target_count: int` — field comment verbatim: "How many accounts the human asked discovery for."
  - `asked: int | None` — field comment verbatim: "How many companies the long list was asked to return, once the provider was called." `None` before the provider call.
  - `found: int` — field comment verbatim: "Strict plus relaxed — the companies the run actually brought back." Computed `int(run.found_strict or 0) + int(run.found_relaxed or 0)`; the code notes "A run still in flight has neither counter yet; 'found 0 so far' is the honest reading."
  - `verified: int` — field comment verbatim: "How many candidates the verifier actually judged against the ICP — the ones that carry a verdict. Companies skipped before any gate (already an account, surfaced and not chosen before) are NOT counted here; they are in ``candidate_total``." SQL predicate is the shared `VERIFIED_PREDICATE = "jsonb_array_length(c.verdicts_json) > 0"`.
  - `shown: int` — candidates whose disposition is in `SHOWN_DISPOSITIONS: tuple[str, ...] = ("pass", "partial", "unclear")` ("The dispositions that mean the human was shown this company").
  - `approved: int` — candidates with `decision = 'approved'`.
  - `relaxed_requested: bool` — whether the widened re-search was requested on this run.
  - `started_at: str | None` — ISO-8601, `None` until the run starts.
  - `finished_at: str | None` — ISO-8601, `None` until the run is terminal.
  - `candidates: tuple[DiscoveryCandidateView, ...]` — field comment verbatim: "The run's candidates, shown-first and best-fit-first." Sorted by `_candidate_order` = `(0 if disposition in SHOWN_DISPOSITIONS else 1, fit is None, -(fit or 0.0), name)`; the code notes "A candidate with no fit sorts *after* every scored one rather than as a zero: an unscored company is unknown, not bad." Sliced to `candidate_limit`.
  - `candidate_total: int` — field comment verbatim: "The run's whole candidate count, so a bounded list never reads as a small run." It is `len(candidates)` **after** the in-Python workspace filter (`candidate.workspace_id == workspace_id`), applied because "``list_candidates`` filters on ``run_id`` alone, and the FK is single-column".
  - Nested `DiscoveryCandidateView(BaseModel, frozen=True)` (read_tools.py:587-601), docstring "One company a discovery run surfaced, with the verdict the verifier gave it." — every field:
    - `name: str` — the company name from the long list.
    - `domain: str` — the company domain.
    - `pass_: str = Field(serialization_alias="pass")` — field comment verbatim: "Which §4 pass surfaced it — ``strict`` (the full criteria) or ``relaxed`` (the widened re-search). Serialized as ``pass``; the trailing underscore is Python's, not the schema's." (`discovery_store.Pass = Literal["strict", "relaxed"]`.)
    - `disposition: str` — field comment verbatim: "``arv2_discovery_candidate.disposition``: ``pending`` until verified, then ``pass`` / ``partial`` / ``unclear`` / ``duplicate_of_existing`` / ``not_chosen_before``." (Matches `discovery_store.Disposition`.)
    - `decision: str | None` — field comment verbatim: "The human's approval — ``approved``, or nothing at all. There is no recorded rejection."
    - `fit: float | None` — the fit derived from the per-gate verdicts; `None` when unscored.
    - (The underlying `CandidateRow` also carries `candidate_id`, `run_id`, `workspace_id`, `project_id`, `websets_url`, `provider_snapshot`, `verdicts`, `decided_by_user_id`, `decided_at`, `account_entity_id`; this view deliberately drops them — notably the per-gate quotes and urls.)
  - Bounds, verbatim with their constant names: `MAX_CANDIDATES = 50` — "The hard ceiling on one candidate list, for the same reason as :data:`MAX_ACCOUNTS`: a run can surface dozens of companies and every one of them is context the model pays for on every later turn. ``candidate_total`` always reports the whole run, so a short list is never a small run." — enforced as `le=MAX_CANDIDATES` on `candidate_limit` (default 25, `ge=0`). No byte budget: `READ_REFERENCES_BUDGET` / `READ_REFERENCES_BUDGET_BYTES` is **not found in code** (worktree-wide search); it appears only in the unexecuted plans `docs/superpowers/plans/2026-09-13-read-tools-hotfix.md` and `…-paged-and-spilled-reads.md`.
- **Side effects / what becomes true afterwards**: none — a pure read. `DbArv2ReadService.read_discovery_run` opens one transaction and runs SELECTs only (project, optionally the latest-run lookup, the run row, the three tallies, the candidate list). Nothing is written, no run is launched or re-run, no candidate is approved ("It approves nothing", per the `model_description`), no card appears in chat. Journaled by the runner's log_span/idempotency wrapper with `parameter_policy = JournalParameterPolicy(safe_display_fields=("project_id", "run_id", "candidate_limit"))`. Registered at toolbelt_wiring.py:2821 via `build_arv2_read_tools(arv2_reads)` with `make_default=True`; composed with no flag (fleet_main.py:960, projections_main.py:157); authority `"read_discovery_run": (AgentRole.HEAD_OF_ABM,)` (agent_registry_wiring.py:166); withheld from the dev/trial surface (agent_registry_wiring.py:507-515).
- **Where the skill teaches it**: stage0-interview v26 **§7b "Discover accounts for this project"** — "Before proposing another discovery run, call `read_discovery_run` for this project and say what the last run asked for, found and how many the human approved. Do not launch again to answer a question the read answers." (SKILL.md:208-216) — and **§7c "Read before you speak about accounts"** — "**What discovery found:** `read_discovery_run`." (SKILL.md:222). Pinned in the skill front matter (SKILL.md:70-73) and in `head-of-abm/v49/profile.yaml:156-163`.
- **Source**: `platform/api/clue_api/arv2/read_tools.py:1-22`, `:102-113` (`Arv2ReadRefused`), `:587-625` (`DiscoveryCandidateView`, `DiscoveryRunView`), `:627-663` (`MAX_CANDIDATES`, `_LATEST_DISCOVERY_RUN`, `_DISCOVERY_COUNTS`), `:665-678` (`_candidate_order`), `:680-770` (`read_discovery_run`), `:810-877` (`DbArv2ReadService`), `:879-886` (`_not_composed`), `:1055-1160` (input/output models and `ReadDiscoveryRunTool`); `platform/api/clue_api/arv2/discovery_store.py:42-121` (`DiscoveryStatus`, `Pass`, `Disposition`, `SHOWN_DISPOSITIONS`, `VERIFIED_PREDICATE`), `:123-195` (`DiscoveryRunRow`, `CandidateRow`), `:425-441` (`list_candidates` ordering context); `platform/toolbelt/clue_toolbelt/envelope.py:1-412`; `platform/api/clue_api/toolbelt_wiring.py:2814-2822`; `platform/api/clue_api/agent_registry_wiring.py:158-166,507-515`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:70-73,208-224`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:156-163`.
- **Discrepancy**: (1) `DiscoveryRunView.candidates` is sliced by `candidate_limit` **after** sorting, but `candidate_total` is `len(candidates)` of the workspace-filtered list, not the run's stored candidate count — so a run whose rows carry a foreign `workspace_id` (the case the code's own comment says the single-column FK permits) reports a `candidate_total` smaller than the run truly holds. The field comment ("The run's whole candidate count") is true of what this workspace may see, not of the run. (2) The output exposes `fit` and `disposition` but drops `verdicts` (the per-gate quotes and urls), so the agent cannot cite evidence for a candidate from this read; neither the `model_description` nor the field comments say so. (3) `ReadDiscoveryRunOutput` carries no `relaxed_enabled`, `strict_count`, `analyzed` or `recall_estimate` from `DiscoveryRunRow` — only `relaxed_requested` — so "the run finished short, can we relax?" is answerable only from `relaxed_requested`, while the skill (§7b) tells the agent to discuss relaxed passes.


---

## `read_arv2_account_research_run@1`

- **Address**: `read_arv2_account_research_run@1` — effect class `read` (`effect_class = ToolEffectClass.READ`), replay policy `effect_free` (`ReplaySafety(policy=ReplayPolicy.EFFECT_FREE, durable_identity="current ARV2 account research run + job states")`; `operation_id_required` is not set → envelope default `False`; `external_boundary` is not set → envelope default `ExternalReplayBoundary.NONE`, which is also the only value `ReplaySafety.__post_init__` permits for an `EFFECT_FREE` policy), pin_requirements `("project",)` — "``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0 pin (standing rule item 5)", opens a human gate: no. Cost prior: envelope default `ToolEstimate.free()`; `estimate` is not overridden. `audit_snapshot` is not overridden → `has_steering_snapshot = False`.
- **Purpose**: It is the reverse edge of ARV2 seam 1: given the run id that `launch_arv2_account_research` (or `launch_arv2_person_research`) returned, it reports what that run was pinned to — the ICP artifact key, the product-selection version, the effort and the committee cap — the run's derived status, and one line per job in the run with that job's status and failure code. It is how the agent answers "how is the research going?" without re-launching anything and without claiming completion it cannot see. The run is looked up by id alone and then checked against the ambient `ctx.workspace_id`; a run of another tenant is reported as absent, never as forbidden, "so the caller learns nothing about a tenant it may not see". A run that does not resolve is a typed refusal rather than an empty projection, because "an empty run projection is a lie about a run that may be running elsewhere".
- **Inputs** (`ReadArv2AccountResearchRunInput(ToolInput)`, account_research_launch.py:1114-1115; base `ToolInput` is `frozen=True, extra="forbid"`, so any extra key is a `ValidationError`):
  - `run_id: str` — the only field. No `Field(...)` constraints (no length, no pattern), and **no field description or comment in code** (checked account_research_launch.py:1114-1115 and the surrounding module docstring). What the model is expected to put there comes from the run id returned by `LaunchArv2AccountResearchOutput.run_id` / `LaunchArv2PersonResearchOutput.run_id`, and from the skill (§7): "Use `read_arv2_account_research_run` when the human asks how it is going." The value is parsed with `UUID(inputs.run_id)` inside `invoke`.
- **Preconditions and refusal codes**:
  - `PreconditionFailure(reason_code="arv2_account_research_not_composed", message="the ARV2 account-research lane is not composed on this deployment (CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED)")` — returned by `preconditions()` (which ignores inputs and ctx) whenever the injected `Arv2LaunchService` is `None`. Unlike the three `read_*` tools in `arv2/read_tools.py`, this tool shares the lane's flag: the service is composed only where `settings.arv2_account_research_enabled` is true (`DbArv2LaunchService(resolved, storage) if resolved.arv2_account_research_enabled else None`, projections_main.py:132-133; the same condition at fleet_main.py:927-929). The message itself names the env switch; that is the only guidance in code.
  - `PreconditionFailure("arv2_account_research_run_not_found", f"no ARV2 account-research run {run_id} in this workspace")` — raised from `invoke` (not from `preconditions`) as `PreconditionFailed([...])` when `service.read_run` returns `None`, which happens when the `arv2_research_run` row does not exist **or** its `workspace_id` differs from the ambient one. Code comment: "Absent is a typed refusal, not an empty success: 'no such run here' is actionable, an empty run projection is a lie about a run that may be running elsewhere." No remediation guidance in code; the skill's §7 guidance covers the launch refusals, not this one.
  - No other refusal exists on this tool. The launch-side codes documented on `Arv2LaunchRefused` (`lane_disabled`, `account_not_found:<id>`, `account_not_in_workspace:<id>`, `project_icp_not_pinned`, `icp_artifact_not_found`, `icp_artifact_not_confirmed`, `icp_digest_mismatch`, `icp_front_matter_invalid`, `product_selection_version_unknown`, `project_not_found`, `icp_artifact_not_project_pin`, `no_contacts`, `contact_not_found:<id>`, `contact_merged:<id>`, `contact_without_account`, `product_set_not_confirmed`) belong to the two `launch_arv2_*` tools and cannot be returned by this read.
- **Output** (`ReadArv2AccountResearchRunOutput(ToolOutput)`, account_research_launch.py:1118-1125 — declared as the descriptor's `output_model` and therefore the pinned `output_schema_sha256`, but **never instantiated**: `invoke` builds a plain `references: dict[str, Any]` by hand and returns `ToolResult(tool=…, version=…, references=references)`):
  - `run_id: str` — `RunRow.run_id` as text.
  - `status: str` — `RunRow.status`, one of `account_research_store.JobStatus = Literal["not_started", "in_progress", "needs_review", "completed", "suspended"]`. It is derived from the run's jobs by `refresh_run_status`'s single statement ("the run row is never a second opinion about its jobs"): any `in_progress` → `in_progress`; any `not_started` alongside a `completed`/`needs_review` → `in_progress`, else `not_started`; any `suspended` → `suspended`; any `needs_review` → `needs_review`; otherwise `completed`.
  - `icp_artifact_key: str` — the storage key of the confirmed ICP document the run was pinned to.
  - `product_selection_version: int` — the project's confirmed product-selection version the run was pinned to.
  - `effort: str` — `RunRow.effort`; the launch vocabulary is `Arv2Effort = Literal["full", "reduced", "cheap-pass"]` (launch default `"full"`).
  - `committee_cap: int` — how many committee members the account job may seat (launch input constraint: `Field(5, ge=1, le=12)`).
  - `jobs: tuple[dict[str, str], ...]` — one dict per row of `list_jobs(conn, run_id=…)`, which is "Every job of a run, oldest first — the order the driver queued the accounts in" (`ORDER BY created_at, job_id`). Each dict has exactly four string keys, built inline:
    - `job_id` — `str(job.job_id)` (deterministic: `arv2_job_id(run_id, subject_id)`).
    - `account_entity_id` — `str(job.account_entity_id)`; for a person job this is the contact's own account.
    - `status` — `JobRow.status`, the same five-value `JobStatus` vocabulary as the run.
    - `failure_code` — `job.failure_code or ""`; an empty string means "no failure recorded", and `failure_message` is deliberately not carried.
    - (The underlying `JobRow` also carries `run_id`, `workspace_id`, `subject_type`, `subject_entity_id`, `profile_sha256`, `attempt`, `started_at`, `finished_at`, `finalization`, `model_rounds`, `tool_calls`, `cost_usd`, `credits`, `media_seconds` and `stage` — none of which this output exposes.)
  - Bounds: **none in code.** There is no `MAX_*` constant, no page size, no candidate cap and no byte budget on this tool's `references` — `list_jobs` returns every job of the run and all of them are serialized. The practical ceiling comes from the launch side: `LaunchArv2AccountResearchInput.account_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=200)` and `committee_cap: int = Field(5, ge=1, le=12)`, so one run can accumulate up to 200 account jobs plus their committee person jobs. `READ_REFERENCES_BUDGET` / `READ_REFERENCES_BUDGET_BYTES` is **not found in code** (searched the whole worktree): it exists only in the unexecuted plans `docs/superpowers/plans/2026-09-13-read-tools-hotfix.md` (`READ_REFERENCES_BUDGET_BYTES = 12 * 1024`) and `docs/superpowers/plans/2026-09-13-paged-and-spilled-reads.md`, and those plans scope it to the `arv2/read_tools.py` trio, not to this tool.
  - `RunRow` fields the output drops entirely: `workspace_id`, `project_id`, `brand_id`, `project_run_id`, `icp_artifact_sha256`, `icp_key`, `icp_version`, `directive_text`, `profile_ref`, `profile_sha256`, `requested_by_user_id`, `request_sha256`, `created_at`, `finished_at`.
- **Side effects / what becomes true afterwards**: none — a pure read, and the `model_description` says so: "Effect-free; it never starts, resumes or changes research." `DbArv2LaunchService.read_run` opens one transaction (`ConnFactory`, default `clue_db.transaction`) and runs two SELECTs (`read_run`, then `list_jobs`); no row is written, no fleet task is enqueued, no gate is opened, no card appears in chat, and nothing is re-launched. The invocation is journaled by the runner's log_span/idempotency wrapper; `parameter_policy = JournalParameterPolicy(safe_display_fields=("run_id",))` is the allowlist for the display-safe journal projection. Registered at toolbelt_wiring.py:2808 via `build_arv2_launch_tools(arv2_account_launch)` with `make_default=True` — "Registered on every deployment so the platform's write surface stays complete and the authority audit sees both tools"; authority `"read_arv2_account_research_run": (AgentRole.HEAD_OF_ABM,)` (agent_registry_wiring.py:328). Unlike its launching siblings and unlike the three `arv2_reads` tools, it stays **installed on the dev/trial surface**: "`read_arv2_account_research_run` stays installed: it is read-only, spends nothing, and addresses nobody" (agent_registry_wiring.py:485-487).
- **Where the skill teaches it**: stage0-interview v26 **§7 "Launch account research"** — "A successful result means the jobs were queued or replayed. It is never completed research. Say the research is running, and say that each account's buying committee is researched automatically once the account job settles. Use `read_arv2_account_research_run` when the human asks how it is going." (SKILL.md:194-206). It is **not** mentioned in §7c (the read-before-you-speak section), which covers only the three `arv2/read_tools.py` reads. Pinned in the skill front matter (SKILL.md:54-57, `input_schema_sha256: 029dddd3db84fcdbb076aac5dd874d7e2cad14cdbefb945555b8e820a3b7d0ba`, `output_schema_sha256: 5663712620131bc9019b80e535f021552f2fcef08e410400d65bea71ad606162`) and in `head-of-abm/v49/profile.yaml:152-155`.
- **Source**: `platform/api/clue_api/arv2/account_research_launch.py:1-20` (module docstring), `:95-149` (`__all__`, `Arv2Effort`), `:164-233` (`Arv2LaunchRequest`, `Arv2LaunchRefused` codes, `QueuedJob`, `Arv2LaunchReceipt`, `Arv2RunView`), `:1000-1075` (`Arv2LaunchService` protocol, `DbArv2LaunchService.read_run`), `:1078-1097` (`LaunchArv2AccountResearchInput` bounds), `:1114-1125` (input/output models), `:1127-1137` (`_not_composed`), `:1337-1399` (`ReadArv2AccountResearchRunTool`), `:1401-1415` (`build_arv2_launch_tools`); `platform/api/clue_api/arv2/account_research_store.py:67-75` (`JobStatus`, `JobSubject`, `JobStage`), `:89-120` (`_RUN_COLUMNS`, `_REFRESH_RUN`), `:123-187` (`RunRow`, `JobRow`), `:398-441` (`read_run`, `list_jobs`); `platform/api/clue_api/arv2/committee_step.py:200-230` (person jobs land in the account's run); `platform/toolbelt/clue_toolbelt/envelope.py:1-412`; `platform/api/clue_api/toolbelt_wiring.py:69,2804-2809`; `platform/api/clue_api/fleet_main.py:750,927-929,991`; `platform/api/clue_api/projections_main.py:132-133,161`; `platform/api/clue_api/agent_registry_wiring.py:320-328,475-490,615-632`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:54-57,194-206`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:152-155`.
- **Discrepancy**: (1) The declared `output_model` is never used — `invoke` returns a hand-built `references` dict, so nothing validates the payload against `ReadArv2AccountResearchRunOutput` (contrast the three `arv2/read_tools.py` tools, which construct their output model and `model_dump()` it). The pinned `output_schema_sha256` in the skill/profile therefore describes a shape the code asserts by convention only. (2) The `model_description` promises "the state of each account's job", but `list_jobs` returns **every** job of the run including `subject_type="person"` committee/person jobs (`committee_step.py:209-222` writes them under the same `run_id`), and the output carries neither `subject_type` nor `subject_entity_id` — so several rows can share one `account_entity_id` and read as duplicate account jobs. (3) A malformed `run_id` raises an unhandled `ValueError` from `UUID(inputs.run_id)` inside `invoke` rather than a typed refusal — its ARV2 read siblings deliberately fold a malformed id into `account_not_found` / `discovery_run_not_found`. (4) The tool declares `pin_requirements = ("project",)` but never resolves or checks a project: scoping is workspace-only, so a run of a *different project of the same workspace* is served without comment. (5) The `model_description` says the read includes "the failure code of anything that needs review" — `failure_message` (the human-readable half of `JobRow`) is dropped, and `stage` (the progress field the research card reads) is not served either, so "how is it going?" is answerable only at job granularity.


---

## `get_research_view@1`

- **Address**: `get_research_view@1` — effect class `read` (`effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.READ`), replay policy `effect_free` (`durable_identity="exact workspace/project/run/product/subject read"`, `operation_id_required=False`, `external_boundary=ExternalReplayBoundary.NONE`, `notes="the tool resolves current authority and returns references only"`), pin_requirements `("project_run", "field_registry", "verification_policy")`, opens a human gate: no.
- **Purpose**: Resolves the live, governed C7 research view for exactly one research subject (an account or a contact) inside one project run, and returns only its stable references — the view id, the hash of the source state it was composed from, any matching saved snapshot id, and an opaque fetch reference. It composes nothing durable and returns no research body: the tool's own docstring is "Resolve the live governed view and return only its stable fetch reference and hashes." The scope is proved fail-closed against `project` / `project_run` / `account_entity`-or-`contact_entity` before anything is read, so a subject outside the exact workspace/project/run/product scope is refused rather than served.
- **Inputs** (`GetResearchViewInput(ResearchViewScopeInput)`, `platform/api/clue_api/research_view_tools.py:56-69`; `GetResearchViewInput` adds no fields of its own — its body is `pass`. `ToolInput` base: `model_config = ConfigDict(frozen=True, extra="forbid")`):
  - `project_id: str` (no default), constraint `Field(min_length=1)` — no field description, comment or docstring in code (searched `research_view_tools.py:56-69`).
  - `project_run_id: UUID` (no default) — no description in code.
  - `subject_entity_id: UUID` (no default) — no description in code.
  - `subject_entity_type: EntityType | None = None` — no description on the tool input; the mirrored core field (`clue_core/research_view.py:692-695`) carries the comment "Optional for backwards-compatible callers. HTTP account/contact routes and production tools always stamp it, letting the shared scope resolver reject cross-kind ids without probing both identity tables."
  - `product_id: str | None = Field(default=None, min_length=1)` — no description in code.
  - Model-facing description: the tool sets no `model_description`, so the descriptor's generated default applies verbatim — `"Invoke exact governed platform tool get_research_view@1."`
  - Nested models: none. There is **no section selector on this input** — `section_kinds` exists only on `RecheckResearchViewInput` (the sibling `recheck_research_view@1`), not found in `get_research_view`'s schema (looked in `research_view_tools.py:56-78` and `clue_core/research_view.py:683-698`).
- **Preconditions and refusal codes** (`GetResearchViewTool.preconditions` → `_canary_failure` → `_ResearchViewScopeTool.preconditions`, `research_view_tools.py:80-91,94-164,337-358`):
  - `research_view_workspace_not_admitted` — a canary allowlist is configured (`admitted_workspace_ids` non-empty, from `CLUE_C7_WORKSPACE_CANARY_IDS`, default `()`) and this workspace is not in it. Message: "this workspace is not admitted to the research-view canary". Guidance: no guidance in code.
  - `research_view_feature_disabled` — `read_enabled` is false, i.e. `CLUE_C7_RESEARCH_VIEW_READ_ENABLED` is off (`clue_config/settings.py:546`, `c7_research_view_read_enabled: bool = False`; `.env.example:347` `CLUE_C7_RESEARCH_VIEW_READ_ENABLED=false`). Message: "research-view reads are disabled in this process". Guidance: no guidance in code.
  - `research_view_not_configured` — no `ResearchViewComposer` was injected in this process. Message: "the research-view composer is not configured in this process". Guidance: no guidance in code.
  - `research_view_subject_not_found` — the single scope query found no row joining `project` + `project_run` + (`account_entity` or `contact_entity` with `merged_into IS NULL`) for this workspace/project/run/product/subject. Message: "no canonical research subject exists in the exact workspace/project/run/product scope". Guidance: no guidance in code; the shared class docstring is "Shared fail-closed authorization for exact project/run/product/subject scope."
  - Ordering note: the canary and flag checks run *before* the DB scope check, so a disabled process never discloses whether the subject exists.
- **Output** (`ResearchViewRefOutput`, `platform/api/clue_api/tool_outputs.py:209-218`, populated from `ResearchViewRef.model_dump(mode="json")`, `clue_core/research_view.py:751-763`):
  - `view_id: str` — the composed live view's id (`ResearchViewId`).
  - `snapshot_id: str | None` — the most recent saved `research_view_snapshot` whose `source_state_sha256` equals the live view's, in the same workspace/project/run/product scope (`ORDER BY created_at DESC, snapshot_id DESC LIMIT 1`); `None` when no saved snapshot matches the current source state.
  - `workspace_id: str` — taken from `ctx.workspace_id`, never from inputs.
  - `project_id: str` — echoed from the input.
  - `subject_entity_id: str` — echoed from the input.
  - `product_id: str | None` — echoed from the input.
  - `source_state_sha256: str` — the hash of the underlying claim/source state the live view was composed from; this is what makes a matching snapshot identifiable.
  - `fetch_ref: str` — the opaque handle, literally `f"research-view:{view.view_id}"`.
  - Caps/bounds: none declared on this tool — no MAX_* constant, page size, section cap or reference budget in `research_view_tools.py` (searched the whole file). The result carries references only, never the view body (`ToolResult` contract: "The reference-carrying result of an invocation (never blobs)").
- **Side effects / what becomes true afterwards**: none durable. `ReplayPolicy.EFFECT_FREE` with `external_boundary=NONE`; the class comment is "read-only … the tool resolves current authority and returns references only". It writes no rows, queues no jobs, appends no `run_event` and emits no research-view event (that is `compose_dossier@1`'s job, which writes `research_view_snapshot`/`research_view_snapshot_section` and appends `research_view.updated`). The only record of a call is the standard runner journaling; the journal display allowlist is `("project_id", "project_run_id", "subject_entity_id", "product_id")`. Nothing appears in chat unless the agent reports it.
- **Where the skill teaches it**: not taught. `get_research_view` does not appear anywhere in `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md` — neither in the frontmatter `tools` pin nor in any section (§7c teaches the ARV2 reads `read_project_accounts` / `read_account_research` / `read_discovery_run` instead). The grant is profile-level only: `head-of-abm/v49/profile.yaml` lists `get_research_view@1` in `tools` and again in `delegation_tool_grants` for all three delegation roles (`research`, `content_drafter`, `reviewer`).
- **Source**: `platform/api/clue_api/research_view_tools.py:1-551` (input models 56-78; canary 80-91; shared scope tool 94-175; the tool 297-405; builder 523-551); `platform/api/clue_api/tool_outputs.py:209-218`; `libs/clue-core/clue_core/research_view.py:683-698,751-763`; `libs/clue-config/clue_config/settings.py:540-564`; `.env.example:347`; `platform/api/clue_api/toolbelt_wiring.py:140,2649-2651,3046-3054`; `platform/toolbelt/clue_toolbelt/envelope.py:93-220,285-332`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml`.
- **Discrepancy**: (1) Every input field is description-free, so the only model-facing prose is the generated boilerplate `"Invoke exact governed platform tool get_research_view@1."` — the agent is told nothing about what a research view is, which scope ids are trusted authority, or that `project_run_id` must belong to the project. Contrast `Stage0InspectionInput`'s docstring, which makes exactly this point ("a governed tool's model-visible description is generated boilerplate, so the input fields carry the *entire* prose surface"). (2) The tool is granted in profile v49 and to all delegation roles, but is default-off in every process (`c7_research_view_read_enabled=False`), so as composed today a call returns `research_view_feature_disabled` rather than a view. (3) The module docstring says "All three tools delegate to the one deterministic composer/snapshot/re-check path", yet `get_research_view` additionally runs its own raw `research_view_snapshot` lookup to attach `snapshot_id`.


---

## `inspect_statement_history@1`

- **Address**: `inspect_statement_history@1` — effect class `read` (`effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.READ`), replay policy `effect_free` (`durable_identity="exact workspace/project read of durable Stage-0 history"`, `operation_id_required=False`, `external_boundary=ExternalReplayBoundary.NONE`, `notes="read-only: the tool appends to neither the statement table nor the readiness ledger"`), pin_requirements `("project",)`, opens a human gate: no.
- **Purpose**: Reads back the durable interview history for one project — the `volunteered_statement` rows `record_interview_answer` wrote — one bounded page at a time, with each row's correction lineage in both directions and, where the evidence can still be read, the user's exact words resolved from the captured artifact. It is the tool that resolves the project card's `statements_over_cap` and `excluded_statement_evidence_missing` omissions: the card is hard-bounded, so history lives here rather than in the opening prompt. A row whose words cannot be read is returned with a named exclusion reason and a null quote — "the tool never fabricates the words it could not read, exactly as the card does not."
- **Inputs** (`InspectStatementHistoryInput(Stage0InspectionInput)`, `platform/api/clue_api/stage0_inspection_tools.py:108-167`; `ToolInput` base: `model_config = ConfigDict(frozen=True, extra="forbid")`):
  - `project_id: str` (no default), constraint `Field(min_length=1)` — "Trusted project authority; supplied by the platform, never by you."
  - `statement_id: UUID | None = None` — "One statement to read, with its whole correction lineage in both directions. Refused together with `route_key`: two selectors that disagree is a bug, not an intersection."
  - `route_key: str | None = None`, constraint `min_length=1` — "Read every statement under one route key instead of one statement. Refused together with `statement_id`."
  - `cursor: str | None = None`, constraint `min_length=1` (overrides the base field's description) — "Opaque position marker. This is the tool that resolves the card's `statements_over_cap` and `excluded_statement_evidence_missing` omissions — pass their `cursor` verbatim to read exactly the rows the card could not carry. A `next_cursor` from a previous page continues that walk; leave it out to start at the newest row. Never build or edit one."
  - Base-class docstring (`Stage0InspectionInput`): "Shared scope + position. `project_id` is engine-injected trusted authority, not model input; `cursor` is opaque and only ever came from a card omission or a previous page. … a governed tool's model-visible description is generated boilerplate, so the input fields carry the *entire* prose surface. In particular they are the only place the model can learn that a card `omissions` cursor is resolved by *this* tool."
  - Subclass docstring: "``statement_id`` **or** ``route_key``, or neither for the whole history. Supplying both is refused rather than silently intersected: two selectors that disagree is a caller bug, and an intersection would quietly return a narrower answer than either asked for."
  - The base `Stage0InspectionInput.cursor` description (shadowed here, kept for the readiness sibling): "Opaque position marker: either an `omissions[].cursor` from the project card (to read exactly what the card left out) or a previous page's `next_cursor` (to continue). Leave it out to start at the newest row. Never build or edit one — a cursor from another tool or another view is refused, not reinterpreted."
  - Nested models: none. The cursor is an opaque encoded payload (`encode_card_cursor` / `decode_card_cursor`), not a model the caller composes; its decoded shape is `{"kind": <cursor kind>, "before_statement_id": <uuid str>}`.
  - Model-facing description: no `model_description` is set, so the descriptor default applies — `"Invoke exact governed platform tool inspect_statement_history@1."`
- **Preconditions and refusal codes** (class docstring: "Reason codes: `stage0_project_not_found`, `statement_selector_ambiguous`, `cursor_invalid`, `cursor_kind_unsupported`, `statement_evidence_not_configured`."; `stage0_inspection_tools.py:218-258,311-329`):
  - `statement_selector_ambiguous` — both `statement_id` and `route_key` supplied. Message: "supply statement_id or route_key, not both". Guidance (from the input docstring): pick one; an intersection "would quietly return a narrower answer than either asked for".
  - `cursor_invalid` — the cursor does not decode (`ValueError`/`TypeError`/`UnicodeDecodeError` from `decode_card_cursor`). Message: "the supplied cursor is not a readable card cursor". Guidance: "Never build or edit one" (field description).
  - `cursor_kind_unsupported` — the decoded `kind` is not in `STATEMENT_CURSOR_KINDS = ("statements", "excluded_statement_evidence")`. Message: `f"this tool resolves cursor kinds {list(self.cursor_kinds)}"` → "this tool resolves cursor kinds ['statements', 'excluded_statement_evidence']". Guidance (from the class comment): "A cursor from the *other* tool is a typed refusal, never a silently-ignored position (which would serve page one and look like the end of history)."
  - `statement_evidence_not_configured` — no `StatementEvidenceReader` injected in this process. Message: "no statement evidence reader is configured in this process". Guidance (inline comment): "Fail-closed rather than returning rows with every quote blank: 'no evidence reader' and 'the words were erased' must never look the same to a reader."
  - `stage0_project_not_found` — the project is absent, or belongs to another workspace (checked last, so the selector/cursor/wiring failures never leak project existence). Message: "no such Stage-0 project in this workspace". The refusal is WARNING-logged (`stage0_inspection.project_scope_refused` with tool/actor/workspace/project). Guidance (module docstring): "a cross-tenant id is indistinguishable from a non-existent one (no existence leak) … Cross-*project* access is refused the same way rather than filtered to empty, because a silent empty page reads as 'no history' instead of 'not yours'."
- **Output** (`StatementHistoryOutput`, `platform/api/clue_api/tool_outputs.py:303-328`, returned as `model_dump(mode="json")`):
  - `project_id: str` — echoed from the input.
  - `view: str` — which view this page is: the cursor's `kind`, defaulting to `STATEMENT_CURSOR_KINDS[0]` = `"statements"`; the other legal value is `"excluded_statement_evidence"`.
  - `statements: list[dict[str, object]]` — the page's rows (see per-row keys below).
  - `page_size: int` — always the constant `MAX_INSPECTION_PAGE = 20` ("The hard page bound (spec §7: 'page size ≤ 20'). Not an input: a caller cannot ask for more, so the bound is a property of the contract rather than of the caller's restraint.").
  - `returned: int` — `len(page)`; `returned <= page_size` always.
  - `total_matching: int | None` — how many rows the selector matched; **null in the `excluded_statement_evidence` view** ("the total is genuinely unknown without resolving evidence for the entire ledger … Reporting the candidate-pool size there would let a caller read a truncated page as a complete one, so the field abstains instead").
  - `candidates_scanned: int` — how many candidate rows this page examined, which is what the cursor advanced by.
  - `has_more: bool` — `scanned_to < len(candidates)`.
  - `next_cursor: str | None` — `encode_card_cursor({"kind": view, "before_statement_id": <last consumed row id>})`, or `None` when the walk is finished (or nothing was consumed). "`has_more` + `next_cursor` are the complete-traversal contract in every view."
  - Per-row keys (`_statement_payload`, `stage0_inspection_tools.py:615-647`): `statement_id: str`; `onboarding_input_id: str`; `route_kind: str` (the `StatementRoute` value); `route_key: str`; `route_ref: str | None`; `supersedes: str | None` (this row's `correction_of_id`); `superseded_by: list[str]` (a **list** — corrections can fork; "silently choosing one version of what replaced a client's words is the wrong failure"); `superseded: bool`; `quote_start: int`; `quote_end: int`; `quoted_text: str | None` (null when excluded); `quote_excluded_reason: str | None` (the `ExcludedEvidenceReason` value — today only `artifact_missing`, "The captured onboarding artifact is gone — DSAR erasure, tombstone, or a purged row"); `created_at: str` (ISO-8601).
  - Other caps/bounds VERBATIM: `MAX_EXCLUSION_SCAN = 200` — "How many statements one `excluded_statement_evidence` page may *examine* before returning what it found so far with a resume cursor. The response stays ≤ `MAX_INSPECTION_PAGE` either way; this additionally bounds the evidence reads behind a page whose matches are sparse." `STATEMENT_CURSOR_KINDS = ("statements", "excluded_statement_evidence")`. Ordering is newest-first (`rows.sort(key=lambda row: (row.created_at, str(row.id)), reverse=True)`), the same order the card speaks. A stale cursor position resumes past the end (an empty page), never silently at the beginning.
- **Side effects / what becomes true afterwards**: none durable. The module docstring is explicit: "**Not writers.** `effect_class=READ` / `ReplayPolicy.EFFECT_FREE`: they append nothing to the statement table and nothing to the readiness ledger. The only record of a call is the standard runner journaling every tool gets." It reads `volunteered_statement` (through `read_statements`) plus artifact bytes via the injected evidence reader; the journal display allowlist is `("project_id", "statement_id", "route_key", "cursor")`. A refused project scope additionally emits the WARNING log line above. Nothing appears in chat unless the agent reports it.
- **Where the skill teaches it**: not taught. `inspect_statement_history` appears nowhere in `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md` — not in the frontmatter `tools` pin, not in §6 (which teaches writing statements via `record_interview_answer`), not in §7c (which teaches the three ARV2 reads). The grant is profile-level only (`head-of-abm/v49/profile.yaml`, `inspect_statement_history@1`).
- **Source**: `platform/api/clue_api/stage0_inspection_tools.py:1-441,540-707` (module contract 1-38; constants 90-105; inputs 108-184; shared tool 187-268; resume 270-284; the tool 287-441; payload helpers 546-647; builder 679-694); `platform/api/clue_api/tool_outputs.py:303-328`; `platform/projections/clue_projections/stage0.py:326-363`; `platform/api/clue_api/toolbelt_wiring.py:141,3021-3031`; `platform/toolbelt/clue_toolbelt/envelope.py:93-220`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md` (grep: no hits).
- **Discrepancy**: (1) The input docstring's premise — the field descriptions "are the only place the model can learn that a card `omissions` cursor is resolved by *this* tool" — is undercut by the skill, which never mentions the tool, the card omissions, or when to page history; the wiring comment still claims the deferred grant "landed against profile v10". (2) The wiring comment says both tools are "*not* withheld by the trial's `C6_SURFACE_POLICIES` entry … because they are read-only, effect-free, page-bounded and fail-closed", and asserts the tools run "inside `recipe0-stage0@4`'s interaction slot" — the current Head-of-ABM surface (profile v49 + skill v26) is a chat surface with no such instruction. (3) `StatementHistoryOutput.statements` is typed `list[dict[str, object]]`, i.e. the per-row shape is untyped in the output schema even though profile v49's changelog makes typed row models the rule for the newer reads — a row-shape change here would not move the pinned output digest.


---

# Part 2 — The launches (the ARV2 research lane)


---

## `launch_arv2_account_research@1`

- **Address**: `launch_arv2_account_research@1` — effect class `spend` (`ToolEffectClass.SPEND`), replay policy `domain_idempotent` (`ReplayPolicy.DOMAIN_IDEMPOTENT`; `durable_identity="workspace + project + account set + ICP digest + product-set version + profile digest"`, `operation_id_required` not set → class default `False`, `external_boundary=ExternalReplayBoundary.NONE`), pin_requirements `("project",)`, opens a human gate: **no** (it *requires* a human gate already taken — `ctx.action_ref` must be present — but it opens none of its own).

- **Purpose**: This is the only door into the ARV2 R2 research lane. Given a project and an explicit set of account entities, it validates every prerequisite (project exists in this workspace, every account exists and is this workspace's, the project has pinned a confirmed ICP document whose bytes still match, the named product-selection version was actually confirmed), then writes the authorization record: one `arv2_research_run` row whose id *is* the sha256 of the signed-off request, one `arv2_research_job` row per account, a project-run row, run lineage and project-account membership. After the transaction commits, the service offers one fleet task per job. Everything the driver later spends is spent against that run row, so relaunching the identical request lands on the same run, inserts no second job, and buys no second research pass; a job that later finds the ICP bytes or the agent-profile bytes moved refuses and asks to be relaunched.

- **Inputs** (`LaunchArv2AccountResearchInput`, `account_research_launch.py:1081-1089`; base `ToolInput` is `frozen`, `extra="forbid"`, so an unknown key is a loud `ValidationError`):
  - `project_id: str` — required, no constraint, no field description in code. Skill §7: "`project_id`: this project, from the project card in your context".
  - `account_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=200)` — no field description in code. Skill §7: "`account_entity_ids`: the account refs attached to the current turn, exactly". Each element is parsed with `UUID(value)` inside `invoke`.
  - `icp_artifact_key: str` — required, no constraint, no field description in code. Skill §7: "`icp_artifact_key` and `icp_artifact_sha256`: from the index card's confirmed ICP entry, never from a proposed one".
  - `icp_artifact_sha256: str` — required, no constraint, no field description in code. Same skill sentence as above.
  - `product_selection_version: int = Field(ge=1)` — required (only the `ge=1` constraint, no default). Skill §7: "`product_selection_version`: from the index card's product set".
  - `effort: Arv2Effort = "full"` — `Arv2Effort = Literal["full", "reduced", "cheap-pass"]` (`:149`). Verbatim comment at `:147-148`: "The run row's effort dial. Kept as a closed literal (and CHECK-ed in the migration) so a typo cannot silently become a research posture nobody defined." Skill §7 teaches `effort: "full"`.
  - `committee_cap: int = Field(5, ge=1, le=12)` — no field description in code. Skill §7 teaches `committee_cap: 5`. (DB CHECK is only `arv2_research_run_cap CHECK (committee_cap >= 1)`, `alembic/versions/a3602967bb73_arv2_r2_account_research_jobs.py:106`; the upper bound of 12 exists only in the input model.)
  - `directive_text: str = ""` — no field description in code. Skill §7: "the human's own words about what to look for in `directive_text`".
  - Not input fields — **ambient**, taken from `ToolContext` in `invoke` (`:1229-1241`), with the verbatim comment "The tenant and the requesting human are AMBIENT authority, never model-authored.": `workspace_id = ctx.workspace_id`; `requested_by_user_id = ctx.actor_id or ctx.actor`. `project_run_id` exists on the service-level `Arv2LaunchRequest` (`:180`) but the tool never sets it, so the launch derives it deterministically as `uuid5(NAMESPACE_URL, f"arv2-project-run:{project_id}:{icp_key}:{icp_version}")`.

- **Preconditions and refusal codes**:
  - `arv2_account_research_not_composed` — the lane is not composed on this deployment (`self._service is None`). Message verbatim: "the ARV2 account-research lane is not composed on this deployment (CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED)" (`_not_composed`, `:1128-1137`). Guidance: `build_arv2_launch_tools` docstring — the tool is registered everywhere so the agent "gets the named `arv2_account_research_not_composed` refusal rather than an `UnknownTool` it cannot explain to the human". Skill §7: "If the tool refuses, report the exact missing precondition … and remain `awaiting_input`. Never say the research started."
  - `launch_action_ref_missing` — `ctx.action_ref is None`. Message verbatim: "launching account research requires the captured user action that approved this exact account set" (`_trusted_action`, `:1140-1151`). Guidance (skill §7): "Launch only when the human's **current** message names the accounts … Never widen the set, never launch from an earlier message, and never launch before both gates are answered."
  - Every `Arv2LaunchRefused` raised by the service is re-raised as `PreconditionFailed([PreconditionFailure(refused.code, str(refused))])` (`:1244-1245`), so the codes below reach the agent identically:
    - `lane_disabled` — `settings.arv2_account_research_enabled` is false. Message: "CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED is false on this deployment" (`:258-261`). No guidance in code beyond the flag name.
    - `project_not_found` — no `project` row for this id in this workspace. Message: "project {project_id!r} has no row in workspace {workspace_id!r}, so there is no project run to research under" (`:267-273`, and the defensive repeat at `:291-299`). Code rationale: the project is checked first "so a launch naming a project that does not exist must be told THAT, rather than 'you have pinned no ICP'".
    - `account_not_found:<id>` — a named account has no row. Message: "account {account_id} does not exist; import or discover it before launching" (`_check_accounts`, `:440-443`). Guidance in docstring: refused **by id**, because "a launch of forty accounts that refuses with 'one of these is wrong' is a refusal a human cannot act on".
    - `account_not_in_workspace:<id>` — the account belongs to another tenant. Message: "account {account_id} belongs to another workspace and cannot be researched here" (`:444-448`).
    - `project_icp_not_pinned` — the project has pinned no confirmed ICP. Message: "project {project_id!r} has not pinned a confirmed icp-definition; confirm one at the ICP gate before researching anything" (`_project_icp_pin`, `:461-467`). Guidance: founder rulings 2026-09-10 — a project researches against the one confirmed ICP version a human pinned; there is no fallback to "the brand's newest confirmed".
    - `icp_artifact_not_project_pin` — the request names an ICP artifact that is not this project's pin. Message: "project {project_id!r} pins {pin.artifact_key!r} ({pin.artifact_sha256}); this request names {request.icp_artifact_key!r} ({request.icp_artifact_sha256})" (`:523-532`). Account-launch-only code.
    - `icp_artifact_not_found` — the pinned `brand_knowledge_document` row is not held by this workspace. Message: "the pinned document {pin.document_id} is not held by workspace {workspace_id!r}" (`:490-493`).
    - `icp_artifact_not_confirmed` — the pinned document is not a `confirmed` `icp-definition`. Message: "document {row['path']!r} is a {row['kind']!r} at status {row['status']!r}; a launch researches only against a confirmed icp-definition" (`:495-500`).
    - `icp_digest_mismatch` — the stored document's bytes are not the pinned bytes. Message: "the pinned ICP document's bytes are not the ones the project pinned: stored {…}, pinned {…}" (`:501-506`).
    - `icp_front_matter_invalid` — three spellings: unreadable YAML front matter ("document {path!r} carries no readable YAML front matter: {error}", `:559-562`), no `icp_key` ("document {path!r} names no icp_key; a run is pinned to the ICP's own key", `:568-572`), non-integer `version` ("document {path!r} has version {version!r}, which is not an integer; a run is pinned to the ICP version the human confirmed", `:573-578`).
    - `product_selection_version_unknown` — the named version is not among the project's confirmed product sets. Message: "project {project_id!r} has no confirmed product set at version {n}" plus " (confirmed: {sorted(versions)})" when any exist, else " (none confirmed yet)" (`_check_product_selection`, `:598-604`). Guidance in docstring: *any* confirmed version is accepted, not only the current one, "a launch pins the version the human saw, and a later confirmation must not silently repoint a run that is already authorized".
  - Untyped failure path (not a refusal code): a malformed uuid string in `account_entity_ids` raises `ValueError` out of `UUID(value)` in `invoke` (`:1233`) — no `PreconditionFailure` wraps it. No guidance in code.

- **Output** (`LaunchArv2AccountResearchOutput`, `:1092-1096`; the runner validates `ToolResult.references` against this model in JSON mode — `runner.py:48-64, 84-106`):
  - `run_id: str` — the deterministic run id, `uuid5(_RUN_NS, request_sha)` where `request_sha` is the sha256 of the canonical signed-off payload (`_request_sha256`, `:607-627`: workspace, project, **sorted** account ids, ICP sha, product-selection version, effort, committee cap, directive text, profile digest).
  - `job_ids: tuple[str, ...]` — one job id per named account, each `uuid5(_JOB_NS, f"{run_id}:{subject_id}")` (`arv2_job_id`, `:135-144`).
  - `replayed: bool` — `not inserted`; `True` means the run row already existed (`create_run` did not insert). Note `Arv2LaunchReceipt.to_enqueue` still carries **every** job of the run on a replay, verbatim: "*Every* job of the run is offered, not only the ones this call inserted… `replayed` still means 'the run row existed'."
  - Caps and constants (verbatim): input cap `account_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=200)`; `committee_cap: int = Field(5, ge=1, le=12)`; `product_selection_version: int = Field(ge=1)`. Fleet constants: `ARV2_ACCOUNT_DEDUP_PREFIX = "arv2-account-research:"` and `ARV2_ACCOUNT_TASK_PRIORITY = -100` (`fleet_task.py:33,37`; comment: "Account research outranks ordinary work but yields to onboarding (-150)"). Worker-side ceilings that govern the actual spend: `arv2_account_max_model_rounds: int = Field(default=100, ge=1)`, `arv2_account_max_tool_calls_per_round: int = Field(default=50, ge=1)`, `arv2_account_max_runtime_s: int = Field(default=1800, ge=60)`, `arv2_account_max_parallel_jobs: int = Field(default=4, ge=1)`, `arv2_account_provider_concurrency: int = Field(default=4, ge=1)`, `arv2_media_seconds_ceiling: int = 9000` (`libs/clue-config/clue_config/settings.py:343-358, 331-333`).

- **Side effects / what becomes true afterwards**:
  - Inside one transaction (`DbArv2LaunchService.launch`, `:1030-1047`): `ensure_project_run(...)` writes/joins the deterministic `project_run` row at `ProjectPhase.DEEP`; `create_run` inserts one `arv2_research_run` row (`account_research_store.py:218`) carrying workspace, project, brand, project-run, ICP key/sha/key/version, product-selection version, effort, committee cap, directive text, `profile_ref=ARV2_ACCOUNT_PROFILE_REF`, `profile_sha256`, requester and `request_sha256`; `record_run_lineage(kind="entity_research")` writes the run-lineage row; per account `ensure_project_account(..., added_via="manual")` writes `project_account` membership; `create_job` inserts one `arv2_research_job` row per account with `subject_type="account"` (`account_research_store.py:277`).
  - After the commit (`enqueue_launched_jobs`, `:382-421`): one `fleet_task` row per job (`FleetTaskKind.ARV2_ACCOUNT_RESEARCH`, work id = job id, dedup key `arv2-account-research:<job_id>`, priority `-100`, payload `{job_id, run_id, workspace_id}`, `reopen_terminal=False`). The ordering is the safety property (verbatim, `Arv2LaunchReceipt`): "Rows first, offer second (the O3 rule, `onboarding_routes`)."
  - **Real money is spent — but by the fleet worker, not by this call.** Each task drives `account_research_driver`, whose agent loop makes model and provider calls (OpenRouter structuring/media models, AI Ark, media transcription, web retrieval) bounded by the ceilings above and settled per call on `provider_call_ledger`. The driver re-checks the run's ICP digest and the profile digest before a single model call and lands `needs_review` with a named `failure_code` instead of raising (`account_research_driver.py:1-24`).
  - Downstream: an account job that settles resolves the buying committee, creates the confirmed members as contacts, and enqueues one person job each on the same queue (`fleet_main.py:768-772`). In the UI the research appears on the account's research surfaces (progress card stages `deep_research → synthesis → committee → member_research`, `account_research_store.py:72-76`) and `read_arv2_account_research_run@1` reports run/job status and `failure_code`.

- **Where the skill teaches it**: `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md` — front matter tool grant at lines 42-44; **§7 "Launch account research"** (lines 194-207) is the procedure (when to call, the six argument rules, "A successful result means the jobs were queued or replayed. It is never completed research", the refusal handling); §7c (lines 218-225) tells it to read with `read_arv2_account_research_run` / `read_account_research` rather than re-launch; §10 (lines 243-245) bounds it ("never start anything the human has not asked for on the current turn").

- **Source**: `platform/api/clue_api/arv2/account_research_launch.py:1-135, 135-379, 382-421, 424-628, 1002-1075, 1081-1096, 1128-1152, 1168-1256, 1403-1415`; `platform/api/clue_api/arv2/fleet_task.py:1-40`; `platform/api/clue_api/arv2/account_research_store.py:66-110, 218-295`; `platform/api/clue_api/toolbelt_wiring.py:69-72, 2658-2659, 2801-2809`; `platform/api/clue_api/projections_main.py:130-165`; `platform/api/clue_api/fleet_main.py:740-775, 920-995`; `libs/clue-config/clue_config/settings.py:309-358`; `platform/toolbelt/clue_toolbelt/envelope.py:69-230, 280-412`; `platform/toolbelt/clue_toolbelt/runner.py:48-106`; `platform/fleet/clue_fleet/enums.py:45-72`; `platform/fleet/clue_fleet/queue.py:766-790`; `alembic/versions/a3602967bb73_arv2_r2_account_research_jobs.py:93,106`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:42-44,194-207,218-225,243-245`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:86-92`.

- **Cost**: `estimate()` returns verbatim
  ```python
  ToolEstimate(
      cost_cents=Decimal(0),
      detail={
          "basis": "arv2_account_research_per_account_ceilings",
          "accounts": len(inputs.account_entity_ids),
      },
  )
  ```
  with the verbatim rationale "A research job's spend is governed by the lane's own ceilings and settles in `provider_call_ledger` per call; there is no honest per-account prior to quote here, so the estimate carries the *shape* of the spend (how many accounts) rather than a number nobody derived." The **call itself** buys nothing; the **run it starts spends real money against external providers** (model + data providers, per the driver's ceilings), which is why the tool is classified `SPEND`.

- **Discrepancy**: (a) `model_description` says the run is "pinned to the confirmed ICP artifact digest", which reads as though the caller *selects* the ICP; in code the caller-supplied `icp_artifact_key`/`icp_artifact_sha256` are only a cross-check against the project's own pin — any other artifact is refused `icp_artifact_not_project_pin` (`:520-534`), and the run's `icp_key`/`icp_version` are read out of the pinned document's front matter, never from the call. (b) The tool is `effect_class = SPEND` yet `estimate()` reports `cost_cents=Decimal(0)`; the zero is a deliberate "no honest prior", not a free call (comment `:1214-1217`). (c) A malformed uuid in `account_entity_ids` escapes as a bare `ValueError` from `invoke` rather than as one of the typed refusals the module docstring promises ("**Every refusal is typed**", `:11-14`). (d) `LaunchArv2AccountResearchOutput` is declared but `invoke` returns `ToolResult.references` directly — the typed shape is enforced only by the runner's `validate_tool_output_references` (`runner.py:48-64`), not inside the tool.


---

## `launch_arv2_person_research@1`

- **Address**: `launch_arv2_person_research@1` — effect class `spend` (`ToolEffectClass.SPEND`), replay policy `domain_idempotent` (`ReplayPolicy.DOMAIN_IDEMPOTENT`; `durable_identity="workspace + project + contact set + resolved ICP digest + product-set version + profile digest"`, `operation_id_required` not set → class default `False`, `external_boundary=ExternalReplayBoundary.NONE`), pin_requirements `("project",)`, opens a human gate: **no** (it requires an already-captured user action, `ctx.action_ref`, and opens no gate of its own).

- **Purpose**: The same R2/R3 lane door as the account launch, for **named people who already exist as contacts of this workspace**. Given a project and a set of contact entity ids, it validates the prerequisites (project exists here; every contact exists here, is not a merged loser, and has an account this workspace holds; the project has pinned a confirmed ICP document; the project has a currently-confirmed product set), then writes a **run of its own** — a separate authorization record, because "this research was authorized by a different human act… pinning it to an older run would claim an approval nobody gave" — with one person job per contact, and (only for a person who holds no persona claim yet) writes the committee-seat claim that makes them visible on their account's contact list. It never creates a person. After the commit the service offers one fleet task per job.

- **Inputs** (`LaunchArv2PersonResearchInput`, `account_research_launch.py:1098-1105`; base `ToolInput` is `frozen`, `extra="forbid"`):
  - `project_id: str` — required, no constraint, no field description in code. Skill §8: call with "`project_id`".
  - `contact_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=50)` — no field description in code. Skill §8: "the `contact_entity_ids` attached to the current turn exactly … Never add a person the human did not name". Each element is parsed with `UUID(value)` in `invoke`.
  - `directive_text: str = ""` — no field description in code. Skill §8: "the human's own words in `directive_text`".
  - `persona: Persona = Persona.USER` — `Persona` is the closed platform vocabulary `StrEnum`: `CHAMPION = "champion"`, `ECONOMIC_BUYER = "economic_buyer"`, `TECHNICAL_EVALUATOR = "technical_evaluator"`, `BLOCKER = "blocker"`, `USER = "user"` (`libs/clue-core/clue_core/enums.py:358-367`). Verbatim field comment (`:1102-1104`): "The committee seat every named person is given, from the platform's closed vocabulary. It is what makes them visible on their account's contact list at all (W2), and it is only written for a person who does not already hold a seat." The service-level request repeats the rationale verbatim (`:652-658`): "The seat the requesting human puts every named contact in. It is part of the request because a person launched on demand is otherwise **nobody**: the account's contact list is read from the committee claims (`contact_eligibility.Arv2CommitteeReferenceSource`), so a person with no `contact.persona` claim is researched at cost and then invisible on their own account's screen (walk finding W2, 2026-09-09). `user` is the default because it is the seat that assumes the least — the person who would operate the product — and the vocabulary is the platform's closed one, so a launch can never invent a role." Skill §8: "`persona` only when the human said which committee seat a person holds. Otherwise leave the default."
  - Not input fields — **ambient**, from `ToolContext` in `invoke` (`:1312-1320`), with the verbatim comment "The tenant and the requesting human are AMBIENT authority, never model-authored.": `workspace_id = ctx.workspace_id`, `requested_by_user_id = ctx.actor_id or ctx.actor`. `Arv2PersonLaunchRequest.project_run_id` (`:651`) is never set by the tool, so the project run is the deterministic `uuid5(NAMESPACE_URL, f"arv2-project-run:{project_id}:{icp_key}:{icp_version}")`.
  - Deliberately **not** inputs: there is no `icp_artifact_key`/`icp_artifact_sha256`/`product_selection_version`/`effort`/`committee_cap` on this model. The launch resolves the ICP from the project's pin, the product-selection version from `current_project_product_set`, sets `effort="full"` and `committee_cap=len(request.contact_entity_ids)` itself (`:746-769`, docstring `:672-679`).

- **Preconditions and refusal codes**:
  - `arv2_account_research_not_composed` — the lane is not composed (`self._service is None`; the person tool shares the account lane's flag and message). Message verbatim: "the ARV2 account-research lane is not composed on this deployment (CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED)" (`_not_composed`, `:1128-1137`, used by `LaunchArv2PersonResearchTool.preconditions`, `:1293-1297`). Guidance (`build_arv2_launch_tools`, `:1403-1410`): the named refusal exists so the agent is not handed an `UnknownTool` "it cannot explain to the human".
  - `launch_action_ref_missing` — `ctx.action_ref is None`. Message verbatim: "launching person research requires the captured user action that approved researching these exact people" (`_trusted_person_action`, `:1154-1165`). Guidance (skill §8): "Launch people yourself only when the human's **current** message names specific people … never launch from an earlier message."
  - Service refusals, each re-raised as `PreconditionFailed([PreconditionFailure(refused.code, str(refused))])` (`:1323-1324`):
    - `lane_disabled` — message "CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED is false on this deployment" (`:682-685`).
    - `no_contacts` — message "a person launch must name at least one contact" (`:686-687`). (Unreachable from the tool: `min_length=1` rejects it first; reachable for CLI/direct callers.)
    - `project_not_found` — message "project {project_id!r} has no row in workspace {workspace_id!r}" (`:689-694`), plus the defensive repeat "project {project_id!r} has no project run to research under" (`:729-736`).
    - `contact_not_found:<id>` — the contact has no row **or** belongs to another workspace. Message: "no contact {contact_id} in workspace {workspace_id!r}; resolve the person before researching them" (`_check_contacts`, `:936-941`). Docstring guidance verbatim: "A contact of another workspace is `contact_not_found`, not 'forbidden': the caller learns nothing about a tenant it may not see, and the fix is the same either way — name a contact this workspace holds."
    - `contact_merged:<id>` — the contact was merged into a survivor. Message: "contact {contact_id} was merged into {contact.merged_into}; research the surviving person instead, or their claims land on a row nothing reads" (`:942-947`).
    - `contact_without_account` — the contact names an account this workspace does not hold (marked `# pragma: no cover`; "The composite FK should make this unrepresentable"). Message: "contact {contact_id} names account {…}, which this workspace does not hold; a person is researched at their employer" (`:948-956`).
    - `project_icp_not_pinned` — message "project {project_id!r} has not pinned a confirmed icp-definition; confirm one at the ICP gate before researching anything" (`_project_icp_pin`, `:461-467`). Code comment at the call site (`:696-699`): the person launch "now reads the project's own pin, like every other consumer", instead of the old "brand's newest confirmed".
    - `icp_artifact_not_found` — "the pinned document {document_id} is not held by workspace {workspace_id!r}" (`:490-493`).
    - `icp_artifact_not_confirmed` — "document {path!r} is a {kind!r} at status {status!r}; a launch researches only against a confirmed icp-definition" (`:495-500`).
    - `icp_digest_mismatch` — "the pinned ICP document's bytes are not the ones the project pinned: stored {…}, pinned {…}" (`:501-506`).
    - `icp_front_matter_invalid` — unreadable front matter / missing `icp_key` / non-integer `version`, messages as at `:559-578`.
    - `product_set_not_confirmed` — `current_project_product_set` returned `None`. Message: "project {project_id!r} has no confirmed product set; confirm one before researching anybody" (`:709-714`).
    - Not raised on this path: `icp_artifact_not_project_pin` and `product_selection_version_unknown` are account-launch-only (the person launch takes no artifact ref and no version from the caller), and `account_not_found:<id>` / `account_not_in_workspace:<id>` are replaced by `contact_without_account`.
  - Untyped failure path: a malformed uuid string in `contact_entity_ids` raises `ValueError` out of `UUID(value)` in `invoke` (`:1316`) rather than a typed refusal. No guidance in code.

- **Output** (`LaunchArv2PersonResearchOutput`, `:1108-1112`; validated by the runner against `ToolResult.references` in JSON mode, `runner.py:48-64, 84-106`):
  - `run_id: str` — `uuid5(_RUN_NS, request_sha)` where `request_sha` is `_person_request_sha256` (`:966-994`) over `{"subject": "person", workspace_id, project_id, sorted contact ids, persona, resolved icp_artifact_sha256, product_selection_version, directive_text, profile_sha256}`. The `"subject": "person"` discriminator is what keeps a person run distinct from an account run of the same project; the persona is inside it "because the same people at a different persona is a different request".
  - `job_ids: tuple[str, ...]` — one per contact, `arv2_job_id(run_id, contact_id) = uuid5(_JOB_NS, f"{run_id}:{contact_id}")`. An account job and a person job under one run can never collide because the subjects are different entities (`:135-144`).
  - `replayed: bool` — `not inserted` (the run row already existed). As with the account launch, **every** job of the run is re-offered on a replay.
  - Caps and constants (verbatim): `contact_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=50)`; the run row's `committee_cap=len(request.contact_entity_ids)` (`:761`) — the DB constraint is only `arv2_research_run_cap CHECK (committee_cap >= 1)` (`alembic/versions/a3602967bb73_arv2_r2_account_research_jobs.py:106`), so a 50-person launch is legal even though the *account* launch's input caps its own `committee_cap` at `le=12`. Person-job media ceiling: `arv2_person_media_max_items: int = Field(default=3, ge=0)` with the verbatim note "A person is a much smaller media surface than an account, and each item costs a transcription; 0 disables media for person jobs entirely" (`libs/clue-config/clue_config/settings.py:360-366`). Fleet constants shared with the account lane: `ARV2_ACCOUNT_DEDUP_PREFIX = "arv2-account-research:"`, `ARV2_ACCOUNT_TASK_PRIORITY = -100` (`platform/api/clue_api/arv2/fleet_task.py:33,37`).

- **Side effects / what becomes true afterwards**:
  - In one transaction (`DbArv2LaunchService.launch_person`, `:1049-1064`): `ensure_project_run(...)` at `ProjectPhase.DEEP`; one new `arv2_research_run` row via `create_run` with `profile_ref=ARV2_PERSON_PROFILE_REF`, the person profile's digest, `effort="full"`, `committee_cap=len(contacts)`, the resolved ICP key/sha/key/version and the *current* product-selection version; `record_run_lineage(kind="entity_research")`; per contact `ensure_project_account(..., added_via="manual")` for the person's employer account and `create_job(..., subject_type="person", subject_entity_id=contact_id)` into `arv2_research_job`.
  - **A committee claim write**: `seat_person_on_committee` (`:857-911`) writes the `contact.persona` claim set (via `committee_member_claims`, `ExtractionMethod.HUMAN`, tier 1, `rationale=f"launched on demand by {requested_by_user_id}"`, `confirmed_by=None`) through `LenientClaimWriter` — **only** when the contact holds no live `PERSONA_FIELD` claim. Verbatim: "A person who **already** holds a live persona claim is left alone. Re-seating them would let a launch overwrite the committee's own assessment ('champion', read off a page that says so) with a default nobody chose". No URL is cited and that is not a refusal: `ExtractionMethod.HUMAN` is not one of the writer's URL-requiring methods.
  - After the commit (`enqueue_launched_jobs`, `:382-421`): one `fleet_task` per job — `FleetTaskKind.ARV2_ACCOUNT_RESEARCH`, work id = job id, dedup key `arv2-account-research:<job_id>`, priority `-100`, payload `{job_id, run_id, workspace_id}`, `reopen_terminal=False`. Rows first, offer second, for the reason `Arv2LaunchReceipt` gives.
  - **Real money is spent by the fleet worker**, not by this call: each person job runs the R3 person agent (model rounds, provider calls, up to `arv2_person_media_max_items` transcriptions), settled per call on `provider_call_ledger`; the driver re-checks the run's ICP digest and the profile digest before any model call and lands `needs_review` with a named `failure_code` rather than raising.
  - In the UI: the person now appears on their account's contact list (that is what the seat claim buys — walk finding W2), their job walks the `deep_research → synthesis` stages of the research progress card (`account_research_store.py:72-76`), and the run is readable through the ARV2 read surfaces.

- **Where the skill teaches it**: `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md` — front matter tool grant at lines 50-52; **§8 "Research named people"** (lines 226-233) is the procedure: account research already covers the committee, so launch people only when the current message names them; call with `project_id`, the turn's `contact_entity_ids` exactly, the human's words in `directive_text`, and `persona` only when the human said the seat; "a successful result means the jobs were queued. Say the research is running. It is never completed research." §10 (lines 243-245) bounds it.

- **Source**: `platform/api/clue_api/arv2/account_research_launch.py:1-135, 135-144, 382-421, 451-583, 630-994, 1002-1075, 1098-1112, 1128-1166, 1258-1334, 1403-1415`; `platform/api/clue_api/arv2/account_research_store.py:66-76, 218-295`; `platform/api/clue_api/arv2/fleet_task.py:1-40`; `libs/clue-core/clue_core/enums.py:358-367`; `libs/clue-config/clue_config/settings.py:309-366`; `platform/api/clue_api/toolbelt_wiring.py:69-72, 2658, 2801-2809`; `platform/api/clue_api/projections_main.py:130-165`; `platform/api/clue_api/fleet_main.py:740-775, 920-995`; `platform/toolbelt/clue_toolbelt/envelope.py:69-230, 280-412`; `platform/toolbelt/clue_toolbelt/runner.py:48-106`; `alembic/versions/a3602967bb73_arv2_r2_account_research_jobs.py:93,106`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:50-52,226-233,243-245`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:103-109`.

- **Cost**: `estimate()` returns verbatim
  ```python
  ToolEstimate(
      cost_cents=Decimal(0),
      detail={
          "basis": "arv2_person_research_per_person_ceilings",
          "people": len(inputs.contact_entity_ids),
      },
  )
  ```
  (no explanatory comment on this one; its account sibling's comment states the shared rationale — the spend "is governed by the lane's own ceilings and settles in `provider_call_ledger` per call"). The call itself buys nothing; the runs it starts spend real money against external providers, which is why it is classified `SPEND`.

- **Discrepancy**: (a) `model_description` says the run is pinned "to the project's currently confirmed ICP and product selection"; in code the ICP is the project's **pin** (`current_project_icp_pin` → the exact version a human pinned, explicitly *not* "the newest confirmed"), while only the product selection is the *current* one (`current_project_product_set`) — two different resolution rules under one phrase. (b) `model_description` says "It researches existing contacts and never creates a person" — true of entities, but the launch does perform a durable **claim write** (the `contact.persona` committee seat) for any named person who holds none, which the description mentions only as "the committee seat each named person is given". (c) The tool is `effect_class = SPEND` with `estimate()` reporting `cost_cents=Decimal(0)`. (d) A malformed uuid in `contact_entity_ids` escapes as a bare `ValueError` from `invoke`, contradicting the module docstring's "**Every refusal is typed**" (`:11-14`). (e) `Arv2LaunchRefused`'s docstring enumerates the person launch's added codes as "`no_contacts`, `contact_not_found:<id>`, `contact_merged:<id>`, `contact_without_account` and `product_set_not_confirmed`" — accurate, but the shared list above it includes `product_selection_version_unknown` and (for the account launch) `icp_artifact_not_project_pin`, neither of which this path can raise.


---

## `launch_arv2_discovery@1`

- **Address**: `launch_arv2_discovery@1` — effect class `spend` (`ToolEffectClass.SPEND`), replay policy `domain_idempotent` (`ReplayPolicy.DOMAIN_IDEMPOTENT`; `durable_identity="workspace + project + pinned ICP digest + target count + provider ask + criteria gate keys"`, `operation_id_required` not set → class default `False`, `external_boundary=ExternalReplayBoundary.NONE`), pin_requirements `("project",)`, opens a human gate: **no** (it requires an already-captured user action, `ctx.action_ref`; the human's approval of the *found* companies happens later, on the accounts table, not here).

- **Purpose**: The only door into the ARV2 R4 verified-account-discovery lane. For one project it resolves the confirmed ICP document the project pinned, **compiles the brief out of that document before writing anything** (so a criteria gate key the document does not define refuses the launch instead of being discovered by a worker that already paid for a webset), and writes one `arv2_discovery_run` row whose id is the sha256 of the request. After the transaction commits the service offers one fleet task, and the worker buys an Exa Webset long list, verifies each company gate by gate with Answer calls, and lands candidate accounts with a fit score. The launch approves nothing and researches nothing: candidates appear on the accounts table and a human adds the ones they want. Asking the same thing twice is one run, one webset and one bill.

- **Inputs** (`LaunchArv2DiscoveryInput`, `discovery_launch.py:710-713`; base `ToolInput` is `frozen`, `extra="forbid"`):
  - `project_id: str` — required, no constraint, no field description in code. Skill §7b: call with "`project_id`".
  - `target_count: int = Field(default=20, ge=1, le=500)` — no field description in code. Skill §7b: "the number of accounts the human wants (`target_count`)". The service-level guard `:474-478` repeats the floor for non-tool callers with the verbatim comment "The tool's input model bounds this 1–500; the CLI and direct callers do not, and a run for zero companies would buy a webset nobody can use."
  - `relaxed_enabled: bool = True` — no field description in code. Skill §7b: "Leave `relaxed_enabled` on unless the human says they want strict matches only."
  - Not input fields — **ambient**, from `ToolContext` in `invoke` (`:803-814`), with the verbatim comment "The tenant and the requesting human are AMBIENT authority, never model-authored.": `workspace_id = ctx.workspace_id`, `requested_by_user_id = ctx.actor_id or ctx.actor`, and `launching_turn_ref = ctx.action_ref if ctx.principal_kind == "service" else None` with the verbatim comment "The turn this launch is an act of. When the deepagent launches from the fleet the invoker is a *service* principal (`svc_execution_worker`), which is nobody's owner (ruling 10′: creator is owner) — the launch resolves the turn's human from this." `_requesting_human` (`:389-412`) then reads `agent_turn_submission.submitted_by_user_id` for a `turn-action:<uuid>` ref; an unresolvable ref falls back to the invoker's id.
  - Deliberately **not** inputs (resolved from the pinned document and settings): `strict_count` (`None` → `settings.arv2_discovery_strict_count`), `criteria_gate_keys` (`()` → `settings.arv2_discovery_criteria_gate_keys`, and empty means the pinned ICP document chooses its own criteria), `project_run_id`, and the ICP artifact ref itself. Verbatim on the request dataclass (`:134-137`): "Every `None`/empty field falls back to the deployment's settings, and the *resolved* value is what the run row records — so a run is readable years later without knowing what the flags said on the day it was launched."

- **Preconditions and refusal codes**:
  - `arv2_discovery_not_composed` — the lane is not composed on this deployment (`self._service is None`). Message verbatim: "the ARV2 discovery lane is not composed on this deployment (CLUE_ARV2_DISCOVERY_ENABLED)" (`_not_composed`, `:721-730`). Guidance (`build_arv2_discovery_tools`, `:827-834`): registered uncomposed on purpose so the agent "gets the named `arv2_discovery_not_composed` refusal rather than an `UnknownTool` it cannot explain".
  - `launch_action_ref_missing` — `ctx.action_ref is None`. Message verbatim: "launching discovery requires the captured user action that approved searching for accounts against this project's pinned ICP" (`_trusted_action`, `:733-744`). Guidance (skill §7b): call only "When the human asks you to find accounts, and this project has a confirmed ICP and a confirmed product set".
  - Service refusals, each re-raised as `PreconditionFailed([PreconditionFailure(refused.code, str(refused))])` (`:817-818`):
    - `lane_disabled` — message "CLUE_ARV2_DISCOVERY_ENABLED is false on this deployment" (`:468-471`). (Default is off: `arv2_discovery_enabled: bool = False`.)
    - `target_count_invalid` — message "a discovery run must ask for at least one company, not {target_count}" (`:474-478`). Not reachable from the tool (`ge=1`).
    - `project_not_found` — message "project {project_id!r} has no row in workspace {workspace_id!r}, so there is no project run to discover under" (`:483-489`). Rationale verbatim: the project is checked first so a bad project id is not reported as "you have pinned no ICP", "which is true of a non-existent project and useless".
    - `project_icp_not_pinned` — message "project {project_id!r} has not pinned a confirmed icp-definition; confirm one at the ICP gate before discovering anything" (`read_pinned_icp`, `:236-242`). Guidance verbatim: "Founder rulings 2026-09-10: a project works against the one confirmed ICP version a human pinned for it. Resolving 'the brand's newest confirmed' instead would let a re-synthesis, or another project's confirmation, silently repoint what this project spends money discovering."
    - `icp_artifact_not_found` — message "the pinned document {document_id} is not held by workspace {workspace_id!r}" (`:253-257`).
    - `icp_artifact_not_confirmed` — message "document {path!r} is a {kind!r} at status {status!r}; a discovery run searches only against a confirmed icp-definition" (`:259-264`).
    - `icp_digest_mismatch` — two spellings: the pinned row's digest moved — "the pinned ICP document's bytes are not the ones the project pinned: stored {…}, pinned {…}" (`:265-270`); and the artifact's own content digest does not match — "document {label!r} does not hold the bytes it was pinned to: stored {…}, pinned {…}" (`_icp_document`, `:337-342`). The driver raises the second on resume; verbatim guidance at `read_icp_document` (`:290-302`): "A digest that has moved refuses by name (`icp_digest_mismatch`) so the driver contains it as `needs_review` and a human relaunches."
    - `icp_front_matter_invalid` — unreadable YAML ("document {label!r} carries no readable YAML front matter: {error}", `:343-349`), missing `icp_key` ("document {label!r} names no icp_key; a run is pinned to the ICP's own key", `:355-359`), non-integer `version` ("document {label!r} has version {version!r}, which is not an integer; a run is pinned to the ICP version the human confirmed", `:360-365`).
    - `unknown_criteria_gate_key` — `compile_brief` raised `BriefError`; the message is the `BriefError`'s own text (`:495-506`). Rationale verbatim: the brief is compiled here "It proves the document CAN be compiled before a row exists, rather than by a worker that has already paid for a long list."
    - Not reachable from this tool: `run_not_found` and `run_not_finished` belong to `request_relaxed_pass` (`:594-616`), which has **no toolbelt surface** — the relaxed pass is asked for elsewhere (skill §7b tells the agent to say "a relaxed pass can be run for that discovery" and not to launch a second discovery).

- **Output** (`LaunchArv2DiscoveryOutput`, `:716-718`; validated by the runner against `ToolResult.references` in JSON mode, `runner.py:48-64, 84-106`):
  - `run_id: str` — `uuid5(_DISCOVERY_RUN_NS, request_sha)` under the lane's own namespace "so an R4 run id can never collide with an R2 run id derived from the same bytes" (`:111-112`); `request_sha` is `_request_sha256` (`:426-451`) over `{workspace_id, project_id, icp_artifact_sha256, target_count, strict_count, relaxed_enabled, criteria_gate_keys}` — with the gate keys keeping their **order**, "because the order is the order the criteria are sent in".
  - `replayed: bool` — `not inserted`; `True` means the run row already existed (`create_discovery_run` does `ON CONFLICT (run_id) DO NOTHING`).
  - Not surfaced to the model but carried on the internal `Arv2DiscoveryReceipt` (`:174-193`): `project_run_id`, `workspace_id`, and `to_enqueue` — the latter computed from a read-back of the row (`:576-590`) and true only when `run.status == "not_started"`, with the verbatim note "It is `True` only while the run is `not_started`: a run another worker is already driving has its task, and a finished one is not re-offered until a human asks for the relaxed pass."
  - Caps and constants (verbatim): input cap `target_count: int = Field(default=20, ge=1, le=500)`. Settings that bound the run: `arv2_discovery_strict_count: int = Field(default=35, ge=1)` ("The strict pass's Websets ask (ruling 4: 35 for a target of 20 while precision is measured)"), `arv2_discovery_relaxed_auto: bool = True`, `arv2_discovery_criteria_gate_keys: str = ""` (operator override only; "A comma-separated list of the document's hard-gate keys (≤ 3) forces those instead"), `arv2_discovery_answer_model: str = "exa"`, `arv2_discovery_poll_interval_s: float = Field(default=15.0, gt=0)`, `arv2_discovery_wall_s: int = Field(default=1800, ge=60)`, `arv2_discovery_websets_usd_per_credit: Decimal = Field(default=Decimal("0.00449"), ge=0)` ("Websets bill 10 credits per all-green result; this is the plan's dollar rate per credit"), `arv2_discovery_verify_concurrency: int = Field(default=4, ge=1)` (`libs/clue-config/clue_config/settings.py:366-393`). Fleet constants: `ARV2_DISCOVERY_DEDUP_PREFIX = "arv2-discovery:"`, `ARV2_DISCOVERY_TASK_PRIORITY = -90` (`platform/api/clue_api/arv2/fleet_task.py:45,51`; verbatim: "a discovery run at -90 outranks ordinary work but **yields to account research** at -100").

- **Side effects / what becomes true afterwards**:
  - In one transaction (`DbArv2DiscoveryService.launch`, `:689-702`): `ensure_project_run(...)` writes/joins the **same deterministic project run the account launch joins**, at `ProjectPhase.DEEP`, "so a project's discovery and the research it feeds hang off one row rather than two that nothing relates"; `create_discovery_run` inserts one `arv2_discovery_run` row (`discovery_store.py:205`) carrying workspace, project, brand, project run, the pinned `icp_artifact_key`/`icp_artifact_sha256`/`icp_key`/`icp_version`, the resolved requester, `request_sha256`, `target_count`, the resolved `strict_count`, `relaxed_enabled`, and the resolved `criteria_gate_keys`; `record_run_lineage(kind="discovery")`.
  - After the commit (`enqueue_discovery_run`, `:627-657`): at most one `fleet_task` — `FleetTaskKind.ARV2_DISCOVERY`, work id = run id, dedup key `arv2-discovery:<run_id>`, priority `-90`, payload `{run_id, workspace_id}`, **`reopen_terminal=True`** (because the relaxed pass re-offers the task of a run whose first pass already finished). A receipt with `to_enqueue` false offers nothing and returns `False`.
  - **Real money is spent against external providers by the worker**: the driver buys one Exa **Webset** (billed in credits), then one Exa **Answer** call per hard gate per candidate, plus a website-identification answer per candidate; every provider call is drained onto `provider_call_ledger` under the run's stamp in a cancellation-shielded `finally` ("a call that happened is money truth even when the task is being killed"). `handle` never raises — a failure lands the run `needs_review` and keeps the candidates already paid for (`discovery_driver.py:1-45`).
  - In the UI: verified companies land as `arv2_discovery_candidate` rows and new `candidate` accounts carrying an `account.scoring.fit` claim (fit = `passes / gates`, an unclear counted as half) and appear on the accounts table, where a human approves them by adding them to the project. Companies already held by the workspace are recorded `duplicate_of_existing`, ones an earlier run of this project showed and the human did not tick are `not_chosen_before` (ruling 1′: unapproved is not rejected) — both cost the one website answer and never a gate.
  - The launch itself creates no accounts, approves nothing, and starts no research.

- **Where the skill teaches it**: `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md` — front matter tool grant at lines 46-48; **§7b "Discover accounts for this project"** (lines 208-217) is the procedure: when to call, the two arguments, "What happens next is not yours to do", "A successful result means the discovery is running… It is never a finished list, and you never name accounts you have not been shown", the relaxed-pass rule ("Do not start a second discovery for the same target; the platform re-runs the existing one"), and "Before proposing another discovery run, call `read_discovery_run` for this project". §7c (lines 218-225) adds "What discovery found: `read_discovery_run`" and "A read costs nothing and is never a launch." §10 (lines 243-245) bounds it.

- **Source**: `platform/api/clue_api/arv2/discovery_launch.py:1-124, 130-193, 195-374, 377-451, 454-591, 594-657, 665-702, 710-744, 747-835`; `platform/api/clue_api/arv2/discovery_store.py:180-215, 290-340`; `platform/api/clue_api/arv2/discovery_driver.py:1-45`; `platform/api/clue_api/arv2/fleet_task.py:41-58`; `libs/clue-config/clue_config/settings.py:366-393`; `platform/api/clue_api/toolbelt_wiring.py:70-72, 2659, 2810-2815`; `platform/api/clue_api/projections_main.py:130-165`; `platform/api/clue_api/fleet_main.py:778-800, 920-995`; `platform/fleet/clue_fleet/enums.py:45-72`; `platform/fleet/clue_fleet/queue.py:766-790`; `platform/toolbelt/clue_toolbelt/envelope.py:69-230, 280-412`; `platform/toolbelt/clue_toolbelt/runner.py:48-106`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:46-48,208-217,218-225,243-245`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:93-101`.

- **Cost**: `estimate()` returns verbatim
  ```python
  ToolEstimate(
      cost_cents=Decimal(0),
      detail={
          "basis": "arv2_discovery_websets_plus_answer_ceilings",
          "target_count": inputs.target_count,
      },
  )
  ```
  with the verbatim rationale "A discovery run's spend is governed by the lane's own ceilings and settles in `provider_call_ledger` per call; the webset's credit price and the number of Answer calls are not knowable from this call, so the estimate carries the *shape* of the spend (how many companies were asked for) rather than a number nobody derived." The call itself buys nothing; the run it starts **does** spend real money at Exa (Websets credits at `arv2_discovery_websets_usd_per_credit`, plus Answer calls), which is why it is classified `SPEND`.

- **Discrepancy**: (a) `model_description` says "The ICP, the gates and the provider ask all come from the pinned document and the deployment's settings — **never from this call**", but `target_count` and `relaxed_enabled` *are* taken from this call and are both part of the run's identity digest (`_request_sha256`, `:441-449`); only `strict_count` (the literal provider ask) and the criteria gate keys are settings/document-resolved on this path. (b) `Arv2DiscoveryRequest`'s docstring says "Every `None`/empty field falls back to the deployment's settings", yet the tool always passes a concrete `relaxed_enabled` (its input default is `True`, not `None`), so `settings.arv2_discovery_relaxed_auto` can never take effect through this tool — only through CLI/direct callers. (c) The tool is `effect_class = SPEND` while `estimate()` reports `cost_cents=Decimal(0)`; the zero is a deliberate "no honest prior", not a free run. (d) `Arv2DiscoveryRefused`'s docstring lists `run_not_found`/`run_not_finished` as codes of this module, but no toolbelt surface can reach them — `request_relaxed_pass` has no tool, so the agent can never produce (or be shown) those two refusals even though skill §7b talks about the relaxed pass.


---

# Part 3 — The human gates


---

## `open_product_set_selection_gate@1`

- **Address**: `open_product_set_selection_gate@1` — effect class `write` (`ToolEffectClass.WRITE`), replay policy `domain_idempotent` (`durable_identity="one product-set presentation for one presenting turn and one brand catalog"`, `operation_id_required=False` — the dataclass default, `external_boundary=ExternalReplayBoundary.NONE`), pin_requirements `("project",)`, opens a human gate: **yes**. Journal policy: `JournalParameterPolicy(safe_display_fields=("icp_key",))`. `estimate()` is `ToolEstimate.free()`. Registered (and made the default for its name) in `toolbelt_wiring.py:2938-2942` via `build_product_set_selection_gate_tools(conn_factory=conn_factory, storage=storage)` — the wiring comment: *"the set-valued sibling of the S5-F product gate. It reads the brand's own product rows and knowledge documents (never a Client-KB version), so it needs the storage the knowledge documents live in; without one it still presents every candidate, just without the catalog's descriptions."*

  **The gate row it creates** — one `agent_gate` row via `insert_gate`, with:
  - `gate_id` = `product_set_selection_gate_id(workspace_id, turn_id, subject_ref, expected_subject_sha256)` — `uuid5` under namespace `uuid5(NAMESPACE_URL, "clue:arv2:onboarding:product-set-selection-gate")` over the length-framed 4-tuple.
  - `kind = KIND_PRODUCT_SET_SELECTION = "product_set_selection"`; `project_id`/`thread_id`/`turn_id` from the presenting turn; `addressee_user_id = turn.submitted_by_user_id`.
  - `subject_ref = f"brand-product-catalog:{brand_id}:{catalog.document_id if catalog is not None else 'none'}"`; `subject_revision = 1 if catalog is None else catalog.version` — comment: *"D10: the subject is this brand's catalog as it currently stands. A brand with no catalog document yet is still a legitimate subject — its products exist — so the reference names the absence explicitly and the revision floors at 1 (the frontend refuses a revision < 1)."*
  - `expected_subject_sha256` = sha256 over the canonical JSON (`sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False`) of the snapshot.
  - `max_spend_cents=None`, `currency=None` — *"A product question spends nothing, so it carries no amount at all — and the route refuses an answer that echoes one back."* (`insert_gate` enforces both-or-neither.)
  - `permitted_decisions` = the `insert_gate` default `DECISIONS = ("approved", "rejected", "revised")`; no `subject_bindings` are written for this kind.
  - `subject_snapshot`: `brand_id`, `catalog_document_id` (or `None`), `catalog_version` (`1` when no catalog), `products` (one member per candidate: `product_id`, `name`, `short_description` — `""` when the catalog does not describe it, *"A product row the catalog does not describe is honestly blank, never invented."* —, `aliases`, `status`, `resolution_state`, `reconcile_confidence`, `reconcile_reason`, plus the four `_CATALOG_MEMBERS = ("offering_kind", "family", "lifecycle", "official_url")`), `omitted_count` (catalog entries onboarding resolved to no product row — *"they exist in the document the human may be reading, and they are deliberately not selectable here"*), `current_selection` (`None`, or `{selection_version, product_ids}`), `suggested_product_ids`.

  **The chat card**: the agent puts `{object_type: "agent_gate", object_id: <gate_id>}` in `open_gate_refs`; `chat/turn_stream.py` renders the gate with the domain ref `{workspace_id, object_type: "brand_product_catalog", object_id: <snapshot["brand_id"]>, sha256: <expected_subject_sha256>, version: <subject_revision>}` — comment: *"The subject is the brand's catalog as a whole — the candidates are its products — so the ref names the brand, and the exact catalog document lives in the snapshot beside it."* The card's choices are the snapshot's `products` (with `suggested_product_ids` pre-checked and `current_selection` shown as the current answer); the decisions offered are **approved / rejected / revised**, and an approval carries a *set* (`selected_product_ids`).

  **When the human answers** (`chat/router.py`, `POST …/turns` with `gate_response`): the generic checks run first (404 `GATE_NOT_FOUND`, 422 `GATE_KIND_UNSUPPORTED`, 410 `GATE_SNAPSHOT_ERASED`, 422 `GATE_DECISION_UNSUPPORTED`, 403 `GATE_FORBIDDEN` unless the answerer *is* `addressee_user_id`, 409 `GATE_ALREADY_ANSWERED`, 409 `GATE_SUBJECT_STALE` on digest mismatch, 409 `DESIGN_LEG_OPEN` while a design leg is open). Then the kind-specific ones: `422 GATE_AMOUNT_UNEXPECTED` ("this gate carries no spend amount") if a cost is echoed; `422 GATE_PRODUCT_UNEXPECTED` for a single `selected_product_id` ("this question takes a set of products, not one") or for a choice on a non-approved decision; `422 GATE_REVISION_REQUEST_UNEXPECTED` ("a product-set question does not accept revision text" — *"The durable answer for this kind carries its choices and nothing else (the answer trigger enforces it), so there is nowhere to record revision text"*); `422 GATE_PRODUCT_REQUIRED` ("select at least one product from the presented catalog") on an empty approval; `422 GATE_PRODUCT_DUPLICATE` ("a product can only be chosen once"); `409 GATE_PRODUCT_STALE` ("a chosen product was not selectable in the presented catalog") when a choice is outside the snapshot's **non-archived** products (*"An archived candidate is *presented*… but cannot be chosen, so the allowed set is narrower than the snapshot."*).
  - **approved**: one `agent_gate_answer` row with `decision_payload = {"selected_option_refs": [...]}` and `selected_option_ref = None`, **and** — tool-free, in the same transaction — `confirm_project_product_set(conn, workspace_id, project_id, product_ids, gate_id, confirmed_by_user_id)`: *"Human-only and tool-free: confirming a set is one spine write with server-derived authority… Either both effects commit or neither does."* That writes one `project_product` row per chosen product at `selection_version = MAX(selection_version)+1` (repeats collapse, first occurrence wins; empty list raises `ValueError("a project product set needs at least one product")`). A product that is not a product of the project's own brand/workspace makes the call return `None`, which the route turns into `409 GATE_SUBJECT_STALE` ("a chosen product no longer belongs to this project's brand").
  - **rejected / revised**: only the `agent_gate_answer` row is written; no product set is confirmed. Per the skill, *"A later change of the set is a new gate and a new version, never an edit."*

- **Purpose**: Ask the current human which of this brand's products the project is about, when the answer may legitimately name more than one. The model may decide the conversation is ready to ask; it may not author what is asked. Its `model_description`: *"Ask the current human which of this brand's products this project is about. The platform derives the candidates from the brand's own product rows and the current product catalog; you may pass the icp_key you are working from to pre-check its products. This call confirms nothing. End the turn awaiting input with the returned gate_ref."* The module docstring adds that the presenting turn supplies project/thread/addressee, the project's brand supplies the candidates, the `product-catalog` knowledge document and its `onboarding_product_lineage` rows annotate them (*"a ``model_unsure`` match is shown as such rather than hidden"*), the confirmed set is shown as the current answer, and *"An ICP document supplies a *suggestion* and nothing more."* It is deliberately **not** a version of the S5-F single-product gate: *"Nothing in this module reads a Client-KB version, a readiness decision or a Stage-0 pin."*

- **Inputs**: input model `OpenProductSetSelectionGateInput` (`ToolInput` ⇒ `frozen`, `extra="forbid"`). Two fields only.

  - `icp_key: str | None = None` — `Field(default=None, min_length=1, max_length=200)`. Comment above the field: *"The ICP the conversation is working from, if there is one. It only decides which candidates are *pre-checked*; it never decides what may be chosen, and it confirms nothing."*
  - `source_turn_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]` — `Field(json_schema_extra={TRUSTED_TURN_FIELD: True})`; **stripped from the model-visible schema** and injected at the execution seam from the trusted turn binding.

  There is no project id, no product id list, no addressee, and no candidate list on the input ("not found in code"; looked at `OpenProductSetSelectionGateInput`, `_resolve`, and `invoke` in `product_set_selection_gate_tools.py`). The skill states the same rule: *"You supply nothing else: no product ids, no project, no addressee."*

- **Preconditions and refusal codes**: `preconditions()` calls the same `_resolve()` as `invoke()` and renders each `_SelectionRefused` as one `PreconditionFailure`.

  - `product_set_turn_not_found` — message: `"the current turn reference is unavailable"`. Raised both when `parse_turn_action_ref` rejects the ref and when no turn row exists in this workspace. Agent: no guidance in code (the ref is engine-injected).
  - `product_set_addressee_missing` — message: `"the current turn has no human addressee"`. Raised when `turn.submitted_by_user_id` is empty.
  - `product_set_project_unavailable` — message: `"the current turn's project is unavailable"`. Project absent or in another workspace.
  - `product_set_no_candidates` — message: `"this brand has no products to choose between"`. Raised when the brand has no `product` rows in this workspace.
  - `icp_key_unknown` — message: `f"no current ICP document carries the key {icp_key!r}"`. Docstring: *"A named ``icp_key`` that no servable ICP document carries is a refusal, not an empty list: the agent asked for a specific pre-check and must not be told silently that it got one."* Agent: pass a key that a current `icp-definition` document actually carries, or omit `icp_key`.

  Non-refusals worth knowing (they degrade silently by design, never refuse): with `storage=None`, or bytes that fail `read_verified_artifact`/digest/front-matter parsing, `_front_matter` returns `{}` — *"an annotation the platform cannot read is left blank rather than guessed"* — so the gate still presents every candidate, without catalog descriptions and (when no ICP document can be read) with no suggestions. A brand with no `product-catalog` document is also fine: `catalog_document_id=None`, `catalog_version=1`, and `subject_ref` names the absence. A project-scoped `product/catalog.md` is deliberately ignored (`_current_catalog` filters `ref.project_id is None`): *"what this brand sells is the brand's fact, and the gate confirms a selection *from* it."*

- **Output**: output model `OpenProductSetSelectionGateOutput` (`ToolOutput` ⇒ `frozen`, `extra="forbid"`, `strict=True`).

  - `gate_id: str` — the derived gate uuid (`str(row.gate_id)`).
  - `gate_ref: str` — `gate_ref(row.gate_id)` = `f"agent-gate:{gate_id}"` (`GATE_REF_PREFIX = "agent-gate:"`, imported from `agent_gate_tools`). This is what goes in `open_gate_refs`.
  - `gate_kind: Literal["product_set_selection"]` — a `Literal`, not a free string.
  - `candidate_count: int` — `len(candidates)` = the brand's workspace-scoped `product` rows presented.
  - `suggested_count: int` — `len(suggested)` = how many candidates the ICP pre-checks.
  - `addressee_user_id: str` — the human derived from the turn.
  - `created: bool` — `False` on a replayed presentation of the same derived gate id.

  Bounds/constants: `icp_key` `max_length=200`; `source_turn_ref` `max_length=1_000`; `_CATALOG_KIND = "product-catalog"`; `_ICP_KIND = "icp-definition"`; `_CATALOG_MEMBERS = ("offering_kind", "family", "lifecycle", "official_url")`; `KIND_PRODUCT_SET_SELECTION = "product_set_selection"`; `DECISIONS = ("approved", "rejected", "revised")`. The candidate list itself is **uncapped** in this module ("not found in code"; looked at `_resolve` and the snapshot construction — no slice or max on `candidates`, unlike the directive gate's `_MAX_SNAPSHOT_FIELDS`/`_MAX_SNAPSHOT_QUESTIONS`).

- **Side effects / what becomes true afterwards**:
  - One immutable `agent_gate` row of kind `product_set_selection` (or a replay of the existing one, `created=False`). No `agent_gate_subject` rows, no amount, no currency.
  - Reads only (no writes) against: `agent_turn`/turn identity, `project`, `product` (`list_products`), the brand and project knowledge-document readers (`current_knowledge_documents`, `current_project_knowledge_refs`), `onboarding_product_lineage`, `project_product` (`current_project_product_set`), and artifact storage for front matter.
  - Nothing is confirmed and nothing is spent. The module docstring: *"The tool writes only the immutable question. The chat route records the human's structured answer and confirms the set outside the model surface."*
  - **The turn pauses**: the agent ends the turn `awaiting_input` with the returned `gate_ref` in `open_gate_refs` (skill §4: *"exactly `{object_type: "agent_gate", object_id: <returned gate_id>}` in `open_gate_refs`"*).
  - On approval, rows written by the route: `agent_gate_answer` (with `decision_payload.selected_option_refs`) and one `project_product` row per chosen product at a new `selection_version`.

- **Where the skill teaches it**: `stage0-interview` v26 **§4 "The product-set gate"** (the whole section), with the hand-off into §5 ("When the product set is confirmed…"). It is also the only one of these four tools listed in the skill's frontmatter `tools:` block (`name: open_product_set_selection_gate`, `version: "1"`, `input_schema_sha256: 0c8e2b60…`, `output_schema_sha256: 3586c058…` — identical digests to the profile grant). Related instructions live in §3 (which route reaches the gate), §5 (gate-receipt-only authority: *"A gate receipt is the only authority… Ordinary prose such as 'looks good' confirms nothing."*), §7/§7b (a confirmed product set is a precondition of research and discovery) and §10 (*"You cannot confirm an ICP or a product set"*). Granted by profile `head-of-abm/v49` at version `"1"` (`profile.yaml:133-136`).

- **Source**: `platform/api/clue_api/product_set_selection_gate_tools.py:1-543` (module docstring 1-30; constants 85-89; input/output models 92-112; tool class 149-240; `_resolve` 242-350; `_front_matter` 352-380; `_suggested_product_ids` 382-435; helpers 438-530; builder 540-543); `platform/api/clue_api/agent_gate.py:67-97, 146-185, 253-268, 291-386, 408-470`; `platform/api/clue_api/chat/router.py:1840-2160, 2400-2580`; `platform/api/clue_api/chat/turn_stream.py:1120-1161`; `libs/clue-spine/clue_spine/spine.py:478-556`; `platform/api/clue_api/toolbelt_wiring.py:2934-2942`; `platform/toolbelt/clue_toolbelt/envelope.py:1-412`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:128-136`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:1-30, 125-135`.

- **Discrepancy**:
  - The gate is opened with the full default decision vocabulary `("approved", "rejected", "revised")`, but `revised` is unusable in practice for this kind: the route refuses any `revision_request` on a product-set gate (`GATE_REVISION_REQUEST_UNEXPECTED`) and refuses a product choice on a non-approved decision, so a `revised` answer can carry no content at all. Neither the tool nor the skill says so; the skill's §5 "Revised" guidance is written for the ICP gate only.
  - `_resolve()` is executed **twice** on a successful call — once in `preconditions()` and again at the top of `invoke()` (unlike the directive and design-leg tools, `invoke` does not reuse the precondition's resolution), and it opens its own connection each time (`async with self._conn_factory()` inside `_resolve`, separate from the `insert_gate` transaction in `invoke`). The gate row is therefore inserted in a different transaction from the reads that produced its digest, so a catalog change landing between them makes the stored snapshot the winner (`insert_gate` replay semantics) rather than a refusal.
  - The tool's `pin_requirements = ("project",)` while nothing in the input names a project — the project is derived from the trusted turn.


---

## `open_icp_confirmation_gate@2`

*(Version note: `@1` — `clue_api/stage0_icp_gate_tools.py` — is the frozen, **ungranted** predecessor. It presents one durable draft **`icp_spec` row** (input `icp_key` + `icp_version: int = Field(gt=0)`, output `subject_ref: DraftIcpSpecRef`), resolved through a governed execution's Stage-0 project scope, with `pin_requirements = ("project", "product", "client_kb", "icp")`. `@2` presents an **artifact the human can actually read** — the brand's current `icp-definition` knowledge document, pinned by the digest of its exact bytes — needs no `icp_version`, reads no Client-KB version / readiness decision / Stage-0 pin, and carries `pin_requirements = ("project",)`. Per the profile: "@1's subject was a draft `icp_spec` row, which this lane no longer writes; @1 stays registered and frozen for replay, ungranted here." `@2` is also the **default** registration for the unversioned address.)*

- **Address**: `open_icp_confirmation_gate@2` — effect class `write` (`ToolEffectClass.WRITE`), replay policy `domain_idempotent` (`ReplayPolicy.DOMAIN_IDEMPOTENT`; `durable_identity="one presenting turn plus one exact ICP knowledge document"`, `operation_id_required` not set — defaults `False`, `external_boundary=ExternalReplayBoundary.NONE`), `pin_requirements = ("project",)`, opens a human gate: **yes**.
  **What gate row is created**: one row in **`agent_gate`** (via `insert_gate`, `ON CONFLICT (gate_id) DO NOTHING`) with `kind = "icp_confirmation"` (`KIND_ICP_CONFIRMATION`), `gate_id` derived by `icp_artifact_gate_id(workspace_id, project_id, subject_ref, expected_subject_sha256)` — "Keyed on the **project**, not the presenting turn, and on the document ref plus its digest — the same four coordinates the ``agent_gate_one_icp_subject`` unique index enforces. One project asking about one exact ICP document is one question, however many turns reach for it." The row carries `workspace_id`, `project_id`, `thread_id`, `turn_id`, `subject_ref = f"brand-knowledge-document:{document_id}:v{version}"`, `subject_revision = subject.version`, `expected_subject_sha256 = subject.artifact_sha256`, `subject_snapshot` (see Output), `permitted_decisions = ("approved", "rejected", "revised")`, `max_spend_cents = None`, `currency = None` ("An ICP question spends nothing, so it carries no amount at all — and the route refuses an answer that echoes one back"), `addressee_user_id`. The row is **immutable**: "A repeat presentation of the same derived id is a replay and returns the stored row … the stored values are authoritative and the caller's recomputed ones are simply discarded."
  **What card appears**: the gate renders as a decision card in the chat with a typed subject ref `{"workspace_id", "object_type": "brand_knowledge_document", "object_id": <document_id>, "sha256": <expected_subject_sha256>, "version": <subject_revision>}` — "the subject is a file the human can open, so the ref names the document rather than the ICP key — the key is one of the document's own facts" (`chat/turn_stream.py:1135-1141`). The agent attaches it by ending the turn `awaiting_input` with `{object_type: "agent_gate", object_id: <returned gate_id>}` in `open_gate_refs`.
  **What approving it does** (`chat/router.py:2584-2641`, all in the same transaction as the immutable answer — "Either both effects commit or neither does"): the route reads the gate's `subject_snapshot`, re-resolves `current_icp_document` and the project's `current_project_product_set`, then (1) `confirm_icp_document(...)` mints the **`confirmed`** version of that same document path, stamped with `confirmed_by`, `confirmed_at`, `confirmed_for_project_id` and `product_selection_version`; and (2) `pin_project_icp(...)` **pins that confirmed document to this project** — "the approval is also the moment this project pins its ICP. Same transaction as the confirmed version and the immutable answer — a project can never end up having confirmed a document it does not pin, or pinning one nobody approved. A replayed approval finds its own document already pinned and writes nothing." If the reviewed document is no longer readable, the route refuses `409 GATE_SUBJECT_STALE`. Journal parameter policy: `JournalParameterPolicy(safe_display_fields=("icp_key",))`. Estimate: `ToolEstimate.free()`.

- **Purpose**: This is how the Head of ABM asks the human to confirm an ICP. The model may decide the conversation is ready to ask, and it may name which ICP — it may not author what is asked. The tool derives everything the gate carries from durable rows (the presenting turn supplies the project, thread and addressee; the project supplies the brand; the brand's knowledge documents supply the subject, re-read through its verified bytes) and persists exactly one immutable question. "The tool writes only the immutable question; the chat route records the human's answer and mints the confirmed version." The call itself confirms nothing.

- **Inputs** (`OpenIcpArtifactGateInput`, `icp_artifact_gate_tools.py:86-94`; class docstring: "The ICP to present, and nothing else: scope, subject bytes, digest and addressee are derived from the presenting turn."):
  - `icp_key: str` (required) — `Field(min_length=1, max_length=200)`. Note: **no `pattern`** here, and the bound is 200, not the `ICP_KEY_MAX_LENGTH = 60` the authoring tool uses. `model_description`: "Supply the icp_key of the document you have read; the platform derives and persists the exact document, digest, permitted decisions, project and addressee."
  - `source_turn_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})` — **engine-injected, stripped from the model-visible schema** (`turn_binding.py:1-15`); must be exactly `turn-action:<canonical uuid>`.

  Nested models the platform builds, field by field:
  - `IcpDocumentSubject` (`arv2/icp_confirmation.py:103-121`; "One ICP knowledge document, named precisely enough to re-read exactly these bytes") — `document_id: UUID`, `brand_id: str`, `path: str`, `icp_key: str`, `version: int`, `status: str`, `artifact_key: str`, `artifact_sha256: str`, `product_ids: tuple[str, ...]`, `title: str`, `confirmed_for_project_id: str | None`, `project_id: str | None` ("``None`` for the brand's own document; set for a project-local variant, which only that project may read and confirm"), `derived_from_document_id: UUID | None`. Resolved by `current_icp_document(conn, storage, workspace_id, brand_id, icp_key, project_id=turn.project_id)` — the project scope is supplied "exactly as it supplies the brand: a project that authored its own variant of this key is asked about that variant, not about the brand's document."
  - `icp_gate_subject_ref(subject) -> str` — `f"brand-knowledge-document:{subject.document_id}:v{subject.version}"` ("The versioned display reference; the bare ids live in the snapshot beside it").
  - `icp_gate_snapshot(subject) -> dict` ("The immutable record of what was presented — the document, not a rendering of it") — `subject_kind: "brand_knowledge_document"`, `document_id: str`, `brand_id: str`, `path: str`, `icp_key: str`, `version: int`, `status: str`, `artifact_key: str`, `artifact_sha256: str`, `product_ids: list[str]`, `title: str`.
  - `ICP_GATE_DECISIONS: tuple[IcpGateDecision, ...] = ("approved", "rejected", "revised")` where `type IcpGateDecision = Literal["approved", "rejected", "revised"]` (`stage0_project_contracts.py:83, 93`). The model does not choose these; the platform sets them.
  - `_Resolved` (internal) — `gate_id: UUID`, `turn_id: UUID`, `thread_id: str`, `project_id: str`, `addressee: str`, `subject: IcpDocumentSubject`.

- **Preconditions and refusal codes** (all raised as `_GateRefused` inside `_resolve`, surfaced from `preconditions` as `PreconditionFailure(reason_code, message)`):
  - `gate_turn_ref_malformed` — `parse_turn_action_ref` rejected the injected ref; message is the `TurnActionUnresolvable` text (`"an action reference must be an opaque turn-action reference"` / `"…must name one turn by its canonical identifier"` / `"…must spell its turn identifier canonically"`). No guidance in code.
  - `gate_turn_not_found` — (a) `"the presenting turn is not part of this workspace"`; (b) `"the presenting turn's project is not part of this workspace"` ("Fail-closed and indistinguishable from an unresolvable turn: a turn whose project this workspace cannot see is not a turn this workspace may present in."). No guidance in code.
  - `gate_addressee_missing` — `turn.submitted_by_user_id is None`. Message: `"the presenting turn records no human addressee"`. No guidance in code.
  - `icp_document_not_found` — `current_icp_document` returned `None`. Message: `f"this brand has no readable current ICP document for {icp_key!r}"`. Note this is **also** the code returned when `self._storage is None` (the subject is short-circuited to `None` before the lookup runs). Guidance: skill §5b — author the document first with `author_icp_document`, then "In the same turn, open the ICP confirmation gate on that key (section 5)".
  - `icp_document_not_servable` — the document's status is outside `_ANSWERABLE_STATUSES = ("proposed", "confirmed")`. Message: `f"the ICP document for {icp_key!r} is {subject.status}, not a proposal"`. Rationale in code: "``ready`` is servable *input* — a persona file, a catalog — not a proposal, so there is nothing to say yes to; ``confirmed`` is presentable because a brand's ICPs are shared and another project's confirmation is not this project's answer."
  - `icp_already_confirmed_for_project` — `subject.status == "confirmed"` **and** `subject.confirmed_for_project_id == turn.project_id`. Message: `"this project has already confirmed this exact ICP document"`. No further guidance in code.
  - `icp_gate_already_presented_elsewhere` — a gate at this derived id exists but in a different thread. Message: `"this exact ICP document is already governed by a gate in another thread"`. No guidance in code.
  - `icp_gate_already_answered` — a gate at this derived id exists and is not open. Message: `"this exact ICP document already has an immutable human decision"`. No guidance in code.

  There is **no `not_composed` refusal** on this tool: `build_icp_artifact_gate_tools` takes `storage: StorageBackend | None = None` and is always registered; a deployment with no storage reaches `icp_document_not_found` instead. Unlike its three ARV2 neighbours, this tool has no injected service and its `preconditions` never returns a composition failure.

  Downstream refusals the *human's answer* can hit at the chat route (not this tool's, but the same gate): `404 GATE_NOT_FOUND`, `422 GATE_KIND_UNSUPPORTED`, `410 GATE_SNAPSHOT_ERASED`, `422 GATE_DECISION_UNSUPPORTED`, `403 GATE_FORBIDDEN` ("this gate was addressed to somebody else" — addressee, not membership), `409 GATE_ALREADY_ANSWERED`, `409 GATE_SUBJECT_STALE` ("the reviewed subject revision differs from the current gate"), `422 GATE_AMOUNT_UNEXPECTED` ("this gate carries no spend amount"), `422 GATE_PRODUCT_UNEXPECTED` ("an ICP confirmation does not accept a product choice"), `422 GATE_REVISION_REQUEST_REQUIRED` (a `revised` decision with an empty `revision_request`).

- **Output** (`OpenIcpArtifactGateOutput`, `icp_artifact_gate_tools.py:97-106`; returned as `ToolResult.references = output.model_dump()`):
  - `gate_id: str` — the derived, immutable `agent_gate.gate_id` (`uuid5` over length-framed `workspace_id`, `project_id`, `subject_ref`, `expected_subject_sha256`). This is the value the agent puts in `open_gate_refs`.
  - `gate_ref: str` — `gate_ref(gate.gate_id)` = `f"{GATE_REF_PREFIX}{gate_id}"`. The `model_description` says: "Then end the turn awaiting input with the returned gate_ref."
  - `gate_kind: Literal["icp_confirmation"]` — the only admissible value.
  - `subject_ref: str` — the **stored** gate's `subject_ref`, i.e. `brand-knowledge-document:<document_id>:v<version>`.
  - `subject_revision: int` — `subject.version` (the freshly resolved document's version).
  - `expected_subject_sha256: str` — the **stored** gate's digest of the exact document bytes. This is the load-bearing staleness check at answer time: "a directive redrafted since, or an amount recomputed since, cannot be approved by a click aimed at the previous one."
  - `permitted_decisions: tuple[IcpGateDecision, ...]` — always `("approved", "rejected", "revised")`.
  - `addressee_user_id: str` — the stored gate's addressee (the human on the presenting turn).
  - `created: bool` — `True` when this call inserted the gate row, `False` when it replayed an existing one. Note: unlike C1/C2/C3, `ToolResult.replayed` is **not** set from this flag — `invoke` returns `ToolResult(tool=..., version=..., references=...)` with `replayed` left at its default `False`.

  Caps/bounds, verbatim with constant names: `icp_key` `Field(min_length=1, max_length=200)`; `source_turn_ref` `max_length=1_000`; `_ANSWERABLE_STATUSES = ("proposed", "confirmed")`; `ICP_GATE_DECISIONS = ("approved", "rejected", "revised")`; `KIND_ICP_CONFIRMATION = "icp_confirmation"`; `max_spend_cents = None` / `currency = None`. `insert_gate` itself enforces: the kind must be in `GATE_KINDS`; `permitted_decisions` must be non-empty and unique and a subset of `DECISIONS`; `(max_spend_cents is None) != (currency is None)` raises `"gate amount and currency must either both be present or both be absent"`.

- **Side effects / what becomes true afterwards**:
  - One immutable row in **`agent_gate`** as described above (and zero rows in `agent_gate_subject` — this tool passes no `subject_bindings`).
  - The **gate card appears in chat** when the agent ends the turn `awaiting_input` with `{object_type: "agent_gate", object_id: <gate_id>}` in `open_gate_refs`; its subject ref renders with `object_type: "brand_knowledge_document"`. This tool emits no `domain_refs` object type of its own.
  - **No document status transitions, no pin movement, no background turn** at call time. All of that happens when the human answers:
    - **Approved** → in one transaction with the immutable answer: a new `confirmed` version of that document path is minted (`confirm_icp_document`), and `pin_project_icp` pins it to this project with the project's `product_selection_version`. Skill §5: "On your next turn the index card names it as this project's confirmed ICP. Read the confirmed file before relying on it."
    - **Rejected** → "leaves the proposal as it was" (no document write). Skill §5: "Offer the other proposals or ask what is wrong with this one."
    - **Revised** → "carries the human's requested changes in the gate receipt"; the route requires a non-empty `revision_request`. Skill §5: "Apply them: draft the revised profile (section 5b) in the same scope as the reviewed one, then open the confirmation gate on the new version. Record the human's words in project context as well (section 6)."
  - Authority rule, from skill §5: "A gate receipt is the only authority for any of these outcomes. Ordinary prose such as 'looks good' confirms nothing."

- **Where the skill teaches it**: `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md` **§5 "The ICP confirmation gate"** (lines 133–143; the call at line 135), including the three decision outcomes and the gate-receipt authority rule, and the finalization pattern by reference to **§4** ("End the turn `awaiting_input` with the gate reference in `open_gate_refs`, as in section 4" — §4 line 131 spells it out: "your explanation in `user_message` and exactly `{object_type: \"agent_gate\", object_id: <returned gate_id>}` in `open_gate_refs`"). Also taught at **§5b** line 153 as the mandatory same-turn follow-on to `author_icp_document`. Pinned in the skill front matter at version `"2"` (lines 22-25) and granted at `head-of-abm/v49/profile.yaml:126-129`.

- **Source**: `platform/api/clue_api/icp_artifact_gate_tools.py:1-298` (whole file); `platform/api/clue_api/stage0_icp_gate_tools.py:1-140` (the `@1` comparison); `platform/api/clue_api/agent_gate.py:45, 75, 83, 270-390` (`icp_artifact_gate_id`, `insert_gate`, `get_gate`); `platform/api/clue_api/agent_gate_tools.py:101-103` (`gate_ref`); `platform/api/clue_api/arv2/icp_confirmation.py:103-135, 301-334`; `platform/api/clue_api/stage0_project_contracts.py:83, 93`; `platform/api/clue_api/chat/router.py:1850-1940, 2584-2650`; `platform/api/clue_api/chat/turn_stream.py:1127-1161`; `platform/toolbelt/clue_toolbelt/envelope.py:90-412`; `platform/api/clue_api/turn_binding.py:1-61`; `platform/api/clue_api/turn_action.py:180-209`; `platform/api/clue_api/toolbelt_wiring.py:109, 2926-2932`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:22-25, 125-143, 145-155`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:120-129`.

- **Discrepancy**:
  1. **A deployment with no storage refuses with a message that is false.** `_resolve` short-circuits `subject = None if self._storage is None else await current_icp_document(...)`, and `None` then raises `icp_document_not_found` with `"this brand has no readable current ICP document for '<key>'"`. When storage is absent, that statement is not true — nothing was looked up. Every ARV2 neighbour (C1/C2/C3) refuses with a distinct `*_not_composed` code in exactly this situation; this tool has none.
  2. `icp_key` here is `Field(min_length=1, max_length=200)` with **no pattern**, while `author_icp_document@1` and `request_persona_synthesis@1` both constrain the same concept to `pattern=ICP_KEY_PATTERN, max_length=ICP_KEY_MAX_LENGTH` (60, lowercase kebab-case). The three tools disagree on what an `icp_key` may be; the gate's looser bound is inherited from the `@1` schema.
  3. `created` is returned on the output model, but `ToolResult.replayed` is left `False` even on a replay (`invoke` does not pass `replayed=not created`), unlike C1, C2 and C3, which all propagate their replay flag to the envelope. A caller reading `ToolResult.replayed` cannot tell a replayed gate presentation from a fresh one.
  4. The `model_description` says "Present one of this brand's ICP knowledge documents", but `current_icp_document` is called with `project_id=turn.project_id`, so a project-local variant at that key wins over the brand's document — as the inline comment states. The model-facing wording understates the project-scoped resolution.


---

## `open_directive_confirmation_gate@1`

- **Address**: `open_directive_confirmation_gate@1` — effect class `write` (`ToolEffectClass.WRITE`), replay policy `domain_idempotent` (`durable_identity="the presented gate for one turn + one exact directive revision"`, `operation_id_required=False` — the dataclass default, since a `DOMAIN_IDEMPOTENT` policy does not require one, `external_boundary=ExternalReplayBoundary.NONE`), pin_requirements `("project_run", "research_directive")`, opens a human gate: **yes**. Journal policy: `JournalParameterPolicy(safe_display_fields=("project_run_id", "research_directive_id", "account_entity_ids"))`. `estimate()` is `ToolEstimate.free()` ("Presenting a gate is free. The *amount on it* is what the human is asked about."). Registered as the default for its name by `register_agent_gate_tools` (`agent_gate_wiring.py`), called from `toolbelt_wiring.py:2922-2926` with `budget_controls_enabled=resolved_settings.budget_controls_enabled`; the wiring docstring notes the flag *"changes only the *value* the tool result carries for ``max_spend_cents`` — never the descriptor"*.

  **The gate row it creates** — one `agent_gate` row (via `insert_gate`, `ON CONFLICT (gate_id) DO NOTHING`, immutable by append-only trigger), with:
  - `gate_id` = `directive_confirmation_gate_id(workspace_id, turn_id, subject_ref, expected_subject_sha256)` — a `uuid5` under namespace `uuid5(NAMESPACE_URL, "clue:lane-d:d4:directive-confirmation-gate")` over the length-framed 4-tuple. *"Derived rather than minted so that re-running a turn (a fleet retry, a replayed plan step) presents *the same gate* instead of a second one… The digest is in the key because a re-drafted directive is genuinely a different thing to approve and deserves its own gate."*
  - `kind = KIND_DIRECTIVE_CONFIRMATION = "directive_confirmation"`; `project_id`/`thread_id`/`turn_id` from the presenting turn; `subject_ref = directive.directive_ref`; `subject_revision = directive.version`; `expected_subject_sha256 = directive.canonical_json_sha256`; `max_spend_cents` = the server-computed Σ; `currency = DEFAULT_GATE_CURRENCY = "USD"`; `permitted_decisions` = the default `DECISIONS = ("approved", "rejected", "revised")`; `addressee_user_id = turn.submitted_by_user_id` (derived from the durable submission, never proposed).
  - `subject_snapshot` (bounded card payload): `directive_ref`, `directive_version`, `research_directive_id`, `project_run_id`, `account_entity_ids`, `account_count`, `tier` (`first.effort_policy.tier`), `field_keys` (first `_MAX_SNAPSHOT_FIELDS = 40`), `questions` (question `text` only, first `_MAX_SNAPSHOT_QUESTIONS = 20`).
  - one `agent_gate_subject` row per account: `AgentGateSubjectBinding(subject_entity_id=<account uuid>, binding_kind="research_directive_account")` — *"Body-free DSAR reach for one subject copied into a gate snapshot."*

  **The chat card**: the agent carries `{object_type: "agent_gate", object_id: <gate_id>}` in its finalization's `open_gate_refs`; `chat/turn_stream.py` renders a `GatePart` whose domain ref for this kind is `{workspace_id, object_type: "research_directive", object_id: <snapshot["research_directive_id"]>, sha256: <expected_subject_sha256>, version: <subject_revision>}`. Options presented are the row's `permitted_decisions`: **approved / rejected / revised**.

  **When the human answers** (`POST /projects/{project_id}/threads/{thread_id}/turns` with a `gate_response`, `chat/router.py`): the route checks the gate *before any byte is written* — gate must exist in this thread/project (`404 GATE_NOT_FOUND`), kind must be answerable (`422 GATE_KIND_UNSUPPORTED`), snapshot not erased (`410 GATE_SNAPSHOT_ERASED`), decision ∈ `permitted_decisions` (`422 GATE_DECISION_UNSUPPORTED`), answerer must be the `addressee_user_id` (`403 GATE_FORBIDDEN`), not already answered (`409 GATE_ALREADY_ANSWERED`), `expected_subject_sha256` must match (`409 GATE_SUBJECT_STALE`), and — only when `budget_controls_enabled` — `expected_estimated_cost_cents` must equal the stored `max_spend_cents` (`409 GATE_AMOUNT_STALE`). A directive gate refuses `revision_request` (`422 GATE_REVISION_REQUEST_UNEXPECTED`, message *"an account-research directive does not accept revision text"*) and any product choice (`422 GATE_PRODUCT_UNEXPECTED`). Answering while a design leg is open is refused (`409 DESIGN_LEG_OPEN`). The answer is written once into `agent_gate_answer` (`gate_id` is that table's primary key).
  - **approved**: in the same transaction the route invokes a human-only tool with server-derived authority and `operation_id = operation_id_from_key(workspace_id, f"gate-answer:{gate_id}:{turn_id}")`. With `budget_controls_enabled` **on** → `confirm_account_research_directive` with `{directive_id: snapshot["research_directive_id"], expected_sha256: gate.expected_subject_sha256}` (confirm only). With budget controls **off** (founder ruling 2026-08-19, Slice B) → `launch_selected_account_research@1` with `{project_run_id, research_directive_id, account_entity_ids: <the gate-frozen account set injected as this turn's context refs>, source_turn_ref: <derived turn-action ref>}` — one atomic confirm *and* launch.
  - **rejected / revised**: the answer row is written and nothing else happens — *"Rejection and revision deliberately confirm nothing: they are durable records of a decision, and the agent answers them in its turn."* (`revised` is documented as "I want changes", not a soft reject; but for this kind the route forbids carrying revision text, so the only record is the decision itself.)

- **Purpose**: The agent asks the human for authority to spend on one exact drafted account-research directive and one exact set of accounts. Its `model_description`: *"Present the human with the confirmation gate for one drafted account-research directive and one exact account set: it records what you are asking them to approve and the server-computed maximum spend for that set. It spends nothing, confirms nothing, and launches nothing — end the turn awaiting input with the returned gate_ref, and only the human's own confirming turn can answer it."* Everything of consequence is derived, not accepted: the addressee comes from the durable turn submission, the amount from the same Σ the launcher runs, the subject digest from the directive row.

- **Inputs**: input model `OpenDirectiveConfirmationGateInput` (docstring: *"What the agent proposes; every authority value is added by the engine, not by this model."*; `ToolInput` ⇒ `frozen`, `extra="forbid"`).

  - `project_run_id: str` — `Field(min_length=1, max_length=64)`; must parse as a canonical UUID.
  - `research_directive_id: str` — `Field(min_length=1, max_length=64)`; must parse as a canonical UUID.
  - `account_entity_ids: tuple[str, ...]` — `Field(min_length=1, max_length=500)` (required; at least one, at most 500); each must parse as a UUID and the set must be unique.
  - `source_turn_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]` — `Field(json_schema_extra={TRUSTED_TURN_FIELD: True})`. **Stripped from the model-visible schema** and injected at the execution seam; module docstring: *"The gate is anchored to the turn the agent is currently answering (served through the PC-C8 ``TRUSTED_TURN_FIELD`` seam as ``source_turn_ref``, stripped from the model-visible schema), and its addressee is the human who *submitted* that turn, read from the durable submission row. A model that could name an addressee could address a gate to an account it controls."*

  No other input fields exist — in particular there is no addressee field, no amount field, and no snapshot field ("not found in code"; looked at `OpenDirectiveConfirmationGateInput` in `agent_gate_tools.py:104-115` and the `_resolve`/`invoke` bodies).

- **Preconditions and refusal codes**: `preconditions()` runs the *same* `_resolve()` as `invoke()` (docstring: *"One method rather than two so the tool cannot pass its own preconditions and then fail differently"*) and renders each typed `_GateRefused` as one `PreconditionFailure`.

  - `gate_subject_malformed` — the ids are not canonical identifiers. Message: `"gate subject identifiers must be canonical identifiers"`; or, for a repeated account, `"a gate's account set must be unique"`. Agent: no guidance in code beyond the message.
  - `gate_turn_ref_malformed` — `source_turn_ref` is not `turn-action:<canonical uuid>`. Message is `str(TurnActionUnresolvable)`: `"an action reference must be an opaque turn-action reference"` or `"a turn-action reference must name one turn by its canonical identifier"`. Agent: no guidance in code (the field is engine-injected, so this is an engine fault).
  - `gate_turn_not_found` — message: `"no such turn in this workspace"`.
  - `gate_addressee_missing` — message: `"this turn records no human submitter, so no gate can be addressed to anyone"`.
  - `gate_project_run_not_found` — the run is absent, in another workspace, or in another project than the turn's. Message: `"no such project run in this conversation's project"`.
  - `account_discovery_not_started` — message: `"Account discovery is not complete. Please finish account discovery before starting account profiling."`
  - `account_discovery_in_progress` — message (`ACCOUNT_DISCOVERY_IN_PROGRESS_MESSAGE`): `"Account discovery is still in progress. Please wait and try account profiling again after discovery finishes."`
  - `account_discovery_not_sealed` — message: `"Account discovery did not finish with a final seal. Please retry discovery before starting account profiling."`
  - `account_discovery_seal_invalid` — message: `"Account discovery's final seal is incomplete. Please retry discovery before starting account profiling."` (These four arrive from `require_sealed_account_discovery` → `AccountResearchDiscoveryNotReady.reason_code`; each message is itself the operator instruction.)
  - `research_directive_not_found` — the directive is absent or belongs to another project. Message: `"no such workspace directive in this conversation's project"`.
  - `research_directive_not_draft` — message: `"only a current draft can be presented for confirmation"`. (A gate can be opened over a draft only; a confirmed/superseded directive is refused.)
  - `research_directive_invalid` — a `ResearchDirectiveError` from `compute_account_research_estimate`; message is `str(exc)` (the D1 validation/lineage messages, e.g. `"account is outside the directive's explicit scope"` from `compose_account_research_directive`). Agent: no guidance in code.

- **Output**: output model `OpenDirectiveConfirmationGateOutput` (`ToolOutput` ⇒ `frozen`, `extra="forbid"`, `strict=True`). It is explicitly **frozen** — the in-file comment: *"``head-of-abm/v23`` pins its ``output_schema_sha256``, so the FI pilot budget-controls switch may not add, remove, or retype a field here — nor even give this class a docstring, which pydantic publishes as the schema's ``description`` and which therefore moves the digest (spec AC5, learned the hard way)."*

  - `gate_id: str` — the derived gate uuid.
  - `gate_ref: str` — `f"{GATE_REF_PREFIX}{gate_id}"`, `GATE_REF_PREFIX = "agent-gate:"`. This is what goes in `open_gate_refs`.
  - `gate_kind: str` — `"directive_confirmation"`.
  - `subject_ref: str` — the directive's versioned ref (`research-directive:<id>:v<n>`).
  - `subject_revision: int` — `int(row.subject_revision or 0)`.
  - `expected_subject_sha256: str` — the directive digest the answer must echo.
  - `max_spend_cents: str` — the canonical `money_text(row.max_spend_cents)` spelling **only when `budget_controls_enabled`**; otherwise the constant `AMOUNT_WITHHELD = ""` (the empty string). Comment: *"the amount is computed and stored on the immutable row above in BOTH modes (audit + approval integrity); only its *presentation* is gated… The empty string is not a number ``money_text`` can ever produce, so 'withheld' and 'zero' stay distinguishable."* With controls on and a missing stored cap, `invoke` raises `RuntimeError("directive confirmation gate is missing its computed spend cap")`.
  - `currency: str` — `"USD"` (`DEFAULT_GATE_CURRENCY`); kept in both modes because *"a denomination without a quantity discloses nothing."*
  - `account_count: int` — `len(resolved.account_ids)` (≤ the input cap of 500).
  - `addressee_user_id: str` — the derived human.
  - `created: bool` — `False` on a replayed presentation (the stored row wins: *"if the amount changed between the two presentations, the number the human is looking at is the one that was written first"*).

  Bounds with constant names: `_MAX_SNAPSHOT_FIELDS = 40`, `_MAX_SNAPSHOT_QUESTIONS = 20` (snapshot truncation, *"Bounded so the snapshot stays a readable card rather than a second copy of the directive."*), `account_entity_ids` `max_length=500`, `AMOUNT_WITHHELD = ""`, `DEFAULT_GATE_CURRENCY = "USD"`, `GATE_REF_PREFIX = "agent-gate:"`.

- **Side effects / what becomes true afterwards**:
  - One immutable `agent_gate` row (or a replay of the existing one), plus one `agent_gate_subject` row per account (`binding_kind="research_directive_account"`, `ON CONFLICT DO NOTHING`).
  - `max_spend_cents` is computed by `compute_account_research_estimate(..., allow_draft=True)` = Σ over the named accounts of `EffectiveAccountResearchDirective.effort_policy.budget_cap_cents` — *"the identical Σ the launcher runs — and written immutably. Ratified §6-D5: no estimate tool, one number, verified again at launch."* The `allow_draft=True` relaxation is pricing-only: *"Composing is not authorizing — every execution path keeps this ``False``."*
  - Nothing is spent, nothing is confirmed, no research starts, no external boundary is crossed.
  - **The turn pauses**: the agent is expected to end the turn `awaiting_input` with `{object_type: "agent_gate", object_id: <gate_id>}` in `open_gate_refs`; the gate card is what the human sees. Module docstring: *"Presenting a gate spends nothing and confirms nothing. The agent's next act is to end its turn ``awaiting_input`` with the returned ``gate_ref`` in ``open_gate_refs``."*
  - Later, on approval, rows written by the route (not by this tool): `agent_gate_answer`, plus whatever `confirm_account_research_directive@2` or `launch_selected_account_research@1` writes (directive `status='confirmed'` + confirmation event, or the fleet launch rows).

- **Where the skill teaches it**: **not taught.** `stage0-interview` v26 never names `open_directive_confirmation_gate`; the gate sections it does teach are §4 (product-set gate) and §5 (ICP confirmation gate), and its account-research section §7 launches through `launch_arv2_account_research` without any directive gate. Granted by profile `head-of-abm/v49` at version `"1"` (`profile.yaml:119-122`).

- **Source**: `platform/api/clue_api/agent_gate_tools.py:1-402` (module docstring 1-27; constants 84-97; input/output models 104-137; `_parse` 158-181; tool class 183-330; `_resolve` 332-393; `build_agent_gate_tools` 396-402); `platform/api/clue_api/agent_gate.py:1-500` (kinds/decisions 67-97, `money_text` 120-132, `AgentGateRow` 146-172, `AgentGateSubjectBinding` 174-185, `directive_confirmation_gate_id` 215-236, `insert_gate` 291-386, `insert_gate_answer` 408-470); `platform/api/clue_api/agent_gate_wiring.py:1-52`; `platform/api/clue_api/account_research_discovery_readiness.py:14-120`; `platform/api/clue_api/account_research_estimate.py:56-92`; `platform/api/clue_api/chat/router.py:1840-2560`; `platform/api/clue_api/chat/turn_stream.py:1120-1161`; `platform/api/clue_api/turn_action.py:180-206`; `platform/toolbelt/clue_toolbelt/envelope.py:1-412`; `platform/api/clue_api/toolbelt_wiring.py:2920-2926`; `libs/clue-core/clue_core/research_directive.py:380-470`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:115-122`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:1-245`.

- **Discrepancy**:
  - The module docstring says the account set is proposed by the agent and the *addressee/amount/subject* are derived — but the **account set itself is model-authored** (`account_entity_ids`) and is only checked for canonical shape and uniqueness here; its membership in the directive's scope is enforced indirectly, by `compose_account_research_directive` raising `"account is outside the directive's explicit scope"` inside the estimate (surfaced as `research_directive_invalid`, not as a dedicated code).
  - The docstring's third guarantee — *"The subject cannot drift… an answer that names a different digest is refused by the turn route"* — is true for the digest, but the **amount** half of staleness is disarmed when `budget_controls_enabled` is off: the route then skips the `GATE_AMOUNT_STALE` check entirely (its own comment calls the digest check "the load-bearing half").
  - `model_description` says the tool "launches nothing", which holds for the tool; but with budget controls **off** the human's approval of this gate does launch (`launch_selected_account_research@1`, one atomic confirm-and-launch in the route). The tool's own copy never says so, so an agent reading only the description will understate what "Approve" does on such a deployment.
  - `replay.durable_identity` names "one turn + one exact directive revision", yet the derived `gate_id` also includes the `subject_ref` **and** the digest but **not** the account set — so two presentations for the same turn+directive with *different* account sets converge on the same gate row, and the first-written `account_entity_ids`/`max_spend_cents` snapshot wins silently (`insert_gate`'s documented "the stored values are authoritative and the caller's recomputed ones are simply discarded").


---

# Part 4 — Authoring and recording


---

## `author_icp_document@1`

- **Address**: `author_icp_document@1` — effect class `write` (`ToolEffectClass.WRITE`), replay policy `domain_idempotent` (`ReplayPolicy.DOMAIN_IDEMPOTENT`; `durable_identity="presenting turn + scope + icp_key"`, `operation_id_required` not set — defaults `False`, `external_boundary=ExternalReplayBoundary.NONE`), `pin_requirements = ("project",)` (commented in code as "``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0 pin (standing rule item 5)"), opens a human gate: **no**. The module docstring is explicit: "It writes a *proposal* and nothing more. Nothing is confirmed by this call, no project pin moves, and no research is launched: the human's yes is still the ICP confirmation gate, which is the tool the agent reaches for next." Journal parameter policy: `JournalParameterPolicy(safe_display_fields=("icp_key", "scope", "derived_from_icp_key"))` — the `document` itself stays artifact-backed rather than displayed. Estimate: `ToolEstimate.free()` ("Writing a file the agent already drafted buys nothing from anybody").

- **Purpose**: This is where an ICP document comes from. The Head of ABM, having read the brand's knowledge files and talked to the human about who they sell to, writes the profile down and stores it as one **proposed** version of a knowledge document — either a new brand-level ICP (or a new version of an existing brand profile under the same key), or a project-local variant with its own key and a `derived_from` naming the brand profile it adapts. The model authors *content* (hard gates, exclusions, persona map, qualifier fields, prose); the platform authors *identity* — status is always `proposed`, scope is the caller's and never the front matter's, lineage is resolved from a brand document that exists or is absent, and authorship is the presenting turn and the human on it.

- **Inputs** (`AuthorIcpDocumentInput`, `icp_authoring_tools.py:74-86`; class docstring: "The document and what it is. Scope's *coordinates*, authorship and lineage ids are derived from the presenting turn and the rows it names."):
  - `icp_key: str` (required) — `Field(min_length=1, max_length=ICP_KEY_MAX_LENGTH, pattern=ICP_KEY_PATTERN)` where `ICP_KEY_MAX_LENGTH = 60` and `ICP_KEY_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"`. No per-field description on the model; the constants carry the reasoning — "An ICP key is a path segment and a file name, so it is lowercase kebab-case and nothing else. Anything looser would let one ICP have several spellings — and the key is how a human, a gate, a pin and a launch all name the same document." and "A key also has to stay a readable file name; the column is unbounded, the contract is not."
  - `document: str` (required) — `Field(min_length=1, max_length=_DOCUMENT_MAX_CHARS)` where `_DOCUMENT_MAX_CHARS = 200_000`, commented: "A document long enough for a real ICP — gates, exclusions, persona map, qualifier fields and prose — and bounded so one call cannot become an unbounded upload." The model-facing description says what must be in it: "The document must carry the icp-definition front matter: kind, icp_key, product_ids, hard_gates, exclusions, persona_map, qualifier_fields, then the body."
  - `scope: Literal["brand", "project"]` (required, no default) — the module docstring: "**scope** is the caller's, never the front matter's — ``brand`` writes an unscoped row, and ``project`` writes a row owned by the presenting turn's project."
  - `derived_from_icp_key: str | None = None` — comment on the field: "The brand ICP a project-local variant adapts, by key. ``None`` for an original profile." No `pattern`, `min_length` or `max_length` is declared on this field (unlike `icp_key`); it is validated only by existence, at `_derived_from`.
  - `source_turn_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})` — **engine-injected, not model-authored**. `TRUSTED_TURN_FIELD = "clue_trusted_turn_field"`; per `turn_binding.py:3-10`, "A tool that needs either declares the field and marks it :data:`TRUSTED_TURN_FIELD`; the field is then stripped from the model-visible schema (``agent_runtime_wiring._with_trusted_runtime``) and served at the execution seam from the trusted binding". The value must be exactly `turn-action:<canonical uuid>` (`parse_turn_action_ref`).

  Nested / derived values the model does **not** supply, assembled into `IcpAuthoringRequest` (`icp_authoring.py:126-142`): `workspace_id` (from `ctx.workspace_id`), `brand_id` (from the project row), `project_id` (from the presenting turn), `turn_id`, `user_id` (`turn.submitted_by_user_id`). The document's front matter is parsed by `parse_front_matter`, and these keys are **stripped and re-stamped by the platform** (`_PLATFORM_OWNED_KEYS`): `confirmed_by`, `confirmed_at`, `confirmed_for_project_id`, `product_selection_version`, `user_edit`, `derived_from`, `project_id`, `brand_id`, `status` — "A model that typed any of them is not believed: a draft cannot confirm itself, scope itself, or claim a lineage." The platform then stamps `status="proposed"`, `brand_id`, `project_id` (project scope only), `derived_from` (resolved uuid, only when found), `authored_by = {"turn_id": ..., "user_id": ...}`, `authored_at` (ISO timestamp).

- **Preconditions and refusal codes**:
  - `icp_authoring_not_composed` — the service is `None` on this deployment. Message: `"ICP authoring is not composed on this deployment"`. Returned from `preconditions` before any row is read. Composition: `DbIcpAuthoringService(storage)` in `fleet_main.py:943` and `projections_main.py:141` — no feature flag ("ICP authoring needs no flag of its own: writing a proposal spends nothing and confirms nothing"). Guidance: none in code beyond the message.
  - `authoring_turn_ref_malformed` — `parse_turn_action_ref` rejected the injected ref. Message is the `TurnActionUnresolvable` text, one of: `"an action reference must be an opaque turn-action reference"`, `"a turn-action reference must name one turn by its canonical identifier"`, `"a turn-action reference must spell its turn identifier canonically"`. No guidance in code — the field is engine-injected, so the model cannot fix it.
  - `authoring_turn_not_found` — two causes, deliberately indistinguishable. (a) `load_turn_identity` returned `None`: `"the presenting turn is not part of this workspace"`. (b) the turn's project is missing or belongs to another workspace: `"the presenting turn's project is not part of this workspace"` ("Fail-closed and indistinguishable from an unresolvable turn: a turn whose project this workspace cannot see is not a turn this workspace may write in."). No guidance in code.
  - `authoring_addressee_missing` — `turn.submitted_by_user_id is None`. Message: `"the presenting turn records no human to credit this document to"`. No guidance in code.
  - `icp_key_invalid` — raised by `_validate_key` when the key fails `ICP_KEY_PATTERN` or exceeds 60 chars. Message: `"icp_key must be lowercase kebab-case (letters, digits and single hyphens), at most 60 characters"`. (Reachable from the service even though the pydantic field already enforces both.)
  - `icp_front_matter_invalid` — four distinct messages, all from the same code. From `parse_front_matter` via `ValueError`: `"no front matter"` (the text does not start with `---\n`, or has no closing `\n---\n`) or `"front matter is not a mapping"`. From `_validate_front`: `f"front matter must declare kind: {ICP_KIND} (found {kind!r})"`; `f"front matter icp_key must be {icp_key!r} (found {declared!r})"`; `"front matter must declare product_ids: a non-empty list of product ids this ICP buys"`; `"front matter must declare hard_gates: a non-empty list of gates an account must pass"`. `_validate_front` is explicitly "Deliberately a floor, not a schema… what is refused here is a document that could not be an ICP at all — the wrong kind, another key, no products to sell, no gates to qualify on." Skill guidance (§5b): write the front matter "in the shape the existing ICP files use" and "Never invent a product id: take `product_ids` from `product/catalog.md`'s front matter."
  - `icp_key_taken_by_brand` — `scope="project"` but a servable brand-scoped row already owns `audience/icp-<key>.md`. Message: `f"the brand already has an ICP named {icp_key!r}; a project variant needs its own key, with derived_from naming the brand profile it adapts"`. Guidance is in the message and in skill §5b: "Choose a new lowercase kebab-case key only for a new profile, or for a project variant, which always needs its own key, never the brand profile's."
  - `icp_key_taken_by_project` — `scope="brand"` but some project already owns that path. Message: `f"a project already owns an ICP named {icp_key!r}; a brand profile needs a key no project has taken"`. Note the writer's own caveat: "**The rule is this writer's, not the schema's.** The synthesis writer does not apply it… so a full re-onboarding can mint a brand-level ``audience/icp-foo.md`` after a project has already taken ``foo`` for a variant, and the invariant this function asserts is then false at rest."
  - `derived_from_not_found` — `derived_from_icp_key` was supplied but `current_icp_document(..., project_id=None)` found nothing. Message: `f"this brand has no readable ICP document named {derived_from_icp_key!r} to derive from"`. The lookup is deliberately brand-scoped: "a lineage pointing at another project's private variant would be a link this project may not follow, and pointing at its own would make the chain circular rather than explanatory."
  - `icp_document_version_race` — two causes. (a) `IntegrityError` on `brand_knowledge_document_scope_path_version`: `"another writer published a version of this path; re-read the document and retry"` ("The agent's draft is not lost and nothing partial is at rest — it re-reads the path and retries."). (b) the defensive post-insert read-back found nothing: `"the authored ICP document did not persist"` (marked `# pragma: no cover`).

  Mechanics: `preconditions` runs `_resolve` (turn/project resolution) only; every domain refusal above surfaces from `invoke`, where `IcpAuthoringRefused` is re-raised as `PreconditionFailed([PreconditionFailure(code, message)])` — "A domain refusal is feedback the author can act on — a typed precondition failure, never a stack trace the model has to guess at."

- **Output** (`AuthorIcpDocumentOutput`, `icp_authoring_tools.py:89-96`; returned as `ToolResult.references = output.model_dump()`):
  - `document_id: str` — the uuid of the stored `brand_knowledge_document` row, derived (not minted) as `uuid5(NAMESPACE_URL, f"arv2-icp-authoring:{turn_id}:{scope}:{icp_key}")` — "The one id this turn's authoring of this key in this scope will ever have… a retried tool call finds its own row instead of publishing a second version of the same draft."
  - `icp_key: str` — echoes the request's key.
  - `version: int` — the version this write minted, read back from the row rather than trusted from the computed value ("the stored one is what every later reader, gate and pin will cite"). Computed as `COALESCE(MAX(version), 0) + 1` over the same `(workspace, brand, path, project_id IS NOT DISTINCT FROM …)` scope.
  - `path: str` — the row path, always `f"audience/icp-{icp_key}.md"` (`ICP_FOLDER = "audience"`).
  - `workspace_path: str` — where the document is readable in the agent's workspace next turn: `"inputs/brand/knowledge/" + path` for brand scope, `"inputs/project/" + path.removeprefix("project/")` for project scope — and **version-qualified** (`audience/icp-gi.md` at v3 → `audience/icp-gi.v3.md`) when another version of that same path in that same scope is the project's current pin. "An authored row is always born ``proposed``, so it is never the pin itself — which means the very first authoring over a pinned path lands at the qualified name."
  - `status: str` — the row's own status, read back. On a fresh write this is `"proposed"`; on a replay it is whatever is at rest now, because "by the time a call is replayed a later version may have superseded this one, and reporting what is at rest is the honest answer."
  - `replayed: bool` — `True` when the derived `document_id` already existed and the call short-circuited before rendering or storing anything.

  Caps/bounds, verbatim with constant names: `_DOCUMENT_MAX_CHARS = 200_000`; `ICP_KEY_MAX_LENGTH = 60`; `ICP_KEY_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"`; `source_turn_ref` `max_length=1_000`; `_SERVABLE_STATUSES: tuple[str, ...] = ("ready", "proposed", "confirmed")`; `_RETIRABLE_STATUSES: tuple[str, ...] = ("ready", "proposed")`; `ICP_AUTHORING_SOURCE_KEY = "arv2-icp-authoring"`; `ICP_FOLDER = "audience"`; `_BRAND_INPUT_PREFIX = "inputs/brand/knowledge/"`; `_PROJECT_INPUT_PREFIX = "inputs/project/"`.

- **Side effects / what becomes true afterwards**:
  - One row inserted into **`brand_knowledge_document`** (`ON CONFLICT (document_id) DO NOTHING`) with `status = 'proposed'`, `kind = 'icp-definition'`, `folder = 'audience'`, `path = audience/icp-<key>.md`, `project_id` = the turn's project for `scope="project"` / `NULL` for `scope="brand"`, `derived_from_document_id` = the resolved brand document or `NULL`, `supersedes_document_id` = the highest-version servable row in the same scope, `produced_by_step_id = NULL`, `produced_by_turn_id = NULL` (deliberate: "the turn's ``agent_turn`` row does not exist yet while the turn is running, so the FK could not be satisfied. The front matter's ``authored_by`` carries the same fact durably.").
  - One row recorded in the **artifact table** via `record_artifact` with `source_key = "arv2-icp-authoring"`, `media_type = ICP_ARTIFACT_MEDIA_TYPE`, `content_sha256`, `size_bytes`.
  - The rendered markdown bytes written to object storage at `artifact_key(workspace_id, sha)` — **last**, after every refusable condition has passed, "so writing it before a refusal … would leave bytes in object storage that nothing references and nothing reaps — and this is the one write path an agent can retry in a loop."
  - Status transition on siblings: every other row at the same `(workspace, brand, path, scope)` whose status is in `('ready', 'proposed')` is `UPDATE`d to `status = 'superseded', updated_at = now()`. A `confirmed` row is **never** retired — "it is some project's pinned ICP, and a new proposal stands beside it until a human moves the pin."
  - Nothing is confirmed, no `project_icp_pin` moves, no background turn is queued, and **no card is created by this tool** — the chat card for the ICP comes from the confirmation gate opened afterwards (see C4). No `domain_refs` object type is emitted by this tool; `_PLAN_OBJECT_TYPES` in `conversation_turns.py:145-147` (`{"research_directive", "agent_plan", "plan", "project_document"}`) does not include ICP documents.
  - The new version becomes readable in the agent's workspace at `workspace_path` **on the next turn**.

- **Where the skill teaches it**: `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md` **§5b "Author a profile"** (lines 145–155; the call itself at line 153), which also mandates the follow-on: "In the same turn, open the ICP confirmation gate on that key (section 5) and end the turn `awaiting_input`." Guard rails in the same section: "Do not write a profile before the questions in section 2 are answered, and do not write one the user did not ask for." Cross-referenced from §5 (Revised → "draft the revised profile (section 5b) in the same scope as the reviewed one"). The tool is pinned in the skill front matter (line 10-13) and granted in `head-of-abm/v49/profile.yaml:70-73`.

- **Source**: `platform/api/clue_api/icp_authoring_tools.py:1-247` (whole file); `platform/api/clue_api/arv2/icp_authoring.py:1-631` (whole file); `platform/api/clue_api/arv2/knowledge_frontmatter.py:13-32`; `platform/toolbelt/clue_toolbelt/envelope.py:90-412`; `platform/api/clue_api/turn_binding.py:1-61`; `platform/api/clue_api/turn_action.py:180-209`; `platform/api/clue_api/toolbelt_wiring.py:74, 110, 2661, 2823-2830`; `platform/api/clue_api/fleet_main.py:940-996`; `platform/api/clue_api/projections_main.py:138-166`; `platform/api/clue_api/conversation_turns.py:142-147`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:1-16, 145-155`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:60-75`.

- **Discrepancy**:
  1. The `model_description` says "The document must carry the icp-definition front matter: kind, icp_key, product_ids, hard_gates, exclusions, persona_map, qualifier_fields, then the body." — but `_validate_front` (`icp_authoring.py:238-273`) enforces **only** `kind`, `icp_key`, `product_ids` and `hard_gates`. `exclusions`, `persona_map` and `qualifier_fields` are never checked; a document omitting all three is accepted. The service docstring concedes this ("Deliberately a floor, not a schema"), so the model-facing "must" overstates the enforced contract.
  2. Skill §5b tells the agent "A refusal names what to fix: a key already taken, a missing gate, **a product id the catalog does not carry**." No code path validates `product_ids` against the brand's catalog — `_validate_front` only requires a non-empty list of non-empty strings. That third refusal does not exist in this tool.
  3. `derived_from_icp_key` carries no format constraint while `icp_key` carries `pattern=ICP_KEY_PATTERN, max_length=60`. A malformed lineage key is not refused as invalid; it simply fails the existence lookup and comes back as `derived_from_not_found`.


---

## `request_persona_synthesis@1`

- **Address**: `request_persona_synthesis@1` — effect class `spend` (`ToolEffectClass.SPEND`), replay policy `domain_idempotent` (`ReplayPolicy.DOMAIN_IDEMPOTENT`; `durable_identity="project + pinned ICP document; one open personas run per document"`, `operation_id_required` not set — defaults `False`, `external_boundary=ExternalReplayBoundary.NONE`), `pin_requirements = ("project",)` ("``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0 pin (standing rule item 5)"), opens a human gate: **no**. Journal parameter policy: `JournalParameterPolicy(safe_display_fields=("icp_key",))`. Estimate: `ToolEstimate(cost_cents=Decimal(0), detail={"basis": "one_onboarding_persona_synthesis_turn"})` — "The call itself buys nothing; the spend is one governed persona turn, settled against that run's own step and the deployment's turn budget. So the estimate carries the *shape* of the spend rather than a number nobody derived."

- **Purpose**: A project's ICP is confirmed and pinned by a human at the gate, but the buying committee that profile sells to is a *separate* document written by the audience-persona turn — and after a newly authored ICP nothing has written it yet. This tool is how the agent asks for it: it opens a **personas-only onboarding run** (one governed persona turn for the exact document version the project pinned, driven on the fleet) and returns that run's id. It writes no persona itself, confirms or repoints nothing, and cannot ask for a profile the project did not pin — the ICP is resolved from `project_icp_pin` and the model's `icp_key` is only *checked against* it. A successful result means "the work is queued", never "the personas exist".

- **Inputs** (`RequestPersonaSynthesisInput`, `persona_request_tools.py:294-303`; class docstring: "Which profile's personas. Scope, authorship and the document itself are platform-derived."):
  - `icp_key: str` (required) — `Field(min_length=1, max_length=ICP_KEY_MAX_LENGTH, pattern=ICP_KEY_PATTERN)`, imported from `clue_api.arv2.icp_authoring`, where `ICP_KEY_MAX_LENGTH = 60` and `ICP_KEY_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"`. No per-field description on the model; the `model_description` says what to put there: "Ask the platform to write (or rewrite) the persona document for this project's confirmed ICP."
  - `source_turn_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})` — **engine-injected, stripped from the model-visible schema** (`turn_binding.py:1-15`); must be exactly `turn-action:<canonical uuid>`.

  Nested / derived values assembled into `PersonaSynthesisRequest` (`persona_request_tools.py:99-112`; docstring: "One ask: write the personas of this project's pinned ICP. Every field but ``icp_key`` is platform-derived — the workspace is ambient, and the project, brand, turn and human come from the presenting turn's own rows."): `workspace_id` (from `ctx.workspace_id`), `project_id` (`turn.project_id`), `brand_id` (`project.brand_id`), `turn_id`, `user_id` (`turn.submitted_by_user_id`), `icp_key`. Everything about the subject document — `document_id`, `version`, `path`, `project_id` scope — is read off `current_project_icp_pin`, never supplied by the model; those five ride the fleet payload as an `IcpRef` "because the run's subject is that exact document version, and a worker must not re-resolve 'the project's current ICP' and quietly write personas for a profile the human never asked about."

- **Preconditions and refusal codes**:
  - `persona_synthesis_not_composed` — the service is `None`. Message: `"persona synthesis is not composed on this deployment"`. Composition is flag-gated: `DbPersonaRequestService(queue=work_queue) if settings.onboarding_v2_enabled else None` (`fleet_main.py:947-949`) and `DbPersonaRequestService() if resolved.onboarding_v2_enabled else None` (`projections_main.py:146`) — "The persona request DOES need the onboarding flag: what it opens is an onboarding run, and with the lane off no worker would ever drive it — the row would sit ``queued`` forever, holding that ICP document's one open slot."
  - `persona_turn_ref_malformed` — `parse_turn_action_ref` rejected the injected ref; message is the `TurnActionUnresolvable` text (`"an action reference must be an opaque turn-action reference"` / `"…must name one turn by its canonical identifier"` / `"…must spell its turn identifier canonically"`). No guidance in code.
  - `persona_turn_not_found` — (a) `load_turn_identity` returned `None`: `"the presenting turn is not part of this workspace"`; (b) the turn's project is missing or foreign: `"the presenting turn's project is not part of this workspace"` ("Fail-closed and indistinguishable from an unresolvable turn: a turn whose project this workspace cannot see is not a turn this workspace may spend in."). No guidance in code.
  - `persona_addressee_missing` — `turn.submitted_by_user_id is None`. Message: `"the presenting turn records no human to credit this request to"`. No guidance in code.
  - `icp_not_pinned_for_project` — the pin is absent, or its `icp_key` is not the one named. Message: `f"project {project_id!r} has not pinned an ICP called {icp_key!r}"` plus, when a pin exists, `f"; its pinned ICP is {pin.icp_key!r}"`. Deliberately one code for both: "they are one fact from the agent's side: the profile it named is not the one this project works against. Naming the pin (or its absence) tells it what to do next without it having to guess." Skill guidance (§5c): call it only "On the turn after the confirmation, when the index card names the confirmed ICP as this project's pin".
  - `persona_run_already_open` — an open (`queued`/`running`) personas run exists for that document and it is **not** this turn's derived run. Message: `f"personas for {pin.icp_key!r} are already being written by run {open_run}; wait for it rather than writing that document twice"`. The read is keyed on the document, not the workspace or project, "because two projects pinning the same brand ICP are asking for the same personas at the same path, and two turns racing there would version over each other."
  - `persona_run_settled` — this turn's own derived run already exists and is `failed`. Message: `"that request already failed; ask again on a new turn"`. (The `completed`/`completed_with_gaps` case is **not** a refusal — it returns a receipt with `replayed=True`: "This turn did open that run and the work is done. ``replayed`` is the honest word.")
  - `brand_not_onboarded` — no `onboarding_run` row with `kind = 'full'` and status in `('completed', 'completed_with_gaps')` for this workspace+brand, so no `company_domain` exists. Message: `f"brand {brand_id!r} has no completed onboarding run, so there is no company for a persona turn to write about"`.
  - `enqueue_failed` — the run row was committed but the fleet offer failed or was refused. Message: `"the persona synthesis job could not be queued; ask again"`. Before raising, `fail_run(conn, run_id=run_id)` is called: "A row nothing will drive would hold this document's one open slot forever, so the run is failed and the document is free for the next attempt." The exception catch is deliberately broad — "a transport error, a pool timeout and a programming error in the queue are the same fact here — the run was not offered — and all must be contained." Logged as `persona_synthesis.enqueue_failed` (exception path) or `persona_synthesis.enqueue_refused` (offer returned `False`).

  Mechanics: `preconditions` runs `_resolve` (turn/project resolution) only; every domain refusal above surfaces from `invoke`, where `PersonaSynthesisRefused` is re-raised as `PreconditionFailed([PreconditionFailure(code, message)])` — "A domain refusal is feedback the agent can act on — a typed precondition failure, never a stack trace the model has to guess at." The refusal-code docstring on `PersonaSynthesisRefused` reads: "Codes: ``icp_not_pinned_for_project`` (the named key is not this project's current pin — or it has none), ``persona_run_already_open`` (that document's personas are already being written), ``brand_not_onboarded`` (no completed whole-brand walk to take the company domain from), and ``enqueue_failed`` (the run was recorded but could not be offered, so it was failed)."

- **Output** (`RequestPersonaSynthesisOutput`, `persona_request_tools.py:305-308`; returned as `ToolResult.references = output.model_dump()`):
  - `run_id: str` — the personas onboarding run's uuid, derived not minted: `uuid5(NAMESPACE_URL, f"arv2-persona-run:{workspace_id}:{document_id}:{turn_id}")`. "The turn is part of it deliberately. A replayed tool call inside one turn re-derives the same id and finds its own run (``replayed=True``) rather than opening a second; a *different* turn asking while that run is still open is a different act, and is refused by name instead of quietly racing the first at the same document path."
  - `icp_key: str` — `pin.icp_key`, i.e. the *pin's* key (which equals the requested key, since a mismatch is refused).
  - `replayed: bool` — `True` when this turn had already opened the run (still open, or already settled `completed`/`completed_with_gaps`); `False` on a fresh open-and-offer. Also propagated to `ToolResult.replayed`.

  Caps/bounds, verbatim with constant names: `ICP_KEY_MAX_LENGTH = 60`; `ICP_KEY_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"`; `source_turn_ref` `max_length=1_000`. There is **one open personas run per ICP document**, enforced by the read shaped like the partial index `onboarding_run_persona_open` (`status IN ('queued', 'running')`). Fleet offer constants: `FleetTaskKind.ONBOARDING_RUN`, `onboarding_work_id(run_id)`, `dedup_key = f"{ONBOARDING_DEDUP_PREFIX}{run_id}"`, `priority = ONBOARDING_TASK_PRIORITY`.

- **Side effects / what becomes true afterwards**:
  - One row inserted into **`onboarding_run`** (`ON CONFLICT (run_id) DO NOTHING`) with `kind = 'personas'`, `project_id`, `persona_icp_document_id` (the pinned document), `company_domain` (copied from the brand's completed `kind='full'` walk, not re-derived), `requested_by_user_id`. The DB constraint `onboarding_run_persona_shape` welds the two halves: "a personas run without its ICP document, or a full run with one, is not a row the database will take." Status starts `queued`.
  - **Rows first, offer second** (the O3 rule): the run row is committed *before* the fleet is told, "because a task that reaches a worker must always find its run." Then one fleet task is enqueued (`FleetTaskKind.ONBOARDING_RUN`, payload `kind: "personas"` carrying `run_id`, `workspace_id`, `brand_id`, `project_id`, `company_domain`, `company_name`, and the whole `icp` ref — `document_id`, `icp_key`, `version`, `path`, scope `project_id`). `company_name` = the brand row's `name`, falling back to `str(company_domain)`.
  - On a failed offer the run row is moved to `failed` (`fail_run`) and the call refuses `enqueue_failed` — the document's one open slot is released rather than being held by a row nobody will drive.
  - **Background turn queued**: one governed audience-persona synthesis turn, run on the fleet. Nothing is confirmed, no pin moves, no ICP version is written by this call.
  - The persona document lands on a **later turn**, under the ICP's own scope: `inputs/brand/knowledge/audience/persona-<key>.md` for a brand profile, `inputs/project/audience/persona-<key>.md` for a project-local variant (skill §5c).
  - **No card appears in chat from this tool.** It emits no `domain_refs` object type — `_PLAN_OBJECT_TYPES` (`conversation_turns.py:145-147`) is `{"research_directive", "agent_plan", "plan", "project_document"}` and contains nothing persona-shaped; the skill instructs the agent to *say* that the run is going, not to render a card.

- **Where the skill teaches it**: `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md` **§5c "Personas for a confirmed profile"** (lines 157–159; the call at line 159). Verbatim: "On the turn after the confirmation, when the index card names the confirmed ICP as this project's pin, ask the human whether to write the personas now. If they say yes, call `request_persona_synthesis` with the `icp_key`. … **Say that it is running, not that it is done.** If the human wants a persona rewritten later, the same call redrafts it." Pinned in the skill front matter (lines 14-17) and granted at `head-of-abm/v49/profile.yaml:178-181` (profile comment: "The call queues a background personas-only onboarding turn for the pinned ICP and returns when it is queued — never with a document.").

- **Source**: `platform/api/clue_api/persona_request_tools.py:1-450` (whole file); `platform/api/clue_api/arv2/onboarding_store.py:111-190` (`create_persona_run`, `open_persona_run`, `read_run_status`); `platform/api/clue_api/onboarding_routes.py:121-165` (`DbOnboardingEnqueuer.enqueue_personas`); `platform/api/clue_api/arv2/icp_authoring.py:66-72` (key constants); `platform/toolbelt/clue_toolbelt/envelope.py:90-412`; `platform/api/clue_api/turn_binding.py:1-61`; `platform/api/clue_api/turn_action.py:180-209`; `platform/api/clue_api/toolbelt_wiring.py:115, 2662, 2831-2836`; `platform/api/clue_api/fleet_main.py:944-996`; `platform/api/clue_api/projections_main.py:143-166`; `platform/api/clue_api/conversation_turns.py:142-147`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:14-17, 157-159`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:174-181`.

- **Discrepancy**:
  1. `PersonaSynthesisRefused`'s own docstring enumerates four codes (`icp_not_pinned_for_project`, `persona_run_already_open`, `brand_not_onboarded`, `enqueue_failed`) and claims "``code`` is stable and machine-readable", but the service raises a **fifth**, `persona_run_settled` (`persona_request_tools.py:211-215`), which the docstring never mentions. An agent (or operator) reading the exception contract would not know that code exists.
  2. `effect_class = ToolEffectClass.SPEND` while `estimate()` returns `cost_cents=Decimal(0)`. Deliberate and commented (the spend is the downstream persona turn, settled against that run's own budget), but it means the pre-spend prior the UI shows for this tool is zero even though the call is classified as spend.
  3. The `model_description` says the tool is "Refused when the ICP named is not this project's pinned ICP, or when a persona run for it is already open" — it does not mention the `brand_not_onboarded`, `persona_run_settled` or `enqueue_failed` refusals the model can also receive.


---

## `write_project_document@1`

- **Address**: `write_project_document@1` — effect class `write` (`ToolEffectClass.WRITE`), replay policy `domain_idempotent` (`ReplayPolicy.DOMAIN_IDEMPOTENT`; `durable_identity="presenting turn + document + expected version + body"`, `operation_id_required` not set — defaults `False`, `external_boundary=ExternalReplayBoundary.NONE`), `pin_requirements = ("project",)` ("``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0 pin (standing rule item 5)"), opens a human gate: **no** ("a plan is born ``ready``; there is no confirmation gate for a plan"). Journal parameter policy: `JournalParameterPolicy(safe_display_fields=("document", "expected_version"))` — the plan body itself stays artifact-backed. Estimate: `ToolEstimate.free()` ("Writing down a plan the agent and the human already settled buys nothing from anybody").

- **Purpose**: A project has one plan, `inputs/project/plan.md`, and two hands write it — the agent through this tool, the human through the project-document editor / Plan tab. Both append an immutable version to one chain, which makes it a lost-update problem, so the model must state **which version it read** (`expected_version`); when the file has moved since, the platform refuses by name rather than overwriting words the human typed in between. Everything about *who* and *where* is derived from the presenting turn and the project row; the model authors only the markdown.

- **Inputs** (`WriteProjectDocumentInput`, `project_document_tools.py:107-119`; class docstring: "The plan and the version it was written against. Scope, authorship and the path itself are derived from the presenting turn and the rows it names."):
  - `document: Literal["plan"]` (required, no default) — the only admissible value is the string `"plan"`. The model-facing description: "Write this project's plan (inputs/project/plan.md) as markdown".
  - `body: str` (required) — `Field(min_length=1, max_length=_PLAN_MAX_CHARS)` where `_PLAN_MAX_CHARS = 200_000`, commented: "A plan long enough for a real one — outcome, profile, products, motion, channels, owners, the ninety-day picture and the next steps — and bounded so one call cannot become an upload." What to put there, from the `model_description`: "the execution plan you and the human settled — outcome, the confirmed profile and products, the account motion, channels, owners, what day ninety looks like, and the next steps."
  - `expected_version: int | None = Field(default=None, ge=1)` — field comment: "The version of ``inputs/project/plan.md`` this body was written against; omitted only when no plan exists yet." `model_description`: "Pass expected_version = the version of the file you read (omit it only when no plan exists yet); the platform refuses when the human has edited it since, and you then re-read it." On the request dataclass (`ProjectPlanWrite`): "The version of ``inputs/project/plan.md`` this body was written against; ``None`` when the file does not exist yet."
  - `source_turn_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})` — **engine-injected, stripped from the model-visible schema** (`turn_binding.py:1-15`); must be exactly `turn-action:<canonical uuid>`.

  Nested / derived values assembled into `ProjectPlanWrite` (`arv2/project_documents.py:145-158`; docstring: "One write of a project's plan. Scope, tenancy and authorship are ambient; the body is the model's, and ``expected_version`` is its statement about what it read."): `workspace_id` (`ctx.workspace_id`), `brand_id` (`project.brand_id`), `project_id` (`turn.project_id`), `turn_id`, `user_id` (`turn.submitted_by_user_id`). The front matter is written entirely by the platform — `{"kind": "project-plan", "project_id": ..., "brand_id": ..., "version": <the version this write mints>, "status": "ready", "authored_by": {"turn_id": ..., "user_id": ...}, "authored_at": <iso>}` — so that "the version of the file the agent reads is legible *in* the file it reads (ruling P) rather than only on the index card beside it."

- **Preconditions and refusal codes**:
  - `project_documents_not_composed` — the service is `None`. Message: `"project documents are not composed on this deployment"`. Composition: `DbProjectDocumentService(storage)` at `fleet_main.py:953` and `projections_main.py:150`, with **no feature flag** ("The project plan has no flag of its own either: writing it down spends nothing and confirms nothing, and it needs only the storage the knowledge documents live in").
  - `project_document_turn_ref_malformed` — `parse_turn_action_ref` rejected the injected ref; message is the `TurnActionUnresolvable` text. No guidance in code.
  - `project_document_turn_not_found` — (a) `"the presenting turn is not part of this workspace"`; (b) `"the presenting turn's project is not part of this workspace"` ("Fail-closed and indistinguishable from an unresolvable turn"). No guidance in code.
  - `project_document_addressee_missing` — `turn.submitted_by_user_id is None`. Message: `"the presenting turn records no human to credit this plan to"`. No guidance in code.
  - `project_document_body_empty` — `not request.body.strip()` (whitespace-only passes the pydantic `min_length=1` but fails here). Message: `"the plan body is empty; write the plan as markdown"`.
  - **`project_document_revision_conflict` — the stale-version refusal. This is the tool's defining behaviour.** Raised when `current != request.expected_version`, where `current` is `current_plan_version(...)` (the version of the newest servable `project/plan.md` row in this project's scope, or `None` when no plan exists) read **after** taking the project lock (`_lock_project` — "The one lock order both writers take"). Message, verbatim: `f"plan.md is at version {current}; you expected {request.expected_version}. Re-read {PLAN_WORKSPACE_PATH} and write again."` — i.e. `"plan.md is at version 3; you expected 2. Re-read inputs/project/plan.md and write again."` The comparison is strict equality in both directions, so all three of these refuse: passing a *stale* version (the human edited since), passing a version *ahead* of what is at rest, and passing `None` when a plan already exists (or a number when none does). What the agent should do — `model_description`: "the platform refuses when the human has edited it since, and you then re-read it"; skill §6b: "When the platform refuses because the human edited the plan since, re-read the file, keep their edits, and write again"; code comment at the tool: "A revision conflict is feedback the author can act on — re-read the plan and write again — so it arrives as a typed precondition failure, never a stack trace." Note the interaction with replay identity: the document id is `uuid5(NAMESPACE_URL, f"arv2-project-plan:{turn_id}:{expected_version or 0}:{body_sha256}")`, so *the same turn writing different words against the same version* is a rewrite, not a replay — "with it, the rewrite mints a new id, fails the revision check against the version it just wrote, and comes back as the named revision conflict the agent already knows how to recover from."
  - `project_document_version_race` — (a) `IntegrityError` on `brand_knowledge_document_scope_path_version`: `f"another writer published version {version} of the plan; re-read {PLAN_WORKSPACE_PATH} and write again"`. (b) the post-insert read-back found nothing: `"the written plan did not persist"`.

  Mechanics: `preconditions` runs `_resolve` (turn/project resolution) only; the domain refusals surface from `invoke`, where `ProjectDocumentRefused` is re-raised as `PreconditionFailed([PreconditionFailure(code, message)])`. `ProjectDocumentRefused`'s docstring: "Every refusal names something the caller can act on: an empty body, a version that is no longer current (re-read and write again), a document this project does not own, or another writer that took the version number in between."

- **Output** (`WriteProjectDocumentOutput`, `project_document_tools.py:122-127`; returned as `ToolResult.references = output.model_dump()`):
  - `document_id: str` — the uuid of the stored `brand_knowledge_document` row, derived as `uuid5(NAMESPACE_URL, f"arv2-project-plan:{turn_id}:{expected_version or 0}:{body_sha256}")`. Three things are in the key, "and each of them is a genuinely different write: the **turn**, so one turn's plan is not another's; the **expected version**, because the same turn writing again after re-reading a newer plan is a new link in the version chain; the **body digest**, because the same turn writing *different words* against the same version is a rewrite, not a replay."
  - `path: str` — read back off the row; always `PLAN_PATH = "project/plan.md"` ("Folder-qualified, because the ``path LIKE folder || '/%'`` CHECK holds").
  - `version: int` — the version this write minted, read back from the row. Computed as `(current or 0) + 1`, known *before* the bytes are rendered so it can be stamped into the front matter.
  - `workspace_path: str` — always the constant `PLAN_WORKSPACE_PATH = "inputs/project/plan.md"` ("Where the document is readable in the agent's workspace on the next turn"; one leading `project/` segment is the folder name, not a directory under the prefix).
  - `replayed: bool` — `not inserted`. `True` both when the derived `document_id` already existed (the pre-render short-circuit) and when a concurrent twin of this exact call inserted the row first and the `ON CONFLICT … DO NOTHING` matched — "That is the same logical event as the replay short-circuit above and is reported the same way — the caller is never told it wrote a version it did not write." Also propagated to `ToolResult.replayed`.

  Caps/bounds, verbatim with constant names: `_PLAN_MAX_CHARS = 200_000`; `expected_version` `ge=1`; `source_turn_ref` `max_length=1_000`; `PLAN_PATH = "project/plan.md"`; `PLAN_FOLDER = "project"`; `PLAN_KIND = "project-plan"`; `PLAN_WORKSPACE_PATH = "inputs/project/plan.md"`; `PLAN_SOURCE_KEY = "arv2-project-plan"`; `USER_EDIT_SOURCE_KEY = "arv2-project-document-user_edit"`; `_DOCUMENT_MEDIA_TYPE = "text/markdown"`; `_SERVABLE_STATUSES: tuple[str, ...] = ("ready", "proposed", "confirmed")`; `_RETIRABLE_STATUSES: tuple[str, ...] = ("ready", "proposed")`; `_EDITABLE_KINDS: tuple[str, ...] = (PLAN_KIND, ICP_DEFINITION_KIND, PERSONA_KIND)`.

- **Side effects / what becomes true afterwards**:
  - One row inserted into **`brand_knowledge_document`** (`ON CONFLICT (document_id) DO NOTHING`) with `kind = 'project-plan'`, `folder = 'project'`, `path = 'project/plan.md'`, `project_id` = the presenting turn's project, `status = 'ready'` (the plan is born `ready`; **there is no confirmation gate for a plan**), `version`, `artifact_key`, `artifact_sha256`, `supersedes_document_id` = the previous servable row.
  - One artifact row recorded with `source_key = "arv2-project-plan"` (the human's editor writes `"arv2-project-document-user_edit"` instead, so "the agent's write and the human's edit are different acts and are told apart at the artifact, not only in the front matter"), `media_type = "text/markdown"`.
  - The rendered markdown bytes written to object storage **last**, after the row is at rest: "a refused write above leaves no unreferenced object behind, because its artifact row rolls back with the transaction."
  - Status transitions: when the insert actually landed, `_retire` moves every other `('ready', 'proposed')` row at this project's `project/plan.md` to `superseded`. A `confirmed` row is never retired.
  - The whole write takes the project lock (`_lock_project`) before reading `current_plan_version`, so the agent's write and the human's editor save serialize on one lock order.
  - **A card appears in chat** — but only if the agent asks for it. `model_description`: "Include {object_type: 'project_document', object_id: <document_id>, version: <version>} in your finalization's domain_refs so the plan card appears in the chat." `project_document` is one of the four `_PLAN_OBJECT_TYPES` (`conversation_turns.py:145-147`: `{"research_directive", "agent_plan", "plan", "project_document"}`) that render as a §3.4 `plan` part, and it is the one member with a name of its own: the card title is `"Plan"` and the revision label is `f"v{ref.version}"` rather than a bare ordinal, "because the human calls the document 'the plan', not 'the project document', and its version is a file revision they can see in the editor." An object type outside that closed set is **not** projected at all.
  - The new version is readable in the agent's workspace at `inputs/project/plan.md` **on the next turn** (`model_description`: "The new version appears in your workspace on the next turn."), and in the human's Plan tab.
  - No run is queued, nothing is confirmed, no pin moves.

- **Where the skill teaches it**: `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md` **§6b "Write the plan"** (lines 184–192; the call at line 190). Timing gate, verbatim: "Write it once — not before — the section 2 questions are answered, the ICP is confirmed and pinned (the index card names it) and the product set is confirmed. Never write a plan on the first turn of a project, and never write one the human has not discussed with you." Content shape and the `domain_refs` instruction are in the same section ("Include `{object_type: \"project_document\", object_id: <document_id>, version: <version>}` in `domain_refs` when you finalize, so the plan card appears in the chat and the Plan tab opens"), plus the update rule: "When the human changes course later … update the plan the same way and say what changed. Read `inputs/project/plan.md` before proposing anything that departs from it." Pinned in the skill front matter (lines 58-61) and granted at `head-of-abm/v49/profile.yaml:192-195`.

- **Source**: `platform/api/clue_api/project_document_tools.py:1-276` (whole file); `platform/api/clue_api/arv2/project_documents.py:1-140, 145-215, 245-300, 377-542`; `platform/toolbelt/clue_toolbelt/envelope.py:90-412`; `platform/api/clue_api/turn_binding.py:1-61`; `platform/api/clue_api/turn_action.py:180-209`; `platform/api/clue_api/toolbelt_wiring.py:121-123, 2663, 2837-2843`; `platform/api/clue_api/fleet_main.py:950-996`; `platform/api/clue_api/projections_main.py:147-166`; `platform/api/clue_api/conversation_turns.py:142-147, 465-486`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:58-61, 184-192`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:186-195`.

- **Discrepancy**:
  1. The declared `durable_identity` is `"presenting turn + document + expected version + body"`, but `plan_document_id` (`arv2/project_documents.py:191-210`) keys on `(turn_id, expected_version or 0, body_sha256)` only — `document` is **not** in the key. Harmless today because `document: Literal["plan"]` admits exactly one value, but the replay audit string names a coordinate the derivation does not use, and it would become wrong the moment a second document type is admitted.
  2. `expected_version or 0` collapses `None` and `0` to the same key component. Unreachable today because the field carries `ge=1`, so `0` cannot be supplied — but the collapse is in the id derivation rather than guarded by it.
  3. The `WriteProjectDocumentInput` docstring says "the path itself are derived from the presenting turn and the rows it names", while in practice the path is not derived at all: it is the hard-coded constant `PLAN_PATH = "project/plan.md"` for the single admissible `document` value.


---

## `record_interview_answer@1`

- **Address**: `record_interview_answer@1` — effect class `spend` (`effect_class = ToolEffectClass.SPEND`), replay policy `operation_idempotent` (`durable_identity="onboarding input + deterministic statement ids + RunId(operation_id)"`, `operation_id_required=True`, `external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE`), pin_requirements `("artifact_input", "stage0_skill", "memory_switch")`, opens a human gate: no.
- **Purpose**: Routes one captured user turn into durable Stage-0 records. The model does not carry the turn — the platform supplies the captured input id, its artifact key and its exact bytes — and the model supplies only a classification: a list of statements, each naming what species of record it is (`claim`, `memory`, `project_state`, `field_proposal`, `source_proposal`, `unmapped`), a short route key, and the verbatim quote from the user's message it rests on. Every statement's quote is located by exact substring search in the captured message, every claim's entity is resolved, and every claim value is proved against its own quote (by byte-substring for a text value, by the faithfulness/entailment judge for a typed one) *before* anything is written; a turn whose third statement fails records nothing at all.
- **Inputs** (`RecordInterviewAnswerInput`, `platform/api/clue_api/stage0_tools.py:355-405`; `ToolInput` base is `model_config = ConfigDict(frozen=True, extra="forbid")`):
  - `brand_id: str` (no default) — "Trusted brand authority; supplied by the platform, never by you."
  - `onboarding_input_id: str` (no default; `json_schema_extra={TRUSTED_TURN_FIELD: True}`, i.e. `{"clue_trusted_turn_field": True}` — stripped from the model-visible schema and injected at the execution seam) — "The onboarding input that captured this turn. Trusted turn authority: supplied by the platform from the captured turn, never by you. It must exist in this workspace and carry the same `artifact_key`."
  - `artifact_key: str` (no default; `json_schema_extra={TRUSTED_TURN_FIELD: True}`) — "Artifact key of that captured turn — the same key the onboarding input carries. Trusted turn authority: supplied by the platform, never by you."
  - `answer: str` (no default; `json_schema_extra={TRUSTED_TURN_FIELD: True}`) — "The captured user message, byte-identical. Trusted turn authority: the platform loads these exact bytes from the captured artifact and verifies their SHA-256 against the onboarding input's `content_sha256`, so there is nothing here for you to retype. Every statement's quote offsets index into this exact string."
  - `client_entity_id: str` (no default) — "Trusted client-entity authority; supplied by the platform, never by you."
  - `statements: list[InterviewStatement]` (no default) — "One statement per material fact, preference, or project decision in the answer, each carrying its own exact quote offsets. A turn with nothing material is routed as one `unmapped` statement — routing nothing is never the honest answer."
  - `product_id: str | None = None` — "Confirmed product this answer is about, when one exists."
  - `project_id: str | None = None` — "Trusted project authority; supplied by the platform, never by you."
  - Input-model docstring: "Route one captured turn. The model classifies; the platform supplies the turn itself. … `onboarding_input_id`, `artifact_key` and `answer` are trusted turn authority (PC-C8 §6a): they are stripped from the model-visible schema and served at the execution seam from the binding compiled off this turn's own artifact and capture record … They stay declared here because the C4 recipe path supplies them directly — only the *agent* surface loses them."
- **Nested input model** — `InterviewStatement` (`subsystems/research/clue_research/stage0/interview.py:65-244`; `model_config = ConfigDict(frozen=True, extra="forbid")`):
  - `route: InterviewRoute` (no default; `StrEnum` values `claim`, `memory`, `project_state`, `field_proposal`, `source_proposal`, `unmapped`) — "Which durable species this part of the answer is. `unmapped` is always legal and is the honest route when nothing else fits: it preserves the quote as evidence without asserting a fact."
  - `route_key: str` (no default) — "Short stable label for what this statement is about (the field key, preference topic, or project decision). Recorded verbatim on the durable statement."
  - `quote: str` (no default) — "The evidence span this statement rests on, copied exactly from the captured user message. Copy the span character-for-character out of the message — do not retype, tidy, re-punctuate, translate, or trim it. The platform searches the captured message for this exact text and records the offsets itself; a span that does not appear verbatim in that message is refused (`quote_not_found_verbatim`), and so is a blank one. There is no approximate matching: re-copy the span rather than paraphrasing it."
  - `occurrence: int = 1`, constraint `ge=1` — "Which occurrence of `quote` in the captured user message to lock onto, 1-based; the default 1 means the first. The evidence bytes are identical wherever the span repeats, so leave this out unless you specifically mean a later one."
  - `entity_id: EntityId | None = None` — "Which entity a `claim` is about. Leave it out for a fact about the client itself — an `account` claim defaults to this project's own client entity, which the platform supplies. Fill it only to name a *different* entity, and then it must already exist in this workspace; an id that resolves to nothing is refused. A `contact` claim always needs it."
  - `entity_type: EntityType | None = None` — "`account` or `contact`; required on the `claim` route. A `contact` claim additionally requires `identity_binding` and `use_class`."
  - `field_key: str | None = None` — "Already-registered field this claim writes; required on the `claim` route. A novel field goes through `propose_field` instead of being invented here."
  - `value: JsonValue | None = None` — "The claim's value; required on the `claim` route, and always evidence-locked to `quote`. A **text** value must appear verbatim inside that quote — quote rather than summarize, and narrow the quote to the words that state the fact instead of rewording them. A **typed** value (true/false, a number, a list) cannot appear verbatim in prose, so it is checked instead by an entailment judge reading the quote alone: it is admitted only if those exact user words support it, and refused otherwise. Either way the quote must actually state the fact — a typed value is not a way around the evidence lock."
  - `route_ref: str | None = None` — "Reference to the existing `propose_field` / `propose_source` proposal; required on the `field_proposal` and `source_proposal` routes."
  - `correction_of_statement_id: VolunteeredStatementId | None = None` — "Prior interview statement this one corrects, when the user restates or contradicts something already routed. Recorded as durable correction lineage."
  - `correction_of_claim_id: ClaimId | None = None` — "Prior claim this claim supersedes; refused unless that claim is in this workspace with the same entity and the same field key."
  - `memory_type: MemoryType | None = None` — "`preference` or `behavioral_learning`; required on the `memory` route. Memory is advisory and never becomes fact."
  - `memory_scope_type: MemoryScopeType | None = None` — "Scope level the memory attaches to; required on the `memory` route. Pick the narrowest scope the preference actually holds for."
  - `memory_scope_id: str | None = None` — "Identifier of that scope (product, project, or account id) when the memory scope is not workspace-wide."
  - `identity_binding: IdentityBinding | None = None` — "How strongly this personal claim is bound to that exact person; required, with `use_class`, on every `contact` claim."
  - `use_class: UseClass | None = None` — "Permitted use class of this personal claim; required, with `identity_binding`, on every `contact` claim. A true fact can still be unusable for outreach."
  - Model validator `_route_shape` (raises `ValueError`, i.e. schema-level rejection before any precondition runs): `"claim route requires entity_type, field_key, and value"`; `"contact claim route requires entity_id"`; `"memory route requires memory_type and memory_scope_type"`; `"proposal routes require the C2 proposal reference"` (for `field_proposal`/`source_proposal` with empty `route_ref`); `"contact interview claims require identity_binding and use_class"`.
  - Statement docstring (PC-C8 §6c-a): "the model quotes text, the engine computes offsets… `locate_quote` finds it by **exact substring search** over the captured answer the platform loaded… There is deliberately no fuzzy matching anywhere on this path."
- **Preconditions and refusal codes** (`RecordInterviewAnswerTool.preconditions`, `stage0_tools.py:1021-1082`; engine-side codes raised through `InterviewClaimEntityRefused` / `InterviewEvidenceRefused` and surfaced as `PreconditionFailure`):
  - `onboarding_input_not_found` — the ids are not parseable UUIDs. Message: "interview input or client entity is malformed". Guidance: no guidance in code (the ids are trusted turn/constitution authority the model never supplies).
  - `onboarding_input_not_found` — the captured input is absent/foreign, its `artifact_key` differs, the artifact is absent or cross-workspace, or `sha256(answer) != captured.content_sha256`. Message: "captured interview input does not exist in this workspace". Guidance: no guidance in code; the binding docstring says a turn whose artifact bytes, digest and capture record disagree "produces no binding" and the tool is refused rather than executed against unverified bytes.
  - `memory_not_configured` — a `memory`-route statement was supplied but neither `memory_write` nor `memory_write_factory` is composed. Message: "memory-routed interview statements require the MemoryWriteSeam". Guidance: no guidance in code; stage0-interview v26 §6 says "There is no memory route on this surface" and routes preferences/learnings as `project_state` instead.
  - `quote_not_found_verbatim` (`QUOTE_NOT_FOUND`) — the quote (or the requested `occurrence`) is not in the captured message. Message: "the quote {…} was not found in the captured user message: {it does not appear in that message | it appears only N time(s) there, so occurrence K does not exist}. Copy the span exactly from the message — character for character, no retyping, tidying, or re-punctuating." Guidance: re-copy the span; the skill's §6 rule is "When it is refused, copy it again rather than rewording it."
  - `interview_quote_empty` (`QUOTE_EMPTY`) — blank/whitespace-only quote. Message: "the evidence quote is blank; quote the user's actual words".
  - `claim_value_not_entailed` (`VALUE_NOT_ENTAILED`), text path — a JSON-string value is not a case-folded substring of its own quote. Message: "claim value is not textually entailed by the exact interview quote; quote the words that state the fact, or send the fact as a typed value".
  - `claim_value_not_entailed` (`VALUE_NOT_ENTAILED`), judge path — **the entailment/faithfulness-judge refusal**: a typed (non-string) value the judge did not support. Message: "the entailment judge read the quote alone and returned {verdict!r} for this typed claim value: those exact user words do not support it. Quote the sentence that actually states the fact, correct the value, or route the statement as `unmapped`". `verdict` is the judge's own label (`supported` / `partial` / `unsupported` / `contradicted`).
  - `claim_value_judge_unavailable` (`VALUE_JUDGE_UNAVAILABLE`) — the judge answered `verdict == "unavailable"`. Message: "the entailment judge could not be reached, so this typed claim value cannot be admitted; nothing was written — try again, or route the statement as `unmapped`". Note the R0 ruling in `check_claim_value_entailment`: when *no* judge is composed at all (`entailment_judge is None`) the typed value is admitted **unjudged** (born UNVERIFIED) rather than refused.
  - `interview_entity_required` — a non-`account` claim with no `entity_id` (defence in depth; the model validator already refuses it). Message: "a contact claim must name the contact it is about".
  - `interview_entity_not_found` — the named entity does not exist in this workspace. Message: "claim names {account|contact} {id}, which does not exist in this workspace". Guidance: the skill's §6 rule is "Never author an entity id."
  - `interview_entity_merged` — the named entity has `merged_into` set. Message: "claim names {account|contact} {id}, which was merged into {survivor}; use the surviving entity".
  - Non-precondition refusal, adjacent: `turn_binding_unavailable` — a *plan issue* (not a `PreconditionFailure`) raised at `agent_execution_wiring._resolve_captured_turn` when the execution carries no captured-turn binding, message "this execution carries no captured-turn binding, so the platform cannot supply the turn's captured input, artifact, or body" (`reason_code="no_binding"`; also `capture_not_found`, `capture_digest_mismatch` on the binder).
  - Mid-invoke `ValueError`s that are **not** typed refusals (they escape as errors, not model-visible precondition codes): "project-state interview statements require project_id"; "product-scoped client claim requires a human-confirmed project product"; "memory statement supplied without the MemoryWriteSeam"; "correction claim does not match this workspace, entity, and field".
- **Output** (`InterviewAnswerOutput`, `platform/api/clue_api/tool_outputs.py:281-287`; populated from `InterviewRoutingResult` in `invoke`):
  - `statement_ids: list[str]` — every durable `volunteered_statement` id written this call, one per input statement, in input order.
  - `claim_refs: list[str]` — claim ids written by `claim`-route statements.
  - `memory_refs: list[str]` — memory ids for accepted `memory`-route submissions (a rejected submission's `outcome` string is recorded on the statement's `route_ref` instead and does **not** appear here).
  - `project_state_refs: list[str]` — statement ids of `project_state`-route statements.
  - `proposal_refs: list[str]` — the `route_ref` (or statement id when absent) of `field_proposal`/`source_proposal` statements.
  - `unmapped_statement_ids: list[str]` — statement ids of `unmapped`-route statements.
  - Caps/bounds: none declared — no page size, no statement-count cap, no MAX_* constant on this path (searched `stage0_tools.py`, `interview.py`, `tool_outputs.py`). `InterviewRoutingResult` additionally carries `client_kb_version` / `product_kb_version`, which the tool's `references` does **not** return.
  - Cost estimate: `record_interview_answer` does not override `Tool.estimate`, so despite `effect_class = SPEND` its pre-spend estimate is `ToolEstimate.free()` (`cost_cents=Decimal(0)`).
- **Side effects / what becomes true afterwards**:
  - `volunteered_statement` — one append-only row per statement (`record_statement`, `governed.py:553`/`:582`), carrying route kind/key/ref, the located `quote_start`/`quote_end`, `correction_of_id`, actor, and the brand/product/project/client-entity spine.
  - `claim` — one claim per `claim`-route statement via `insert_claim` (or `supersede_claim` when `correction_of_claim_id` is set), id `uuid5(NAMESPACE_URL, "stage0-interview-claim:{onboarding_input_id}:{entity_id}:{field_key}")` so a replay is a no-op; `source_key` is `client_interview` (substring-admitted string values) or `client_interview_judged` (judge-admitted typed values), `source_tier` 1 for the client's own entity else 3, `extraction_method=HUMAN`, `confidence=1.0`, `reuse_scope=TENANT_PRIVATE`, `evidence_span` = the located quote, `source_url = interview://{onboarding_input_id}`.
  - `run_lineage` — `record_run_lineage(kind="stage0")` for `RunId(ctx.operation_id)` before any claim.
  - Client-KB checkpoints — `client_kb_write_target_for_materialization` allocates an append-only company target (`operation_key=f"interview:{onboarding_input_id}:company"`) and, for `PRODUCT_KNOWLEDGE_FIELDS`, a product target (`…:product:{product_id}`), inside the same transaction; the claims are stamped with that target's run id.
  - Memory — `memory_write.submit(MemorySubmission(...))` for `memory`-route statements (advisory scoped memory, `provenance_class=USER_STATED`, `trigger=f"stage0-interview:{onboarding_input_id}"`).
  - Source registry — `register_client_interview_source` registers/refreshes both `client_interview` and `client_interview_judged` manifests.
  - External boundary: the entailment judge is called (an LLM gateway call) once per typed claim value, content-address cached so the precondition pass and the engine pass ask one question.
  - In chat: nothing is written to the thread by the tool itself; the skill requires the agent to report the returned receipt ("Report receipts, never claim capture").
- **Where the skill teaches it**: stage0-interview v26 §6 ("Record in project context") — the tool is named as the only durable record path, with the route table, the seven authoring rules (copy the span, never send the message back, quote never summarize, never author an entity id, corrections carry lineage, a refusal is information) and the receipt-reporting rule; also listed in the skill's frontmatter `tools` pin (`record_interview_answer@1`, input sha `6e597a93…`, output sha `5f0e0fe7…`).
- **Source**: `platform/api/clue_api/stage0_tools.py:1-120,280-405,582-700,996-1120,1468-1504`; `subsystems/research/clue_research/stage0/interview.py:1-965`; `subsystems/research/clue_research/stage0/governed.py:553-600`; `platform/api/clue_api/tool_outputs.py:281-288`; `platform/api/clue_api/turn_binding.py:1-80`; `platform/api/clue_api/agent_execution_wiring.py:1280-1310,1380-1430`; `platform/api/clue_api/toolbelt_wiring.py:2950-2990`; `platform/toolbelt/clue_toolbelt/envelope.py:69-412`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:26-29,161-183`.
- **Discrepancy**: (1) `effect_class = ToolEffectClass.SPEND` but no `estimate()` override, so the pre-spend prior the UI shows is zero even though the tool can make one judge call per typed claim value. (2) The input model still declares `onboarding_input_id` / `artifact_key` / `answer` with descriptions addressed to the model ("It must exist in this workspace…"), while the agent surface never sees those fields — the docstring itself names the split (C4 recipe path vs agent path). (3) `InterviewStatement.occurrence`'s description says the offsets "index into this exact string" and the input `answer` description still speaks of "quote offsets", but since §6c-a the model supplies no offsets at all — the engine computes them. (4) The `memory` route is fully implemented in the tool, but stage0-interview v26 §6 states "There is no memory route on this surface"; a memory statement on a composition without the `MemoryWriteSeam` is refused `memory_not_configured`.


---

## `propose_field@2`

- **Address**: `propose_field@2` — effect class `write` (`effect_class = ToolEffectClass.WRITE`), replay policy `domain_idempotent` (`durable_identity="workspace + complete proposal scope + field key + immutable payload hash"`, `operation_id_required=False` (default), `external_boundary=ExternalReplayBoundary.NONE` (default)), pin_requirements `("proposal_policy", "brand", "field_registry")`, opens a human gate: no — but it *creates the thing a human decides*: the proposal is staged for `decide_field_proposal@2`, which is the human-authority tool (`insufficient_proposal_authority` unless an authenticated human principal calls it).
- **Purpose**: Stages a new field-registry definition as an immutable, scoped proposal instead of inventing a field mid-interview. The model describes the field it wants (key, value type, validation, corroboration/equality rules, rationale, evidence refs) plus — for the tenant-local `client.*` dynamic Client-KB namespace — the exact candidate value, the interview statement it came from, and explicit declarations of how authoritative the field would be. The proposal is written under the workspace/brand/product/project/ICP scope, its payload hashed so the same proposal replays to the same row, and its required authority computed from policy. `@2` is the version that may carry a `client.*` dynamic Client-KB proposal at all (`@1` refuses `dynamic_client_kb_requires_v2`); under the default policy a proposal lands `proposed` and waits for a human. A proposal grants no authority by itself.
- **Inputs** (`ProposeFieldInput`, `platform/api/clue_api/proposal_tools.py:95-105`; `ToolInput` base: `model_config = ConfigDict(frozen=True, extra="forbid")`):
  - `brand_id: str` (no default) — "Trusted brand authority; supplied by the platform, never by you."
  - `scope: ProposalScopeInput` (no default) — no field-level description in code.
  - `payload: FieldProposalPayload` (no default) — no field-level description in code.
  - `proposed_by_ref: str | None = None` — no description in code.
  - `project_id: str | None = None` — "Trusted project authority; supplied by the platform, never by you."
  - Model-facing description: no `model_description` set → descriptor default `"Invoke exact governed platform tool propose_field@2."`
- **Nested input model** — `ProposalScopeInput` (`proposal_tools.py:61-92`; `frozen=True, extra="forbid"`): docstring "The narrowing part of a proposal's scope: what the proposal is *about*. `brand_id` and `project_id` deliberately do **not** live here (PC-C8 task 1.4). They are `MODEL_FORBIDDEN_AUTHORITY_KEYS` — this execution's brand, this execution's project — and the strip/inject seam is top-level only, so a nested copy was neither hidden from the model nor served from the constitution."
  - `product_id: str | None = None` — no description in code.
  - `icp_key: str | None = None` — no description in code.
  - `icp_spec_version: int | None = Field(default=None, ge=1)` — no description in code.
  - Rejoined engine-side by `for_execution(workspace_id, brand_id, project_id)` into `ProposalScope`, whose validator raises `"icp_key and icp_spec_version must be supplied together"`.
- **Nested input model** — `FieldProposalPayload` (`subsystems/research/clue_research/proposals/models.py:92-160`; `frozen=True, extra="forbid"`): docstring "The complete field-registry write, staged immutably before promotion."
  - `field_def: FieldDef` (no default) — see below.
  - `value_schema: dict[str, JsonValue] | None = None` — no description in code.
  - `corroboration_min: int = Field(default=1, ge=1)` — no description.
  - `single_source_sufficient: bool = False` — no description.
  - `equality_mode: EqualityMode = EqualityMode.EXACT` — no description.
  - `description: str | None = None` — no description; required non-empty for `client.*` ("dynamic Client-KB fields require a semantic description").
  - `pack: str | None = None` — no description; must equal the namespace for a pack field, must be `"client"` for `client.*`, must be absent for canonical namespaces.
  - `version: int = Field(default=1, ge=1)` — no description.
  - `sensitive: bool = False` — no description; a sensitive field must declare `gate='outreach-disabled'` (constant `SENSITIVE_OUTREACH_DISABLED_GATE = "outreach-disabled"`).
  - `rationale: str` (required, no default) — no description.
  - `evidence_refs: tuple[str, ...] = ()` — no description; required non-empty for `client.*` and must contain `f"volunteered_statement:{client_kb.source_statement_id}"`.
  - `client_kb: ClientKbFieldSpec | None = None` — no description; required for `client.*`, forbidden otherwise ("client_kb proposal details are valid only for client.* fields").
  - Validator `_check_namespace_and_reuse` messages VERBATIM: `"pack field {key!r} must declare pack={namespace!r}"`; `"pack field {key!r} must explicitly declare reuse_scope"`; `"pack field {key!r} must explicitly declare research_scope"` (except namespace `client`); `"canonical field namespaces must not declare a pack"`; `"sensitive fields must declare gate='outreach-disabled'"`; `"client.kb_version is platform-owned internal vocabulary"`; `"dynamic Client-KB fields must declare pack='client'"`; `"dynamic Client-KB fields must declare reuse_scope=tenant_private"`; `"dynamic Client-KB fields require client_kb proposal details"`; `"dynamic Client-KB fields require a semantic description"`; `"dynamic Client-KB fields require durable evidence_refs"`; `"dynamic Client-KB evidence_refs must include the canonical volunteered_statement:<source_statement_id> ref"`; `"a non-expiring dynamic Client-KB field requires non_expiring_rationale"`; `"client_kb proposal details are valid only for client.* fields"`.
- **Nested input model** — `ClientKbFieldSpec` (`models.py:49-66`; `frozen=True, extra="forbid"`): docstring "Immutable materialization value and downstream-authority declarations."
  - `candidate_value: JsonValue` (required) — no description in code.
  - `source_statement_id: VolunteeredStatementId` (required) — no description; must name a live (non-corrected), same-scope `volunteered_statement`.
  - `intended_use: str = Field(min_length=1, max_length=1_000)` (required) — no description.
  - `client_kb_role: Literal["extended"] = "extended"` — the only legal value.
  - `non_expiring_rationale: str | None = Field(default=None, max_length=1_000)`.
  - `readiness_requested: bool = False`; `scoring_authoritative: bool = False`; `qualification_authoritative: bool = False`; `outreach_authoritative: bool = False`; `compliance_authoritative: bool = False`; `contains_personal_data: bool = False`; `introduces_new_source: bool = False`; `elevates_source_trust: bool = False` — each declaring a downstream authority; each `True` is a safe-auto disqualifier (reason codes below).
- **Nested input model** — `FieldDef` (`libs/clue-core/clue_core/field.py:151-200`; `frozen=True, extra="forbid"`): docstring "`field_definition` (substrate §1/§3): the per-field contract."
  - `field_key: FieldKey` (required); `value_type: str` (required) — comment: "declared value shape, e.g. \"int\" | \"str\" | \"enum:...\". (contract: `type`)"; `validation: dict[str, JsonValue] | None = None`; `tier_plan: tuple[str, ...] = ()` — "ordered resolver/source keys (1->...->4)"; `freshness_ttl: timedelta | None = None`; `pass_kind: PassKind` (required) — "(contract: `pass`) scoring vs deep"; `gate: str | None = None` — "gate expression, e.g. \"tier>=1\" | \"committee-gated\""; `signal_class: str | None = None`; `reuse_scope: ReuseScope | None = None` (None ⇒ class default; a PACK field must declare one); `research_scope: ResearchScope | None = None` (same rule; `client.*` exempt); `product_scope: SkipJsonSchema[ProductScopePolicy | None] = None` — deliberately **absent from the generated JSON schema**: "This is registry/storage policy, not model-authored proposal input. Keep it out of generated JSON schemas so adding the substrate invariant does not silently expand or repin agent tool authority."
- **Preconditions and refusal codes** (`ProposeFieldTool.preconditions`, `proposal_tools.py:195-215`):
  - `proposal_scope_not_found` — `scope_exists` failed for the rejoined workspace/brand/product/project/ICP tuple. Message: "proposal scope not found". Guidance: no guidance in code; the store helper's docstring is "Validate the complete object-spine scope without revealing which coordinate failed."
  - `dynamic_client_kb_materializer_not_configured` — a `client.*` field that *would* auto-promote (`client_field_mode is SAFE_AUTO_PROMOTE` and `evaluate_safe_client_field` eligible) in a process with no `DynamicClientKbMaterializer`. Message: "safe autonomous field promotion requires statement-evidence materialization". Guidance: no guidance in code.
  - `dynamic_client_kb_requires_v2` — **`@1` only** (`LegacyProposeFieldTool`), for any `client.*` key. Message: "tenant-local dynamic Client-KB proposals require propose_field@2". The Head-of-ABM grant is `@2`, so this is the version-selection tripwire, not a live refusal for this agent.
  - Non-precondition failures raised from `invoke` (they surface as errors, not typed refusals): `ProposalScopeError("proposal scope not found")` re-checked engine-side; `ClientFieldEvidenceRefused("dynamic Client-KB source statement is absent, superseded, or outside the proposal's trusted workspace/object-spine scope")`; `WorkspaceFieldDefinitionError("workspace field-registry scope does not exist")` and `WorkspaceDynamicClientKbErasedError(f"workspace {id!r} dynamic Client-KB has been erased")` from `assert_workspace_dynamic_client_kb_active`; `RuntimeError("dynamic Client-KB materializer is not configured")` if a promoted `client_kb` proposal reaches an unconfigured materializer.
- **Output** (`FieldProposalOutput`, `platform/api/clue_api/tool_outputs.py:220-229`; `invoke` always sets the first three and merges `MaterializedFieldRefs.model_dump(exclude_none=True)` when a `client.*` proposal auto-promoted and materialized):
  - `field_proposal_id: str` — the staged proposal row id.
  - `field_key: str` — `payload.field_def.field_key`, echoed back.
  - `status: str` — `ProposalStatus` value: `proposed` | `promoted` | `rejected` | `withdrawn`. Under `DEFAULT_PROPOSAL_POLICY` (`client_field_mode = ClientFieldPromotionMode.HUMAN_CONFIRM`) a `client.*` proposal lands `proposed`.
  - `materialization_id: str | None = None` — the field-materialization receipt id (only on the auto-promote path).
  - `materialization_status: str | None = None` — that receipt's status.
  - `claim_ref: str | None = None` — the claim written from the cited statement's quote, when materialization succeeded.
  - `client_kb_version: int | None = None` — the Client-KB version the materialized claim landed in.
  - `refusal_code: str | None = None` — a terminal materialization refusal, e.g. `statement_evidence_missing`, or the `InterviewEvidenceRefused.reason_code` (`claim_value_not_entailed`); `claim_value_judge_unavailable` deliberately leaves **no** receipt so the same operation can retry.
  - Caps/bounds VERBATIM, all on `ProposalPolicy` (`libs/clue-config/clue_config/proposals.py:22-57`), enforced through `evaluate_safe_client_field`: `max_client_field_schema_bytes: int = Field(default=4_096, ge=128, le=65_536)` (over-cap → reason `schema_over_cap`); `max_client_field_evidence_refs: int = Field(default=8, ge=1, le=64)` (over-cap → `too_many_evidence_refs`); `human_field_classes` default `frozenset({FieldClass.CONTACT, FieldClass.CONTACT_FACET})` (validator floor: "human_field_classes must include contact and contact.facet"); `client_field_mode: ClientFieldPromotionMode = ClientFieldPromotionMode.HUMAN_CONFIRM`; `client_field_policy_version: str = "dynamic-client-kb-v1"`; `safe_auto_client_field_contract_hashes: frozenset[str]` default empty — "The proposing model can describe sensitivity/authority, but it cannot add a hash to this set: only trusted configuration can pre-authorize the exact field meaning/schema/use contract for autonomous promotion." Safe-auto disqualifier reason codes (returned by `evaluate_safe_client_field`, not surfaced on the output): `not_dynamic_client_field`, `reuse_scope_not_tenant_private`, `not_supplemental_client_kb`, `semantic_contract_not_policy_approved`, `sensitive`, `personal_data`, `readiness_authority`, `scoring_authority`, `qualification_authority`, `outreach_authority`, `compliance_authority`, `scoring_pass`, `use_gate`, `signal_class_authority`, `new_source`, `trust_elevation`, `source_plan_requires_human`, `missing_evidence`, `too_many_evidence_refs`, `missing_value_schema`, `schema_over_cap`, `invalid_schema`, `candidate_schema_mismatch`.
- **Side effects / what becomes true afterwards**:
  - `field_definition_revision` — one append-only proposal row (workspace, brand, product, project, icp_key, icp_spec_version, field_key, payload_hash, payload_json, required_authority, proposed_by_actor, proposed_by_ref), inserted `ON CONFLICT ON CONSTRAINT field_definition_revision_dedupe DO NOTHING` — that dedupe is the domain-idempotent identity, so re-proposing the identical payload in the identical scope returns the existing row rather than a second one.
  - `required_authority` is computed at insert (`field_required_authority`): `HUMAN` for `client.*` unless safe-auto is on *and* the payload is eligible; `HUMAN` for a `sensitive` field or a field class in `human_field_classes`; otherwise `POLICY`. A global or workspace-local field-key collision forces `HUMAN` regardless.
  - For a `client.*` proposal the workspace row is locked `FOR KEY SHARE` and the erasure marker checked before anything is staged; the cited statement is verified live and in-scope.
  - Only on the safe-auto path (off by default): an immediate `decide_field_proposal(..., authority=POLICY, decided_by="policy:dynamic_client_kb", reason=f"{policy_version}:safe_auto_promote:eligible:contract={hash}")`, then `DynamicClientKbMaterializer.materialize` — which resolves the statement's quote from its artifact, re-runs the entailment check, and writes one claim plus one materialization receipt atomically (or a refusal receipt).
  - Nothing is queued and nothing appears in chat; the journal display allowlist is `("scope", "proposed_by_ref")`.
- **Where the skill teaches it**: stage0-interview v26 §6 ("Record in project context"), one line: "**A novel field or source** goes through `propose_field` or `propose_source`. A proposal grants no authority." Also pinned in the skill frontmatter `tools` (`propose_field@2`, input sha `381ff072…`, output sha `3250d58a…`). §6 additionally forbids the alternative in the `record_interview_answer` route table ("A novel field goes through `propose_field` instead of being invented here" is the statement model's own wording; the skill's version is "Guessing a field is the failure"). No section teaches the payload shape, the `client_kb` declarations, or what happens after a proposal is staged.
- **Source**: `platform/api/clue_api/proposal_tools.py:1-272,519-531`; `subsystems/research/clue_research/proposals/models.py:1-300`; `subsystems/research/clue_research/proposals/service.py:93-360`; `subsystems/research/clue_research/proposals/store.py:48-63,137-232`; `subsystems/research/clue_research/claimstore/registry.py:186-210`; `libs/clue-config/clue_config/proposals.py:1-63`; `libs/clue-core/clue_core/field.py:151-231`; `libs/clue-core/clue_core/proposals.py:29-39`; `platform/api/clue_api/dynamic_client_kb.py:32-137`; `platform/api/clue_api/tool_outputs.py:220-240`; `platform/api/clue_api/toolbelt_wiring.py:131-133,2886-2889`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:30-33,167`.
- **Discrepancy**: (1) The module docstring says "Integration registers these four tools centrally after C1→C2 lands. This module intentionally does not edit `build_toolbelt` or the shared router aggregation" — stale: `toolbelt_wiring.py:2886-2889` registers `ProposeFieldTool` as the default and `LegacyProposeFieldTool` as `@1`. (2) `ProposeFieldTool` is wired as `ProposeFieldTool(dynamic_client_kb_materializer=…)` with no `policy=`, so it always runs `DEFAULT_PROPOSAL_POLICY` — `client_field_mode=HUMAN_CONFIRM` and an empty `safe_auto_client_field_contract_hashes`, meaning the entire safe-auto path (and the `dynamic_client_kb_materializer_not_configured` precondition that guards it) is unreachable in the composed process. (3) Neither `scope` nor `payload` carries a model-facing description, so the tool's whole prose surface for a field proposal is the generated boilerplate plus pydantic validator messages — while the sibling authority fields (`brand_id`, `project_id`) do carry descriptions. (4) `FieldProposalOutput` declares `materialization_*`/`claim_ref`/`client_kb_version`/`refusal_code`, but on the default policy `invoke` never populates them.


---

## `propose_source@1`

- **Address**: `propose_source@1` — effect class `write` (`effect_class = ToolEffectClass.WRITE`), replay policy `domain_idempotent` (`durable_identity="workspace + complete proposal scope + source key + immutable payload hash"`, `operation_id_required=False` (default), `external_boundary=ExternalReplayBoundary.NONE` (default)), pin_requirements `("proposal_policy", "brand", "source_registry")`, opens a human gate: no — the decision tool `decide_source_proposal@1` is the human-authority one (`insufficient_proposal_authority` for a non-human principal), and it is the only place a trust tier is assigned. The class carries no explicit `version`, so it inherits `Tool.version = "1"`.
- **Purpose**: Stages a new research source (a provider, feed, registry or site the platform does not yet know) as an immutable, scoped proposal. The model describes the source's *capability* — its key, modality, entity scope, what field keys/classes it yields, cost, latency, geo coverage, credential reference, adapter requirement — plus a discovery URL that must match a declared discovery domain, a capability description, a rationale and evidence refs. It deliberately cannot describe the source's *trust*: `SourceManifestDraft` is "A source manifest without an assigned trust tier. The proposer describes capability. The decision service supplies `tier` under the authority matrix, so an agent-controlled payload can never award itself trust."
- **Inputs** (`ProposeSourceInput`, `platform/api/clue_api/proposal_tools.py:114-124`; `ToolInput` base: `model_config = ConfigDict(frozen=True, extra="forbid")`):
  - `brand_id: str` (no default) — "Trusted brand authority; supplied by the platform, never by you."
  - `scope: ProposalScopeInput` (no default) — no field-level description in code.
  - `payload: SourceProposalPayload` (no default) — no field-level description in code.
  - `proposed_by_ref: str | None = None` — no description in code.
  - `project_id: str | None = None` — "Trusted project authority; supplied by the platform, never by you."
  - Model-facing description: no `model_description` set → descriptor default `"Invoke exact governed platform tool propose_source@1."`
- **Nested input model** — `ProposalScopeInput` (`proposal_tools.py:61-92`; `frozen=True, extra="forbid"`), identical to `propose_field`'s: docstring "The narrowing part of a proposal's scope: what the proposal is *about*. `brand_id` and `project_id` deliberately do **not** live here (PC-C8 task 1.4). They are `MODEL_FORBIDDEN_AUTHORITY_KEYS` … Hoisting them onto the tool input … means there is no nested authority left to strip: the invalid state is unrepresentable instead of defended against."
  - `product_id: str | None = None` — no description in code.
  - `icp_key: str | None = None` — no description in code.
  - `icp_spec_version: int | None = Field(default=None, ge=1)` — no description in code.
  - Rejoined engine-side into `ProposalScope` (validator: "icp_key and icp_spec_version must be supplied together").
- **Nested input model** — `SourceProposalPayload` (`subsystems/research/clue_research/proposals/models.py:215-238`; `frozen=True, extra="forbid"`; no class docstring):
  - `manifest: SourceManifestDraft` (required) — no description in code.
  - `discovery_url: str` (required) — no description; validated jointly (below).
  - `discovery_domain: str` (required) — no description.
  - `capability_description: str` (required) — no description.
  - `rationale: str` (required) — no description.
  - `evidence_refs: tuple[str, ...] = ()` — no description.
  - Validator `_check_discovery_target` messages VERBATIM: `"discovery_url must not contain credentials"` (a URL carrying username/password); `"discovery_url must match discovery_domain"` (normalized hosts must be non-empty and equal).
- **Nested input model** — `SourceManifestDraft` (`models.py:163-212`; `frozen=True, extra="forbid"`): docstring "A source manifest without an assigned trust tier. The proposer describes capability. The decision service supplies `tier` under the authority matrix, so an agent-controlled payload can never award itself trust."
  - `source_key: str` (required), validator `_source_key_shape` against `_SOURCE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")` → `"source_key must be a lowercase identifier"`.
  - `modality: Modality` (required) — no description.
  - `entity_scope: EntityScope` (required) — no description.
  - `yields: tuple[str, ...] = ()`, validator `_yield_shapes` (each entry must satisfy `is_field_key_or_class`) → `f"invalid source yields: {invalid}"`.
  - `cost_cents: CostCents = Decimal(0)` — no description.
  - `latency_ms: int | None = Field(default=None, ge=0)`.
  - `geo_coverage: tuple[str, ...] = ()`.
  - `freshness_profile: str | None = None`.
  - `identity_binding_strength: IdentityBinding | None = None`.
  - `active: bool = True`.
  - `provider: str | None = None`.
  - `auth_ref: str | None = None`, validator `_auth_ref_shape` against `_AUTH_REF_RE = re.compile(r"^CLUE_[A-Z][A-Z0-9_]*$")` → `"auth_ref must be a CLUE_* credential reference, never a secret"`.
  - `rate_limit: dict[str, JsonValue] | None = None`.
  - `requires_adapter: str | None = None`.
  - `version: int = Field(default=1, ge=1)`.
  - **No `tier` field** — it is absent by design (see the class docstring); tier is assigned only at decision time, `ge=1, le=4` on `DecideSourceProposalInput.assigned_tier`.
- **Preconditions and refusal codes** (`ProposeSourceTool.preconditions`, `proposal_tools.py:406-414`):
  - `proposal_scope_not_found` — `scope_exists` failed for the rejoined workspace/brand/product/project/ICP tuple (brand must exist in the workspace; a named product must belong to that brand; a named project must belong to that brand and match the product; a named `icp_key`+`version` must exist). Message: "proposal scope not found". Guidance: no guidance in code; the store helper's docstring is "Validate the complete object-spine scope without revealing which coordinate failed."
  - That is the tool's only precondition. Everything else is schema-level (the validators above) or engine-raised from `invoke`: `ProposalScopeError("proposal scope not found")`.
  - Downstream (the human decision tool, for context, `proposal_tools.py:443-488`): `insufficient_proposal_authority` ("source proposal decisions require authenticated human authority"), `proposal_not_found` ("no such source proposal"), `assigned_tier_required` ("source promotion requires a policy/human-assigned tier"), `credential_setup_required` ("credentialed source promotion requires confirmed administrator setup"), `compliance_approval_required` ("personal-data source promotion requires compliance-policy approval").
- **Output** (`SourceProposalOutput`, `platform/api/clue_api/tool_outputs.py:242-245`):
  - `source_proposal_id: str` — the staged proposal row id.
  - `source_key: str` — `payload.manifest.source_key`, echoed back.
  - `status: str` — `ProposalStatus` value: `proposed` | `promoted` | `rejected` | `withdrawn`. Under `DEFAULT_PROPOSAL_POLICY` (`auto_promote_tier3_sources: bool = False`) a new proposal lands `proposed`; `promoted` is reachable only when that flag is on *and* `required_authority is POLICY`, in which case the engine self-decides with `reason="policy auto-promotion of an audited public tier-3 source"`, `decided_by="policy:proposal_auto_promote"`, `assigned_tier=3`.
  - Caps/bounds VERBATIM, all on `ProposalPolicy` (`libs/clue-config/clue_config/proposals.py:22-57`): `auto_promote_tier3_sources: bool = False`; `human_source_tiers: frozenset[int] = Field(default_factory=lambda: frozenset({1, 2}))` with validator floors "human_source_tiers must include tiers 1 and 2" and "human_source_tiers entries must be in 1..4"; `min_observations_for_yield: int = Field(default=10, ge=1)` and `demotion_yield_floor: float = Field(default=0.1, ge=0.0, le=1.0)` (the later yield-demotion path, not this tool). No page size, reference budget or section cap exists on this tool.
  - Authority rule (`source_required_authority`, `service.py:233-236`): `HUMAN` when `manifest.auth_ref is not None` **or** `source_yields_personal_data(payload)` (any yield token equal to `contact` / `contact.facet` or prefixed `contact.`); otherwise `POLICY`.
- **Side effects / what becomes true afterwards**:
  - `source_manifest_revision` — one append-only proposal row carrying the scope, the immutable payload JSON, its `payload_hash`, the computed `required_authority`, the proposing actor (`ctx.actor`) and `proposed_by_ref`; inserted with the same dedupe-on-conflict shape as the field proposal, which is the domain-idempotent identity (an identical payload in an identical scope returns the existing row).
  - No source is registered and no research runs: the source registry itself is written only when `decide_source_proposal` promotes with a human/policy-assigned tier.
  - No job is queued, no claim is written, nothing appears in chat. The journal display allowlist is `("scope", "proposed_by_ref")`.
- **Where the skill teaches it**: stage0-interview v26 §6 ("Record in project context"), one line, shared with the field proposal: "**A novel field or source** goes through `propose_field` or `propose_source`. A proposal grants no authority." Also pinned in the skill frontmatter `tools` (`propose_source@1`, input sha `64125234…`, output sha `708d9b50…`). No section teaches the manifest shape, the discovery-URL rule, or that tier is not the model's to declare.
- **Source**: `platform/api/clue_api/proposal_tools.py:1-58,61-135,138-178,392-435,438-488,519-531`; `subsystems/research/clue_research/proposals/models.py:43-47,163-238,246-268,289-300`; `subsystems/research/clue_research/proposals/service.py:233-246,417-452`; `subsystems/research/clue_research/proposals/store.py:48-63,137-186,282`; `libs/clue-config/clue_config/proposals.py:1-63`; `libs/clue-core/clue_core/proposals.py:29-39`; `platform/api/clue_api/tool_outputs.py:242-252`; `platform/api/clue_api/toolbelt_wiring.py:131-133,2905`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:34-37,167`.
- **Discrepancy**: (1) The module docstring ("Integration registers these four tools centrally after C1→C2 lands. This module intentionally does not edit `build_toolbelt` …") is stale — `toolbelt_wiring.py:2905` registers `ProposeSourceTool()` as the default. (2) `ProposeSourceTool()` is constructed with no `policy=`, so it always runs `DEFAULT_PROPOSAL_POLICY`; with `auto_promote_tier3_sources=False` the auto-promote branch in `propose_source` is unreachable in the composed process and every proposal lands `proposed`. (3) Neither `scope` nor `payload` carries a model-facing description, so the only prose the model sees is the generated boilerplate plus validator messages — including the one rule it is most likely to break (tier is not proposable, which is stated only in a Python docstring the model never reads).


---

## `submit_ingestion@1`

- **Address**: `submit_ingestion@1` — effect class `spend` (`effect_class = ToolEffectClass.SPEND`), replay policy `at_least_once` (`durable_identity="workspace + artifact content hash + declared material-context hash"`, `operation_id_required=False` (default), `external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE`), pin_requirements `("artifact_input", "ingestion_policy", "brand")`, opens a human gate: no.
- **Purpose**: Hands a document already captured in this workspace to the C3 ingestion engine so its contents can become durable records, and tells the engine what the document *is*. The bytes are captured separately (the `/ingestion/uploads` transport content-addresses them first); this tool takes the resulting `artifact_key` plus a declared material context — which product it concerns, what kind of material it is, and optionally the exact typed targets (entity + field) an extractor may fill from it — and creates or replays the ingestion job. It returns the job reference and status, never extracted content. Job creation is content-addressed, so re-submitting the same artifact with the same declared context returns the same job rather than a second one.
- **Inputs** (`SubmitIngestionInput`, `platform/api/clue_api/ingestion_tools.py:118-127`; `ToolInput` base: `model_config = ConfigDict(frozen=True, extra="forbid")`):
  - `artifact_key: str` (no default) — no field description in code (searched `ingestion_tools.py:118-127`).
  - `brand_id: str` (no default) — "Trusted brand authority; supplied by the platform, never by you."
  - `declared_context: DeclaredMaterialInput` (no default) — no field description in code.
  - `project_id: str | None = None` — "Trusted project authority; supplied by the platform, never by you."
  - Model-facing description: no `model_description` set → descriptor default `"Invoke exact governed platform tool submit_ingestion@1."` The tool class docstring is `"""Reason codes: ``ingestion_artifact_not_found``, ``ingestion_artifact_erased``."""`
- **Nested input model** — `DeclaredMaterialInput` (`ingestion_tools.py:74-115`; `frozen=True, extra="forbid"`): docstring "The caller-authored part of a declared material context: what the document *is*. The domain model (`DeclaredMaterialContext`) also carries `brand_id`/`project_id`, which are `MODEL_FORBIDDEN_AUTHORITY_KEYS` — this execution's brand and project. The strip/inject seam is top-level only, so while they lived here the model both saw and authored them (PC-C8 task 1.4). They are hoisted onto `SubmitIngestionInput` instead, where the existing seam hides and serves them; this model is the remainder, and the domain context is rejoined engine-side by `for_execution`. The durable idempotency key is unchanged — it hashes the *composed* domain context, whose shape and values are the same as before."
  - `product_id: str | None = None` — no description in code.
  - `targets: tuple[IngestionTarget, ...] = ()` — no description in code.
  - `document_context: MaterialContext = MaterialContext.UNKNOWN` — no description in code. `MaterialContext` values: `client_about_self`, `client_about_product`, `client_about_target`, `client_preference`, `project_instruction`, `unknown`.
- **Nested input model** — `IngestionTarget` (`subsystems/research/clue_research/ingestion/models.py:45-55`; `frozen=True, extra="forbid"`): docstring "One typed field the shared ClaimExtractor may extract from the document."
  - `entity_id: EntityId` (required) — no description in code.
  - `entity_type: EntityType` (required) — no description in code.
  - `field_key: FieldKey` (required) — no description in code.
  - `material_context: MaterialContext` (required) — no description in code.
  - `use_class: UseClass | None = None` — no description in code.
  - `manifest_identity_binding: IdentityBinding | None = None` — no description in code.
- **Rejoined domain model** (engine-side, from `for_execution(brand_id, project_id)`) — `DeclaredMaterialContext` (`models.py:58-78`): docstring "Caller-declared scope. It contributes to the durable idempotency key." Fields `brand_id: str`, `product_id: str | None = None`, `project_id: str | None = None`, `targets: tuple[IngestionTarget, ...] = ()`, `document_context: MaterialContext = MaterialContext.UNKNOWN`; validator `_validate_routes` messages VERBATIM: `"project_instruction material requires project_id"`; `"client_about_product material requires product_id"`.
- **Preconditions and refusal codes** (`SubmitIngestionTool.preconditions`, `ingestion_tools.py:167-213`, in evaluation order):
  - `ingestion_artifact_not_found` — the artifact key resolves to nothing, or to an artifact in another workspace. Message: "captured artifact does not exist in this workspace". Guidance: no guidance in code; the skill's §6 line is "**An upload** already captured in the workspace goes through `submit_ingestion` with its material context."
  - `ingestion_artifact_erased` — `artifact.erased_at is not None`. Message: "captured artifact has been erased; upload it again before ingestion". Guidance: as stated in the message — re-upload first.
  - `ingestion_not_configured` — no `IngestionEngine` was injected at the API composition root. Message: "the ingestion engine is not configured at the API composition root". Wiring comment: "The two ingestion tools are always registered; without an engine they fail closed with `ingestion_not_configured` after proving the referenced job/artifact."
  - `ingestion_context_invalid` — the rejoined `DeclaredMaterialContext` fails its own route rules (a `project_instruction` document with no project, a `client_about_product` document with no product). Message: "declared material context is not valid for this execution's brand and project". Inline rationale: "The domain context's own route rules … now bind across the hoisted authority and the declared remainder, so they are reported as a typed refusal here rather than as a bare validation error thrown from the middle of a spend path."
  - Engine-side `IngestionError` codes raised from `invoke` (not `PreconditionFailure`s; the HTTP transport maps them to 422 with `{"error": <code>, "message": <detail>}`): `artifact_not_found` ("captured artifact does not exist"), `artifact_erased` ("captured artifact has been erased"), `artifact_scope_mismatch` ("captured artifact is absent from this workspace"), `size_limit_exceeded` ("captured artifact exceeds the configured byte limit"), `unsupported_media_type` ("captured artifact media type is not allowed" / "no document adapter is registered for this media type"), `ocr_disabled` (same adapter path when the media type is `image/*` and `ocr_enabled` is false), `invalid_context` ("declared brand is absent from this workspace" / "declared product is absent from the selected brand/workspace" / "declared project is absent from the selected brand/workspace" / "declared product does not match the project's selected product" / "ingestion job disappeared"). The full `IngestionFailureCode` enum additionally carries `gate_blocked`, `adapter_failed`, `segment_limit_exceeded`, `extraction_failed`, `retry_limit_exceeded` for the drive/extraction phase.
- **Output** (`IngestionSubmitOutput`, `platform/api/clue_api/tool_outputs.py:254-258`):
  - `ingestion_job_id: str` — the durable `IngestionJobId` created or replayed.
  - `artifact_key: str` — the captured artifact this job is bound to.
  - `status: str` — an `IngestionStatus` value (`libs/clue-core/clue_core/ingestion.py:27-35`): `queued`, `snapshotted`, `extracting`, `completed`, `failed`, `erased`. A job already in `completed`/`erased`/`failed` is returned as-is without re-driving; a media type with no registered adapter is failed and returned `failed`; otherwise the engine drives the job and returns its post-drive status.
  - Caps/bounds VERBATIM, all on `IngestionPolicy` (`libs/clue-config/clue_config/ingestion.py:26-36`, "Absolute upload and execution ceilings for C3"; module note: "The policy is injected into the engine. Prompt/tool inputs cannot raise these ceilings."): `max_bytes: int = Field(default=25 * 1024 * 1024, ge=1)`; `allowed_media_types: frozenset[str] = DEFAULT_INGESTION_MEDIA_TYPES` = `{"text/plain", "text/markdown", "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "image/png", "image/jpeg", "image/webp", "image/tiff"}`; `max_segments: int = Field(default=2_000, ge=1)`; `max_retries: int = Field(default=3, ge=0)`; `ocr_enabled: bool = True`. No page size or reference budget applies — the result is three references, never the extracted body (`IngestionResultRefs` — "Durable reference-only outputs. No extracted body is stored here" — carries `claims`, `proposals`, `memory`, `project_state`, `unmapped_segments` on the job row, not on this tool's output).
- **Side effects / what becomes true afterwards**:
  - One ingestion job row via `create_or_get_job` (workspace, brand, product, project, artifact_key, `content_sha256`, the full `declared_context`, the resolved `adapter_key`, actor) — content-addressed on workspace + artifact content hash + declared-context hash, so a replay returns the existing job.
  - The job insert takes the artifact FK key-lock, which serializes against DSAR's artifact lock; the artifact is re-read after insert so an erasure that won the race rolls the transaction back instead of creating a job over erased bytes.
  - The engine then drives the job (`_drive`): snapshot → adapter extraction → governed routing, moving it through `snapshotted`/`extracting` to `completed` or `failed`, and producing the durable reference sets on the job (claims, proposals, memory, project-state, unmapped segments). That drive is the spend and the at-least-once external boundary; `retry_ingestion@1` re-drives a job in `failed`/`snapshotted`/`extracting` (its own refusals: `ingestion_not_found`, `ingestion_not_configured`, `ingestion_not_retryable` — "ingestion job in status {status!r} is not retryable").
  - A media type with no registered adapter writes a terminal failure on the job (`fail_job`, detail "no document adapter is registered for this media type") rather than raising.
  - Nothing is written to chat by the tool; the journal display allowlist is `("artifact_key", "declared_context")` — `brand_id`/`project_id` are deliberately excluded because "a journal display summarises what the *caller* chose, and trusted scope authority is not chosen — it is injected from the constitution."
- **Where the skill teaches it**: stage0-interview v26 §6 ("Record in project context"), one line: "**An upload** already captured in the workspace goes through `submit_ingestion` with its material context." Also pinned in the skill frontmatter `tools` (`submit_ingestion@1`, input sha `9b0a3d6c…`, output sha `8e2acc7a…`). No section teaches the `MaterialContext` values, the typed `targets`, or what the returned status means.
- **Source**: `platform/api/clue_api/ingestion_tools.py:1-236,239-306,309-331,345-473`; `subsystems/research/clue_research/ingestion/models.py:21-103`; `subsystems/research/clue_research/ingestion/engine.py:142-204,206-212,579-599,600-671`; `libs/clue-core/clue_core/ingestion.py:27-45`; `libs/clue-config/clue_config/ingestion.py:1-38`; `platform/api/clue_api/tool_outputs.py:254-263`; `platform/api/clue_api/toolbelt_wiring.py:112,2704-2707,2913-2914`; `platform/toolbelt/clue_toolbelt/envelope.py:93-220`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:38-41,168`.
- **Discrepancy**: (1) The module docstring says "Central registration is intentionally absent: the C0 treaty assigns that one-line composition to the Phase-C integration branch" — stale: `toolbelt_wiring.py:2913-2914` registers both `SubmitIngestionTool(ingestion_engine)` and `RetryIngestionTool(ingestion_engine)` as defaults. (2) The class docstring lists only two reason codes ("`ingestion_artifact_not_found`, `ingestion_artifact_erased`") while `preconditions` returns four — `ingestion_not_configured` and `ingestion_context_invalid` are undocumented there. (3) `artifact_key`, `declared_context` and every field of `DeclaredMaterialInput`/`IngestionTarget` are description-free, so a model calling this tool is told nothing about where an artifact key comes from or which `document_context` value to pick; only the two trusted-authority fields carry prose. (4) `preconditions` proves the artifact is present and un-erased, then `invoke` re-proves it inside the engine with a different failure species (typed `PreconditionFailure` vs raised `IngestionError`), so the same condition surfaces two different ways depending on which check wins the race.


---

# Part 5 — Delegating and directing


---

## `open_design_leg@4`

- **Address**: `open_design_leg@4` — effect class `write` (`ToolEffectClass.WRITE`), replay policy `domain_idempotent` (`durable_identity="one design leg per delegating turn (leg id derived from the turn), and one born document per leg (document id derived from the leg) — both in one transaction"`, `operation_id_required=False` — the dataclass default, `external_boundary=ExternalReplayBoundary.NONE`), pin_requirements `("project",)`, opens a human gate: **no**. It is a *delegation*, not an approval: it hands the thread to the design deepagent. Comment on `pin_requirements`: *"The leg is anchored to one project (through its thread); the C5 step pins that project… The design-side pins (document CAS guard, brand-kit version) are validated by the tool itself against durable design rows — they have no platform pin kind, and inventing one here would fork the design substrate's own versioning."* Journal policy: `JournalParameterPolicy(safe_display_fields=("document_id", "doc_kind", "expected_document_version", "brand_kit_id", "brand_kit_version"))`. `estimate()` is `ToolEstimate.free()` (*"Opening a leg is free — the spend happens inside governed design turns, later."*). Registered unconditionally and as the default for its name (`toolbelt_wiring.py:3099-3103`, `build_design_leg_tools(conn_factory=…, storage=storage, enabled=resolved_settings.design_runtime_enabled)`); the registration is unconditional *"for the same audit reason"* (the C6 authority audit is strict set equality) while liveness is gated on `CLUE_DESIGN_RUNTIME_ENABLED` — a disabled deployment refuses `design_leg_runtime_not_configured` before any write, and a storage-less one refuses `design_leg_storage_not_configured`.

- **Purpose**: Hand this conversation to the design deepagent — the only way a website, ad, or any designed artifact gets made. The call validates the pins, freezes a §2.3 delegation bundle as one immutable canonical-JSON artifact, optionally *births* the document the work will land in, and inserts the `design_leg` row whose existence **is** the routing rule ("an open leg on the thread receives the user's message"). It dispatches nothing: *"Opening a leg spends nothing and runs no design turn; the agent's next act is to tell the user the design session is open and end its turn. The user's next message on the thread is what becomes the first design turn."*

  Its `model_description` (long, model-facing) says in full: *"Hand this conversation to the design deepagent — the only way to get a website (or any design artifact) made. Use it the moment the user asks for a landing page, microsite, or page to be built or changed. For a NEW website pass doc_kind='web' and no document_id: an empty web document is created and the leg is pinned to it, so the artifact appears in the project's gallery immediately. Pass title as the name the user would recognise ("Insight Health landing page"); omitted, it is taken from the brief. Put the user's actual ask in brief — what the page is for, who it is for, what it must say — because Design sees the brief, not this conversation. To keep working on an EXISTING artifact pass its document_id instead (doc_kind is then ignored). For a NEW ad or any designed page pass doc_kind='scene' and no document_id: an empty design document is created (no page yet) and the design agent authors the page itself — size, unit (px for digital, mm/in for print) and layout come from the user's own words, so put everything the user said about format, dimensions, medium and purpose in brief. Do not infer or restate dimensions yourself; Design owns them. To resume a design session you closed by mistake, pass reopen_leg_id — a reopen ignores every other field. While the leg is open, every user message on this thread goes directly to Design — you will not see the thread again until the leg closes. Opening a leg spends nothing and runs no design turn: the user's NEXT message is what starts generation, and generating a page takes minutes, not seconds. Tell the user the design session is open and end your turn."*

  **What @4 deleted relative to @3**: the `ad_format` / `ad_width` / `ad_height` parameters are **gone** from `OpenDesignLegInput`, and with them @3's format refusals (`design_leg_ad_format_required`, `design_leg_ad_format_invalid` — both now only mentioned in the historical paragraph of the module docstring, neither raised anywhere in the file). @3 required a format on a document-less `doc_kind="scene"` open (one of the ratified presets, or `custom` with explicit px dimensions) and minted an artboard; @4 births a **zero-page** scene instead — one `new_scene` call, `medium="ad"`, no artifact type, `pages == {}`. Module docstring: *"the founder reversed their *format* half the same week. The platform must not own page geometry at all — not a preset table, not a unit, not an artboard… (`ToolInput` forbids extras, so an agent still sending one gets a loud validation refusal rather than a silently dropped belief)… The design deepagent authors the page itself in a later turn, at the size and unit the user's own words imply (``size(w,h,px|pt|mm|in)`` in its DSL, normalized by the engine), which is the only place that knowledge honestly lives."* Everything else — one document per leg, one transaction, brand decided at birth and only read back — is unchanged from @3, which is unchanged from the web path. The profile grant records the same: *"only the input digest moves (the output shape is unchanged)."*

- **Inputs**: input model `OpenDesignLegInput` (docstring: *"What the agent proposes; every authority value is derived by the engine, not accepted."*; `ToolInput` ⇒ `frozen`, `extra="forbid"` — so any leftover `ad_format`/`ad_width`/`ad_height` is a loud `ValidationError`).

  - `source_turn_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]` — `Field(json_schema_extra={TRUSTED_TURN_FIELD: True})`. **Stripped from the model-visible schema**, injected at the execution seam. Module docstring: *"The leg's anchor is not the agent's choice. The leg is derived from the turn the agent is answering… One presenting turn derives one leg id, so a replayed delegation converges on the same leg instead of racing the partial-unique index."*
  - `brief: str` — `Field(min_length=1, max_length=16_000)`. Comment: *"The design brief — what the user wants made. Free text (D5: no fabricated content plane)."*
  - `document_id: str | None = None` — `Field(default=None, min_length=1, max_length=200)`. Comment: *"Target document (nullable — a leg may create its document, §2.1)."*
  - `doc_kind: Literal["web", "scene"] | None = None` — `Field(default=None)`. Comment: *"What to create when there is no ``document_id`` — REQUIRED on a document-less open. ``web`` births one empty website-mode document; ``scene`` births one empty, PAGELESS design document (genad2 ruling 1, 2026-08-23 — @3 took an ``ad_format`` and minted an artboard; the design deepagent owns page geometry now). With a ``document_id`` present the durable row's own kind is the truth and this field is ignored."*
  - `title: str | None = None` — `Field(default=None, min_length=1, max_length=200)`. Comment: *"The born document's title (F5). Absent ⇒ the brief's first ~8 words. Ignored when the leg pins an existing document — a delegation never renames someone else's artifact."* (`DESIGN_LEG_TITLE_WORD_BUDGET = 8`; a whitespace-only brief with no title falls back to `_FALLBACK_DOCUMENT_TITLE = "Untitled page"`, because *"``design_document.title`` is NOT NULL, and an empty string is not a title"*.)
  - `expected_document_version: int | None = None` — `Field(default=None, ge=0)`. Comment: *"The document version the agent believes is current. When present it must match the durable ``current_version`` exactly (the D5 CAS guard); when absent the current version is pinned."*
  - `brand_kit_id: str | None = None` — `Field(default=None, min_length=1, max_length=200)`. Comment above the pair: *"The D5 fail-closed brand pin — both fields or neither."*
  - `brand_kit_version: int | None = None` — `Field(default=None, ge=1)`.
  - `claim_refs: tuple[ContactHandoffClaimRef, ...] = ()` — `Field(default=(), max_length=200)`. Comment: *"Governed claim edges (ids + stamps, never values) — the C8 §2.3 vocabulary."*
  - `binding_set_ref: str | None = None` — `Field(default=None, min_length=1, max_length=500)`. Comment above the pair: *"Design's real content vocabulary, both nullable (ruling D5a)."*
  - `template_revision_ref: str | None = None` — `Field(default=None, min_length=1, max_length=500)`.
  - `reopen_leg_id: str | None = None` — `Field(default=None, min_length=1, max_length=64)`. Comment: *"The §2.2 mis-exit recovery: re-delegation NAMES the closed leg to reopen it. The same leg returns ``open_awaiting_user`` with its original bundle and history — context resumes, and the exit journal record survives. When present, the pin/bundle fields above are ignored: a reopen is a resumption, not a fresh delegation."*

  The input model declares **no** model validators ("not found in code"; looked at `OpenDesignLegInput` in `design_leg_tools.py:229-266` — all cross-field rules live in `_resolve` as typed refusals).

  **Nested — `ContactHandoffClaimRef`** (`clue_core.contact_handoff`, `frozen`, `extra="forbid"`; docstring: *"One governed claim edge. Values and evidence bodies stay behind the claim id."*):

  - `claim_id: ClaimId`
  - `field_key: FieldKey`
  - `kind: ContactHandoffClaimKind`
  - `support_claim_ids: tuple[ClaimId, ...] = ()`
  - `identity_binding: IdentityBinding | None = None`
  - `use_class: UseClass | None = None`
  - `use_decision: UseDecision | None = None`
  - `conflict: ResearchConflictState = ResearchConflictState.NONE`
  - `_is_safe_for_its_declared_use` validator, verbatim messages: `"raw contact-channel claims cannot enter the drafting handoff"`; `"handoff support claim ids must be unique"`; `"a handoff claim cannot support itself"`; `"role refs require contact.role_on_committee"`; `"persona refs require contact.persona"`; `"professional refs require a registered professional field"`; `"value-narrative refs require account.value_narrative"`; `"contact.facet.* and personal_facet kind must agree"`; `"personalized facets require strong identity binding"`; `"personalized facets require an allowed exact-claim use decision"`; `"sensitive or unclassified facets cannot enter drafting"`; `"a use decision must refer to the same claim"`. Module docstring on how the agent may legitimately hold these at all: *"the only way a head-of-abm holds claim ids at all is by having read them through ``get_research_view``."*

- **Preconditions and refusal codes**: `preconditions()` runs `_require_runtime()` (before any DB touch) and then the same `_resolve()` `invoke()` runs (*"Every check the delegation depends on, run identically by preconditions and invoke."*), rendering each `_LegRefused` as one `PreconditionFailure`.

  - `design_leg_runtime_not_configured` — message: `"the design runtime is not composed on this deployment (CLUE_DESIGN_RUNTIME_ENABLED is off), so a design leg opened here could never run a design turn; delegation is refused rather than wedging the thread"`. Docstring: *"refuse BEFORE any database touch on a design-disabled deployment — a leg opened where no runtime is composed is a thread nothing can serve."*
  - `design_leg_storage_not_configured` — message: `"this deployment has no artifact storage, so no delegation bundle can be frozen; the design leg cannot open"`.
  - `design_leg_turn_ref_malformed` — `str(TurnActionUnresolvable)`: `"an action reference must be an opaque turn-action reference"` or `"a turn-action reference must name one turn by its canonical identifier"`. Engine-injected field, so no agent-side fix; no guidance in code.
  - `design_leg_turn_not_found` — message: `"no such turn in this workspace"`.
  - `design_leg_turn_execution_missing` — message: `"the presenting turn has no execution row yet, so the leg has no platform parent to attach to"`.
  - `design_leg_replay_closed` — message: `"this turn's design leg was already closed; a re-delegation reopens it by naming it in reopen_leg_id, not by opening it again"`. Comment: *"Practically unreachable… refused rather than silently reopened."* Agent action: re-call with `reopen_leg_id`.
  - `design_leg_already_open` — message: `"this thread already has an open design leg; finish it (or let the user keep talking to Design) before delegating again"` (fresh path) or `"this thread already has an open design leg; finish it before reopening another"` (reopen path).
  - `design_document_not_found` — message: `"no such design document in this workspace"`.
  - `design_document_pin_stale` — message: `f"the document is at version {current}, not {inputs.expected_document_version}; re-read it before delegating"`. Agent action is in the message: re-read the document, then delegate.
  - `design_document_pin_incomplete` — message: `"an expected document version without a document id pins nothing"`.
  - `design_leg_doc_kind_required` — message: `"this delegation names no document, so it must say what to create: pass doc_kind='web' to start a new website, doc_kind='scene' to start a new ad or designed page, or document_id to work on an existing artifact"`. The message *is* the guidance.
  - `brand_kit_pin_incomplete` — message: `"a brand pin is (brand_kit_id, version) together or absent entirely"`.
  - `brand_kit_pin_not_found` — message: `"no such brand kit version in this workspace — the pin is fail-closed (PD-part3 D5), so a missing kit is a refusal, never a default fallback"` (checked against `design_brand_kit` on `(brand_kit_id, version, workspace_id)`).
  - `design_bundle_too_large` — message: `f"the delegation bundle is {len(bundle_bytes)} bytes; the hard cap is {DESIGN_DELEGATION_BUNDLE_MAX_BYTES} (PD-part3 §2.3 — refs only, trim the brief or the claim set)"`. Guidance in the message: trim the brief or the claim set. (Re-checked after the birth path re-freezes the bundle with the actually-born brand pin.)
  - Reopen-path only: `design_leg_reopen_not_found` — `"no such design leg in this workspace"`; `design_leg_reopen_wrong_thread` — `"that design leg belongs to another thread; a re-delegation may only reopen a leg of its own conversation"`; `design_leg_reopen_not_closed` — `"that design leg is not closed — the user can simply keep talking to Design"`.

  Not a refusal: when an existing **open** leg derived from *this same turn* already exists, `_resolve` returns it and `invoke` reports `created=False` (an idempotent replay, not an error).

- **Output**: output model `OpenDesignLegOutput` (`ToolOutput` ⇒ `frozen`, `extra="forbid"`, `strict=True`).

  - `leg_id: str` — `leg["id"]`; derived as `derive_design_leg_id(workspace_id, turn_id)` = `uuid5(_LEG_NAMESPACE, f"{len(ws)}:{ws}{len(turn)}:{turn}")` where `_LEG_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design-leg")` — *"One presenting turn ⇒ one leg id — the replay identity of the delegation."*
  - `leg_ref: str` — `f"{DESIGN_LEG_REF_PREFIX}{leg_id}"`, `DESIGN_LEG_REF_PREFIX = "design-leg:"`.
  - `thread_id: str` — the thread the leg now owns.
  - `bundle_artifact_key: str` — the frozen §2.3 bundle's storage key (`""` when the leg carries none, e.g. a reopen of a leg whose ref is absent).
  - `bundle_sha256: str` — read back from `artifact.content_sha256` for that key in this workspace (`""` when there is no key/row).
  - `document_id: str | None` — the pinned or born document. On the birth path it is `derive_leg_document_id(leg_id=leg_id)` = `f"doc_{uuid5(_LEG_DOCUMENT_NAMESPACE, leg_id).hex}"` with `_LEG_DOCUMENT_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design-leg-document")` — *"One leg ⇒ one born document — the A9 replay identity of the birth… It carries the design subsystem's ``doc_<32 hex>`` id shape so nothing downstream can tell a leg-born document from a route-born one."*
  - `document_version_guard: int | None` — the CAS guard stored on the leg; `0` for a newborn document (*"A newborn document is at version 0, and that is exactly what the leg guards."*), else the document's `current_version` at open.
  - `brand_kit_id: str | None` / `brand_kit_version: int | None` — the leg's D5 brand pin, **read back off the stored document row** on the birth path (`effective_brand_kit_id` / `effective_brand_kit_version`), both `None` when the workspace has no approved kit (or the multi-brand fail-closed case): *"an all-null theme and a leg with NO pin — un-branded, honestly, and generation still works."*
  - `created: bool` — `True` only when this call inserted the leg row.
  - `document_created: bool = False` — comment: *"``True`` when this call BIRTHED the pinned document (@2). A replay of the same delegation returns the same ``document_id`` with ``False`` — the birth already happened, and nothing is created twice."*
  - `reopened: bool = False` — comment: *"``True`` when this call reopened a closed leg (the mis-exit recovery path)."*

  Caps/constants, verbatim: `DESIGN_DELEGATION_BUNDLE_MAX_BYTES = 24_000` (*"§2.3's day-one hard size policy. The bundle lands in the 48k-token L3 layer (``utf8-bytes-v1`` counter: tokens are bytes) that the C8 project card can half-fill, so the bundle's budget is the other half. An oversized bundle is refused at build."*); `DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE = "application/vnd.clue.design-delegation-bundle+json"`; `DESIGN_LEG_REF_PREFIX = "design-leg:"`; `DESIGN_LEG_TITLE_WORD_BUDGET = 8`; `_FALLBACK_DOCUMENT_TITLE = "Untitled page"`; `brief` ≤ 16 000 chars; `claim_refs` ≤ 200.

  **The frozen bundle** (`_bundle_payload`, "delegation-bundle schema v1 — refs and stamps, never claim values"): `schema_version: "1"`, `bundle_kind: "design_delegation"`, `workspace_id`, `project_id`, `thread_id`, `leg_id`, `opened_by_turn_id`, `brief`, `brand_kit` (`{"brand_kit_id", "version"}` or `null` — both halves or nothing), `target_document` (`{"document_id", "version_guard"}` or `null`), `claim_refs` (each `model_dump(mode="json")`), `binding_set_ref`, `template_revision_ref`, `turn_contract: {"proposal_flow": "propose_accept_reject", "clarification_rounds": 1}`. On the birth path the bundle is re-frozen with the brand pin the document was *actually* born with, then re-checked against the cap.

- **Side effects / what becomes true afterwards** (one `conn_factory()` transaction; the engine mint hops a thread via `asyncio.to_thread` because `lumen-api-helper` is a blocking subprocess):

  - **Fresh delegation, document-less**: `design_document` — one new row via `clue_design.documents.create_document` (`doc_kind="web"` from `mint_empty_web_document`, or `doc_kind="scene"` from `_default_scene_document_minter` → `new_scene(document_id, title, None, "ad")`, pageless). The DAL's frozen creation contract stamps the workspace's latest APPROVED brand kit; the leg only reads it back. *"Both run inside the CALLER's transaction, the same one that inserts the leg, so a failed delegation leaves no orphan document."*
  - `artifact` (+ its project binding `(project_id, "design_delegation_context")`) — the frozen canonical-JSON bundle persisted through `DurableAgentArtifactStore.persist_body` with the bundle media type.
  - `design_leg` — one row via `design_legs.open_leg`, born `open_awaiting_user`, carrying `thread_id`, `parent_execution_id` (the presenting turn's `agent_turn.execution_id`), `opened_by_turn_id`, `bundle_artifact_ref`, `document_id`, `document_version_guard`, `brand_kit_id`, `brand_kit_version`, `id=<derived leg id>`. A second open leg on the thread violates the partial unique index — which is why `design_leg_already_open` exists.
  - `agent_turn_event_stream` — one `leg.opened` (`TurnEventType.LEG_OPENED`) frame, or `leg.reopened` (`LEG_REOPENED`) on the recovery path, emitted *"in the SAME transaction as the durable transition, on the turn that performed it — so a crash can never leave a frame without its row, and a replayed invocation (which performs no transition) emits nothing."* This is what appears in chat.
  - **Reopen path**: `design_legs.reopen_leg` flips the named CLOSED leg back to open; no new bundle, no new document, no new pins — *"a reopen is a resumption, not a fresh delegation… The exit journal record survives by construction (the DAL never deletes journal rows)."*
  - **Routing**: from this point the thread is the design agent's. `chat/router.py` reads `get_open_leg_for_thread` at accept time and labels the pending turn `routed_to="design"`; a gate answer submitted while a leg is open is refused `409 DESIGN_LEG_OPEN`. The leg is closed by the separate `finish_design_leg@1` tool.
  - **No human gate is opened and the turn does not pause on an approval** — the agent simply tells the user the design session is open and ends its turn; the *user's next message* starts generation. Nothing is spent by this call.

- **Where the skill teaches it**: **not taught.** `stage0-interview` v26 never names `open_design_leg` (it is not in the skill's frontmatter `tools:` list and no section mentions design delegation; §10 "What you cannot do" does not mention it either). All of its steering lives in the `model_description` quoted above. Granted by profile `head-of-abm/v49` at version `"4"` (`profile.yaml:109-118`, `input_schema_sha256: b78a27a3…`, `output_schema_sha256: aede29ad…`, with the genad2 note that @3's schema stays frozen for replay).

- **Source**: `platform/api/clue_api/design_leg_tools.py:1-1035` (module docstring 1-85; constants 133-165; `design_leg_ref`/`derive_design_leg_id`/`derive_leg_document_id`/`_document_title` 167-196; `_emit_leg_lifecycle` 198-227; input/output models 229-284; `_ResolvedDelegation` 294-318; `_require_bundle_within_cap` 334-348; minters 350-397; tool class 399-620; `_birth_web_document` 620-667; `_birth_scene_document` 669-716; `_artifacts` 718-724; `_bundle_sha` 726-737; `_resolve` 739-921; `_resolve_reopen` 923-981; `_brand_kit_ref`/`_bundle_payload` 983-1033) — plus `FinishDesignLegTool` at 1072-1420 for the close side and `build_design_leg_tools` at 1422; `libs/clue-core/clue_core/contact_handoff.py:52-106`; `subsystems/design/clue_design/legs.py:57-120`; `platform/api/clue_api/chat/turn_events.py:90-100, 185-200`; `platform/api/clue_api/chat/router.py:2260-2290, 2380-2400`; `platform/api/clue_api/toolbelt_wiring.py:3090-3103`; `platform/toolbelt/clue_toolbelt/envelope.py:1-412`; `platform/api/clue_api/turn_action.py:180-206`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:109-118`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:1-245`.

- **Discrepancy**:
  - The module docstring's @2 paragraph still says *"``doc_kind="scene"`` creation was refused in v1 (@2)… **Superseded 2026-08-23 (genad ruling 1), @3**"* and the @3 paragraph still describes the `ad_format` aperture as if it were live, with only the @4 paragraph reversing it. The refusal codes `design_leg_ad_format_required` and `design_leg_ad_format_invalid` appear **only** in that historical prose — no code path raises them at @4 — so an operator grepping refusal codes will find two that cannot occur.
  - `replay.policy` is `DOMAIN_IDEMPOTENT` and `operation_id_required` is `False`, yet the durable identity is derived from the *presenting turn*, not from `ctx.operation_id`: two different logical operations inside the same turn would converge on the same leg id (the second is served as the existing leg with `created=False`), regardless of a differing brief or document pin.
  - `document_created` is computed per-invocation, not read back from the row, so on a genuine replay it correctly reports `False`; but on the **reopen** path `document_created`/`created` are both `False` while `document_id` still names the original leg's document — the output cannot distinguish "reopened onto an existing document" from "replayed an open leg" except through the `reopened` flag.
  - The output's `bundle_sha256` is read on a **separate** connection (`_bundle_sha` opens its own `conn_factory()`), outside the transaction that persisted the artifact; when the caller's factory is a bound single-connection one this read sees the same transaction, but on a pooled factory an uncommitted bundle would read back `""`.


---

## `draft_account_research_directive@5`

- **Address**: `draft_account_research_directive@5` — effect class `write` (`ToolEffectClass.WRITE`, inherited from `DraftAccountResearchDirectiveTool`), replay policy `operation_idempotent` (`durable_identity="ResearchDirectiveId(operation_id)"`, `operation_id_required=True`, `external_boundary=ExternalReplayBoundary.NONE`), pin_requirements `("project", "product", "icp", "field_registry", "source_registry")`, opens a human gate: **no**. It persists an immutable DRAFT directive version only; the human gate over that draft is the separate `open_directive_confirmation_gate@1` (D2), and the human-only confirmation act is `confirm_account_research_directive` (@1/@2) — a *different, ungranted* tool that head-of-abm@v49 does not hold and that the chat route invokes server-side on gate approval. Journal parameter policy: `JournalParameterPolicy(safe_display_fields=("project_id", "product_id", "icp_key", "icp_version"))` (inherited from v1). `estimate()` returns `ToolEstimate.free()`. Version 5 is the granted and default-registered version (`toolbelt_wiring.py:3015`: `make_default=(tool.name != "draft_account_research_directive" or tool.version == "5")`); @1–@4 stay registered, non-default, for replay.
- **Purpose**: The agent writes down, once and immutably, exactly what account research it is proposing — which accounts, which of the 21 comprehensive account fields, which hypotheses/questions, which sources, which privacy posture, which effort/budget envelope — after the human has finished revising the plan conversationally. Its own `model_description` (inherited from v1) says: "Persist one non-spending immutable account-research directive draft only after the human has finished revising the conversational working plan. The result is a complete review preview, not human confirmation, spend authorization, launch, or research." Nothing is spent and nothing runs; the output is a bounded review preview the agent can narrate, and a `directive_id` a confirmation gate can later be opened over.

- **Inputs**: input model `DraftAccountResearchDirectiveInputV5` (extends `…V4` → `…V3`; `ToolInput` base ⇒ `model_config = ConfigDict(frozen=True, extra="forbid")`, so any unknown key is a loud `ValidationError`).

  - `project_id: str` — `Field(min_length=1, max_length=255, description="Trusted current project; supplied by the platform.")`
  - `product_id: str` — `Field(min_length=1, max_length=255)` (no description in code)
  - `icp_key: str` — `Field(min_length=1, max_length=255)` (no description in code)
  - `icp_version: int` — `Field(ge=1)` (no description in code)
  - `directive: ResearchDirectiveBodyDraftInput` — the v5-only draft body subclass (see below). v3's docstring: *"Agent-plan-safe directive input; v2's frozen ``body`` field remains replayable."* (v1/v2 spelled this field `body: ResearchDirectiveBody`.)
  - `account_overrides: tuple[ResearchDirectiveOverrideInput, ...] = ()` — `Field(default=(), max_length=500)`
  - `predecessor_id: ResearchDirectiveId | None = None` — no `Field` constraints
  - `user_instruction: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)]` — `Field(json_schema_extra={TRUSTED_TURN_FIELD: True})`. **Stripped from the model-visible schema** and served at the execution seam from the trusted turn binding (`turn_binding.py`: "the field is then stripped from the model-visible schema (`agent_runtime_wiring._with_trusted_runtime`) and served at the execution seam from the trusted binding"). Also byte-capped by the model validator below against `USER_RESEARCH_INSTRUCTION_MAX_BYTES = 8_000`.
  - `source_turn_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]` — `Field(json_schema_extra={TRUSTED_TURN_FIELD: True})`, same trusted-turn stripping.
  - `profile: Literal["comprehensive", "custom"] = "comprehensive"` — added by `…InputV4`. v4 class docstring: *"Field breadth is a *contract*, not a model decision: the normal request is the whole fixed 21-field account profile, and the model's job is to say which of the two breadths the human asked for — not to retype a field list it could truncate or invent. So ``profile`` defaults to ``comprehensive`` and the expansion happens here, mechanically, from `COMPREHENSIVE_ACCOUNT_FIELDS`. ``custom`` is the narrower request the human explicitly asked for and passes through untouched. Declaring ``comprehensive`` *and* an explicit field list is two conflicting statements of breadth, so it is refused rather than silently resolved."*

  Validators on the input model:

  - `@model_validator(mode="after") overrides_are_unique` (inherited from V3): raises `ValueError("account research directive overrides must be unique by account")`; then, when `user_instruction` is present (it is absent on the agent-facing runtime model), raises `ValueError("user research instruction exceeds its 8000-byte context contract")` when `len(user_instruction.encode("utf-8")) > USER_RESEARCH_INSTRUCTION_MAX_BYTES`. Inline comment: *"The agent-facing runtime model deliberately removes trusted turn fields from its schema. It still inherits this validator, so validate the byte ceiling only when the full tool input is being materialized after trusted-turn injection."*
  - `@model_validator(mode="before") profile_decides_field_breadth` (v5 override of v4's): when `profile == "comprehensive"`, an explicit `directive.field_keys` that is not *exactly* the full 21-field set raises `ValueError("a comprehensive research directive covers the whole fixed 21-field account profile; pass profile='custom' to request an explicit narrower field set")`; otherwise `field_keys` is overwritten with `list(COMPREHENSIVE_ACCOUNT_FIELDS)` (so a verbatim full retyping normalizes to contract order). v5 docstring: *"the advertised schema finally agrees with the steering skill (the model may — and should — omit ``field_keys`` entirely), and an explicit list that is *exactly* the full fixed profile normalizes to the contract order instead of being refused… Any other non-empty list under ``comprehensive`` is still two conflicting statements of breadth and is refused."*

  **Nested — `ResearchDirectiveBodyDraftInput`** (subclass of `clue_core.ResearchDirectiveBody`; class docstring: *"The v5 draft-input directive body: ``field_keys`` is omittable at the schema level… Only the *advertised input schema* relaxes here: the durable body type is unchanged"*). `model_config = ConfigDict(frozen=True, extra="forbid")` inherited.

  - `account_scope: ResearchAccountScope` (required)
  - `field_keys: tuple[StableKey, ...] = ()` — v5 override: `Field(default=(), max_length=128, description="Omit for the normal comprehensive request — the tool itself expands the fixed 21-field account profile. List fields only together with profile='custom' when the user explicitly asked for a narrower subset.")`. (Base `ResearchDirectiveBody.field_keys` is `Field(max_length=128)` with **no** default — required.)
  - `questions: tuple[ResearchQuestion, ...] = ()` — `Field(default=(), max_length=64)`
  - `committee_plan: ResearchCommitteePlan` (required)
  - `source_policy: ResearchSourcePolicy` (required)
  - `privacy_policy: ResearchPrivacyPolicy` (required)
  - `effort_policy: ResearchEffortPolicy` (required)
  - `exclusions: tuple[NonEmptyStr, ...] = ()` — `Field(default=(), max_length=64)`; `NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]`
  - Base validator `_keys_are_unique`: `ValueError("research directive requires at least one field or question")` when both empty; `ValueError("research directive field keys must be unique")`; `ValueError("research directive question ids must be unique")`; and `ValueError("research directive body exceeds its 48000-byte execution-context contract")` when canonical JSON size > `RESEARCH_DIRECTIVE_BODY_MAX_BYTES = 48_000`.
  - v5-only validator `_committee_intent_names_a_capable_source`: if `committee_plan != ResearchCommitteePlan()` and not (`sumble_people` ∈ `source_policy.allowed_source_keys` and ∉ `excluded_source_keys` and `privacy_policy.committee_discovery_allowed`), raises `ValueError("the draft states an intentional buying-committee plan but authorizes no committee-capable source: include 'sumble_people' in source_policy.allowed_source_keys with privacy committee discovery allowed, or reset committee_plan to its defaults to state explicitly that committee discovery is off")`. Docstring: *"An intentional committee plan must be executable, or committee-off must be explicit… Draft-input only: durable historical bodies never re-validate through this subclass."* (`PEOPLE_SOURCE_KEY` is imported from `clue_research.resolvers.sumble.people`.)

  **Nested — `ResearchAccountScope`** (`frozen`, `extra="forbid"`), docstring *"The exact account selection described by a project directive."*:

  - `explicit_account_ids: tuple[EntityId, ...] = ()` — `Field(default=(), max_length=500)`
  - `sealed_selection_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)] | None = None`
  - `_exactly_one_scope_kind`: `ValueError("research account scope requires explicit ids or one sealed selection reference")` when both or neither; `ValueError("research account scope ids must be unique")`; a non-null `sealed_selection_ref` must parse as `discovery-seal:<batch_uuid>:<seal_sha256>` else `ValueError("sealed research selection must be discovery-seal:<batch_uuid>:<seal_sha256>")`.

  **Nested — `ResearchQuestion`** (`frozen`, `extra="forbid"`), docstring *"A search question, never an assertion that its hoped-for answer is true."*:

  - `question_id: StableKey` — `StableKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]`
  - `text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]`
  - `target_field_key: StableKey | None = None`
  - `target_facet: StableKey | None = None`
  - `priority: int = 3` — `Field(default=3, ge=1, le=5)`
  - `source_family_hints: tuple[StableKey, ...] = ()` — `Field(default=(), max_length=16)`
  - `stop_rule: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)] = "stop when grounded or terminally unsupported"`
  - `_target_and_hints_are_bounded`: `ValueError("research question requires a target field or facet")`; `ValueError("research question source-family hints must be unique")`.

  **Nested — `ResearchCommitteePlan`** (`frozen`, `extra="forbid"`):

  - `functions: tuple[StableKey, ...] = ()` — `Field(default=(), max_length=32)`
  - `levels: tuple[StableKey, ...] = ()` — `Field(default=(), max_length=32)`
  - `teams: tuple[StableKey, ...] = ()` — `Field(default=(), max_length=32)`
  - `personas: tuple[StableKey, ...] = ()` — `Field(default=(), max_length=32)`
  - `candidate_cap: int = 20` — `Field(default=20, ge=1, le=200)`
  - `relationship_depth: int = 1` — `Field(default=1, ge=0, le=2)`
  - `_selectors_are_unique`: `ValueError(f"committee {label} must be unique")` for `functions`/`levels`/`teams`/`personas`.

  **Nested — `ResearchSourcePolicy`** (`frozen`, `extra="forbid"`):

  - `allowed_source_keys: tuple[StableKey, ...]` — `Field(max_length=64)` (required)
  - `preferred_source_keys: tuple[StableKey, ...] = ()` — `Field(default=(), max_length=64)`
  - `excluded_source_keys: tuple[StableKey, ...] = ()` — `Field(default=(), max_length=64)`
  - `use_primary_source_for_contradictions: bool = True`
  - `_sets_are_coherent`: `ValueError("research source policy requires at least one allowed source")`; `ValueError("research source-policy lists must not contain duplicates")`; `ValueError("preferred research sources must also be allowed")`; `ValueError("a research source cannot be both allowed and excluded")`.

  **Nested — `ResearchPrivacyPolicy`** (`frozen`, `extra="forbid"`):

  - `account_research_allowed: bool = True`
  - `committee_discovery_allowed: bool = True`
  - `contact_profiling_allowed: bool = False`
  - `contact_reveals_allowed: bool = False`
  - `allowed_use_classes: tuple[UseClass, ...] = (UseClass.PROFESSIONAL_PUBLIC,)`
  - `exclusions: tuple[NonEmptyStr, ...] = ()` — `Field(default=(), max_length=64)`
  - `_privacy_is_coherent`: `ValueError("research privacy use classes must be unique")`; `ValueError("contact reveals cannot be allowed when contact profiling is excluded")`.

  **Nested — `ResearchEffortPolicy`** (`frozen`, `extra="forbid"`) — all required:

  - `tier: StableKey`
  - `max_depth: int` — `Field(ge=0, le=4)`
  - `max_fanout: int` — `Field(ge=1, le=64)`
  - `budget_cap_cents: Decimal` — `Field(ge=0, le=100_000_000)` (this per-account number is what D2's gate sums into `max_spend_cents`)
  - `budget_envelope_ref: StableKey`
  - `recursion_policy_ref: StableKey`
  - `freshness_policy_ref: StableKey`

  **Nested — `ResearchDirectiveOverrideInput`** (`ToolInput` subclass, `frozen`, `extra="forbid"`):

  - `account_id: EntityId`
  - `body: ResearchDirectiveAccountOverrideBody`

  **Nested — `ResearchDirectiveAccountOverrideBody`** (`frozen`, `extra="forbid"`):

  - `include_field_keys: tuple[StableKey, ...] = ()` — `Field(default=(), max_length=128)`
  - `exclude_field_keys: tuple[StableKey, ...] = ()` — `Field(default=(), max_length=128)`
  - `additional_questions: tuple[ResearchQuestion, ...] = ()` — `Field(default=(), max_length=64)`
  - `exclude_question_ids: tuple[StableKey, ...] = ()` — `Field(default=(), max_length=64)`
  - `source_policy: ResearchSourcePolicy | None = None`
  - `committee_plan: ResearchCommitteePlan | None = None`
  - `effort_policy: ResearchEffortPolicy | None = None`
  - `exclusions: tuple[NonEmptyStr, ...] = ()` — `Field(default=(), max_length=64)`
  - `_override_is_coherent`: `ValueError("override included field keys must be unique")`; `ValueError("override excluded field keys must be unique")`; `ValueError("an override field cannot be both included and excluded")`; `ValueError("override question ids must be unique")`; `ValueError("override excluded question ids must be unique")`.

  **The 21 fields `profile="comprehensive"` expands to** (`COMPREHENSIVE_ACCOUNT_FIELDS`, re-exported from `clue_core.research_profile` via `clue_research.narrative.prose.PROSE_ACCOUNT_FIELDS`, in contract-table order): `core.account_name`, `core.industry`, `core.company_about`, `core.employee_count`, `core.employee_range`, `core.hq_location`, `core.annual_revenue`, `core.revenue_band`, `core.primary_tech_stack`, `core.company_linkedin_url`, `account.total_funding`, `account.recent_funding`, `account.hiring_velocity_eng`, `account.operational_pain`, `account.strategic_moves`, `account.resonance.culture`, `account.resonance.employee_sentiment`, `account.resonance.attrition_signal`, `account.resonance.eng_blog_tone`, `account.resonance.public_frustrations`, `account.resonance.buying_culture`.

- **Preconditions and refusal codes**: `preconditions()` is v1's, called through `V3._v2_input(...)` (v5 re-declares the same downcast). Three `PreconditionFailure` codes:

  - `memory_write_not_configured` — message: `"project research direction requires the scoped-memory write seam"`. Raised when the tool was composed with `memory_write_factory=None`. Agent guidance: no guidance in code (it is a deployment-composition fault, not an agent-repairable one; `invoke` would raise `RuntimeError("research directive memory write seam is not configured")`).
  - `research_directive_replay_conflict` — message: `"draft operation id was already used with different research direction"`. Raised when `research_directive_draft_replay_matches(...)` returns `False`, i.e. this `operation_id` already produced a draft whose `research_directive_draft_request_sha256` differs. Agent guidance: no guidance in code. (A `True` match is a clean replay and returns no failures.)
  - `research_directive_invalid` — message is `str(exc)` of any `ResearchDirectiveError` raised by `validate_research_directive_draft`. The exact messages it can carry, verbatim from `subsystems/research/clue_research/directives.py`:
    - `"research directive project is absent or cross-workspace"`
    - `"research directive product is not selected by the project"`
    - `"research directive ICP/product lineage is absent"`
    - `f"research directive field {field_key!r} is not a registered deep field"`
    - `f"research directive field {field_key!r} is not active in the pinned ICP"`
    - `"account source-policy override may only narrow project sources"`
    - `f"research directive source {source_key!r} is not active in the registry"`
    - `f"research directive source {source_key!r} is outside the pinned ICP field plans and is not a registered committee-enumeration source"`
    - `"account override excludes unknown project question ids: " + ", ".join(sorted(unknown_question_ids))`
    - `f"research directive account {account_id} is absent or cross-workspace"`
    - `"account override lies outside the resolved account scope"`
    - also reachable at `invoke` time through the same error class: `"user research instruction must contain 1 to 8000 UTF-8 bytes"`, `"initial directive cannot name a predecessor"`, `"successor must name the latest directive version"`, `"cannot append behind an unconfirmed directive"`.
    - Agent guidance: no guidance in code beyond the message text itself (the messages name the exact offending field/source/account).

  Note the fixed-profile carve-out inside validation: *"The fixed comprehensive account profile (contract §3.1, COMPREHENSIVE_ACCOUNT_FIELDS) is a platform contract, not an ICP choice… Every field OUTSIDE the fixed profile keeps the strict deep-registration and ICP-activation gates unchanged."*

- **Output**: output model `DraftAccountResearchDirectiveOutputV2` (inherited from `…ToolV2`; `ToolOutput` base ⇒ `frozen`, `extra="forbid"`, `strict=True`):

  - `directive_id: str` — the new directive's id. It is **derived from the operation id**: `directive_id = ResearchDirectiveId(UUID(str(operation_id)))`.
  - `directive_ref: str` — `f"research-directive:{directive_id}:v{version}"`.
  - `version: int` — the lineage version (`1` for the first directive on `(workspace, project, product, icp_key, icp_version)`, else previous `version + 1`).
  - `canonical_json_sha256: str` — the execution digest over `execution_payload()`; this is the value D2's gate stores as `expected_subject_sha256` and the confirmation checks.
  - `status: str` — `ResearchDirectiveStatus` value; always `"draft"` on this path.
  - `memory_outcome: str` — one of `"persisted"`, `"memory_disabled"`, `f"memory_rejected:{reason}"`, `"memory_rejected:person_adjacent_precondition"`, `"unknown"`.
  - `future_thread_memory_persisted: bool` — `bool(directive.memory_refs)`.
  - `memory_refs: list[str]` — the accepted memory ids (empty unless the advisory memory write was accepted); `ResearchDirective.memory_refs` is `Field(default=(), max_length=64)` and must be unique.
  - `account_override_refs: list[str]` — one `f"research-directive-override:{override_id}"` per persisted override.
  - `preview_sha256: str` — sha256 over the canonical-JSON serialization of `preview`.
  - `preview: ResearchDirectivePreview` (dumped `mode="json"`) — bounded review payload, docstring *"Bounded complete review payload; questions remain explicitly labeled as hypotheses."*, fields: `directive_ref: str`, `version: int`, `status: str`, `account_ids: tuple[str, ...]`, `sealed_selection_ref: str | None`, `field_keys: tuple[str, ...]`, `hypotheses: tuple[ResearchQuestion, ...]`, `source_policy: ResearchSourcePolicy`, `committee_plan: ResearchCommitteePlan`, `privacy_policy: ResearchPrivacyPolicy`, `effort_policy: ResearchEffortPolicy`, `exclusions: tuple[str, ...]`, `account_overrides: tuple[ResearchDirectiveAccountPreview, ...]`, `memory_outcome: str`, `future_thread_memory_persisted: bool`, `unresolved_prerequisites: tuple[str, ...]`, `rendered_summary: str`, plus property `budget_cap_cents -> Decimal` (= `effort_policy.budget_cap_cents`).

  Caps/bounds carried into the output by construction: `RESEARCH_DIRECTIVE_BODY_MAX_BYTES = 48_000` (body canonical-JSON ceiling), `USER_RESEARCH_INSTRUCTION_MAX_BYTES = 8_000`, `EFFECTIVE_RESEARCH_DIRECTIVE_MAX_BYTES = 64_000` (the per-account composition ceiling enforced later, in `EffectiveAccountResearchDirective`), `account_overrides` ≤ 500, `field_keys` ≤ 128, `questions` ≤ 64.

  (v1's output shape — `DraftAccountResearchDirectiveOutput` with `preview_ref`, `preview_hypothesis_count`, `preview_account_count`, `unresolved_prerequisites` — is **not** what @5 returns.)

- **Side effects / what becomes true afterwards**: all inside one `conn_factory()` transaction, after a `pg_advisory_xact_lock` on `research-directive:{workspace_id}:{project_id}:{product_id}:{icp_key}`:

  - `account_research_directive` — one new immutable row (`directive_id`, `workspace_id`, `project_id`, `product_id`, `icp_key`, `icp_version`, `version`, `predecessor_id`, `content_json`, `memory_refs`, `created_by`, `source_turn_ref`, `draft_operation_id`, `draft_request_sha256`, `canonical_json_sha256`), status `draft`.
  - `account_research_directive` UPDATE — when the lineage's latest row was itself an unconfirmed `draft`, that draft is set `status='superseded'` (comment: *"A draft is a proposal, not an authority: a fresh draft replaces it instead of deadlocking the lineage… Confirmed history stays immutable — only the unconfirmed latest is superseded"*), and the new draft's `predecessor_id` is re-pointed at the lineage's currently-confirmed directive (or NULL).
  - `account_research_directive_account` — one row per resolved account (`scope_kind` = `"explicit"` or `"discovery_seal"`, `selection_ref` = the sealed ref when present).
  - `project_account` (via `ensure_project_account(..., added_via="directive")`) — idempotent, first-add-wins membership: *"scoping an account into a directive is a project claiming it as a target"*.
  - `account_research_directive_override` — one row per `account_overrides` entry, id `uuid5` of `f"{directive_id}:{account_id}"`.
  - `account_research_directive_event` — a `'drafted'` event; plus a `'superseded'` event on the replaced draft naming this directive as `successor_id`.
  - Scoped-memory seam — one advisory `MemorySubmission` (`scope_type=PROJECT`, `type=PREFERENCE`, `trigger=f"account-research-directive:{project_id}"`, body/creating_quote = `user_instruction`, `provenance_class=USER_STATED`). **Advisory only**: a `MemoryRejected` or a `MemoryPreconditionFailed` is recorded via `record_policy_refusal_skipped` and the directive still lands (comment: *"a rejection is recorded, never fatal… an advisory subsystem's hygiene opinion may not stop a directive in *any* posture"*).
  - No gate is opened, nothing appears in chat from this tool itself, the turn does not pause, no external call is made, `estimate()` is zero. The next act is normally opening D2's gate over the returned `directive_id` + `canonical_json_sha256`.

- **Where the skill teaches it**: **not taught.** `stage0-interview` v26 never names `draft_account_research_directive` (its frontmatter tool list does not carry it, and §7 "Launch account research" routes account research through `launch_arv2_account_research` instead). The tool is granted by profile `head-of-abm/v49` (`platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:74-77`, version `"5"`, `input_schema_sha256: 5cf321a5…`, `output_schema_sha256: 1d805a75…`) with no accompanying skill procedure.

- **Source**: `platform/api/clue_api/research_directive_tools.py:1-935` (input models 57-292; output models 293-317; tool classes 361-620; `ConfirmAccountResearchDirectiveTool` 640-771 — the *different, ungranted* tool; `build_research_directive_tools` 878-912); `libs/clue-core/clue_core/research_directive.py:1-330` (constants 25-41, nested models 89-236, `ResearchDirectiveAccountOverrideBody` 318-352); `libs/clue-core/clue_core/research_profile.py:39-66`; `platform/api/clue_api/comprehensive_research_contract.py:1-80`; `platform/projections/clue_projections/research_directives.py:36-62`; `subsystems/research/clue_research/directives.py:100-260, 673-1050`; `platform/toolbelt/clue_toolbelt/envelope.py:1-412`; `platform/api/clue_api/toolbelt_wiring.py:3006-3020`; `platform/api/clue_api/turn_binding.py:1-60`; `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:63-140`; `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:1-245`.

- **Discrepancy**:
  - The class-level `model_description` the model actually sees is **v1's**, inherited unchanged by @2–@5. It speaks of "the conversational working plan" and never mentions `profile="comprehensive"`, the omittable `field_keys`, or the renamed `directive` field — the v4/v5 breadth contract exists only in class docstrings the model never reads. The v5 docstring itself records the consequence of that mismatch at @4: *"the skill says 'no field list', the schema says the list is mandatory, and any non-empty value is refused as ambiguous breadth (found live in the Slice B browser gate; the agent looped plan-rejected and gave up)."*
  - `pin_requirements` advertises `("project", "product", "icp", "field_registry", "source_registry")` but the tool body validates the field and source registries itself via `validate_research_directive_draft` — the pins are declared for the C5.2 compatibility loader, not read by this tool.
  - `validate_research_directive_draft` refuses unless `project.product_id == product_id` (`"research directive product is not selected by the project"`), i.e. it reads the **single**-product `project.product_id` column, while the ARV2 lane this profile otherwise uses confirms a product **set** (`project_product` / `confirm_project_product_set`, see D3). The two product models are not reconciled in this tool's path.
  - v1/v2's `preconditions` recompute `research_directive_draft_request_sha256` from the **v2-shaped** downcast input (`_v2_input`), so the replay identity of a v5 call is the v2 request hash — deliberate per the v4 docstring (*"a v3 draft replays as a v3 draft"*) but it means `profile` and the draft-only committee validator are outside the replay digest.


---

# Part 6 — The framework surface


---

# The deepagents framework tools

These are not platform tools: they have no descriptor, no effect class, no replay policy, no
`GovernedOperationReceipt`, and no journal entry. They are installed by `create_deep_agent`
(`platform/agents/clue_agents/runtime.py:313-333`) over the workspace `backend`, and the middleware
allows exactly the set `_FRAMEWORK_TOOL_NAMES` (`runtime.py:36-46`):

```
{"write_todos", "ls", "read_file", "write_file", "edit_file", "glob", "grep"}
```

plus `_FINALIZE_TOOL_NAME = "finalize_turn"`. Anything else the framework installs is a hard
`RuntimeError("undeclared runtime tools were installed: …")` at model-call time, except `task`, which
is explicitly tolerated-and-stripped (`runtime.py:127`: `unexpected = sorted(set(by_name) - self._allowed - {"task"})`;
the filtered list handed to the model is `[by_name[name] for name in sorted(self._allowed)]`, so
`task` is never offered). `"execute"` in the tool set raises
`RuntimeError("agent workspace unexpectedly exposes code execution")` (`runtime.py:130-131`).

## The workspace they act on

`head-of-abm@v49`'s `workspace:` block:

- `virtual_mode: true` — enforced: `WorkspaceSecurityError("agent workspace requires virtual_mode=True")` otherwise (`workspace.py:221-222`).
- `max_total_bytes: 10485760` (10 MiB)
- `max_file_bytes: 1048576` (1 MiB)
- `max_file_count: 200`
- `allowed_extensions: [".json", ".md", ".txt", ".yaml"]`
- `readable_prefixes: [".deepagent", "inputs", "context", "work", "outputs"]`
- `writable_prefixes: ["work", "outputs"]`
- `retention_class: agent-ephemeral-v1`

`_validate_path` (`workspace.py:273-289`) is the fence:

- path normalized by `normalize_virtual_path`; a bad path → `WorkspaceSecurityError`.
- not under a readable prefix → `WorkspaceSecurityError("path is outside the readable workspace authority")`.
- on write, not under a writable prefix → `WorkspaceSecurityError("path is outside the writable workspace authority")`.
- on write under `outputs/` after `snapshot_outputs()` → `WorkspaceConflict("snapshotted outputs are immutable")`.
- on write with a suffix outside `allowed_extensions` → `WorkspaceSecurityError("file type is not allowed in the agent workspace")`.

**Consequence for the manual:** the agent can READ `inputs/brand/knowledge/**`,
`inputs/project/status.md`, `inputs/project/decisions.md`, `inputs/project/plan.md`,
`inputs/project/audience/*`, and `context/**`, but it can only WRITE under `work/` and `outputs/`.
It cannot edit a knowledge file or the plan file directly — the plan is changed only through
`write_project_document@1`.

Errors are returned as strings on the result object, prefixed by `_error` (`workspace.py:733-739`):
`quota_exceeded: …` for `WorkspaceQuotaExceeded`, `conflict: …` for `WorkspaceConflict`, and
`permission_denied: …` for every other `WorkspaceError`.

## `ls(path)`

- **Signature**: `ls(self, path: str) -> LsResult` (`workspace.py:741-750`).
- Root is allowed (`allow_root=True`): `""` or `"."` or `"/"` list everything.
- Returns `LsResult(entries=[{"path": item.path, "is_dir": False, "size": item.byte_count}, …])`.
- **Note**: `is_dir` is hard-coded `False` for every entry — the listing is a flat file walk, not a
  directory tree. There are no directory entries in an `ls` result, ever.
- On error: `LsResult(error=...)`.

## `read_file(file_path, offset=0, limit=2000)`

- **Signature**: `read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult` (`workspace.py:752-764`).
- `offset` and `limit` are in **LINES**, not bytes: the file is read whole, then
  `content.splitlines(keepends=True)` and `"".join(lines[offset : offset + limit])`.
- Default window is the first 2000 lines.
- Returns `ReadResult(file_data={"content": <str>, "encoding": "utf-8"})`.
- Underlying `read_text_sync` (`workspace.py:529-544`) refuses a file over `max_file_bytes`
  (1 MiB) with `WorkspaceQuotaExceeded("workspace file exceeds its read quota")` — checked twice,
  once on `st_size` and once on the bytes actually read — and refuses non-UTF-8 with
  `WorkspaceSecurityError("workspace file is not valid UTF-8 text")`.
- **Reads are not restricted to writable prefixes** — the whole `readable_prefixes` set is legal.
- Skill §1 tells the agent to batch: "Read them all in one step: issue every `read_file` call
  together in a single turn."

## `write_file(file_path, content)`

- **Signature**: `write(self, file_path: str, content: str) -> WriteResult` (`workspace.py:766-772`).
- Validated `write=True`, so: writable prefix (`work`, `outputs`) + allowed extension.
- Whole-file replace (`_create_file(logical, content.encode("utf-8"), read_only=False)`); atomic
  (same-directory temp file + link/replace, per the module docstring).
- Quota check before write (`_quota_before_write`, `workspace.py:376-392`): per-file
  `max_file_bytes`, then total `max_total_bytes` and `max_file_count` over the whole walked tree;
  each violation is a distinct `WorkspaceQuotaExceeded` message
  (`"file exceeds the per-file workspace quota"`, `"workspace file-count quota would be exceeded"`,
  `"workspace total-byte quota would be exceeded"`, plus the three `…is already exceeded` variants).
- Returns `WriteResult(path=entry.path)`.

## `edit_file(file_path, old_string, new_string, replace_all=False)`

- **Signature**: `edit(self, file_path, old_string, new_string, replace_all: bool = False) -> EditResult` (`workspace.py:774-788`).
- **`replace_all=True` is refused outright**: `EditResult(error="permission_denied: replace_all is not available")`. Not a workspace error — a flat platform refusal.
- `edit_text_sync` (`workspace.py:550-575`) runs the compare-and-replace under one process +
  filesystem lock "preventing lost updates":
  - `count == 0` → `WorkspaceConflict("edit source text was not found")`
  - `count != 1` → `WorkspaceConflict("edit source text is not unique")`
  - otherwise `original.replace(old, new, 1)`.
- Returns `EditResult(path=entry.path, occurrences=1)` — always exactly 1.

## `glob(pattern, path=None)`

- **Signature**: `glob(self, pattern: str, path: str | None = None) -> GlobResult` (`workspace.py:790-802`).
- `path` defaults to root (`allow_root=True`).
- Implemented as `fnmatch.fnmatch(relative, pattern)` over `list_entries_sync(logical)` where
  `relative = item.path.removeprefix(f"{logical}/")`. This is **fnmatch, not pathlib glob**:
  `*` crosses `/` boundaries, and `**` is just two stars.
- Returns `GlobResult(matches=[{"path", "is_dir": False, "size"}, …])`.

## `grep(pattern, path=None, glob=None)`

- **Signature**: `grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult` (`workspace.py:804-819`).
- Implemented on top of `self.glob(glob or "**", path)` then a **plain substring test**:
  `if pattern in line`. **It is not a regular-expression search** despite the name.
- Returns `GrepResult(matches=[{"path", "line": <1-based int>, "text": <full line>}, …])`.
- Every matched file is read in full, so the per-file 1 MiB read quota applies mid-scan and a single
  oversized file makes the whole grep raise.

## `write_todos(...)`

- Allowed by `_FRAMEWORK_TOOL_NAMES` and therefore installed and offered to the model, but it is
  deepagents' own scratch-plan tool: **not found in this repo's code** — I looked in
  `platform/agents/clue_agents/runtime.py`, `platform/agents/clue_agents/workspace.py` and
  `platform/api/clue_api/agent_runtime_wiring.py`; only the name appears, in the allow-set. It
  writes to LangGraph state, not to the workspace, and produces no durable platform row.

## `upload_files` / `download_files`

Present on the backend (`workspace.py:821-845`) but **not** in `_FRAMEWORK_TOOL_NAMES`, so they are
never offered to the model on this surface.


---

# `finalize_turn` — the mandatory terminal action

Note the name: the tool the model sees is **`finalize_turn`**, not `finalize`
(`_FINALIZE_TOOL_NAME = "finalize_turn"`, `platform/agents/clue_agents/runtime.py:48`;
`StructuredTool.from_function(..., name="finalize_turn", return_direct=True)`,
`platform/api/clue_api/agent_runtime_wiring.py:1192-1199`).

- **Address**: no `name@version` address — it is not a toolbelt tool. No effect class, no replay
  policy, no `pin_requirements`. `return_direct=True`, so calling it ends the graph.
- **Opens a gate**: no, but it is how a gate opened by a gate tool reaches the human: the gate card
  is projected from `open_gate_refs`.

## Purpose

Every turn must end with a durable `AgentFinalizeEnvelope`. The middleware sets
`tool_choice="required"` on every model call (`runtime.py:143`), and a plain-text stop is given one
bounded finalize-only recovery round before the turn dies `missing_finalize`. `finalize_turn` is
where the assistant message becomes an artifact, where the output tree is frozen, and where the
chat's gate/plan cards are declared.

## Inputs (`ModelFinalizeRequest`, `agent_runtime_wiring.py:323-370`)

`model_config = ConfigDict(frozen=True, extra="forbid", strict=False)` (inherited from `_ModelInput`,
line 293-297: "Tool arguments arrive as JSON, so arrays must validate into immutable tuples.
Authority fields remain forbidden or injected; accepting JSON representation is not authority
coercion.")

- `status: FinalizeStatus` — required, no default. The four values are `completed`,
  `awaiting_input`, `blocked`, `failed`.
- `user_message: str | None = Field(default=None, max_length=65_536)` — the message the human reads.
  Persisted as a `text/markdown` artifact; its ref becomes `user_message_artifact_ref`.
- `domain_refs: tuple[DomainObjectRef, ...] = ()` — no declared max length. The typed references
  this turn's answer rests on. Only `object_type` in `_PLAN_OBJECT_TYPES`
  (`research_directive`, `agent_plan`, `plan`, `project_document`) produces a chat card.
- `open_gate_refs: tuple[DomainObjectRef, ...] = ()` — no declared max length. Each becomes a gate
  card via `stream.emit_gate_parts`. Skill §4: "exactly `{object_type: "agent_gate", object_id: <returned gate_id>}` in `open_gate_refs`".
- `assumptions: tuple[str, ...] = Field(default=(), max_length=64)` — each item persisted as its own
  `text/plain` artifact; the refs become `assumption_refs`.
- `next_actions: tuple[str, ...] = Field(default=(), max_length=64)` — each persisted `text/plain`;
  refs become `next_action_refs`.
- `failure_code: ReasonCode | None = None` — "The envelope's own alias, not a copy of its pattern."
  The finalize tool's own description states the pattern: `^[a-z0-9_.-]+$` (lowercase, at most 128
  characters).

Each element of `domain_refs` / `open_gate_refs` is a model-side `ModelDomainRef`
(`agent_runtime_wiring.py:386-391`): `object_type: str = Field(min_length=1, max_length=128)`,
`object_id: str = Field(min_length=1, max_length=255)`, `version: int | None = Field(default=None, ge=1)`.
`workspace_id` is injected, never model-supplied.

## Refusals

Two independent rejectors, each worth one repair out of `_MAX_FINALIZE_REPAIRS = 2`:

**1. The shape contract** — `terminal_shape_is_honest` (`agent_runtime_wiring.py:339-375`),
a mirror of `AgentFinalizeEnvelope.terminal_shape_is_honest` so the refusal happens "where the model
can still see and repair it":

- `status='failed'` with no `failure_code` → `ValueError("status 'failed' must carry a stable snake_case failure_code")`.
- any other status with a `failure_code` → `ValueError(f"status {status!r} cannot carry a failure_code; only 'failed' may")`.
- `status='completed'` with `user_message is None` → `ValueError("status 'completed' must carry a user_message")`.
- `status` in `{awaiting_input, blocked}` with none of `open_gate_refs` / `next_actions` / `user_message` →
  `ValueError("status <s> must identify what it is waiting for: supply next_actions, open_gate_refs, or a user_message that asks for it")`.

**2. The surface's `CompletionGuard`** — invoked only for `_GUARDED_STATUSES = {COMPLETED, AWAITING_INPUT}`
(`agent_runtime_wiring.py:1106-1107`). "`failed` and `blocked` are never gated, because an honest
failure must not be forced through work it could not do."
**On the production project conversation there is no guard**: `ProjectConversationTurnRunner` calls
`self._engine.execute(...)` without a `completion_guard`
(`platform/api/clue_api/agent_turn_fleet_wiring.py:854-864`), and `completion_guard` defaults to
`None` (`conversation_turns.py:291`). The only `CompletionGuard` in the repo is
`Stage0RoutingReceiptGuard`, wired on the **trial** surface only (`stage0_trial.py:212-253, 793`).
See Inconsistencies.

**3. A specialist-only check**: `status='completed'` with a `required_output_path` whose entry is
not a non-empty file → `ValueError("completed specialist turn requires its non-empty role output file")`
(`agent_runtime_wiring.py:1097-1105`). `required_output_path` is `None` on the conversation surface.

## Output

Returns `ref.model_dump_json()` — the reference of the committed finalization
(`self._execution.finalize(envelope=...)`). `return_direct=True`, so this is the last thing the
model does.

## Side effects / what becomes true afterwards

- `user_message` → one content-addressed `text/markdown` artifact.
- each `assumptions` item → one `text/plain` artifact; each `next_actions` item likewise.
- **Implicit-next-action repair** (`agent_runtime_wiring.py:1127-1146`): when `status` is
  `awaiting_input`/`blocked`, there are no `open_gate_refs`, no `next_actions`, and a `user_message`
  exists, the message's own artifact ref is reused as the single `next_action_refs` entry — "Preserve
  that exact message as the action reference so the honest-finalization envelope remains valid
  without inventing new content."
- `output_refs = tuple(await self._lease.backend.snapshot_outputs())` — **the `outputs/` tree is
  frozen and persisted here**, and after this any write under `outputs/` is
  `WorkspaceConflict("snapshotted outputs are immutable")`.
- One `AgentFinalizeEnvelope` row, with `finalization_id = uuid5(_FINALIZATION_NAMESPACE, str(execution_id))`
  — deterministic per execution, so a replay commits the same identity.
- Gate cards, plan cards and launched-task cards appear in chat (see the overview).

## Where the skill teaches it

Not named by name, but its fields are the subject of skill §4 ("end the turn `awaiting_input`, with
your explanation in `user_message` and exactly `{object_type: "agent_gate", object_id: <returned gate_id>}`
in `open_gate_refs`"), §5 ("End the turn `awaiting_input` with the gate reference in `open_gate_refs`"),
§5b ("end the turn `awaiting_input`"), §6b ("Include `{object_type: "project_document", object_id: <document_id>, version: <version>}`
in `domain_refs` when you finalize, so the plan card appears in the chat and the Plan tab opens"),
§6 (report receipts, never claim capture) and §7 ("remain `awaiting_input`").

## Source

`platform/api/clue_api/agent_runtime_wiring.py:92-98, 293-297, 300-321, 323-375, 377-383, 386-391, 1092-1199`;
`platform/agents/clue_agents/runtime.py:36-57, 84-170`;
`platform/api/clue_api/conversation_turns.py:145-147, 285-300, 435-497`;
`platform/api/clue_api/agent_turn_fleet_wiring.py:190, 840-870`.


---

# `delegate_specialist` — **not exposed on this surface**

The profile grants `delegation_roles: [research, content_drafter, reviewer]` and a full
`delegation_tool_grants` block (`get_research_view@1` + `run_verification@1` for research;
`compose_handoff@1` + `compose_contact_content_handoff@1` + `get_research_view@1` for
content_drafter and reviewer), with `max_delegation_depth: 1` and `max_delegations: 6`.
**None of it is reachable from the production project conversation.**

The mechanism is structural subtraction, not a runtime refusal
(`platform/api/clue_api/agent_registry_wiring.py:541-565`):

```python
AgentSurfacePolicy(
    surface=PROJECT_CONVERSATION_SURFACE,
    role=AgentRole.HEAD_OF_ABM,
    withheld_tools=frozenset(),
    withheld_delegation_roles=frozenset({
        AgentRole.RESEARCH, AgentRole.CONTENT_DRAFTER, AgentRole.REVIEWER,
    }),
    withheld_reason_code="project_conversation_no_autonomous_research",
    framing=(...),
)
```

The chain, from the module docstring at `agent_registry_wiring.py:454-463` and the code:

1. Withholding all three roles empties the resolved profile's `delegation_roles`.
2. `GovernedAgentToolFactory.build()` then adds no delegation tool
   (`agent_runtime_wiring.py:695-704`).
3. `ExactAgentToolSurfaceMiddleware` therefore does not include `delegate_specialist` in its
   allowed set (`runtime.py:105`: `*(("delegate_specialist",) if profile.profile.delegation_roles else ())`),
   so the model is never offered it and the Delegation block of the resource map names nobody.
4. `DelegationWithheld.run` (`conversation_turns.py:150-176`) and the child runner's refusal are
   "a backstop, not the fence": *"Restriction by crash is what ruling §2.4 rejects; the withheld
   roles are the actual mechanism."*

The comment at `agent_registry_wiring.py:456-463` explains why withholding the **tool** alone was
judged insufficient: *"A tool ceiling alone left the trial's own map promising 'no external research'
while still advertising `delegate_specialist` and the three specialist roles under it — one of which
is *the research role*."*

**For the manual:** the Head of ABM on a project conversation has no subagents. Everything it does,
it does itself, with the 21 governed tools and the framework file tools. Skill §10 states the same
thing in prose: *"You cannot … research the web, declare a company ready, or start anything the human
has not asked for on the current turn."*

For completeness, had it been installed, the input model is `DelegateSpecialistRequest`
(`agent_runtime_wiring.py:394-412`): `role: Literal["research","content_drafter","reviewer"]`;
`goal: str = Field(min_length=1, max_length=2_048)`; `instructions: str = Field(min_length=1, max_length=8_192)`;
`verbatim_context: tuple[str, ...] = Field(default=(), max_length=16)` with each item 1..16384 chars;
`canonical_paths: tuple[str, ...] = Field(default=(), max_length=32)` (normalized + must be unique);
`domain_refs: tuple[ModelDomainRef, ...] = Field(default=(), max_length=64)`. Required child outputs
are `outputs/research-strategy.md`, `outputs/content-exemplar.md`, `outputs/review-verdict.md`
(`agent_runtime_wiring.py:916-920`).

**Source**: `platform/api/clue_api/agent_registry_wiring.py:441-565`;
`platform/api/clue_api/agent_runtime_wiring.py:394-412, 695-704, 916-1085`;
`platform/agents/clue_agents/runtime.py:101-118`;
`platform/api/clue_api/conversation_turns.py:150-176`;
`platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml` (`delegation_roles`, `delegation_tool_grants`, `max_delegation_depth`, `max_delegations`).


---

# Part 7 — Cross-cutting


---

# Composition reality — which granted tools are actually live on the production worker

Every tool is registered in **every** process, by design, because
`build_agent_profile_registry` does a strict set-equality audit against `C6_AGENT_TOOL_AUTHORITY`
(`agent_registry_wiring.py:726-730`) — a registry whose shape depended on a flag would make
flipping that flag an `AgentCatalogError` at boot. So a capability the deployment does not have is
expressed as a **registered tool that refuses in `preconditions`**, never as an absent tool. The
practical consequence for the manual: several granted, advertised tools refuse every call on a
normal deployment.

The production project-conversation worker builds its registry at
`platform/api/clue_api/fleet_main.py:961-997` (`build_toolbelt(...)`), and the `AGENT_TURN` handler
is composed against that same registry object *before* `register_execution_control_tools` widens it.

## What `fleet_main` passes, and what it does not

| `build_toolbelt` keyword | Passed by `fleet_main`? | Consequence for a granted tool |
| --- | --- | --- |
| `arv2_account_launch` | yes (behind `arv2_account_research_enabled`) | `launch_arv2_account_research@1`, `launch_arv2_person_research@1` live; else `arv2_account_research_not_composed` |
| `arv2_discovery_launch` | yes (behind `arv2_discovery_enabled`) | `launch_arv2_discovery@1` live; else `arv2_discovery_not_composed` |
| `arv2_reads` | yes ("composed with no flag of its own") | the three reads live; else `arv2_reads_not_composed` |
| `icp_authoring` | yes | `author_icp_document@1`; else `icp_authoring_not_composed` |
| `persona_requests` | yes | `request_persona_synthesis@1`; else `persona_synthesis_not_composed` |
| `project_documents` | yes | `write_project_document@1`; else `project_documents_not_composed` |
| `storage` | yes | `open_icp_confirmation_gate@2`, `open_product_set_selection_gate@1`, `inspect_statement_history@1` get their evidence/document reader |
| `research_directive_memory_write_factory` | yes (`memory_write_factory_builder(settings, gateway)`) | `draft_account_research_directive@5`; else `memory_write_not_configured` |
| `research_view_composer` | yes, *if* `research_views is not None` | `get_research_view@1`; else `research_view_not_configured` |
| **`ingestion_engine`** | **NO** — grep for `ingestion_engine` in `fleet_main.py`, `projections_main.py` and `app.py` returns **zero hits** | `submit_ingestion@1` refuses `ingestion_not_configured` ("the ingestion engine is not configured at the API composition root") on **every** call, after the artifact-existence check passes. The skill teaches this tool in §6. |
| `proposal_credential_ready` / `proposal_personal_source_allowed` | NO | affects the `decide_*` tools (human-only, ungranted), not `propose_field`/`propose_source` |
| `stage0_memory_write` / `stage0_memory_write_factory` | NO | `record_interview_answer@1`'s memory route is unconfigured — and the skill already says "There is no memory route on this surface" (§6) |
| `committee_sources`, `channels`, `independent_contact_research`, `targeted_enrichment_starter`, `account_gap_enrichment_starter`, `entity_research_launches` | NO / old-lane | all feed ungranted tools |

## Flags that silence a granted tool

Read off `.env.example` and the lane's current `.env` (parity rule):

| Flag | `.env.example` | current `.env` | Effect on a granted tool |
| --- | --- | --- | --- |
| `CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED` | `true` | `true` | off ⇒ `lane_disabled` on both launches |
| `CLUE_ARV2_DISCOVERY_ENABLED` | `false` | `true` | off ⇒ `arv2_discovery_not_composed` |
| `CLUE_C7_RESEARCH_VIEW_READ_ENABLED` | `false` | `false` | **off today** ⇒ `get_research_view@1` refuses `research_view_feature_disabled` ("research-view snapshot composition is disabled in this process") on every call |
| `CLUE_C7_WORKSPACE_CANARY_IDS` | — | — | a non-empty canary set makes `get_research_view` refuse any workspace outside it (`_canary_failure`) |
| `CLUE_VERIFICATION_ENABLED` | `false` | `false` | **off today** ⇒ `entailment_judge = None` in `build_toolbelt` (`toolbelt_wiring.py:2736-2742`), so `record_interview_answer@1` cannot admit a typed (bool/number/list/object) claim value — "a typed value is then refused rather than written unvouched-for" |
| `CLUE_DESIGN_RUNTIME_ENABLED` | `1` | `1` | off ⇒ `open_design_leg@4` refuses `design_leg_runtime_not_configured`; no storage ⇒ `design_leg_storage_not_configured` |
| `CLUE_BUDGET_CONTROLS_ENABLED` | see `.env.example` | — | threaded into `register_agent_gate_tools` and the entity-research launch tools; the surface framing sentence still says "when the pilot budget gate is disabled" |

**Source**: `platform/api/clue_api/toolbelt_wiring.py:2625-2715` (the `build_toolbelt` docstring and
signature) and `:2716-3105` (the registration body); `platform/api/clue_api/fleet_main.py:961-997,
1063-1075, 1125-1160`; `platform/api/clue_api/ingestion_tools.py:144-235`;
`platform/api/clue_api/research_view_tools.py:212-240, 297-345`; `.env.example`; `.env`.


---

# Summary table — all 21 granted tools

"Spends money?" means *the call, or what the call sets in motion, buys something from an external
provider or a paid model completion*. Note that `effect_class` and real spend do not coincide: all
three ARV2 launches are `SPEND` yet `estimate()` returns `ToolEstimate.free()` (zero cents),
because the money is spent later by the fleet jobs the launch queues.

| # | Tool | Effect class | Opens a human gate? | Spends money? | Taught in skill |
| --- | --- | --- | --- | --- | --- |
| 1 | `author_icp_document@1` | `write` | no | no | §5b (called at line 153); §3 routes to it |
| 2 | `draft_account_research_directive@5` | `write` | no | no | **not taught** |
| 3 | `get_research_view@1` | `read` | no | no | **not taught** |
| 4 | `inspect_statement_history@1` | `read` | no | no | **not taught** |
| 5 | `launch_arv2_account_research@1` | `spend` | no | **yes** — queues one provider-spending research job per account | §7 |
| 6 | `launch_arv2_discovery@1` | `spend` | no | **yes** — buys a long list and verifies it company by company | §7b |
| 7 | `launch_arv2_person_research@1` | `spend` | no | **yes** — one provider-spending job per named person | §8 |
| 8 | `open_design_leg@4` | `write` | no (opens a design *leg*, not a gate) | no — "Opening a leg spends nothing and runs no design turn" | **not taught** |
| 9 | `open_directive_confirmation_gate@1` | `write` | **yes** | no | **not taught** |
| 10 | `open_icp_confirmation_gate@2` | `write` | **yes** | no | §5 (called at line 135); §3, §5b route to it |
| 11 | `open_product_set_selection_gate@1` | `write` | **yes** | no | §4 (the whole section) |
| 12 | `propose_field@2` | `write` | no | no (a proposal grants no authority) | §6, one line |
| 13 | `propose_source@1` | `write` | no | no | §6, same line |
| 14 | `read_account_research@1` | `read` | no | no | §7c |
| 15 | `read_arv2_account_research_run@1` | `read` | no | no | §7 ("Use it when the human asks how it is going") |
| 16 | `read_discovery_run@1` | `read` | no | no | §7b and §7c |
| 17 | `read_project_accounts@1` | `read` | no | no | §7c |
| 18 | `record_interview_answer@1` | `spend` | no | **yes when a typed value is sent** — the M9.3 faithfulness judge is one model completion; disabled today (`CLUE_VERIFICATION_ENABLED=false`) | §6 (the whole section) |
| 19 | `request_persona_synthesis@1` | `spend` | no | **yes** — queues a background onboarding persona turn that spends | §5c |
| 20 | `submit_ingestion@1` | `spend` | no | in principle yes; in practice it refuses `ingestion_not_configured` at every root | §6, one line |
| 21 | `write_project_document@1` | `write` | no | no | §6b (the whole section) |

Framework tools, for completeness: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`,
`write_todos` — no effect class, no gate, no spend, taught in §1 (read the brand's knowledge) and
§1's batching rule; and `finalize_turn`, the mandatory terminal action, whose fields §4/§5/§5b/§6b
prescribe. `delegate_specialist` is not installed on this surface.

By effect class: **6 `read`**, **10 `write`**, **5 `spend`**, **0 `steering`**.
Three tools open a human gate. Every tool pins `("project",)` except
`draft_account_research_directive@5` (`("project", "product", "icp", "field_registry", "source_registry")`),
`open_directive_confirmation_gate@1` (`("project_run", "research_directive")`),
`get_research_view@1` (`("project_run", "field_registry", "verification_policy")`),
`propose_field@2` (`("proposal_policy", "brand", "field_registry")`),
`propose_source@1` (`("proposal_policy", "brand", "source_registry")`),
`record_interview_answer@1` (`("artifact_input", "stage0_skill", "memory_switch")`) and
`submit_ingestion@1` (`("artifact_input", "ingestion_policy", "brand")`).
No granted tool declares `"product_kb"`, so `_tool_admitted`'s constitution-dependent hiding
(`agent_runtime_wiring.py:706-718`) never removes one of them.


---

# Registered in the toolbelt but NOT granted to head-of-abm

`C6_AGENT_TOOL_AUTHORITY` (`platform/api/clue_api/agent_registry_wiring.py:131-411`) maps every
registered tool name to the roles that may call it; `()` means *"structurally absent from every
current model surface"*. `build_agent_profile_registry` refuses to compose when
`set(tool_registry.names()) != set(C6_AGENT_TOOL_AUTHORITY)` (line 726), so the map is a complete
statement of the platform's write surface, not a convenience list. Granting is never a dict edit —
it requires a new reviewed profile version **and** moving `PROJECT_CONVERSATION_AGENT_PROFILE_ID`.

Per-address overrides live in `_roles_for` (`agent_registry_wiring.py:645-658`): `propose_field` is
granted only at `@2`; `draft_account_research_directive` only at `@5`; `open_icp_confirmation_gate`
only at `@2`; `research_account_gaps` and `profile_contact` are `()` at every version.

## Relevant to project conversations

| Tool | Why ungranted (per the code comments) |
| --- | --- |
| `create_thread`, `archive_thread`, `rename_thread`, `set_thread_pinned` | "FI Lane D D0 / REQ-21 thread shell. Empty for now — the tools exist and are invocable by the authenticated chat surface, but no *model* surface has been given thread management yet. They are deliberately NOT in `_HUMAN_ONLY_TOOLS`: REQ-21 anticipates an agent filing or splitting its own threads, so this is an ungranted capability, not a human-authority gate." |
| `rename_project` | `()` with no comment — same thread/project-shell family. |
| `list_client_knowledge`, `inspect_client_claim` | "ARV2 onboarding O6 drops five of them at `head-of-abm@v44`: they all read the Client-KB / Product-KB claim surfaces, and the new lane's Stage-0 knowledge is brand knowledge documents the agent reads off its own workspace instead." Reserved reason: `superseded_by_onboarding_v2`. |
| `list_product_knowledge`, `inspect_product_claim` | Same sentence — the Product-KB reads. Also gated at the per-turn level: `_tool_admitted` hides any descriptor whose `pin_requirements` contains `"product_kb"` unless the constitution carries a product scope (`agent_runtime_wiring.py:706-718`). Reserved: `superseded_by_onboarding_v2`. |
| `inspect_readiness_history` | Same drop; only `inspect_statement_history` survived, "it reads what the human said in this conversation, which the new lane still records through `record_interview_answer`." Reserved: `superseded_by_onboarding_v2`. |
| `confirm_icp`, `confirm_project_product`, `confirm_account_research_directive`, `decide_field_proposal`, `decide_source_proposal`, `override_stage0_readiness`, `submit_tier_checkpoint`, `submit_project_checkpoint`, `pause_run`, `resume_run`, `adjust_budget` | In `_HUMAN_ONLY_TOOLS` (`agent_registry_wiring.py:577-593`). The agent proposes and presents; only the human decides. This is why `propose_field`/`propose_source` are granted but their `decide_*` siblings are not, and why the gate tools open a gate the agent cannot answer. |
| `open_icp_confirmation_gate@1` | Registered and frozen for replay only. "`@1`'s subject — a draft `icp_spec` row — is not written on this lane at all, so the grant moves to `@2`." |
| `open_product_selection_gate` (single-product) | "dropped at v44, superseded by the set-valued gate below. A project targets a SET of products, and the candidates come from the brand's own product rows." Reserved: `superseded_by_onboarding_v2`. |
| `open_discovery_configuration_gate` | "Discovery scope is not configured from the Stage-0 conversation on the new lane — the human attaches the accounts to the turn." Reserved: `superseded_by_onboarding_v2`. |
| `evaluate_stage0_readiness`, `override_stage0_readiness` | "There is no readiness check on the new lane — the brand's knowledge documents either exist or they do not, and the agent says which." |
| `start_recon`, `submit_onboarding_input` | "There is no recon on this surface — onboarding produced the brand's knowledge documents before the conversation ever opened." `submit_onboarding_input`'s "only consumer was `start_recon`." |
| `synthesize_icps` | "The ICPs are written by the onboarding synthesis agent into the brand's knowledge documents; the Head of ABM proposes from those files and can never author one." (v46 then gave it `author_icp_document`, which writes a *proposed* document instead.) |
| `launch_account_research`, `launch_selected_account_research`, `launch_contact_research`, `read_account_research_run`, `read_contact_research_run` | Founder ruling 2 (2026-09-10): "`head-of-abm@v44` runs one research lane, and it is the ARV2 pair … these three launches start entity-research fleet jobs the new lane does not use, and the two run reads answer about `account_research_run` rows it never writes." Reserved: `superseded_by_onboarding_v2`. |
| `start_confirmed_project_run`, `start_project_run` | "The new lane launches research per account through `launch_arv2_account_research`, not by starting a phase-machine project run." `start_project_run` reserved `legacy_unconfirmed_entry_forbidden`. |
| `discover_accounts`, `import_accounts`, `score_accounts`, `estimate_project` | Reserved `post_stage0_not_admitted` — the old discovery/scoring pipeline. |
| `enrich_account_gaps`, `enrich_selected_accounts`, `launch_account_deep`, `run_deep_account`, `resolve_committee`, `profile_contact`, `research_account_gaps`, `approve_contact_research_selection`, `compose_dossier`, `recheck_research_view` | `()` — the old research lane's per-account machinery. `research_account_gaps` and `profile_contact` are `()` at *every* address by `_roles_for`. |
| `reverse_profile` | Reserved `superseded_by_governed_stage0_recon`. |
| `retry_ingestion` | Reserved `replay_not_certified` — `submit_ingestion` is granted, its retry sibling is not. |
| `synthesize_entity_prose` | "Machine-invoked only: the post-finalize fleet step offers a just-terminal research job to it. It is deliberately absent from every model surface — an agent that could summarize on demand could spend on prose for a job the research engine never finished." |
| `synthesize_value_narrative` | "Machine-invoked only, for the same reason one slice stronger: positioning spends one completion (and one judge call) *per committee persona*, so an on-demand agent reach for it is an unbounded spend on research the engine may never have finished." |
| `run_verification` | Granted to `AgentRole.RESEARCH` only — reachable through delegation, which this surface withholds. |
| `compose_handoff`, `compose_contact_content_handoff` | Granted to `CONTENT_DRAFTER` / `REVIEWER` only — likewise unreachable here. |
| `exa_search_evidence` | `AgentRole.ONBOARDING_SYNTHESIS` only: "the synthesis agent's one SPEND tool — a single fixed deep-reasoning search for first-person evidence, at most once per persona role. No other role may buy it." |
| `finish_design_leg` | `AgentRole.DESIGN` only: "the leg-level exit … the only path to a closed leg." The Head of ABM opens a design leg but cannot close one. |
| The ~45 `design_*` write tools | `AgentRole.DESIGN` only (P3.3), except `design_set_web_noindex` (`()` + `_HUMAN_ONLY_TOOLS` by founder ruling R-F1) and the four ad-assets tools `design_ingest_ad_assets` / `design_record_ad_creatives` / `design_publish_ad_dna_card` / `design_link_ad_pregenerated_assets` (`()`: "the lane is populated by an onboarding JOB … No model surface plans a harvest, so handing these to one would be authority nobody asked for."). |
| `start_recipe_execution`, `pause_recipe_execution`, `resume_recipe_execution`, `decide_recipe_gate`, `pin_execution_as_recipe`, `advance_project_phase`, `apply_run_control`, `release_run_control`, `acknowledge_run_escalation` | Defined in `platform/api/clue_api/execution_tools.py` and **absent from `C6_AGENT_TOOL_AUTHORITY`** (grepped each name: 0 hits). They *are* registered into the same `ToolRegistry` object, by `register_execution_control_tools` — but deliberately **after** the agent platform components are composed. `fleet_main.py:1063-1069` states the rule: *"ORDERING IS LOAD-BEARING: this must compose BEFORE `register_execution_control_tools` widens the shared registry. `build_agent_platform_components` audits the registry against `C6_AGENT_TOOL_AUTHORITY`, whose reviewed surface is exactly the model-facing toolbelt … the run-control tools registered below are the human/API run-control plane sharing this registry object, not model-surface tools, and composing after them fails the audit at boot."* |


---

# Inconsistencies between what the surface says and what the code does

These are the cross-cutting ones found while reading the wiring. Per-tool docstring-vs-behaviour
mismatches are listed after them, lifted from each tool's own section.

## 1. The skill teaches 16 of the 21 granted tools; 5 are advertised but untaught

`head-of-abm@v49`'s `tools:` has 21 entries. `stage0-interview@v26`'s `tools:` front matter has 16.
The five the agent holds and the skill never mentions:

- `draft_account_research_directive@5`
- `open_directive_confirmation_gate@1`
- `get_research_view@1`
- `inspect_statement_history@1`
- `open_design_leg@4`

They are still offered to the model — the capability map is generated from the *profile*, and the
skill itself says the map is authoritative (SKILL.md §82) — so the model's only guidance for those
five is the one-line `model_description` on the LangChain tool. Skill §10 ("What you cannot do")
does not mention design legs, research directives or the research view at all.

## 2. The directive pair is a dangling grant: its consumers are ungranted on every surface

`draft_account_research_directive@5` writes a directive; `open_directive_confirmation_gate@1`
presents it for approval. The thing a confirmed directive authorizes is
`confirm_account_research_directive` (human-only, `_HUMAN_ONLY_TOOLS`) and then
`launch_account_research` / `launch_contact_research` — all three of which
`C6_AGENT_TOOL_AUTHORITY` sets to `()` with the reserved reason `superseded_by_onboarding_v2`
(founder ruling 2, 2026-09-10). The lane the agent *can* launch says so explicitly
(`arv2/account_research_launch.py:17-19`):

> "It needs only accounts, an ICP artifact ref, and a selection version … No `icp_spec` row, no
> `account_research_directive`, no Stage-0 pin on the project run. The old Stage-0 launch machinery
> is not a dependency of this lane and must never become one."

`draft_account_research_directive@5`'s `pin_requirements` are
`("project", "product", "icp", "field_registry", "source_registry")` — `product` singular and `icp`
(the `icp_spec` row), both of which the ARV2 lane replaced with a product *set* and an ICP
*document*. So the agent can draft and gate a directive nothing downstream on its own surface can
consume.

## 3. `get_research_view@1` is granted, but disabled by flag and pinned to a `project_run`

`pin_requirements = ("project_run", "field_registry", "verification_policy")`, and its input carries
a `project_run_id` — a phase-machine run row. The ARV2 lane creates no `project_run`
(`start_confirmed_project_run` and `start_project_run` are both ungranted,
`superseded_by_onboarding_v2` / `legacy_unconfirmed_entry_forbidden`). On top of that,
`CLUE_C7_RESEARCH_VIEW_READ_ENABLED` is `false` in both `.env.example:347` and the lane's `.env:85`,
so the tool refuses `research_view_feature_disabled` before it reads anything, and a non-empty
`CLUE_C7_WORKSPACE_CANARY_IDS` would narrow it further. v48/v49 added `read_account_research@1` as
the ARV2-native answer to the same question.

## 4. `submit_ingestion@1` is taught by the skill but has no engine anywhere

Skill §6: *"An upload already captured in the workspace goes through `submit_ingestion` with its
material context."* `build_toolbelt(ingestion_engine=...)` is never passed at any composition root
— grepping `ingestion_engine` in `fleet_main.py`, `projections_main.py` and `app.py` returns zero
hits — so `SubmitIngestionTool(None)` refuses `ingestion_not_configured` ("the ingestion engine is
not configured at the API composition root") on every production call. Its retry sibling
`retry_ingestion` is ungranted anyway (`replay_not_certified`).

## 5. The skill promises a routing-receipt guard the production surface does not install

SKILL.md §6, last line: *"The platform refuses a `completed` or `awaiting_input` finalization of a
substantive turn that produced no routing receipt, and the refusal is visible to you."*
That refusal is `Stage0RoutingReceiptGuard` (`stage0_trial.py:212-253`), and its only wiring is
`stage0_trial.py:793` — the **trial** surface. The production project-conversation runner calls
`self._engine.execute(...)` with no `completion_guard`
(`agent_turn_fleet_wiring.py:854-864`; `conversation_turns.py:291` defaults it to `None`), so on the
real surface nothing enforces the sentence. The same sentence has been in the skill since v22.

## 6. The surface's framing sentence is three profile versions stale

`C6_SURFACE_POLICIES`' `project_conversation` framing (`agent_registry_wiring.py:557-564`) still
describes the retired directive flow — "can draft research direction, present its confirmation gate,
or launch an exact Account set … when the pilot budget gate is disabled" — and mentions none of
what v45–v49 added: discovery, ICP authoring, persona requests, the project plan, or the three
reads. It is injected verbatim into the system prompt's Surface-policy block, so the model reads a
description of its own surface that predates most of its tools. The adjacent code comment
(`:534-540`) has been updated; the string has not.

## 7. `record_interview_answer@1` cannot accept a typed value on the current deployment

`build_toolbelt` composes the entailment judge as
`None if gateway is None or not resolved_settings.verification_enabled else FaithfulnessClaimEntailmentJudge(...)`
(`toolbelt_wiring.py:2736-2742`), and `CLUE_VERIFICATION_ENABLED` is `false` in both
`.env.example:338` and `.env:76`. The composition comment concedes the consequence: *"Without a
gateway there is no judge, and a typed value is then refused rather than written unvouched-for."*
Skill §6 tells the agent "A typed value (true or false, a number, a list) is admitted only when the
quoted sentence supports it" — which is true of the contract but not reachable today.

## 8. `grep` is not a regex search, `glob` is not a path glob, and `ls` never reports a directory

`AnchoredAgentWorkspaceBackend.grep` (`workspace.py:804-819`) tests `if pattern in line` — plain
substring. `glob` (`:790-802`) uses `fnmatch.fnmatch` over a flat file list, so `*` crosses `/` and
`**` is only two stars. `ls` (`:741-750`) hard-codes `"is_dir": False` on every entry. None of this
is stated anywhere the model can read: the capability map says only "relative reads inside
authorized virtual prefixes".

## 9. `edit_file`'s `replace_all` is advertised by the framework and refused by the platform

`edit(..., replace_all: bool = False)` returns
`EditResult(error="permission_denied: replace_all is not available")` for `True`
(`workspace.py:774-781`). The parameter is in the tool schema the model sees, so it is a
discoverable-only-by-failing constraint.


---

# Per-tool docstring-vs-code discrepancies

Each block is lifted from that tool's own section above. `- **Discrepancy**` bullets record places
where a `model_description`, a class/module docstring, a declared `replay.durable_identity`, an
output-model field or a skill sentence disagrees with what the code actually does.

## `read_project_accounts`

- **Discrepancy**: (1) The row-order comment says "The row order is the accounts screen's own default (``created_at DESC, id DESC``), so 'the first ten accounts' means the same ten to the agent and to the marketer" — the SQL orders by `a.created_at`/`a.id` (**`account_entity`**, i.e. when the company record was created), not by `pa.added_at`, which is the field the row actually reports as "how it got here"; paging is therefore not ordered by the join date the output surfaces. (2) `model_description` enumerates research status and "how it joined the project" but never mentions `refreshing`, which the output always carries — the model is not told the field exists except through the schema. (3) `research_status=str(row["research_status"] or "not_started")` folds *any* falsy value (NULL **or** an empty string) to `not_started`; the comment justifies only the NULL/no-job case.

## `read_account_research`

- **Discrepancy**: (1) `model_description` contains a duplicated word — "section='claims' returns the the claims the account pages show" (read_tools.py:1000). (2) `model_description` states flatly that "sensitive, unverified tier-4 and outreach-unsafe claims are held back and counted in 'excluded'", but the unverified arm is conditional on deployment posture: `_account_claims` only applies it when `settings.verification_enabled` is true, so on a non-verifying deployment unjudged tier-4 syntheses are served and `excluded["unverified"]` stays 0. (3) `AccountClaimView.verification_status`'s comment enumerates "``unverified`` / ``verified`` / ``rejected``", but `clue_core.VerificationStatus` also has `FLAGGED = "flagged"`, which nothing in this path filters out — a flagged claim is servable and would render a fourth value the comment does not list. (4) `verification_status: str | None` and `outreach_safe: bool | None` are typed optional, yet `_account_claims` always writes `str(...)`/`bool(...)` — the `None` arm is unreachable in production code. (5) `ReadAccountResearchOutput.truncated`'s comment ("The account holds more claims than one read serves; narrow with ``field_prefix``") describes only the claims branch; on the overview branch it is hard-wired `False` even when a section body was clipped — an overview that lost its tail reports `truncated=False` with `body_truncated=True` on the section. (6) The tool-level docstring/description never mentions that the claims read is workspace-wide rather than project-scoped; only the internal `_account_claims` docstring says so ("The claims read spans every project of the workspace that researched this account"), while the tool declares `pin_requirements = ("project",)`.

## `read_discovery_run`

- **Discrepancy**: (1) `DiscoveryRunView.candidates` is sliced by `candidate_limit` **after** sorting, but `candidate_total` is `len(candidates)` of the workspace-filtered list, not the run's stored candidate count — so a run whose rows carry a foreign `workspace_id` (the case the code's own comment says the single-column FK permits) reports a `candidate_total` smaller than the run truly holds. The field comment ("The run's whole candidate count") is true of what this workspace may see, not of the run. (2) The output exposes `fit` and `disposition` but drops `verdicts` (the per-gate quotes and urls), so the agent cannot cite evidence for a candidate from this read; neither the `model_description` nor the field comments say so. (3) `ReadDiscoveryRunOutput` carries no `relaxed_enabled`, `strict_count`, `analyzed` or `recall_estimate` from `DiscoveryRunRow` — only `relaxed_requested` — so "the run finished short, can we relax?" is answerable only from `relaxed_requested`, while the skill (§7b) tells the agent to discuss relaxed passes.

## `read_arv2_account_research_run`

- **Discrepancy**: (1) The declared `output_model` is never used — `invoke` returns a hand-built `references` dict, so nothing validates the payload against `ReadArv2AccountResearchRunOutput` (contrast the three `arv2/read_tools.py` tools, which construct their output model and `model_dump()` it). The pinned `output_schema_sha256` in the skill/profile therefore describes a shape the code asserts by convention only. (2) The `model_description` promises "the state of each account's job", but `list_jobs` returns **every** job of the run including `subject_type="person"` committee/person jobs (`committee_step.py:209-222` writes them under the same `run_id`), and the output carries neither `subject_type` nor `subject_entity_id` — so several rows can share one `account_entity_id` and read as duplicate account jobs. (3) A malformed `run_id` raises an unhandled `ValueError` from `UUID(inputs.run_id)` inside `invoke` rather than a typed refusal — its ARV2 read siblings deliberately fold a malformed id into `account_not_found` / `discovery_run_not_found`. (4) The tool declares `pin_requirements = ("project",)` but never resolves or checks a project: scoping is workspace-only, so a run of a *different project of the same workspace* is served without comment. (5) The `model_description` says the read includes "the failure code of anything that needs review" — `failure_message` (the human-readable half of `JobRow`) is dropped, and `stage` (the progress field the research card reads) is not served either, so "how is it going?" is answerable only at job granularity.

## `launch_arv2_account_research`

- **Discrepancy**: (a) `model_description` says the run is "pinned to the confirmed ICP artifact digest", which reads as though the caller *selects* the ICP; in code the caller-supplied `icp_artifact_key`/`icp_artifact_sha256` are only a cross-check against the project's own pin — any other artifact is refused `icp_artifact_not_project_pin` (`:520-534`), and the run's `icp_key`/`icp_version` are read out of the pinned document's front matter, never from the call. (b) The tool is `effect_class = SPEND` yet `estimate()` reports `cost_cents=Decimal(0)`; the zero is a deliberate "no honest prior", not a free call (comment `:1214-1217`). (c) A malformed uuid in `account_entity_ids` escapes as a bare `ValueError` from `invoke` rather than as one of the typed refusals the module docstring promises ("**Every refusal is typed**", `:11-14`). (d) `LaunchArv2AccountResearchOutput` is declared but `invoke` returns `ToolResult.references` directly — the typed shape is enforced only by the runner's `validate_tool_output_references` (`runner.py:48-64`), not inside the tool.

## `launch_arv2_person_research`

- **Discrepancy**: (a) `model_description` says the run is pinned "to the project's currently confirmed ICP and product selection"; in code the ICP is the project's **pin** (`current_project_icp_pin` → the exact version a human pinned, explicitly *not* "the newest confirmed"), while only the product selection is the *current* one (`current_project_product_set`) — two different resolution rules under one phrase. (b) `model_description` says "It researches existing contacts and never creates a person" — true of entities, but the launch does perform a durable **claim write** (the `contact.persona` committee seat) for any named person who holds none, which the description mentions only as "the committee seat each named person is given". (c) The tool is `effect_class = SPEND` with `estimate()` reporting `cost_cents=Decimal(0)`. (d) A malformed uuid in `contact_entity_ids` escapes as a bare `ValueError` from `invoke`, contradicting the module docstring's "**Every refusal is typed**" (`:11-14`). (e) `Arv2LaunchRefused`'s docstring enumerates the person launch's added codes as "`no_contacts`, `contact_not_found:<id>`, `contact_merged:<id>`, `contact_without_account` and `product_set_not_confirmed`" — accurate, but the shared list above it includes `product_selection_version_unknown` and (for the account launch) `icp_artifact_not_project_pin`, neither of which this path can raise.

## `launch_arv2_discovery`

- **Discrepancy**: (a) `model_description` says "The ICP, the gates and the provider ask all come from the pinned document and the deployment's settings — **never from this call**", but `target_count` and `relaxed_enabled` *are* taken from this call and are both part of the run's identity digest (`_request_sha256`, `:441-449`); only `strict_count` (the literal provider ask) and the criteria gate keys are settings/document-resolved on this path. (b) `Arv2DiscoveryRequest`'s docstring says "Every `None`/empty field falls back to the deployment's settings", yet the tool always passes a concrete `relaxed_enabled` (its input default is `True`, not `None`), so `settings.arv2_discovery_relaxed_auto` can never take effect through this tool — only through CLI/direct callers. (c) The tool is `effect_class = SPEND` while `estimate()` reports `cost_cents=Decimal(0)`; the zero is a deliberate "no honest prior", not a free run. (d) `Arv2DiscoveryRefused`'s docstring lists `run_not_found`/`run_not_finished` as codes of this module, but no toolbelt surface can reach them — `request_relaxed_pass` has no tool, so the agent can never produce (or be shown) those two refusals even though skill §7b talks about the relaxed pass.

## `author_icp_document`

- **Discrepancy**:
  1. The `model_description` says "The document must carry the icp-definition front matter: kind, icp_key, product_ids, hard_gates, exclusions, persona_map, qualifier_fields, then the body." — but `_validate_front` (`icp_authoring.py:238-273`) enforces **only** `kind`, `icp_key`, `product_ids` and `hard_gates`. `exclusions`, `persona_map` and `qualifier_fields` are never checked; a document omitting all three is accepted. The service docstring concedes this ("Deliberately a floor, not a schema"), so the model-facing "must" overstates the enforced contract.
  2. Skill §5b tells the agent "A refusal names what to fix: a key already taken, a missing gate, **a product id the catalog does not carry**." No code path validates `product_ids` against the brand's catalog — `_validate_front` only requires a non-empty list of non-empty strings. That third refusal does not exist in this tool.
  3. `derived_from_icp_key` carries no format constraint while `icp_key` carries `pattern=ICP_KEY_PATTERN, max_length=60`. A malformed lineage key is not refused as invalid; it simply fails the existence lookup and comes back as `derived_from_not_found`.

## `request_persona_synthesis`

- **Discrepancy**:
  1. `PersonaSynthesisRefused`'s own docstring enumerates four codes (`icp_not_pinned_for_project`, `persona_run_already_open`, `brand_not_onboarded`, `enqueue_failed`) and claims "``code`` is stable and machine-readable", but the service raises a **fifth**, `persona_run_settled` (`persona_request_tools.py:211-215`), which the docstring never mentions. An agent (or operator) reading the exception contract would not know that code exists.
  2. `effect_class = ToolEffectClass.SPEND` while `estimate()` returns `cost_cents=Decimal(0)`. Deliberate and commented (the spend is the downstream persona turn, settled against that run's own budget), but it means the pre-spend prior the UI shows for this tool is zero even though the call is classified as spend.
  3. The `model_description` says the tool is "Refused when the ICP named is not this project's pinned ICP, or when a persona run for it is already open" — it does not mention the `brand_not_onboarded`, `persona_run_settled` or `enqueue_failed` refusals the model can also receive.

## `write_project_document`

- **Discrepancy**:
  1. The declared `durable_identity` is `"presenting turn + document + expected version + body"`, but `plan_document_id` (`arv2/project_documents.py:191-210`) keys on `(turn_id, expected_version or 0, body_sha256)` only — `document` is **not** in the key. Harmless today because `document: Literal["plan"]` admits exactly one value, but the replay audit string names a coordinate the derivation does not use, and it would become wrong the moment a second document type is admitted.
  2. `expected_version or 0` collapses `None` and `0` to the same key component. Unreachable today because the field carries `ge=1`, so `0` cannot be supplied — but the collapse is in the id derivation rather than guarded by it.
  3. The `WriteProjectDocumentInput` docstring says "the path itself are derived from the presenting turn and the rows it names", while in practice the path is not derived at all: it is the hard-coded constant `PLAN_PATH = "project/plan.md"` for the single admissible `document` value.

## `open_icp_confirmation_gate`

- **Discrepancy**:
  1. **A deployment with no storage refuses with a message that is false.** `_resolve` short-circuits `subject = None if self._storage is None else await current_icp_document(...)`, and `None` then raises `icp_document_not_found` with `"this brand has no readable current ICP document for '<key>'"`. When storage is absent, that statement is not true — nothing was looked up. Every ARV2 neighbour (C1/C2/C3) refuses with a distinct `*_not_composed` code in exactly this situation; this tool has none.
  2. `icp_key` here is `Field(min_length=1, max_length=200)` with **no pattern**, while `author_icp_document@1` and `request_persona_synthesis@1` both constrain the same concept to `pattern=ICP_KEY_PATTERN, max_length=ICP_KEY_MAX_LENGTH` (60, lowercase kebab-case). The three tools disagree on what an `icp_key` may be; the gate's looser bound is inherited from the `@1` schema.
  3. `created` is returned on the output model, but `ToolResult.replayed` is left `False` even on a replay (`invoke` does not pass `replayed=not created`), unlike C1, C2 and C3, which all propagate their replay flag to the envelope. A caller reading `ToolResult.replayed` cannot tell a replayed gate presentation from a fresh one.
  4. The `model_description` says "Present one of this brand's ICP knowledge documents", but `current_icp_document` is called with `project_id=turn.project_id`, so a project-local variant at that key wins over the brand's document — as the inline comment states. The model-facing wording understates the project-scoped resolution.

## `draft_account_research_directive`

- **Discrepancy**:
  - The class-level `model_description` the model actually sees is **v1's**, inherited unchanged by @2–@5. It speaks of "the conversational working plan" and never mentions `profile="comprehensive"`, the omittable `field_keys`, or the renamed `directive` field — the v4/v5 breadth contract exists only in class docstrings the model never reads. The v5 docstring itself records the consequence of that mismatch at @4: *"the skill says 'no field list', the schema says the list is mandatory, and any non-empty value is refused as ambiguous breadth (found live in the Slice B browser gate; the agent looped plan-rejected and gave up)."*
  - `pin_requirements` advertises `("project", "product", "icp", "field_registry", "source_registry")` but the tool body validates the field and source registries itself via `validate_research_directive_draft` — the pins are declared for the C5.2 compatibility loader, not read by this tool.
  - `validate_research_directive_draft` refuses unless `project.product_id == product_id` (`"research directive product is not selected by the project"`), i.e. it reads the **single**-product `project.product_id` column, while the ARV2 lane this profile otherwise uses confirms a product **set** (`project_product` / `confirm_project_product_set`, see D3). The two product models are not reconciled in this tool's path.
  - v1/v2's `preconditions` recompute `research_directive_draft_request_sha256` from the **v2-shaped** downcast input (`_v2_input`), so the replay identity of a v5 call is the v2 request hash — deliberate per the v4 docstring (*"a v3 draft replays as a v3 draft"*) but it means `profile` and the draft-only committee validator are outside the replay digest.

## `open_directive_confirmation_gate`

- **Discrepancy**:
  - The module docstring says the account set is proposed by the agent and the *addressee/amount/subject* are derived — but the **account set itself is model-authored** (`account_entity_ids`) and is only checked for canonical shape and uniqueness here; its membership in the directive's scope is enforced indirectly, by `compose_account_research_directive` raising `"account is outside the directive's explicit scope"` inside the estimate (surfaced as `research_directive_invalid`, not as a dedicated code).
  - The docstring's third guarantee — *"The subject cannot drift… an answer that names a different digest is refused by the turn route"* — is true for the digest, but the **amount** half of staleness is disarmed when `budget_controls_enabled` is off: the route then skips the `GATE_AMOUNT_STALE` check entirely (its own comment calls the digest check "the load-bearing half").
  - `model_description` says the tool "launches nothing", which holds for the tool; but with budget controls **off** the human's approval of this gate does launch (`launch_selected_account_research@1`, one atomic confirm-and-launch in the route). The tool's own copy never says so, so an agent reading only the description will understate what "Approve" does on such a deployment.
  - `replay.durable_identity` names "one turn + one exact directive revision", yet the derived `gate_id` also includes the `subject_ref` **and** the digest but **not** the account set — so two presentations for the same turn+directive with *different* account sets converge on the same gate row, and the first-written `account_entity_ids`/`max_spend_cents` snapshot wins silently (`insert_gate`'s documented "the stored values are authoritative and the caller's recomputed ones are simply discarded").

## `open_product_set_selection_gate`

- **Discrepancy**:
  - The gate is opened with the full default decision vocabulary `("approved", "rejected", "revised")`, but `revised` is unusable in practice for this kind: the route refuses any `revision_request` on a product-set gate (`GATE_REVISION_REQUEST_UNEXPECTED`) and refuses a product choice on a non-approved decision, so a `revised` answer can carry no content at all. Neither the tool nor the skill says so; the skill's §5 "Revised" guidance is written for the ICP gate only.
  - `_resolve()` is executed **twice** on a successful call — once in `preconditions()` and again at the top of `invoke()` (unlike the directive and design-leg tools, `invoke` does not reuse the precondition's resolution), and it opens its own connection each time (`async with self._conn_factory()` inside `_resolve`, separate from the `insert_gate` transaction in `invoke`). The gate row is therefore inserted in a different transaction from the reads that produced its digest, so a catalog change landing between them makes the stored snapshot the winner (`insert_gate` replay semantics) rather than a refusal.
  - The tool's `pin_requirements = ("project",)` while nothing in the input names a project — the project is derived from the trusted turn.

## `open_design_leg`

- **Discrepancy**:
  - The module docstring's @2 paragraph still says *"``doc_kind="scene"`` creation was refused in v1 (@2)… **Superseded 2026-08-23 (genad ruling 1), @3**"* and the @3 paragraph still describes the `ad_format` aperture as if it were live, with only the @4 paragraph reversing it. The refusal codes `design_leg_ad_format_required` and `design_leg_ad_format_invalid` appear **only** in that historical prose — no code path raises them at @4 — so an operator grepping refusal codes will find two that cannot occur.
  - `replay.policy` is `DOMAIN_IDEMPOTENT` and `operation_id_required` is `False`, yet the durable identity is derived from the *presenting turn*, not from `ctx.operation_id`: two different logical operations inside the same turn would converge on the same leg id (the second is served as the existing leg with `created=False`), regardless of a differing brief or document pin.
  - `document_created` is computed per-invocation, not read back from the row, so on a genuine replay it correctly reports `False`; but on the **reopen** path `document_created`/`created` are both `False` while `document_id` still names the original leg's document — the output cannot distinguish "reopened onto an existing document" from "replayed an open leg" except through the `reopened` flag.
  - The output's `bundle_sha256` is read on a **separate** connection (`_bundle_sha` opens its own `conn_factory()`), outside the transaction that persisted the artifact; when the caller's factory is a bound single-connection one this read sees the same transaction, but on a pooled factory an uncommitted bundle would read back `""`.

## `record_interview_answer`

- **Discrepancy**: (1) `effect_class = ToolEffectClass.SPEND` but no `estimate()` override, so the pre-spend prior the UI shows is zero even though the tool can make one judge call per typed claim value. (2) The input model still declares `onboarding_input_id` / `artifact_key` / `answer` with descriptions addressed to the model ("It must exist in this workspace…"), while the agent surface never sees those fields — the docstring itself names the split (C4 recipe path vs agent path). (3) `InterviewStatement.occurrence`'s description says the offsets "index into this exact string" and the input `answer` description still speaks of "quote offsets", but since §6c-a the model supplies no offsets at all — the engine computes them. (4) The `memory` route is fully implemented in the tool, but stage0-interview v26 §6 states "There is no memory route on this surface"; a memory statement on a composition without the `MemoryWriteSeam` is refused `memory_not_configured`.

## `get_research_view`

- **Discrepancy**: (1) Every input field is description-free, so the only model-facing prose is the generated boilerplate `"Invoke exact governed platform tool get_research_view@1."` — the agent is told nothing about what a research view is, which scope ids are trusted authority, or that `project_run_id` must belong to the project. Contrast `Stage0InspectionInput`'s docstring, which makes exactly this point ("a governed tool's model-visible description is generated boilerplate, so the input fields carry the *entire* prose surface"). (2) The tool is granted in profile v49 and to all delegation roles, but is default-off in every process (`c7_research_view_read_enabled=False`), so as composed today a call returns `research_view_feature_disabled` rather than a view. (3) The module docstring says "All three tools delegate to the one deterministic composer/snapshot/re-check path", yet `get_research_view` additionally runs its own raw `research_view_snapshot` lookup to attach `snapshot_id`.

## `inspect_statement_history`

- **Discrepancy**: (1) The input docstring's premise — the field descriptions "are the only place the model can learn that a card `omissions` cursor is resolved by *this* tool" — is undercut by the skill, which never mentions the tool, the card omissions, or when to page history; the wiring comment still claims the deferred grant "landed against profile v10". (2) The wiring comment says both tools are "*not* withheld by the trial's `C6_SURFACE_POLICIES` entry … because they are read-only, effect-free, page-bounded and fail-closed", and asserts the tools run "inside `recipe0-stage0@4`'s interaction slot" — the current Head-of-ABM surface (profile v49 + skill v26) is a chat surface with no such instruction. (3) `StatementHistoryOutput.statements` is typed `list[dict[str, object]]`, i.e. the per-row shape is untyped in the output schema even though profile v49's changelog makes typed row models the rule for the newer reads — a row-shape change here would not move the pinned output digest.

## `propose_field`

- **Discrepancy**: (1) The module docstring says "Integration registers these four tools centrally after C1→C2 lands. This module intentionally does not edit `build_toolbelt` or the shared router aggregation" — stale: `toolbelt_wiring.py:2886-2889` registers `ProposeFieldTool` as the default and `LegacyProposeFieldTool` as `@1`. (2) `ProposeFieldTool` is wired as `ProposeFieldTool(dynamic_client_kb_materializer=…)` with no `policy=`, so it always runs `DEFAULT_PROPOSAL_POLICY` — `client_field_mode=HUMAN_CONFIRM` and an empty `safe_auto_client_field_contract_hashes`, meaning the entire safe-auto path (and the `dynamic_client_kb_materializer_not_configured` precondition that guards it) is unreachable in the composed process. (3) Neither `scope` nor `payload` carries a model-facing description, so the tool's whole prose surface for a field proposal is the generated boilerplate plus pydantic validator messages — while the sibling authority fields (`brand_id`, `project_id`) do carry descriptions. (4) `FieldProposalOutput` declares `materialization_*`/`claim_ref`/`client_kb_version`/`refusal_code`, but on the default policy `invoke` never populates them.

## `propose_source`

- **Discrepancy**: (1) The module docstring ("Integration registers these four tools centrally after C1→C2 lands. This module intentionally does not edit `build_toolbelt` …") is stale — `toolbelt_wiring.py:2905` registers `ProposeSourceTool()` as the default. (2) `ProposeSourceTool()` is constructed with no `policy=`, so it always runs `DEFAULT_PROPOSAL_POLICY`; with `auto_promote_tier3_sources=False` the auto-promote branch in `propose_source` is unreachable in the composed process and every proposal lands `proposed`. (3) Neither `scope` nor `payload` carries a model-facing description, so the only prose the model sees is the generated boilerplate plus validator messages — including the one rule it is most likely to break (tier is not proposable, which is stated only in a Python docstring the model never reads).

## `submit_ingestion`

- **Discrepancy**: (1) The module docstring says "Central registration is intentionally absent: the C0 treaty assigns that one-line composition to the Phase-C integration branch" — stale: `toolbelt_wiring.py:2913-2914` registers both `SubmitIngestionTool(ingestion_engine)` and `RetryIngestionTool(ingestion_engine)` as defaults. (2) The class docstring lists only two reason codes ("`ingestion_artifact_not_found`, `ingestion_artifact_erased`") while `preconditions` returns four — `ingestion_not_configured` and `ingestion_context_invalid` are undocumented there. (3) `artifact_key`, `declared_context` and every field of `DeclaredMaterialInput`/`IngestionTarget` are description-free, so a model calling this tool is told nothing about where an artifact key comes from or which `document_context` value to pick; only the two trusted-authority fields carry prose. (4) `preconditions` proves the artifact is present and un-erased, then `invoke` re-proves it inside the engine with a different failure species (typed `PreconditionFailure` vs raised `IngestionError`), so the same condition surfaces two different ways depending on which check wins the race.

