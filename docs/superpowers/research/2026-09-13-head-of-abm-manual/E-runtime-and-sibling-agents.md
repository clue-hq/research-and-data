# E — Runtime mechanics and sibling agents

*Operating-manual research, part E. Read-only study of the `research-streaming` worktree at
`/Users/aryankeshri/conductor/workspaces/research-and-data/san-salvador`, 2026-09-13. Every claim
carries a `file:LINE` source; absences are written as "not found" with where they were looked for.
Paths are repo-relative.*

**Subject:** the Head of ABM deepagent — profile `head-of-abm@v49`
(`platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml`), prompt `head-of-abm@v8`, skill
`stage0-interview@v26`, running on the production project-conversation surface
(`PROJECT_CONVERSATION_SURFACE`).

## Contents

1. [The turn lifecycle](#1-the-turn-lifecycle)
2. [Limits and configuration the agent should know about itself](#2-limits-and-configuration-the-agent-should-know-about-itself)
3. [Sibling agents and background work](#3-sibling-agents-and-background-work)
4. [Observability the Head of ABM can use](#4-observability-the-head-of-abm-can-use)
5. [Error vocabulary](#5-error-vocabulary--every-string-the-model-can-receive-as-a-tool-result)
6. [What the agent is never told](#what-the-agent-is-never-told)

### Three corrections to the research brief, up front

1. **`platform/agents/catalog/entity-research/account/v3/manual.md` is the wrong lane.** It belongs
   to the M8D entity-research agent, which is off everywhere
   (`CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=false`, `.env:130`, `.env.example:426`). The live ARV2
   account agent is `entity-research/arv2-account/v1`
   (`platform/api/clue_api/arv2/account_research_catalog.py:33,135`) with a different 12-tool
   surface. §3.1 documents the live one.
2. **`entity-research/person/**` does not exist** and there is no `person_research_*.py` module. The
   live person agent is `entity-research/arv2-person/v1`, and the person path is the *same* driver,
   agent and tools modules dispatched on `job.subject_type`. §3.2.
3. **The profile has no `limits:` block** and no keys named `max_rounds` / `max_runtime_s`. Those
   are the *runtime parameter* names that `max_model_rounds` and `turn_timeout_s` are passed into.
   §2.1.

---

## 1. The turn lifecycle

### 1.1 What a turn physically is

A turn is one row in `agent_turn_submission`, dispatched as one `fleet_task` of kind
`agent_turn`, executed by one fleet worker, and terminated by exactly one call to the
`finalize_turn` tool. Nothing else ends a turn successfully.

| Step | What happens | Source |
| --- | --- | --- |
| 1. Submission | The human POSTs a message. A durable `agent_turn_submission` row is written and the thread's dispatch lock decides whether a task is offered now or the message waits. | `platform/api/clue_api/agent_turn_submission.py` (`dispatch_next_thread_turn`, `lock_thread_queue`), read from `agent_turn_fleet_wiring.py:1362` |
| 2. Task claim | `AgentTurnWorkHandler.handle` claims the `FleetTaskKind.AGENT_TURN` task. | `agent_turn_fleet_wiring.py:1322,1355` |
| 3. Queue-hold check | If the thread carries a `queue_hold_control_id` naming a *different* turn, the task requeues after 1s (`outcome="queue_held"`). | `agent_turn_fleet_wiring.py:1362-1382` |
| 4. Read submission | `get_submission` + `message_artifact_ref` + `submission_context_refs`. Missing row → `UnknownTurnSubmission`. | `agent_turn_fleet_wiring.py:384-395`, `:201` |
| 5. Routing rule | ONE indexed read decides who answers: if the thread has an open design leg, the design deepagent gets the message; otherwise Head-of-ABM does. **No LLM is in this loop.** A gate answer always goes to Head-of-ABM even if a leg is open. | `agent_turn_fleet_wiring.py:406-431` |
| 6. Pending-stop reconciliation | A stop requested before the attempt opened is reconciled first (`_finish_stop`), so recovery never calls a model for a stopped turn. | `agent_turn_fleet_wiring.py:432-436` |
| 7. Stream opened | `TurnStreamEmitter.open` opens this *generation attempt* on the durable outbox before anything runs; a re-claim after a crash opens a distinct attempt and resets whatever the dead one left open. | `agent_turn_fleet_wiring.py:437-451`, `chat/turn_stream.py:221,267` |
| 8. Execution id | `ExecutionId = operation_id_from_key(str(turn_id), _EXECUTION_NAMESPACE_KEY)` — **derived from the turn id, so every retry of a turn reuses the same execution id.** | `agent_turn_fleet_wiring.py:500` |
| 9. Committed-outcome short circuit | `replay_committed` loads the immutable `agent_finalization_commit`. If it exists, the turn is **never executed a second time**; history is re-appended by derived id and the same answer is returned with `replayed=True`. An *unfinalized failed* turn deliberately returns `None` so an honest retry resumes its checkpoint. | `conversation_turns.py:225-281`, `:299-305` |
| 10. Scope pin | `load_or_create_agent_turn_scope_pin` writes an immutable receipt (client entity, `client_kb_version`, `product_kb_version`, `knowledge_scope_policy_version`) *before* composition. A retry reads the winner's row, so background recon cannot move the turn's scope under it. | `agent_turn_fleet_wiring.py:532-550` |
| 11. Knowledge pin | `load_or_create_knowledge_pin` + `read_pinned_documents` pin the brand knowledge document set; `current_project_icp_pin` pins the ICP by id. | `agent_turn_fleet_wiring.py:570-596` |
| 12. Project files pin | `status.md` and `decisions.md` are *compiled fresh on the first attempt only*, then pinned; retries seed the pinned bytes, not a recompiled "current" state. Project-authored documents are added under the same pin. | `agent_turn_fleet_wiring.py:600-676` |
| 13. Recipe start | `recipe0-stage0@CONVERSATION_RECIPE_VERSION` is looked up and started (`actor='human'`), then driven to `AWAITING_INPUT` at its interaction gate. Any other status raises. | `agent_turn_fleet_wiring.py:680-710` |
| 14. Profile check | The advertised profile must equal the promoted `PROJECT_CONVERSATION_AGENT_PROFILE_ID`, and the submission's `agent_profile_id` (if set) must match. | `agent_turn_fleet_wiring.py:711-722` |
| 15. Workspace lease | `workspaces.acquire(workspace_id, project_id, execution_id, policy)` — one isolated on-disk workspace per execution. | `agent_turn_fleet_wiring.py:723-728` |
| 16. Context + artifacts | Project card, budget envelope, resource manifest are persisted as artifacts and named in the `AgentConstitution`. | `agent_turn_fleet_wiring.py:735-805` |
| 17. Run | `ConversationTurnEngine.execute` → `HeadOfAbmStage0Runtime.run` → `DurableDeepAgentTurnRunner.run` → `DeepAgentTurnRuntime.run`. | `conversation_turns.py:285`, `head_of_abm_wiring.py`, `agent_runtime_wiring.py:1199`, `runtime.py:281` |
| 18. Finalize | The model calls `finalize_turn` (`return_direct=True`, so the graph stops there). | `agent_runtime_wiring.py:1092,1195` |
| 19. Recipe completion | On `COMPLETED` only, `_complete_recipe` closes the `stage0_interactions` gate (`actor='human'`) and drives the execution to `COMPLETED`. | `agent_turn_fleet_wiring.py:866-868`, `:1196-1213` |
| 20. Task finish + hand-off | The handler finalizes its **own** fleet task, then dispatches the thread's next turn. Finishing first and dispatching second is what guarantees two live tasks never exist on one thread. | `agent_turn_fleet_wiring.py:1322-1331`, `:1413-1434` |

### 1.2 Turn statuses (`agent_turn_event.status`)

Closed set, enforced by a SQL CHECK.

| Status | Meaning | Source |
| --- | --- | --- |
| `requested` | Submission accepted. | `alembic/versions/7e9269ed8a81_agent_turns_context_and_replay_receipts.py:114-117` |
| `context_ready` | Context assembled. | same |
| `running` | `mark_running` fired at the top of `DurableDeepAgentTurnRunner.run`. | `agent_runtime_wiring.py:1220`, migration `:114-117` |
| `awaiting_input` | Finalized asking the human for something. | same |
| `completed` | Finalized with a durable answer. | same |
| `failed` | Finalized `failed`, or unfinalized with a reason code. | same |
| `cancelled` | Stopped by its submitter (added later; downgrade folds it back into `abandoned`). | `alembic/versions/5d7ab295742b_distinguish_cancelled_agent_turns.py:30-36` |
| `abandoned` | Crashed or cancelled without reconciliation (`mark_unfinalized(..., abandoned=True)`). | `agent_runtime_wiring.py:1255-1260`, migration |
| `privacy_tombstoned` | DSAR/retention erasure of the turn. | migration `:114-117` |

The design-leg lifecycle is projected on the same thread stream as `leg.opened` / `leg.closed`
(`chat/turn_events.py:86-90`).

### 1.3 Failure codes the turn can end with

`failure_code` is a `ReasonCode`: `^[a-z0-9_.-]+$`, 1..128 chars (`contracts.py:91-99`). Only
`status='failed'` may carry one (`execution.py:127-131`, `agent_runtime_wiring.py:1179-1186`).

| Code | Produced when | Source |
| --- | --- | --- |
| `agent_timeout` | The LangGraph invoke exceeded `max_runtime_s`. | `runtime.py:358-365` |
| `missing_finalize` | The graph returned but no committed finalization ref / non-terminal status exists. "The model may have emitted a polished answer, but without the trusted finalize tool it is only an uncommitted framework stop." | `runtime.py:392-405` |
| `graph_recursion_error` | The graph exceeded `recursion_limit` (52 supersteps). LangGraph's `GraphRecursionError` snake-cased by `_error_code`. | `runtime.py:253-255`, `:374-380` |
| `runtime_error`, `value_error`, `type_error`, … | `_error_code(exc)` snake-cases the *exception class name* of whatever escaped the graph. `RuntimeError` → `runtime_error`. | `runtime.py:253-255`, `:374-380` |
| `agent_cancelled_or_crashed` | Any `BaseException` (incl. cancellation) out of the runtime; marks the turn `abandoned=True`. | `agent_runtime_wiring.py:1253-1261` |
| `required_context_artifact_missing` | An exact context/finalization artifact vanished. The model is never re-invoked with a guessed replacement; the user is told to start a new thread. | `agent_turn_fleet_wiring.py:1058-1080`, `:215` |
| `stop_requested` | The submitter pressed Stop. | `agent_turn_fleet_wiring.py` stop path, `chat/turn_stream.py:350` |
| model-chosen code | Whatever the model passes to `finalize_turn(status='failed', failure_code=…)`, validated against the same `ReasonCode` pattern. | `agent_runtime_wiring.py:1179-1186` |

### 1.4 Round and time limits

| Limit | Value | Enforced by |
| --- | --- | --- |
| `max_rounds` | 24 (`profile.max_model_rounds`) | `profiles/head-of-abm/v49/profile.yaml:253` → `conversation_turns.py:549` → `head_of_abm_wiring.py:284` → `runtime.py:271` |
| LangGraph `recursion_limit` (supersteps) | `max_rounds * 2 + 4` = **52** | `runtime.py:280`, applied at `:352` |
| `max_runtime_s` | 300.0s (`profile.turn_timeout_s`) — a hard `asyncio.wait_for` around the whole graph | `profile.yaml:252` → `conversation_turns.py:548` → `runtime.py:270,356` |
| `max_plan_nodes` | 48 | `profile.yaml:251`, checked as `node_ceiling` in `execution.py:276-281` |
| `max_delegations` | 6 | `profile.yaml:250`, `execution.py:332-337` |
| `max_delegation_depth` | 1 | `profile.yaml:249`, `execution.py:340-345` |
| `max_fanout` / `max_parallelism` / `max_dependency_depth` | 8 / 8 / 16 (defaults, not from the profile) | `execution.py:70-74` |

A **round** is one `on_chat_model_start`; the stream numbers them monotonically
(`chat/turn_stream.py:1268-1271`). Every governed tool call the model makes is its own one-step
plan, so the superstep ceiling — not any plan ceiling — is what actually bounds a chat turn.

### 1.5 The repair budget (3 refusals per turn)

`GovernedAgentToolFactory` is constructed once per turn and holds `self._tool_failures = 0`,
**shared by every governed tool the model holds** (`agent_runtime_wiring.py:695-697`).

```python
self._tool_failures += 1
exhausted = self._tool_failures > _MAX_GOVERNED_TOOL_FAILURES   # 3
if exhausted:
    raise raise_when_exhausted
```
`agent_runtime_wiring.py:908-916`, constant at `:92`.

So: refusals **1, 2 and 3** come back to the model as a JSON `GovernedToolFailure`; the **4th**
re-raises the original exception, which kills the LangGraph run and ends the turn with the stable
error code. The rationale is written into the module header: the `max_rounds * 2 + 4` ceiling
*would* eventually stop a repair loop, but only "after ~24 further paid model calls", and "three
refusals is the point past which the model is no longer misreading an argument contract"
(`agent_runtime_wiring.py:87-91`).

Parallel tool calls each increment the counter independently — three refused calls in a single
assistant message exhaust the whole turn's budget in one round.

### 1.5b The second, separate repair budget: 2 finalize repairs

`finalize_turn` refusals are counted independently, in
`ExactAgentToolSurfaceMiddleware._finalize_rejections`, against `_MAX_FINALIZE_REPAIRS = 2`
(`runtime.py:57`, `:119-120`, `:238-250`). Mechanically the refusal clears the tool's
`return_direct` for one call so the correction can come back, and restores it before every attempt;
once the budget is spent `return_direct` stays on and the graph ends at `missing_finalize`
(`runtime.py:189-204`). Full detail in §5.3.

### 1.5c The tool surface is enforced, and a tool call is mandatory every round

`ExactAgentToolSurfaceMiddleware` (`runtime.py:84-187`) wraps every model call:

| Enforcement | Detail | Source |
| --- | --- | --- |
| No general-purpose subagent | Deep Agents 0.6 installs a `task` subagent by default; the platform never exposes that bypass. | `runtime.py:87-89` |
| No code execution | `if "execute" in by_name: raise RuntimeError("agent workspace unexpectedly exposes code execution")` | `runtime.py:134-135` |
| Exact surface | Missing or undeclared tools at model-call time raise `RuntimeError`; the model is handed only `sorted(self._allowed)`. | `runtime.py:124-133`, `:141` |
| Framework file tools | `write_todos`, `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep` — always allowed alongside the governed pins. | `runtime.py:36-45` |
| `tool_choice="required"` | "Every platform turn has a mandatory `finalize_turn` authority. Requiring a tool call asks compatible providers to keep acting until they invoke a governed tool." The model is never free to just answer in prose. | `runtime.py:142-147` |
| Resource map appended | `resolved_profile.generated_resource_map` is appended to the system prompt unless already present. | `runtime.py:136-140` |
| Unknown tool name | Returns an error `ToolMessage`: "Tool {name!r} is structurally unavailable to this exact agent profile." | `runtime.py:177-185` |
| Plain-text stop recovery | One bounded finalize-only retry with `tool_choice="finalize_turn"`; see §5.3b. | `runtime.py:152-176` |

### 1.6 `GovernedToolFailure` — the shape of a refusal

```python
error: Literal["plan_rejected", "operation_failed"]
address: str
node_key: str
recorded: Literal[False] = False
reasons: tuple[str, ...]
guidance: str = _GOVERNED_TOOL_REPAIR_HELP
```
`agent_runtime_wiring.py:300-320`.

`_GOVERNED_TOOL_REPAIR_HELP` (`:94-98`) is fixed text:

> "Nothing was recorded: no durable state changed and this operation did not happen. Correct
> exactly what the reasons name and call the tool again, or tell the human what is blocking you.
> Do not report this as captured."

The docstring records *why* a refusal is a tool **result** rather than an exception: raising killed
the LangGraph run and the model was never told why — "the live Stage-0 defect: a paraphrased claim
value failed the interview verifier and the turn ended `runtime_error` in silence"
(`agent_runtime_wiring.py:303-310`).

### 1.7 `GovernedOperationReceipt` and its 16 KiB bound

The success answer for every governed tool is `receipt.model_dump_json(exclude_none=True)`
(`agent_runtime_wiring.py:834`). Fields (`execution.py:112-124`):

`node_key`, `operation_id`, `kind` (`tool`|`delegation`), `address`, `status`, `replayed`,
`artifact_refs`, `domain_refs`, `reference_values`, `failure_code`.

The bound is on `reference_values` only, measured as canonical JSON bytes:

```python
if len(encoded) > 16_384:
    raise ValueError("bounded operation receipt exceeds 16 KiB")
```
`execution.py:143-150`.

"Substantive output remains behind references" (`execution.py:112`) — a tool that would return a
lot hands back `artifact_refs`/`domain_refs`, and the model must read the file or the domain object
to see the content. A completed *delegation* receipt with neither an artifact nor a domain ref is
rejected outright (`execution.py:135-141`).

### 1.8 Idempotency and replay

| Mechanism | How | Source |
| --- | --- | --- |
| Per-call node identity | `node_key = f"agent_{name}_{sha256(tool_call_id)[:24]}"`, and `plan_id = uuid5(_DIRECT_PLAN_NAMESPACE, f"{execution_id}:{node_key}")`. The *same* provider tool_call_id therefore addresses the same plan and the same operation. | `agent_runtime_wiring.py:729-737` |
| Operation identity | `operation_id_for_plan_node(execution_id, node_key)` = `operation_id_from_key(execution_id, f"agent-plan-node:{node_key}")`. | `execution.py:183-187` |
| Tool-level replay | `ToolInvoker.invoke` begins a journal entry; `JournalDisposition.COMPLETED` returns the stored result with `replayed=True` **without re-running the tool**. | `platform/toolbelt/clue_toolbelt/invoker.py:195-198` |
| A9 cache key | Always derived from journal identity: `f"execution:{execution_id}:operation:{operation_id}"` — a caller-supplied HTTP key "cannot create a second cache identity for the same logical operation". | `invoker.py:216-220` |
| Durable block | `JournalDisposition.BLOCKED` raises `PreconditionFailed` telling the model to "invoke a new operation after satisfying its prerequisite". | `invoker.py:199-208` |
| Turn-level replay | `load_committed_outcome` — a turn holding an `agent_finalization_commit` is never executed twice. | `conversation_turns.py:299-305`, `:345-348` |
| History idempotency | User/assistant messages are appended by `uuid5(turn_id, role)`. | `conversation_turns.py:306-312`, `:265-272` |

### 1.9 Crash, retry, reclaim

- A **failure** is recorded `FleetTaskStatus.FAILED` and **the thread still moves on** — a turn that
  cannot succeed must not block every later turn behind it; retries are explicit requeues only
  (`agent_turn_fleet_wiring.py:1332-1337`).
- A **crash** is different: the task stays `claimed`, the staleness window hands it to another
  worker as a *distinct attempt*, and the committed-outcome short-circuit guarantees convergence on
  one outcome rather than a double execution (`agent_turn_fleet_wiring.py:1337-1340`).
- **Fencing:** if `queue.finish` returns false, a stale reclaim already took the task; this attempt
  logs `agent_turn.fenced_out` and must not dispatch the next turn
  (`agent_turn_fleet_wiring.py:1416-1427`).
- **`resources_frozen`:** on first run the resource snapshot + seed files are *materialized*; on a
  reclaimed turn whose lease is already frozen, they are **re-verified byte for byte** before the
  model resumes — "the frozen tree is evidence, not an assumption"
  (`head_of_abm_wiring.py:229-240`; `workspace.py:164-194`, `:1043`).
- Cross-workspace / cross-execution constitution mismatches raise before any model call
  (`head_of_abm_wiring.py:200-213`).

### 1.10 The durable chat queue: one turn at a time per thread

| Fact | Source |
| --- | --- |
| A thread has at most one live `agent_turn` task; `dispatch_next_thread_turn` takes a per-thread advisory lock and refuses when one is in flight. | `agent_turn_fleet_wiring.py:1466-1470` |
| Stop is a durable row, not an interrupt — the web process does not even compose the model plane (ratified §6-D1). | `agent_turn_fleet_wiring.py:1045-1047` |
| The cancellation window is one poll interval (`CLUE_CHAT_TURN_STOP_POLL_INTERVAL_S=0.25`) plus the in-flight await's unwind. | `agent_turn_fleet_wiring.py:1048-1050`, `.env.example:406` |
| Stop semantics: only *this* generation attempt is cancelled; committed governed tool effects **stay committed** ("undo is not a property this platform claims"); a detached research run keeps running; the partial text stays in the outbox and never gets a `text.end`, so a stopped attempt can never be mistaken for a finished answer. | `agent_turn_fleet_wiring.py:1051-1055` |
| `before_work` is an admission check on *both* the model and tool boundaries: if a stop landed, it raises `asyncio.CancelledError` before any further paid work. | `head_of_abm_wiring.py:260-268`, `TurnWorkGuard` at `agent_runtime_wiring.py:641-653` |
| Pausing a thread: `hold_queue` sets `agent_thread.queue_hold_control_id`; a human `Resume` writes an idempotent `agent_thread_queue_resume` receipt. | `chat/queue_controls.py:45-56`, `:115-133`; migration `d639a2de8bd1` |
| `TurnStopped` is treated as an *executed instruction*, not an error: the task is `DONE` and the thread moves on. | `agent_turn_fleet_wiring.py:1381-1387` |
| Self-heal: `sweep_thread_dispatch` offers the next turn of any thread holding an undispatched submission (a process death between "finalize task" and "dispatch next" otherwise stalls the thread until the next POST). | `agent_turn_fleet_wiring.py:1453-1499`, cadence `CLUE_CHAT_SWEEP_INTERVAL_S=60` |

### 1.11 Streaming to the UI

`TurnStreamEmitter` (`chat/turn_stream.py:177`) writes frames into the durable
`agent_turn_event_stream` outbox. Every emission is **best-effort and never authoritative**: "a
turn's committed outcome is identical whether anybody was watching"
(`conversation_turns.py:310-312`).

| Emission | Method | Source |
| --- | --- | --- |
| `turn.accepted` / `.started` / `.awaiting_input` / `.completed` / `.failed` / `.cancelled` / `.retrying` | `open`, `turn_started`, `turn_finished`, `turn_cancelled` | `turn_stream.py:221,329,335,350`; vocabulary `chat/turn_events.py:70-76` |
| Tool card created | `tool_started(node_key, tool_name, tool_version, tool_call_id, arguments)` — fired **before** plan validation | `agent_runtime_wiring.py:755-762`, `turn_stream.py:501` |
| Tool card finished | `tool_finished(..., operation_id, output=stream_product_tool_receipt(receipt) or stream_tool_receipt(receipt))` — "the card is the receipt, structured refs, never pre-rendered prose (§3.4)" | `agent_runtime_wiring.py:823-833`, `turn_stream.py:531` |
| Tool card failed | `tool_failed(..., error_code, reasons)` — a refusal is a durable fact, so the card says so rather than sitting forever at `input-available` | `agent_runtime_wiring.py:857-878`, `turn_stream.py:563` |
| Plan part | `emit_plan_part(ref, title, revision_label)` | `turn_stream.py:765` |
| Gate parts | `emit_gate_parts(refs)` / `emit_gate_part(...)` | `turn_stream.py:782,885` |
| Sources part | `emit_sources_part(items)` | `turn_stream.py:910` |
| Launched-task parts | `emit_launched_task_parts()` | `turn_stream.py:923` |
| Assistant text | Only text decoded out of the `finalize_turn.user_message` tool argument reaches the wire. The model's plain `content` is treated as provider chatter and is **never streamed**. | `turn_stream.py:1230-1233` |
| Reconcile / reset | `reconcile_text`, `_stream_reset`, `rehydrate` — a mismatch emits `stream.reset` telling every consumer to re-fetch the canonical message | `turn_stream.py:681,746,756`; `chat/turn_events.py:63-67` |

**Reasoning trace** (`CLUE_CHAT_REASONING_TRACE_MODE`): a dev-only lens. `raw` streams the
provider's reasoning deltas onto each round's own `reasoning` part as `text.delta` frames carrying
`part_kind='reasoning'` and no `message_id`. It is gated on the emitter itself so every path,
present and future, passes one check, and `CLUE_CHAT_REASONING_TRACE_MODE=raw` **fails settings
construction in a production process** (`turn_stream.py:138-144`, `:406-424`, `:374-377`;
`fleet_main.py:1122`; `.env.example:412-414`). Provider-dependent: Anthropic gives real thinking
text, OpenAI o-series a model-written summary, plain models nothing.

Outbox retention: `CLUE_CHAT_TURN_EVENT_RETENTION_S=86400`, pruned by
`sweep_turn_stream_retention`, and only whole **terminal** turns are pruned
(`agent_turn_fleet_wiring.py:1501-1520`, `.env.example:407`).

---

## 2. Limits and configuration the agent should know about itself

Every row cites `file:LINE`. Repo root = `/Users/aryankeshri/conductor/workspaces/research-and-data/san-salvador`.
Paths below are repo-relative.

The active profile is `head-of-abm@v49`, pinned in code (not env):
`platform/api/clue_api/agent_registry_wiring.py:113` → `AgentRole.HEAD_OF_ABM: "v49"`.

---

## 2.1 The profile's limit block

There is **no YAML key literally named `limits:`** and **no `max_rounds` / `max_runtime_s` key** in the
profile. The limits are five *top-level* scalar keys at the bottom of the file, and the two names the
brief asked for are the *runtime parameter* names those keys are passed into (`max_rounds` ← `max_model_rounds`,
`max_runtime_s` ← `turn_timeout_s`).

Verbatim tail of `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:249-253`:

```yaml
max_delegation_depth: 1
max_delegations: 6
max_plan_nodes: 48
turn_timeout_s: 300.0
max_model_rounds: 24
```

| Key | Value | Declared at | Schema bound | What actually enforces it |
|---|---|---|---|---|
| `max_delegation_depth` | `1` | `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml:249` | `int 0..4` — `platform/agents/clue_agents/catalog.py:149`, mirrored `platform/agents/clue_agents/contracts.py:397` | `platform/agents/clue_agents/execution.py:339` (a delegation with depth <1 on either policy or profile is rejected) and `platform/agents/clue_agents/registry.py:772` (`current_depth >= parent.profile.max_delegation_depth` refuses a child). Zeroed when no roles survive: `registry.py:636-638`. |
| `max_delegations` | `6` | `…/profile.yaml:250` | `int 0..32` — `catalog.py:150` | `platform/agents/clue_agents/execution.py:331` — `delegation_count > min(policy.max_delegations, profile.max_delegations)` rejects. Zeroed with no roles: `registry.py:639`. |
| `max_plan_nodes` | `48` | `…/profile.yaml:251` | `int 1..256` — `catalog.py:151` | Becomes the plan policy's `max_nodes` at `platform/agents/clue_agents/execution.py:79`; carried to the resolved profile at `registry.py:640`. Plan review raises a `c5_node_ceiling`-class issue (`platform/api/clue_api/agent_execution_wiring.py:1340-1344`, "accepted plan would exceed the C5 execution node ceiling"). |
| `turn_timeout_s` | `300.0` | `…/profile.yaml:252` | `float >0, ≤1800` — `catalog.py:152` | Passed as `max_runtime_s` into the runtime: `platform/api/clue_api/conversation_turns.py:548`; the runtime wraps the whole LangGraph invoke in `asyncio.wait_for(..., timeout=self._max_runtime_s)` at `platform/agents/clue_agents/runtime.py:356`. On expiry → `AgentTurnOutcome(status=FAILED, failure_code="agent_timeout")` (`runtime.py:358-365`). Same pin also feeds `account_research_wiring.py:286`, `specialist_wiring.py:394`, `onboarding_synthesis_wiring.py:1165`. |
| `max_model_rounds` | `24` | `…/profile.yaml:253` | `int 1..128` — `catalog.py:153` | Passed as `max_rounds` at `platform/api/clue_api/conversation_turns.py:549` → `head_of_abm_wiring.py:151,164,284` → `platform/agents/clue_agents/runtime.py:271`. **It is not a round counter on this path**: `runtime.py:280` converts it to a LangGraph `recursion_limit = max_rounds * 2 + 4` = **52**, applied at `runtime.py:353`. Exceeding it raises `GraphRecursionError`, caught by the generic handler (`runtime.py:369-382`) → `FAILED` with `failure_code="graph_recursion_error"` (snake-cased class name, `runtime.py:253-255`). Validated `1 <= max_rounds <= 128` at `runtime.py:275`. |

**Not found** — a `ModelCallLimitMiddleware` on the Head-of-ABM conversation path. That middleware exists
(`platform/agents/clue_agents/entity_research_runtime.py:1009`, `platform/api/clue_api/arv2/account_research_agent.py:358`)
but only on the ARV2 / entity-research lanes; looked in `platform/agents/clue_agents/runtime.py`,
`platform/api/clue_api/head_of_abm_wiring.py`, `platform/api/clue_api/conversation_turns.py`.

### The model block (verbatim, `…/profile.yaml:196-201`)

```yaml
model:
  model_id: x-ai/grok-4.6
  timeout_s: 30.0
  max_retries: 2
  max_output_tokens: 8192
  temperature: 0.1
```

| Key | Profile value | Effective value | What enforces / overrides |
|---|---|---|---|
| `model_id` | `x-ai/grok-4.6` | `x-ai/grok-4.6` (env agrees) | Env-first: `HEAD_OF_ABM_AGENT_MODEL` overrides at registry resolution — `platform/agents/clue_agents/registry.py:392,394`. |
| `timeout_s` | `30.0` | **60.0** | Overridden deployment-wide by `CLUE_AGENT_MODEL_TIMEOUT_S` (`registry.py:393,395`), set to `60` in `.env.example:287` and `.env:330`. Bounded by `CLUE_GATEWAY_TIMEOUT_S` (`.env.example:273` = 60); a profile/override above the ceiling is refused at build time (`.env.example:271-272`). |
| `max_retries` | `2` | `2` | Profile-owned; env never touches it (`registry.py:399-406` copies it through). |
| `max_output_tokens` | `8192` | `8192` | Sent as the provider `max_tokens` — `libs/clue-gateway/clue_gateway/agent_model.py:1047` and `:1062`. |
| `temperature` | `0.1` | `0.1` | Profile-owned, copied at `registry.py:404`. |

### Prompt / skill / tool-grant refs in the profile

| Ref | Value | Source |
|---|---|---|
| Prompt | `head-of-abm` **v8**, sha256 `0d942eb5…76cc3` | `…/profile.yaml:55-58` |
| Skill | `stage0-interview` **v26**, sha256 `0044e38d…f73b5` (file is 26,309 bytes at `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md`) | `…/profile.yaml:59-62` |
| Direct tool grants (**21**, verified by count) | `author_icp_document@1`, `draft_account_research_directive@5`, `get_research_view@1`, `inspect_statement_history@1`, `launch_arv2_account_research@1`, `launch_arv2_discovery@1`, `launch_arv2_person_research@1`, `open_design_leg@4`, `open_directive_confirmation_gate@1`, `open_icp_confirmation_gate@2`, `open_product_set_selection_gate@1`, `propose_field@2`, `propose_source@1`, `read_account_research@1`, `read_arv2_account_research_run@1`, `read_discovery_run@1`, `read_project_accounts@1`, `record_interview_answer@1`, `request_persona_synthesis@1`, `submit_ingestion@1`, `write_project_document@1` (21 pins incl. the three reads) | `…/profile.yaml:63-195`. Each pin carries `input_schema_sha256` + `output_schema_sha256`; a descriptor whose schema digest moves breaks the pin. |
| `memory_policy` | `scoped-advisory-v1` (only legal value) | `…/profile.yaml:202`; `Literal` at `catalog.py:145` |
| `delegation_roles` | `[research, content_drafter, reviewer]` | `…/profile.yaml:212` |
| `delegation_tool_grants` | research → `get_research_view@1`, `run_verification@1`; content_drafter → `compose_handoff@1`, `compose_contact_content_handoff@1`, `get_research_view@1`; reviewer → same three as content_drafter | `…/profile.yaml:213-248` |

**Surface override that matters:** on the live project-conversation surface, all three delegation roles
are **withheld** — `platform/api/clue_api/agent_registry_wiring.py:541-559` (`PROJECT_CONVERSATION_SURFACE`,
`withheld_delegation_roles = {RESEARCH, CONTENT_DRAFTER, REVIEWER}`, reason
`project_conversation_no_autonomous_research`). With no roles left, the registry forces
`max_delegation_depth`/`max_delegations` to `0` (`registry.py:636-639`), and the runner is the
unreachable `DelegationWithheld` backstop (`platform/api/clue_api/conversation_turns.py:150-166`).
So in production the agent's effective delegation budget is **zero**, not 6.

### Workspace policy (`…/profile.yaml:203-211`)

| Key | Value | Enforced at |
|---|---|---|
| `virtual_mode` | `true` (must be `True`) | `catalog.py:112` |
| `max_total_bytes` | `10485760` (10 MiB) | `platform/agents/clue_agents/workspace.py:391,399` → `WorkspaceQuotaExceeded` |
| `max_file_bytes` | `1048576` (1 MiB) | write: `workspace.py:383`; **read**: `workspace.py:535,538` ("workspace file exceeds its read quota") |
| `max_file_count` | `200` | `workspace.py:389,395` |
| `allowed_extensions` | `.json .md .txt .yaml` | `WorkspacePolicyDocument`, `catalog.py:116` |
| `readable_prefixes` | `.deepagent, inputs, context, work, outputs` | `catalog.py:117` |
| `writable_prefixes` | `work, outputs` | `catalog.py:118` |
| `retention_class` | `agent-ephemeral-v1` | `catalog.py:119`; a delegated child may not change it (`registry.py:829-830`). Actual sweep cadence is env: `CLUE_AGENT_WORKSPACE_RETENTION_S=86400`, `CLUE_AGENT_CLEANUP_INTERVAL_S=3600` (`.env.example:389-390`). |

Quota failures surface to the model as a tool string `"quota_exceeded: <message>"` — `workspace.py:734`.

---

## 2.2 Model config and the parity rule

| Key | `.env.example` | local `.env` | Read at |
|---|---|---|---|
| `HEAD_OF_ABM_AGENT_MODEL` | `x-ai/grok-4.6` (`.env.example:288`) | `x-ai/grok-4.6` (`.env:244`) | `platform/agents/clue_agents/registry.py:392` — `os.environ[f"{role.value.upper()}_AGENT_MODEL"]` |
| `HEAD_OF_ABM_AGENT_MODEL_EFFORT` | *(blank)* (`.env.example:289`) | *(blank)* (`.env:245`) | `libs/clue-gateway/clue_gateway/agent_model.py:1124-1127` — `os.environ[f"{role.upper()}_AGENT_MODEL_EFFORT"]`, injected into the provider `reasoning` block |
| `CLUE_AGENT_MODEL_TIMEOUT_S` | `60` (`.env.example:287`) | `60` (`.env:330`) | `registry.py:393` (deployment-wide `timeout_s` override) |
| `CLUE_GATEWAY_TIMEOUT_S` | `60` (`.env.example:273`) | `60` (`.env:336`) | Ceiling; a profile above it is refused at build time (`.env.example:271-272`) |

`build_agent_model_provider` is the composition root — `platform/api/clue_api/agent_model_wiring.py:13-23`;
it raises `RuntimeError("CLUE_OPENROUTER_API_KEY is required for the production deepagent model")`
when no key is present (`agent_model_wiring.py:20-21`).

**The parity rule, stated by the code itself** (`registry.py:371-388`, founder ruling 2026-08-31,
restated at `.env.example:275-286`):

> The profile pins the **role and the envelope**; the environment names the **model**.

Mechanically:
- `<ROLE>_AGENT_MODEL` replaces `model.model_id` at *resolution* time, so changing models is a
  deployment setting, never a new reviewed profile version (`registry.py:392-406`).
- Blank/unset keeps the profile pin — that is what makes tests and historical replay deterministic
  with no environment (`registry.py:377-378`).
- `<ROLE>_AGENT_MODEL_EFFORT` is read at the **gateway**, not the registry, because effort shapes the
  provider request rather than the profile contract (`registry.py:379-381`; implemented
  `agent_model.py:1074-1128`). Blank → the per-model baseline: `grok-4.6`-family gets
  `{"effort": "high"}` (`agent_model.py:1119-1120`), `openai/gpt-5.6*` gets `{"effort": "none"}`
  (`agent_model.py:1122`), plain models get nothing.
- Everything else on the envelope (`max_retries`, `max_output_tokens`, `temperature`) stays profile-owned.
- One documented exception (founder ruling 2026-09-08): `CLUE_AGENT_MODEL_TIMEOUT_S` *does* override an
  envelope field — `timeout_s` — platform-wide, bounded by the gateway ceiling (`registry.py:383-388`).
- CLAUDE.md's parity rule also applies: every flag the code reads must appear in `.env.example` with its
  default. Both keys above do.

---

## 2.3 Budget

`PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS` is **not an env var — it is a module constant**.

- Not found in `.env.example` or `.env` (exact grep over both files returned only the unrelated
  `CLUE_AGENT_ACCOUNT_PLAN_BUDGET_LIMIT_MILLICENTS`).
- Defined `platform/api/clue_api/agent_turn_fleet_wiring.py:190` → `1_000_000` millicents (= 1,000 cents = **$10.00** per turn).
- Its own docstring says why it is a constant (`agent_turn_fleet_wiring.py:185-189`): "A conversation turn
  is model time, not research spend… a module constant rather than a setting because there is nothing here
  an operator should tune per deployment without also revisiting the profile's round/timeout limits."

| Where | Line | Use |
|---|---|---|
| Budget-envelope artifact for the turn | `agent_turn_fleet_wiring.py:768` — `{"limit_millicents": PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS}` | persisted envelope the child/plan reads |
| Turn execution policy | `agent_turn_fleet_wiring.py:858` — `budget_limit_millicents=…` | into `AgentExecutionPolicy` |
| Policy contract | `platform/agents/clue_agents/execution.py:65,72,86` | `budget_limit_millicents: int = Field(ge=0)` |
| Plan contract invariant | `platform/agents/clue_agents/contracts.py:767-771` | a plan whose `estimated_cost_millicents` ≠ sum of its operations, or > its `budget_limit_millicents`, fails validation |

**What happens when exceeded.** At plan validation (`platform/api/clue_api/agent_execution_wiring.py:1587-1605`):
`estimated > policy.budget_limit_millicents` → `raise AgentPlanRejected(AgentPlanReview(issues=(AgentPlanIssue(
code="budget_ceiling", location="plan.steps", message=f"estimated {estimated} millicents exceeds {limit}"))))`.
The plan is refused *before* any operation runs; the model sees a typed rejection naming the code
`budget_ceiling` and both numbers, and must re-plan smaller. A delegated child gets
`budget_limit // delegation_count` (`agent_execution_wiring.py:1578-1580`), and any remaining child budget
is `min(per_plan_limit, max(limit - already_spent, 0))` (`agent_execution_wiring.py:1901,1925-1934`), so
re-planning inside one turn cannot re-spend the ceiling. Child spend outside `[0, limit]` is rejected at
`platform/api/clue_api/specialist_wiring.py:417`.

Neighbouring budget (different lane, do not confuse): `CLUE_AGENT_ACCOUNT_PLAN_BUDGET_LIMIT_MILLICENTS=1000000`
(`.env.example:385`, `.env:121`), read at `platform/api/clue_api/account_research_turn_wiring.py:354` and
clamped further by the durable account envelope (`:356` — `min(setting, durable_limit)`).

### Workspace-level quota

**Not found** — a workspace-level *spend* quota. Grepping `quota` across
`platform/agents/clue_agents/workspace.py` and `platform/api/clue_api/` returns only the **filesystem**
quota (bytes / file count / per-file size, §2.1 above) at `workspace.py:375-399,424,474,535-538,646,692,734`,
plus one final-quota snapshot persisted per turn at `platform/api/clue_api/agent_turn_wiring.py:729`.
There is no per-workspace millicent allowance in this tree. What *is* workspace-scoped is access gating,
not spend: `CLUE_AGENT_WORKSPACE_ALLOWLIST=[]` and `CLUE_AGENT_CANARY_PERCENT=0` (`.env.example:381-382`).

### Retention for turns / threads / workspaces

| Setting | Default | Source | Swept by |
|---|---|---|---|
| `CLUE_AGENT_WORKSPACE_RETENTION_S` | `86400` (24 h) | `.env.example:389`, `.env` parity | fleet cleanup loop; terminal execution roots removed after outputs+finalization are durable (`.env.example:386-388`; `platform/agents/clue_agents/workspace.py:1236`) |
| `CLUE_AGENT_CLEANUP_INTERVAL_S` | `3600` | `.env.example:390` | non-positive disables only the scheduler |
| `CLUE_CHAT_TURN_EVENT_RETENTION_S` | `86400` | `.env.example:407` | `sweep_turn_stream_retention(retention_s=settings.chat_turn_event_retention_s)` — `platform/api/clue_api/fleet_main.py:304-306`; prunes terminal turns' SSE frames past the replay window (`fleet_main.py:294`) |
| `CLUE_CHAT_SWEEP_INTERVAL_S` | `60` | `.env.example:408` | sweep cadence |
| `CLUE_CHAT_STREAM_TOKEN_TTL_S` | `300` | `.env.example:409` | stream token lifetime |
| `design_run_event_retention_s` | (design lane) | `platform/api/clue_api/fleet_main.py:1263` | design-subject-only `run_event` pruner |

Turn *content* (the captured turn, the finalization, the plan journal) is **not** pruned by these — only
stream frames and local workspace roots. `RequiredTurnArtifactMissing`
(`agent_turn_fleet_wiring.py:215-221`) is terminal and non-retryable if the exact bytes a turn needs are gone.

---

## 2.4 The recipe

### Which one

`CONVERSATION_RECIPE_VERSION = 26` — `platform/api/clue_api/conversation_turns.py:140`. **It is a Python
constant, not an env var** (exact grep of `.env.example` and `.env` for `CONVERSATION_RECIPE_VERSION`
returned nothing; the only `RECIPE` line in `.env.example` is none — the recipe version is code-pinned).
So the live recipe is `platform/execution/recipes/recipe0-stage0-v26.json`, and the Stage-0 trial harness
derives its own pin from the same constant (`platform/api/clue_api/stage0_trial.py:57,172`).

### What a recipe IS mechanically

| Aspect | Answer | Source |
|---|---|---|
| Shape | A frozen, `extra="forbid"`, strict pydantic `RecipeDefinition` | `platform/execution/clue_execution/recipes.py:57-72` |
| Loader | `load_recipe_definition(path) = RecipeDefinition.model_validate_json(path.read_text())` | `platform/execution/clue_execution/recipes.py:163-164` |
| Seeding | Idempotent system-recipe seeding at the api composition root; every historical version file is listed and re-seeded | `platform/api/clue_api/recipe_wiring.py:1,39-…` (`SYSTEM_RECIPE_FILENAMES`) |
| Lookup at turn time | `self._recipes.get_by_identity(scope_type=SYSTEM, workspace_id=None, recipe_key=CONVERSATION_RECIPE_KEY, version=CONVERSATION_RECIPE_VERSION)` | `platform/api/clue_api/agent_turn_fleet_wiring.py:680-685` |
| Immutability | A promoted recipe revision is immutable — widening the slot is a **new revision**, never an edit | `platform/api/clue_api/recipe_wiring.py:46-49` |
| Memory binding | `memory_recipe=f"{CONVERSATION_RECIPE_KEY}@{CONVERSATION_RECIPE_VERSION}"` | `platform/api/clue_api/conversation_turns.py:535` |

### What it ADMITS

It binds a **graph** with an interaction *gate* node, and that gate is the ceiling on what any turn may do:

| Element | Meaning | Enforced at |
|---|---|---|
| `graph.tool_allowlist` | the recipe-wide address set | every node's `dynamic_tool_allowlist` entry must be a member — `platform/execution/clue_execution/graph.py:683-684`; a static tool node likewise `graph.py:637` |
| gate `dynamic_tool_allowlist` | the exact tool **addresses** (name@version) a turn may append beneath the slot | `platform/execution/clue_execution/executor.py:996-1000` → `ExecutionConflict("<addr> is not allowed beneath interaction slot <slot>")`; surfaced to the planner as `InteractionSlotView.tool_allowlist` (`executor.py:1359`) |
| plan validation | a proposed step outside the slot allowlist | `platform/api/clue_api/agent_execution_wiring.py:1352-1360` → issue `c5_tool_not_allowed`, "<addr> is absent from the active C5 slot". A step outside the **profile's** grants is dropped separately (`agent_execution_wiring.py:1344,1362+`) — the effective set is the **intersection** of profile grants ∩ recipe allowlist ∩ surface policy. |
| `recipe_safe` descriptor flag | a tool not marked recipe-safe is refused even if allowlisted | `executor.py:1005-1006` |
| `dynamic_pin_kinds` | which **resource pin kinds** the slot may attach (artifact_input, brand, product, project, field_registry, source_registry, client_kb, product_kb, product_context, icp, readiness_decision, model_prompt, source_profile, memory_bundle_journal, proposal_policy, ingestion_policy, project_run, research_directive, account_research_selection, account_research_run, verification_policy) | `recipe0-stage0-v26.json` (gate node) ; `executor.py:1360` |
| `compatibility.nodes` | resource **requirements** (tools + policies + the `stage0-interview` **skill** + optional `memory_switch`) that must resolve before the slot runs | must exactly mirror `node_requirements(graph)` — `recipes.py:85-90` |
| `requested_memory_types` | `[]` for this recipe (memory types come from the caller instead) | `recipe0-stage0-v26.json`; `recipes.py:69` |
| `authority_allowlist` | `["human"]` — the gate's authority | `recipe0-stage0-v26.json`; interaction actor must be `human` or `agent` (`executor.py:1002-1003`) |
| `parameter_schema` | `{"type":"object","properties":{},"additionalProperties":false}` — this recipe takes **no parameters** | `recipe0-stage0-v26.json`; must declare `type=object` (`recipes.py:81-82`) |

### This recipe's actual content (`platform/execution/recipes/recipe0-stage0-v26.json`)

Header: `recipe_key=recipe0-stage0`, `scope_type=system`, `workspace_id=null`, `version=26`,
`executor_protocol=1`, `created_by=system`, `source_execution_id=null`.

Envelope ceilings:

| Key | Value | Enforced at |
|---|---|---|
| `max_nodes` | `128` | `recipes.py:70`; runtime node-count check `executor.py:1341-1362` (`InteractionSlotView.max_nodes` / `node_count`) |
| `max_depth` | `2` | `recipes.py:71` |
| `max_fanout` | `8` | `recipes.py:72` |
| gate `max_children` | `125` | gate node in the JSON; `executor.py:1358` (`child_count` vs `max_children`) |

Steps — **three nodes, linear**:
1. `stage0_open` — `kind: barrier`, ordinal 0, no dependencies, no requirements.
2. `stage0_interactions` — `kind: gate`, ordinal 1, depends on `stage0_open`, `authority: human`,
   `resume_condition: input_available`, `max_children: 125`. This is where everything happens.
3. `stage0_complete` — `kind: barrier`, ordinal 2, depends on `stage0_interactions`.

Admitted tools (the gate's `dynamic_tool_allowlist`, identical to `graph.tool_allowlist`) — **39 addresses**:

`submit_onboarding_input@1`, `start_recon@1`, `record_interview_answer@1`, `confirm_project_product@1`,
`evaluate_stage0_readiness@2`, `synthesize_icps@3`, `confirm_icp@1`, `override_stage0_readiness@1`,
`open_discovery_configuration_gate@1`, `start_confirmed_project_run@3`, `propose_field@2`, `propose_source@1`,
`submit_ingestion@1`, `inspect_statement_history@1`, `inspect_readiness_history@1`,
`draft_account_research_directive@5`, `open_design_leg@4`, `open_directive_confirmation_gate@1`,
`open_product_selection_gate@1`, `get_research_view@1`, `launch_account_research@1`,
`launch_selected_account_research@1`, `read_account_research_run@1`, `list_client_knowledge@2`,
`inspect_client_claim@2`, `list_product_knowledge@1`, `inspect_product_claim@1`,
`open_product_set_selection_gate@1`, `open_icp_confirmation_gate@2`, `launch_arv2_account_research@1`,
`launch_arv2_discovery@1`, `launch_arv2_person_research@1`, `read_arv2_account_research_run@1`,
`author_icp_document@1`, `request_persona_synthesis@1`, `write_project_document@1`,
`read_project_accounts@1`, `read_account_research@1`, `read_discovery_run@1`.

Admitted **skills / policies** (non-tool requirements on the same node, mirrored in `compatibility.nodes`):
`stage0_policy/default@1`, `stage0_skill/stage0-interview@1`, `readiness_policy/default@1`,
`proposal_policy/default@1`, `ingestion_policy/default@1`, `memory_switch/workspace@live` (`required: false`).
`activity_allowlist` is empty; `migration_state: executable`.

**Practical consequence:** the recipe admits 39 tools but `head-of-abm@v49` pins only 21, so the agent's
real surface is the 21 (all of which are in the recipe's 39). The recipe is the *outer* fence; the profile
is the *inner* one. The recipe notes this explicitly: v49/skill-v26 did **not** mint a revision 27 because
"a recipe pins tool ADDRESSES, and no address moved — only the three tools' schema digests, which the
profile and the skill pin and this file does not" (`platform/api/clue_api/conversation_turns.py:134-139`).

### On mismatch

`platform/api/clue_api/agent_turn_fleet_wiring.py:686-689`:

```python
if revision is None:
    raise RuntimeError(
        f"promoted {CONVERSATION_RECIPE_KEY}@{CONVERSATION_RECIPE_VERSION} is not installed"
    )
```

i.e. if the constant names a version the DB has not been seeded with, the turn **fails loud at start**;
it does not fall back to an older revision. The trial harness has the same two checks —
`platform/api/clue_api/stage0_trial.py:436-437` ("recipe0-stage0@N definition is not installed") and
`:724-727` ("promoted recipe0-stage0@N is not installed").

---

## 2.5 Other self-limiting facts the agent should know

### Context window (the seven-layer budget)

`project_conversation_context_policy()` — `platform/api/clue_api/agent_turn_fleet_wiring.py:228-246`.
Version string `project-conversation-context-v1`, counter `utf8-bytes-v1`.

| Layer | Budget | Note |
|---|---|---|
| L1 identity | 24,000 | layer names: `platform/agents/clue_agents/contracts.py:910-917` |
| L2 workspace/product | 12,000 | |
| L3 project | 48,000 | the conversation card, bounded by construction |
| L4 memory | 16,000 | |
| L5 focus | 8,000 | |
| **L6 conversation** | **96,000** | the largest share — "the layer a real conversation grows into" (`agent_turn_fleet_wiring.py:231-232`) |
| L7 turn | 32,000 | |
| **Total** | **236,000 "tokens"** | but the counter is **one token per UTF-8 byte** (`platform/agents/clue_agents/context.py:208-211`), deliberately conservative / over-counting — so this is ≈236 KB of text, not 236 K model tokens. |

Eviction: greedy per layer; a candidate that does not fit is *skipped*, not a stop, so a small later item
still fits behind a large refused one (`context.py:677-698`). L6 alone is walked **newest-first**
(`context.py:71`, `_RETAIN_NEWEST_LAYERS`), so old messages fall out before new ones. A candidate marked
`required` that cannot fit raises `ValueError("required <layer> context exceeds its hard layer budget")`
(`context.py:691-694`) — a hard turn failure, not a silent trim.

### Output cap

`max_output_tokens: 8192` per model call (`profile.yaml:200` → `agent_model.py:1047,1062`).

### Finalization repairs

The turn is only committed through the trusted `finalize_turn` tool. A rejected finalize is retried at most
`_MAX_FINALIZE_REPAIRS = 2` times (`platform/agents/clue_agents/runtime.py:57,241`); after that the model
is told "Nothing was committed and no further finalize attempt will be accepted for this turn."
(`runtime.py:67-69`). If the graph returns with **no** committed finalization ref, the runtime fails the
turn regardless of how polished the model's prose was (`runtime.py:384-400`) — normal framework
termination has no authority (`runtime.py:260-262`).

### Per-thread concurrency

**Exactly one live turn per thread.** `dispatch_next_thread_turn`
(`platform/api/clue_api/agent_turn_submission.py:484-504`) takes a per-thread *transaction* advisory lock
(`lock_thread_queue`, `:504`) and refuses when a task is already in flight; returning `None` is the normal
outcome. Called from exactly two places — the turn route and the `AGENT_TURN` handler — and safe from either
at any time (`:493-497`). The self-heal sweep `sweep_thread_dispatch(thread_limit=200)`
(`platform/api/clue_api/agent_turn_fleet_wiring.py:1453-1469`) covers a process death between finalize and
dispatch; "a sweep racing a POST or a worker cannot produce a second live turn on one thread" (`:1466-1469`).

### Tool-result truncation the agent will see

| Bound | Value | Source |
|---|---|---|
| `read_project_accounts` page | `limit` default 100, `le=MAX_ACCOUNTS=200`; `query` ≤120 chars; `offset ≥0` | `platform/api/clue_api/arv2/read_tools.py:99,895,899,901` |
| `read_account_research` claims | hard ceiling `MAX_CLAIMS = 120`; the rest reported as truncated | `arv2/read_tools.py:329,517,533` |
| `read_discovery_run` candidates | `candidate_limit` default 25, `le=MAX_CANDIDATES=50` | `arv2/read_tools.py:627,1061` |
| Client/product-KB claim text | value ≤4,096 B, evidence span ≤1,024 B, field brief ≤256 B, provenance ref ≤512 B — each with an explicit `*_truncated` boolean | `platform/api/clue_api/client_knowledge_contracts.py:68-71`; applied `client_knowledge_tools.py:366-460` |
| ICP spec echo | label ≤200 chars, rationale ≤4,000, ≤20 criteria/signals, `content_truncated` flag | `platform/api/clue_api/stage0_project_tools.py:965-999` |

The pattern is consistent: reads are clipped to a ceiling and the clip is **declared** in the payload, so
the agent must treat a truncated page as truncated rather than as the whole set (`arv2/read_tools.py:279`,
`stage0_tools.py:126`, `stage0_inspection_tools.py:354`).

### Streaming knobs (affect what the user sees, not what the agent may do)

`CLUE_CHAT_TURN_STREAMING_ENABLED=true`, `CLUE_CHAT_TURN_STREAM_BATCH_MAX_CHARS=256`,
`CLUE_CHAT_TURN_STREAM_BATCH_INTERVAL_S=0.05`, `CLUE_CHAT_TURN_STOP_POLL_INTERVAL_S=0.25`,
`CLUE_CHAT_STREAM_POLL_INTERVAL_S=0.25` — `.env.example:403-410`. A user stop is not a failure: it raises
`TurnStopped` and finalizes the task as *done / cancelled* (`agent_turn_fleet_wiring.py:205-212`).

### Not found

- A `limits:` YAML block, or keys literally named `max_rounds` / `max_runtime_s`, in the profile — looked in
  `platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml` (whole file) and the schema
  `platform/agents/clue_agents/catalog.py:133-153`. The names exist only as runtime *parameters*.
- `PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS` as an env var — looked in `.env.example`, `.env` (exact
  grep, no truncation); it is `platform/api/clue_api/agent_turn_fleet_wiring.py:190` only.
- `CONVERSATION_RECIPE_VERSION` as an env var — same two files; it is
  `platform/api/clue_api/conversation_turns.py:140` only.
- A workspace-level **spend** quota — looked in `platform/agents/clue_agents/workspace.py` and all of
  `platform/api/clue_api/` (grep `quota`); only filesystem quotas exist.
- A per-round tool-call cap on this surface — looked in `platform/agents/clue_agents/runtime.py`,
  `platform/api/clue_api/head_of_abm_wiring.py`, `platform/api/clue_api/conversation_turns.py`. The only
  ceiling is the derived LangGraph `recursion_limit = 24*2+4 = 52` (`runtime.py:280`).

---

## 3. Sibling agents and background work

*(Head of ABM operating manual, part E3. Every claim carries a `file:LINE` source, verified
read-only against the `research-streaming` worktree on 2026-09-13.)*

## 3.0 The shape of every sibling

The Head of ABM never runs research itself. Every sibling below is **a fleet job**: the Head of
ABM's tool call writes durable rows and offers a task to the work queue, then returns. A successful
tool result means *queued or replayed* — never *finished*.

| Sibling | Launch tool | Runs as | Terminal statuses | How HoA reads the outcome |
|---|---|---|---|---|
| ARV2 account research | `launch_arv2_account_research@1` | `arv2_research_job` (subject `account`) on the fleet | `completed` / `needs_review` (`suspended` = pause) | `read_arv2_account_research_run@1`, `read_project_accounts@1`, `status.md`, `read_account_research@1` |
| ARV2 person research | `launch_arv2_person_research@1` **or** auto-spawned by the account job's committee step | `arv2_research_job` (subject `person`), same run | same | same run read (but see §3.2 caveat) |
| ARV2 discovery | `launch_arv2_discovery@1` | `arv2_discovery_run` on the fleet | `completed` / `needs_review` (`suspended`) | `read_discovery_run@1`, `status.md` |
| Onboarding synthesis (personas) | `request_persona_synthesis@1` | `onboarding_run` kind=`personas` on the fleet | `completed` / `failed` | **only** `status.md` "## Personas" |
| Design leg | `open_design_leg@4` | nothing — opening a leg runs no turn | leg `open_awaiting_user` → closed by `finish_design_leg@1` (design role only) | the leg's close summary re-entering thread history |

Status vocabulary is shared by runs and jobs so a reader learns one set of words:
`not_started / in_progress / needs_review / completed / suspended`
(`platform/api/clue_api/arv2/account_research_store.py:67`; discovery mirrors it verbatim at
`platform/api/clue_api/arv2/discovery_store.py:67`).

---

## 3.1 ARV2 account research agent

### (a) How the Head of ABM launches it

Tool: **`launch_arv2_account_research@1`**
(`platform/api/clue_api/arv2/account_research_launch.py:1455` — class at
`account_research_launch.py:1164`, granted in
`platform/agents/catalog/profiles/head-of-abm/v49/profile.yaml` under `launch_arv2_account_research`).

Arguments (`LaunchArv2AccountResearchInput`, `account_research_launch.py:1080-1088`):

| Arg | Constraint | Source per the skill |
|---|---|---|
| `project_id` | str | the project card in context (`skills/stage0-interview/v26` §7 — `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:200`) |
| `account_entity_ids` | 1–200 | the account refs attached to the **current** turn, exactly |
| `icp_artifact_key`, `icp_artifact_sha256` | str | the index card's **confirmed** ICP entry, never a proposed one |
| `product_selection_version` | int ≥ 1 | the index card's product set |
| `effort` | `full` \| `reduced` \| `cheap-pass`, default `full` | always `"full"` — see (c) |
| `committee_cap` | 1–12, default 5 | skill says 5 |
| `directive_text` | str, default "" | the human's own words |

Authority: `effect_class = SPEND` (`account_research_launch.py:1189`), and
`_trusted_action` refuses with `launch_action_ref_missing` unless the current user action approved
this exact set (`account_research_launch.py:1138-1150`). The `project` pin is resolved from the
**execution row**, not the model's body (`platform/api/clue_api/stage0_recipe.py:459-468`).

Output: `{run_id, job_ids[], replayed}` (`account_research_launch.py:1093-1096`). The run id is the
digest of the request, so a double-click returns the same run
(`account_research_launch.py:14-16`).

**What it does NOT need** — decisive for §3.6: "No `icp_spec` row, no `account_research_directive`,
no Stage-0 pin on the project run. The old Stage-0 launch machinery is not a dependency of this
lane and must never become one." (`account_research_launch.py:17-19`).

### (b) What it does

One job = one account = one fleet task with its own lease and its own failure
(`platform/api/clue_api/arv2/account_research_driver.py:3-5`). The driver composes the job under the
launch's pins — the ICP artifact digest and the agent-profile digest are **re-checked before a
single model call**, and moved bytes mean a relaunch, not a resume
(`account_research_driver.py:15-18`, `:683-687`).

The agent itself is `agent-profile:arv2-account:v1`
(`platform/agents/catalog/entity-research/arv2-account/v1/profile.md:7`), composed from five pinned
markdown files — profile, prompt, and three skills (`dossier`, `audit`, `manual`) — hashed, never
parsed (`platform/api/clue_api/arv2/account_research_catalog.py:3-5`, `:22`).

> **Correction to the brief.** `platform/agents/catalog/entity-research/account/v3/manual.md` is
> **not** the ARV2 agent's manual. The live ARV2 loader points at
> `agents/catalog/entity-research/<agent>/<version>` with agent `arv2-account`
> (`account_research_catalog.py:33`, `:38`, `:135`). `entity-research/account/v3` belongs to the
> **M8D** entity-research lane (only reference outside the catalog is
> `tests/api/test_entity_research_cutover_r10.py:203`), which is off everywhere
> (`CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=false`, `.env:130`, `.env.example:426`). The v3 manual's
> content (11 tools, `research_account_deep`, `enrich_account`, `assess_account_coverage`,
> `sumble_*` sources) describes a **different tool surface** than ARV2's 12 tools below.

It runs one `create_agent` graph with 12 tools
(`platform/api/clue_api/arv2/account_research_tools.py:2260-2392`):
`read_account_state`, `read_ats_board`, `fetch_page`, `search_web`, `lookup_company`,
`lookup_people`, `read_media_feeds`, `research_deep`, `structure_material`, `write_claims`,
`verify_links`, `finalize_research`.

Its constitution is ten rules, each traced to a run that failed doing the opposite
(`entity-research/arv2-account/v1/prompt.md:1-90`): a **target lock** against same-name
contamination (§2), an **evidence law** — every assertion carries a verbatim quote and its URL, NOT
FOUND is a correct answer (§3), evidence outranks the already-established block (§4), the ICP is a
*lenient charter* that never vetoes research (§5), **free-first ordering** ATS → RSS/YouTube → own
site → AI Ark → Exa gap searches → one deep call (§6), and finalize once (§10).

The research ladder is eight rungs (`entity-research/arv2-account/v1/dossier.md:6-35`), the dossier
charter is twelve sections (`dossier.md:36`), plus fit verdicts (`dossier.md:81`) and committee
(`dossier.md:91`).

### (c) Stop policy — how long it runs and how it settles

Verified against code + env. The founder's 2026-09-08 ruling is "no pre-emptive caps"
(`platform/api/clue_api/arv2/account_research_agent.py:3-4`):

| Limit | Setting | Default | Env line |
|---|---|---|---|
| Model rounds | `arv2_account_max_model_rounds` | **100** | `CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS=100` (`.env.example:151`) |
| Tool calls per round | `arv2_account_max_tool_calls_per_round` | **50** | `.env.example:153` |
| Wall clock per job | `arv2_account_max_runtime_s` | **1800 s = 30 min** | `.env.example:155` |
| Total tool calls | none — ruled out | — | `arv2-account/v1/profile.md` stop-policy table |
| Zero-yield rounds | none — ruled out | — | same |
| Jobs per worker | `arv2_account_max_parallel_jobs` | 4 | `.env.example:157` |
| Provider concurrency in a job | `arv2_account_provider_concurrency` | 4 | `.env.example:159` |
| Media seconds (ENFORCED) | `arv2_media_seconds_ceiling` | 9000 | `.env.example:142` |

Settings definitions: `libs/clue-config/clue_config/settings.py:345-357`. Confirmed by the settings
test `tests/arv2/test_settings.py:29`.

**Every cap ends the graph; none of them raises** — `ModelCallLimitMiddleware` is built with
`exit_behavior="end"` (`account_research_agent.py:8-10`, `:358`). The per-round ceiling refuses the
*excess calls*, not the round, each with its own `too_many_parallel_calls` envelope
(`account_research_agent.py:13-16`). The runtime cap waits up to 60 s for in-flight provider hops to
drain so money truth reaches the ledger (`account_research_agent.py:18-19`, `:59-62`).

Stop reasons are a closed set of four:
`AgentStopReason = Literal["finalized", "round_cap", "runtime_cap", "model_error"]`
(`account_research_agent.py:65`). Only `model_error` lands the job `needs_review`; the other three
land `completed` (`account_research_driver.py:921`).

**Money is recorded, never enforced** — `over_ceiling` is a row, not a stop; the only enforced
ceiling is media seconds (`arv2-account/v1/profile.md` spend-policy paragraph). A 402 / credit
exhaustion latches that provider for the run and the agent continues with the others.

**Effort is `full` mode only.** The directive carries `effort`, but profile v1 implements one
behaviour — the full ladder; the driver records the rung and runs full regardless
(`arv2-account/v1/profile.md`, "Effort: full mode only").

**Observed live durations** (`_memory/2026-09-09-arv2-r3-person-agent.md:106-124`): a real account
job (Zafran, cap 5) took **12 rounds, 113 claims, $0.94**. Person jobs: per-job wall
**6:00 / 8:46 / 13:03**, cost **$0.67–1.25 + 1.5 AI Ark credits** each, model spend ≈80% of it,
~60k prompt tokens per round at ~85% cached. Three workers gave **+25% throughput, not 3×** — the
bottleneck is the shared providers and the model, not the fleet.

### (d) Stages it moves through

`JobStage = Literal["deep_research", "synthesis", "committee", "member_research"]`
(`account_research_store.py:75`; the DB CHECK carries the same four values). An **account** job
walks all four; a **person** job stamps only the first two (`account_research_store.py:72-74`).

| Stage | Stamped where |
|---|---|
| `deep_research` | after the job is claimed and composed, on the claiming connection (`account_research_driver.py:619`) |
| `synthesis` | when the agent calls `finalize_research` — its last act (`account_research_tools.py:2070-2072`, `:2123-2125`) |
| `committee` | in `_settle`, after `finish_job`, for account subjects only (`account_research_driver.py:937-939`) |
| `member_research` | only if the committee step produced jobs (`account_research_driver.py:941-944`) |

### (e) Committee discovery → person-job spawn

The account agent resolves a buying committee and names candidates in its finalization; each
confirmed candidate becomes one `account.committee_candidate` claim on the account. That is a fact
*about the account* — not yet a person (`platform/api/clue_api/arv2/committee_step.py:1-7`).

`run_committee_step` runs **inside the account job's settling transaction**, after `finish_job`
(`account_research_driver.py:880-884`). Four rules (`committee_step.py:11-24`):

- **A vacant seat is not a person** — no contact, no claims, no job; neither is a named candidate
  with no confirming URL.
- **One member is one savepoint** — the contact, its three claims and its person job land together
  or not at all; a member that cannot be written is a recorded skip.
- **The person job row is the member's latch** — derived from `run + contact`, so re-settling
  writes nothing twice.
- **It queues nothing** — the driver offers the tasks *after* the transaction commits
  (`account_research_driver.py:985-1000`, "Rows first, offer second").

Skip reasons are named: `vacant_seat`, `unconfirmed`, `committee_cap`, `ambiguous_name`,
`member_not_written` (`committee_step.py:60-66`). Members admitted without a LinkedIn URL are
reported in `linkedin_missing` (`committee_step.py:76-79`).

A committee-step failure is **swallowed** so it cannot cost the account job its terminal row
(`account_research_driver.py:964-969`).

### (f) Finalization — what a job produces

| Artifact | Where |
|---|---|
| `claim` rows (shared claim store) | via `LenientClaimWriter` → `insert_claim` (`platform/api/clue_api/arv2/claim_writer.py:38`) |
| `arv2_research_job.finalization` receipt: `reason`, `summary`, `fit_verdicts`, `gaps`, plus derived counts | `account_research_driver.py:1079-1115` |
| `account.icp_fit_verdict` claims, one per ICP gate, born `outreach_safe=False` | `account_research_claims.py:1418`, `:1462` |
| link-audit annotations (EXACT / PARTIAL / NOT_FOUND) | `account_research_store.py` `job_link_audit`, read at `account_research_driver.py:911` |
| `provider_call_ledger` rows — incl. one `agent_completion` row **per model round** | `account_research_agent.py:111-124`; drained at `account_research_driver.py:893-905` |
| `contact_entity` rows + 3 committee claims each + person `arv2_research_job` rows | `committee_step.py` |
| one activity event | `account_research_driver.py:944` (`_record_activity`) |
| `arv2_research_run.status` recomputed from its jobs in one statement | `account_research_store.py:96-120` |

### (g) The overview page written on first view

Separately from the job, the account's **overview page** is a *rendering* of the research, written
lazily. `ensure_page` (`platform/api/clue_api/arv2/display/page.py:288`) writes only the sections
that are missing, skips sections with no claims (naming them in `skipped_empty`), writes the
missing ones concurrently each through its own `ProviderCaller`, and applies the writes
sequentially (`display/page.py:1-26`). "Nothing here writes a claim, and nothing here decides what
is true… a stale page is regenerated and a wrong page is not — the fix for a wrong page is a better
claim" (`display/page.py:23-25`).

The read surface calls it with three constraints (`platform/api/clue_api/frontend_read/display_pages.py:8-20`):
a read never fails because a model did (failure → stored page + a named `degraded_reason`); a read
never pays for a rewrite (`regenerate_stale=False`, always — a stale section is served as written and
repaired on a **background** task, `display_pages.py:220`, `:332`); construction cannot raise (a
keyless deployment serves stored pages only).

**Load-bearing for the Head of ABM:** the page is generated when a *human opens the account screen*
(`frontend_read/account_detail.py:230`, `:411`; `account_workspace.py:79`; `contacts.py:477`, `:643`).
`read_account_research@1` imports `live_blocks` **only** (`arv2/read_tools.py:44`) — it never calls
`ensure_page`, so the agent's own read does not generate the overview; it refuses
`overview_not_written` and tells the model to read `section="claims"` or open the account in the app
(`arv2/read_tools.py:407-412`).

---

## 3.2 ARV2 person research agent

### (a) How the Head of ABM launches it

Two entrances, and the automatic one dominates.

1. **Automatic** — the account job's committee step creates one person job per confirmed member
   (§3.1e). The skill tells the agent to say so: "each account's buying committee is researched
   automatically once the account job settles"
   (`platform/agents/catalog/skills/stage0-interview/v26/SKILL.md:206`, `:228`).
2. **Explicit** — `launch_arv2_person_research@1`
   (`platform/api/clue_api/arv2/account_research_launch.py:1249`, input model at `:1099-1108`):
   `project_id`, `contact_entity_ids` (1–50), `directive_text`, and `persona` (default
   `Persona.USER`). The persona is "the committee seat a person is given **if they do not already
   hold one**" (profile.yaml comment; `account_research_launch.py:1104-1107`).

Skill rules (`SKILL.md:226-232`): launch only when the human's **current** message names specific
people attached as contact refs; the same preconditions as accounts (confirmed ICP + product set);
"Never add a person the human did not name". It **researches contacts that already exist and never
creates a person** (profile.yaml comment on the tool).

Same `SPEND` class, same `launch_action_ref_missing` refusal shape
(`account_research_launch.py:1152-1163`), same execution-derived `project` pin
(`stage0_recipe.py:459-468`).

> The catalog path in the brief (`entity-research/person/**`) does not exist — **not found**; looked
> in `platform/agents/catalog/entity-research/` (which holds `account/v1-v3`, `contact/v1`,
> `arv2-account/v1`, `arv2-person/v1`). The live person agent is **`arv2-person/v1`**
> (`account_research_catalog.py:27`, `:43`, `:140`). Likewise there is no `person_research_*.py`
> module: the person path is the **same** driver/agent/tools modules, dispatched on
> `job.subject_type` (`account_research_driver.py:665-670`, `_compose_person`; `build_person_tools`
> in `account_research_tools.py`).

### (b) What it does

Subject: one committee member the account job named and the committee step confirmed on a
non-provider URL, with current employer exact-matched against the account. **The subject is locked
by that person's verified employment history**, given in the runtime context under `lock`; anyone
with a similar name whose history does not match is a different person
(`platform/agents/catalog/entity-research/arv2-person/v1/profile.md`, "The subject").

Eleven tools (`entity-research/arv2-person/v1/manual.md`, "The tool contract"):
`read_person_state`, `fetch_page`, `search_web` (six unrestricted sweeps, ≤10 results — a
domain-restricted sweep returns a same-name stranger), `lookup_person` (AI Ark name-scoped STRICT +
email export; **no email is ever synthesised**), `read_media_feeds`, `research_deep` (one dossier
call, max 2 attempts), `structure_material` (subject_kind must be `person`; an `account` subject is
refused `invalid_arguments`), `unique_insight`, `write_claims` (≤50 per call), `verify_links`,
`finalize_research`.

Deliberately absent: the account-only tools (`read_account_state`, `read_ats_board`,
`lookup_company`, `lookup_people`), any judge with veto power, any coverage floor
(`arv2-person/v1/manual.md`, final bullet).

A **deterministic compliance pass** runs over every claim the job wrote *before* the claims are
readable: minors redacted; origin and faith recorded as biography only; the sensitivity floor
redacted with the category; rows with no quote or URL marked `unevidenced`; a claim carrying a
phone number, personal email or home address is **dropped whole** (`arv2-person/v1/manual.md`,
compliance bullet; code in `platform/api/clue_api/arv2/person_compliance.py`).

### (c) How long it runs

Same three caps as the account agent — the person profile's stop-policy table points at the
**same `CLUE_ARV2_ACCOUNT_*` env keys** (`arv2-person/v1/profile.md`, stop-policy table): 100 rounds
/ 50 calls per round / 1800 s. Same "full mode only" ruling. One extra enforced ceiling of its own:
`arv2_person_media_max_items`, default **3** — past it `read_media_feeds` refuses `media_cap_reached`
(`libs/clue-config/clue_config/settings.py:363-366`; `.env.example:165`).

Live numbers: 6:00 / 8:46 / 13:03 wall per person, $0.67–1.25 + 1.5 AI Ark credits
(`_memory/2026-09-09-arv2-r3-person-agent.md:110-113`, `:122`).

### (d) What it produces

Person claims in the shared claim store, a person `finalization` receipt built by `_person_receipt`
(`account_research_driver.py:1118`), link-audit annotations, ledger rows, and the receipt's own
fields: depth summary, three openers (each needing a verbatim quote + URL — an opener with an empty
quote is dropped and named back), hooks, a not-found list with channels checked, the same-name log,
`reports_to` (written only with a verbatim quote and URL), and gaps
(`arv2-person/v1/manual.md`, `finalize_research` row). **No fit verdicts and no committee
candidates** — those are the account job's.

### (e) How the Head of ABM reads its outcome

Through the **same run read**, because a committee-spawned person job lives in the *same run* as its
account job (`committee_step.py:20-23`, job id derived from `run + contact`), and `list_jobs`
returns every job of a run (`account_research_store.py:425-440`).

**Caveat worth stating in the manual:** `read_arv2_account_research_run@1`'s per-job payload is
`{job_id, account_entity_id, status, failure_code}` (`account_research_launch.py:1391-1398`) — it
carries **no `subject_type`**, so committee person jobs appear as extra rows sharing the account's
`account_entity_id` with no way for the agent to tell them apart. `status.md` *does* distinguish
them: its research section prints `"<account name>: <status> (<stage>), <n> person jobs"`
(`platform/api/clue_api/project_status.py:576-578`), so the count of person jobs is only visible
through `status.md`, never through the tool.

---

## 3.3 ARV2 discovery

### (a) How the Head of ABM launches it

Tool: **`launch_arv2_discovery@1`** (`platform/api/clue_api/arv2/discovery_launch.py:710-718` for
the IO; tool class further down the same module). Input: `project_id`, `target_count`
(1–500, default 20), `relaxed_enabled` (default true). Output: `{run_id, replayed}`.

Skill §7b (`SKILL.md:208-216`): call it when the human asks you to find accounts and the project has
a confirmed ICP **and** a confirmed product set; leave `relaxed_enabled` on unless they want strict
matches only; **before proposing another run, call `read_discovery_run` and say what the last run
asked for, found and how many were approved.** Do not start a second discovery for the same target —
the platform re-runs the existing one via `request_relaxed_pass`
(`discovery_store.py:311-320`).

Refusals: `arv2_discovery_not_composed` when the lane is off
(`discovery_launch.py:721-730`), `launch_action_ref_missing` without a captured user action
(`discovery_launch.py:733-744`). `estimate()` returns `cost_cents=0` and carries the *shape* of the
spend rather than a number nobody derived (`discovery_launch.py:786-793`).

Composition: off by default — `arv2_discovery_enabled: bool = False`, and a worker composes the
handler only when the flag is on **and** `CLUE_EXA_API_KEY` is configured
(`libs/clue-config/clue_config/settings.py:369-371`; `.env.example:169`;
`platform/api/clue_api/fleet_main.py:776-790`).

### (b) What it does — Websets → verification-with-quotes → candidates → human approval

**The ICP document is the program** (`platform/api/clue_api/arv2/README.md:1350-1355`): every
confirmed ICP carries `hard_gates[] {key, rule, test}` and `exclusions[]` in plain language. R4
encodes no gate in code — the long list is built from the ICP's wording and the verifier asks each
gate's own `rule`/`test` as a question. A new ICP changes the questions and nothing else.

Two providers, each doing the one thing the PoC showed it does well (`README.md:1357-1362`):
**Exa Websets** in company mode *finds* companies (Exa `/search` on prose returns content *about* an
ICP, not members of it); **Exa Answer** with a system prompt and an `outputSchema` *verifies* them
(Websets' own criteria verdicts were wrong 6 times in 15).

Six steps per run (`platform/api/clue_api/arv2/discovery_driver.py:1-27`):

1. **Claim the run** (`begin_discovery_run`) — a run another worker drives, or one already landed,
   costs nothing.
2. **Read the program** — the document *this run* was pinned to, checked against
   `run.icp_artifact_sha256`, recompiled into the brief on every attempt, so a resumed run asks the
   first attempt's questions even if the project has since repinned.
3. **The strict pass** — one webset with the full criteria, polled to `idle` under a wall clock
   (`arv2_discovery_strict_count` default **35** for a target of 20; `settings.py:372-373`), read once.
4. **The verifier, per candidate** — first the company's own website (Websets said `probook.com` for
   a company whose site is `probook.ai`, and everything downstream keys on the verified domain),
   then **one Answer call per hard gate**, graded by `apply_guards`. Fit = `passes / gates`, an
   unclear counted as half, written as an `account.scoring.fit` claim on a new `candidate` account.
5. **The relaxed pass** — only when the run came up short and the run allows it: a second search on
   the *same* webset, excluding the strict results, dropping the criterion the strict pass's own
   success rates proved was starving it.
6. **The receipt** — asked, found, analyzed, Exa's recall estimate, guard counts, money. "A short
   list is information, never padded."

**Three guards, one per error kind the PoC actually produced**
(`platform/api/clue_api/arv2/discovery_verifier.py:5-24`):
(1) **quote on the page** — the quoted sentence must appear in a citation's text after
normalisation; (2) **right company** — the page carrying the quote must be on the company's own
domain or name the company ("a job posting for *infinIT* is not evidence about *INFI*");
(3) **arithmetic is code's** — when a gate states a window, the date subtraction happens here ("the
model called a 2023 round 'within 24 months'; code does not"). And one rule the guards enforce:
**no source found is `unclear`, never `fail`** — the disposition vocabulary has no `fail`.

Verdicts: `("pass", "fail", "unclear")` (`discovery_verifier.py:60`) —`fail` means a source
*contradicted* the test.

**No spend on a company we already have or already showed** (`discovery_driver.py:40-45`): a verified
domain that is already an account is `duplicate_of_existing`; one an earlier run showed and the
human did not tick is `not_chosen_before` ("unapproved is not rejected"). Both cost exactly the one
website answer that identified them — never a gate.

### (c) How long it runs / how it settles

| Limit | Setting | Default |
|---|---|---|
| Wall clock per run | `arv2_discovery_wall_s` | **1800 s** (`settings.py:385`; `.env.example:183`) |
| Websets poll interval | `arv2_discovery_poll_interval_s` | 15 s (`settings.py:383`) |
| Answer calls in flight | `arv2_discovery_verify_concurrency` | 4 (`settings.py:390-393`) |
| Strict ask | `arv2_discovery_strict_count` | 35 |
| Answer model | `arv2_discovery_answer_model` | `exa` |

`handle` never raises: every failure lands the run `needs_review` with a named reason on its
receipt, and the candidates already verified are **kept — they were paid for**
(`discovery_driver.py:33-38`). Observed webset latency: **~5 min for 25 companies / 250 credits
(≈$1.12)**, **~8 min** for the five-gate webset
(`_memory/2026-09-10-arv2-r4-websets-experiment.md:16`, `:20`).

### (d) What it produces

- `arv2_discovery_run` (asked / found_strict / found_relaxed / analyzed / recall_estimate /
  `receipt_json`) and `arv2_discovery_candidate` rows — `discovery_store.py:105-115`, `:190`.
- A `candidate` **account entity** per verified company, with an `account.scoring.fit` claim.
- **Project membership from the moment it is verified** —
  `ensure_project_accounts(..., added_via="discovered")` runs in the same transaction as the
  candidate's verdicts (`discovery_driver.py:769-780`; founder ruling 2026-09-11, supersedes 6′,
  recorded at `README.md:1597-1600`).

  > **Drift to flag:** skill v26 §7b still says "The human approves accounts there by **adding them
  > to the project**" (`SKILL.md:212`). They are already members. What the human does on the table
  > is set `decision='approved'` (`discovery_store.py:509`, counted at `read_tools.py`
  > `_DISCOVERY_COUNTS`). There is **no recorded rejection** (`read_tools.py:597`).

Dispositions: `pending / pass / partial / unclear / duplicate_of_existing / not_chosen_before`
(`discovery_store.py:74-77`). "Shown" = `pass|partial|unclear` (`discovery_store.py:85`).
"**Verified**" is `jsonb_array_length(c.verdicts_json) > 0` — *judged*, not merely "not pending"
(`discovery_store.py:91-101`): it "used to be the complement of `pending`, and that was wrong in a
way nobody could see from the number… the agent told the founder the platform had checked companies
it had skipped."

### (e) How the Head of ABM reads the outcome

`read_discovery_run@1` (`arv2/read_tools.py:1090-1103`). Serves the project's latest run, or one by
id: `run_id, status, icp_key, icp_version, target_count, asked, found, verified, shown, approved,
relaxed_requested, started_at, finished_at, candidates[≤50], candidate_total`
(`read_tools.py:601-620`). Each candidate: `name, domain, pass ("strict"|"relaxed"), disposition,
decision, fit` (`read_tools.py:585-599`). Refusals: `discovery_run_not_found`, `no_discovery_run`
(`read_tools.py:107-108`). `status.md`'s Discovery section carries the same five tallies
(`project_status.py:555-566`).

### (f) What R4 deliberately does not build (`README.md:1583-1610`)

The Websets exclusion import; a per-run concurrency cap; any frontend change; a chat approval gate
("while the accounts table is the approval surface, no gate tool is needed"); and **the ICP's
exclusion questions** — R4 asks the gates only, `DiscoveryBrief.exclusions` is compiled and nothing
reads it, so "a company that clears every hard gate but sells to consumers can still land as a
High-fit candidate for a human to read."

---

## 3.4 Onboarding synthesis

### (a) How the Head of ABM launches it

The Head of ABM has **one** door into this lane: **`request_persona_synthesis@1`**
(`platform/api/clue_api/persona_request_tools.py:321`). Input: an `icp_key` plus the trusted
`source_turn_ref` (stripped from the model-visible schema)
(`persona_request_tools.py:289-304`). Output: `{run_id, icp_key, replayed}`.

It opens a **personas-only onboarding run** — one governed persona turn for the exact document
version the project pinned, driven on the fleet (`persona_request_tools.py:1-13`). "It writes no
persona itself, it never confirms or repoints anything, and it cannot ask for a profile the project
did not pin: the ICP is resolved from `project_icp_pin`, and the model's `icp_key` is only *checked
against* it." A successful result means **"the work is queued", never "the personas exist"**.

`effect_class = SPEND`, `estimate()` returns 0 cents with
`{"basis": "one_onboarding_persona_synthesis_turn"}` (`persona_request_tools.py:333`, `:369-375`).
Refused when the named ICP is not the project's pin, or a persona run for it is already open
(`persona_request_tools.py:324-329`).

Skill §5c (`SKILL.md:157-159`): ask on the turn *after* the gate confirmation; say it is running,
not that it is done; the same call redrafts a persona later. The document lands at
`inputs/brand/knowledge/audience/persona-<key>.md` or `inputs/project/audience/persona-<key>.md`.

**The `full` kind is not launchable by the Head of ABM.** It is the whole-brand walk started by
`POST /onboarding` — the Welcome flow's setting-up screen — behind `onboarding_v2_enabled` (ON by
default, `settings.py:404-407`).

### (b) The two kinds

`kind: Literal["full", "personas"]` (`platform/api/clue_api/arv2/onboarding_driver.py:329`; payload
validated at `:421-424`).

| | `full` | `personas` |
|---|---|---|
| Subject | the whole brand | ONE already-existing ICP document |
| Steps | recon (overview + lineup + reviews), catalog sync, per-product research, then the ICP turn and one persona turn per ICP | **no recon, no catalog, no ICP turn** — just the persona turn (`onboarding_driver.py:318-322`, `:460`) |
| Started by | `POST /onboarding` | `request_persona_synthesis@1` |

The `full` run's fast lane is overview + lineup (+ reviews when `onboarding_reviews_phase == "fast"`,
the ruling O-D3 default), then the ICP turn starts *alongside* the per-product fan-out rather than
after it, and a persona turn begins the moment its ICP exists
(`onboarding_driver.py:460-490`). Exa efforts: overview `high`, reviews `medium`, product `medium`
(`settings.py:408-418`); `onboarding_max_parallel_runs` = 6 (`settings.py:420`).

### (c) The synthesis agent

`onboarding-synthesis@v3` (`platform/agents/catalog/profiles/onboarding-synthesis/v3/profile.yaml`).
Prompt `onboarding-synthesis@v2`; skills **`icp-synthesis@v3`** and **`audience-persona@v2`**; one
tool, `exa_search_evidence@1`. Model `x-ai/grok-4.6`, `timeout_s: 60.0`, `max_output_tokens: 16384`,
`turn_timeout_s: 1200.0` (20 min), `max_model_rounds: 48`, no delegation.

> The brief's `onboarding-*` skills are **not found** — looked in
> `platform/agents/catalog/skills/`, which holds only `account-deep-steering`,
> `account-gap-research`, `artifact-review`, `audience-persona`, `content-exemplar`,
> `icp-synthesis`, `research-task`, `stage0-interview`. The onboarding turn's two skills are
> `icp-synthesis` and `audience-persona`.

**The ICP/persona split is not cosmetic** (`platform/api/clue_api/onboarding_synthesis_wiring.py:13-28`):
in the single-turn version the ICPs were finished early then "sat unregistered for 8–10 minutes"
because a turn's outputs only become documents once the whole turn ends; and the three personas
queued behind each other when they share no state. The split registers each ICP as soon as its own
turn ends and lets persona turns run concurrently. The two tasks carry different authority — the
ICP turn resolves the `onboarding_icp` surface where **the evidence tool is not installed**; a
persona turn keeps the role's full surface (`onboarding_synthesis_wiring.py:26-28`, `:830-841`).

Brand knowledge documents are materialized read-only under `inputs/brand/knowledge/` and the turn's
`outputs/` become new `brand_knowledge_document` rows stamped `produced_by_turn_id`
(`onboarding_synthesis_wiring.py:8-11`). The ICP task sees **every** ICP on file (so a re-run
*refines* under the existing key rather than renaming it); a persona task sees exactly **one**
(`onboarding_synthesis_wiring.py:361-363`, `:558-565`).

### (d) Documents it writes

Two output kinds, each with a durable born status (`onboarding_synthesis_wiring.py:175-184`):
ICP documents and persona documents, under `outputs/audience/`. An output whose front matter is
unreadable, or whose `kind` is not one this surface may write, is rejected
(`onboarding_synthesis_wiring.py:1240-1271`). Registered ICPs come back as `RegisteredIcp` rows
(`onboarding_synthesis_wiring.py:645`).

### (e) How the Head of ABM reads the outcome

**Only through `status.md`.** There is no persona-run read tool. `PersonaRunFacts` exists precisely
for this: "The agent opens these through `request_persona_synthesis@1` and is told 'it is running';
the run then lives entirely on the fleet. **Without a line here, a run that failed, stalled or
finished with gaps is visible to nobody** — not the agent that asked, not the human waiting for the
document — and the agent keeps reporting work that will never land."
(`platform/api/clue_api/project_status.py:113-121`). The `## Personas` section prints the latest
three runs with `run_id, status, requested, finished` (`project_status.py:579-587`,
`_PERSONA_RUNS_SHOWN = 3` at `:203`). The document itself then appears as a file under
`inputs/…/audience/` and in `status.md`'s `## Project documents`.

---

## 3.5 The design trio / design leg

### (a) How the Head of ABM opens one

Tool: **`open_design_leg@4`** (`platform/api/clue_api/design_leg_tools.py:400`). `effect_class =
WRITE` (`design_leg_tools.py:427`), `pin_requirements = ("project",)` resolved from the presenting
turn (`stage0_recipe.py:434-441`).

Arguments, per the model description (`design_leg_tools.py:402-425`):

- a **new website** → `doc_kind="web"` and **no** `document_id` → an empty web document is created
  and the leg pinned to it, so the artifact appears in the project's gallery immediately;
- a **new ad / designed page** → `doc_kind="scene"` and no `document_id` → an empty **pageless**
  scene is minted and the design agent authors the page itself. `@4` **deleted** `ad_format` /
  `ad_width` / `ad_height` from the input (genad2 ruling 1) — "Do not infer or restate dimensions
  yourself; Design owns them" (`design_leg_tools.py:369-385` for the pageless minter);
- an **existing artifact** → pass its `document_id` (`doc_kind` then ignored);
- a **mis-closed leg** → `reopen_leg_id`, which ignores every other field;
- `title` — "the name the user would recognise"; `brief` — the user's actual ask, "because **Design
  sees the brief, not this conversation**".

### (b) What a leg is

"Delegating to Design is not a LangGraph edge but a durable act" — validate the pins, build the
delegation bundle as one immutable canonical-JSON artifact, and open the `design_leg` row **whose
existence *is* the routing rule**: an open leg on the thread receives the user's message
(`design_leg_tools.py:1-7`).

Three authority disciplines (`design_leg_tools.py:9-25`): the leg's anchor is the presenting turn,
not the agent's choice (one turn → one leg id, so a replay converges); pins are verified against
durable rows, never trusted (a stale `expected_document_version` is refused; a brand pin must name an
existing `(brand_kit_id, version)`); the bundle is bounded at build
(`DESIGN_DELEGATION_BUNDLE_MAX_BYTES`, half the 48k L3 layer).

Claim refs ride the `ContactHandoffClaimRef` vocabulary — **ids + governance stamps, never values**;
"the only way a head-of-abm holds claim ids at all is by having read them through
`get_research_view`" (`design_leg_tools.py:27-30`) — note that this justification is now stale,
since `get_research_view` is disabled (§3.6).

### (c) The Head of ABM's role during a leg

**None, and that is the point.** "What this tool does **not** do: dispatch anything. Opening a leg
spends nothing and runs no design turn; the agent's next act is to tell the user the design session
is open and end its turn. The user's next message on the thread is what becomes the first design
turn" (`design_leg_tools.py:32-36`). The model description repeats it: "While the leg is open, every
user message on this thread goes directly to Design — **you will not see the thread again until the
leg closes**… generating a page takes minutes, not seconds."

Worker side (`platform/api/clue_api/design_leg_wiring.py:1-36`): when the `AGENT_TURN` worker claims a
turn whose thread holds an **open** leg, the message does not wake head-of-abm — it becomes a design
turn on that leg, landing as a real `agent_turn` row with role `design`, parented under the
delegating platform execution. Production drives the design fleet handler **inline under a real work
lease** rather than enqueueing a second fleet task, because "the platform fleet drains one task at a
time per worker, so an `AGENT_TURN` handler that queued a `design_job` and waited for it would
deadlock a single-worker deployment against itself."

**Leg-scoped history (§2.4):** `load_design_leg_history` returns exactly this leg's user↔design
exchanges; `load_head_of_abm_history` **excludes every design-role turn**, so head-of-abm never
ingests the leg transcript. Leg summaries enter head-of-abm's view **at leg close**
(`design_leg_wiring.py:26-30`, and the summary-message join at `design_leg_wiring.py:356-376` — "a
summary, never a transcript").

### (d) The trio, and how artifacts come back

The generator is a three-role trio inside the design runtime — orchestrator → `lumen-web-author` →
`lumen-web-reviewer`, with Playwright screenshots at 1440/768/375, driven by
`run_deepagent_web_turn` (`docs/superpowers/plans/2026-08-19-chat-driven-website-generation.md:56-68`,
pointing at `subsystems/clue-design/apps/agent_runtime/lumen_agent/harness_web.py:214`).

A design turn that produced a proposal ends `AWAITING_INPUT` with `open_gate_refs` naming the leg —
"the leg *is* the open interaction" (`design_leg_wiring.py:20-23`). Each turn writes one durable
assistant summary that **names the artifact and invents nothing** (`_assistant_summary` /
`_web_turn_summary`, `design_leg_wiring.py:556-590`), and the chat stream rehydrates with reason
`design_turn_summary` (`design_leg_wiring.py:1018`). The rail's gallery derivation is "legs joined to
`design_document` where `doc_kind='web'`", so the card appears the moment the leg opens
(`design_leg_tools.py:38-44`).

### (e) Closing the leg — the Head of ABM cannot

`finish_design_leg@1` is granted to **`AgentRole.DESIGN` only**
(`platform/api/clue_api/agent_registry_wiring.py:262`); it is not in head-of-abm v49's tool list.
Reasons: `locked` (user accepted), `out_of_scope` (the user's last message is re-delivered to the
strategy agent **verbatim**, never rewritten), `abandoned` (`design_leg_tools.py:1088-1096`). The
summary is what the strategy agent resumes with. The durable summary is "the engine's honest
sentence, never a fabricated model quote" (`design_leg_wiring.py:223-224`).

### (f) The plan's STATUS HEADER — the one blocker

`docs/superpowers/plans/2026-08-19-chat-driven-website-generation.md:3-28`, **STATUS 2026-08-19 —
BUILT AND WALKED; COMPLETE pending founder sign-off and ONE blocker**: slice 4's acceptance walk
proved ask → leg opens → document born → page generated *with layout* → "make the hero darker" lands
→ inspector hand-edit interleaves → brand-themed generation resolves the approved kit.

> **"The one step that could NOT be exercised: 'lock it in' does not close the leg."**
> `build_design_leg_exit_judge` builds the judge with the DESIGN profile's `timeout_s: 120.0`,
> which the gateway refuses (`GatewayConfig.timeout_s` default 30.0; 59 of the other 60 profiles use
> 30.0), so the judge always raises and P3.6's fail-safe envelope turns every exit intent into
> CONTINUE.

Operationally, for the Head of ABM's manual: **a leg you open may not hand the thread back on its
own.** The fix (clamp in the builder, or mint design profile v2) was left as the founder's call, and
the walk's leg was deliberately left OPEN.

---

## 3.6 Legacy tools still granted to head-of-abm v49

Standing project rule: **"ARV2 schema is the only truth"** — never bridge to or preserve the old
research lane's tables. The seven tools below are still in v49's grant list. Verdicts traced from
the table each one actually touches.

| Tool | Version | Writes/reads | Old lane? | Verdict on ARV2 |
|---|---|---|---|---|
| `get_research_view` | 1 | `research_view_snapshot` + the C7 composer over claims | yes (C7) | **DEAD — flag-disabled** |
| `draft_account_research_directive` | 5 | `account_research_directive` | yes (FI Lane D / M8D) | **DEAD-END — writes rows nothing on the ARV2 lane reads** |
| `open_directive_confirmation_gate` | 1 | confirms an `account_research_directive` revision | yes | **DEAD-END — same chain, no consumer granted** |
| `inspect_statement_history` | 1 | Stage-0 `statement` rows via `read_statements` | no — shared | **LIVE** |
| `propose_field` | 2 | `field_proposal` (+ dynamic Client-KB materialization) | shared substrate | **LIVE but bypassed** |
| `propose_source` | 1 | `source_proposal` | shared substrate | **LIVE but bypassed** |
| `submit_ingestion` | 1 | `ingestion_job` via the C3 `IngestionEngine` | shared substrate | **LIVE, unrelated to ARV2 research** |

### `get_research_view@1` — DEAD

What it does today: resolves the live governed C7 research view for one `(workspace, project,
project_run, product, subject)` and returns **references and hashes only** — a `fetch_ref`, a
`source_state_sha256`, and a `snapshot_id` when one matching snapshot already exists
(`platform/api/clue_api/research_view_tools.py:297-298`, `:358-400`).

Why it is inert: it is built with `read_enabled=resolved_settings.c7_research_view_read_enabled`
(`platform/api/clue_api/toolbelt_wiring.py:3046-3054`), and that flag is **false** both in the
shipped example and in the local env — `CLUE_C7_RESEARCH_VIEW_READ_ENABLED=false`
(`.env.example:347`, `.env:85`). Disabled, `preconditions` returns
`research_view_feature_disabled` (`research_view_tools.py:345-352`). Note a second, historical trap
recorded in the recipe: for a long time "no case here ever REQUESTED its three declared pin kinds,
so plan validation refused every call (`missing_tool_requirement`) and **the grant was dead**"
(`stage0_recipe.py:485-490`); the pins were repaired 2026-08-19, but the feature flag was not
flipped.

Consequence for `open_design_leg`: the design tool's docstring still asserts that the only way
head-of-abm holds claim ids is `get_research_view` (`design_leg_tools.py:29-30`). Today the only
claim ids it can hold come from **`read_account_research@1`** (`arv2/read_tools.py:288-310`).

### `draft_account_research_directive@5` / `open_directive_confirmation_gate@1` — DEAD-END

`draft` persists "one non-spending immutable account-research directive draft"
(`platform/api/clue_api/research_directive_tools.py:361-366`; module docstring at `:1` — "A2
non-spending tools for drafting and human-confirming account research direction"). The gate then
confirms that exact revision, which is what makes a redrafted directive refuse rather than slip
through (`stage0_recipe.py:405-408`; gate class at
`platform/api/clue_api/agent_gate_tools.py:183`).

Both work — the pins resolve (`stage0_recipe.py:409-422`, `:470-484`). But the chain terminates.
Every consumer of `get_research_directive` is an **M8D-lane** launch —
`platform/api/clue_api/account_research_fleet_launch.py:244`,
`platform/api/clue_api/entity_research_launch_tools.py:41-43`,
`platform/api/clue_api/contact_research_selection.py:228`,
`platform/api/clue_api/sumble_committee_inputs.py:219`,
`platform/api/clue_api/exa_deep_materialization.py:308` — and **none of those launch tools is
granted to head-of-abm v49** (compare the profile's tool list: `launch_account_research` and
`launch_selected_account_research` are absent). The founder ruling is explicit: "v44 drops the five
old-lane launch/read tools… the old research lane is legacy"
(`_memory/2026-09-09-arv2-onboarding-o6-head-of-abm.md:298`). And the ARV2 launch states in its own
module docstring that it needs "no `account_research_directive`… The old Stage-0 launch machinery is
not a dependency of this lane and must never become one"
(`arv2/account_research_launch.py:17-19`) — the ARV2 launch takes a free-text `directive_text`
instead (`account_research_launch.py:1088`).

Stage0-interview v26 mentions neither tool anywhere
(no match in `platform/agents/catalog/skills/stage0-interview/v26/SKILL.md`).

**So:** a confirmed directive on the ARV2 lane is a row a human signed that nothing will ever
execute. Treat both as vestigial; use `directive_text` on the launch.

### `inspect_statement_history@1` — LIVE

One of the two bounded governed inspection tools the project card's `omissions` point at
(`platform/api/clue_api/stage0_inspection_tools.py:1-8`, class at `:294`). It serves interview
statements with their supersession/correction lineage and their words, resolved through the shared
evidence reader; "an erased or mismatched quote surfaces as *excluded* with its reason; the tool
never fabricates the words it could not read."

It reads the **same** statement table that `record_interview_answer@1` (live, granted, the backbone
of skill §6) writes — `read_statements` over `project_state` / `claim` / `unmapped` routes
(`subsystems/research/clue_research/stage0/governed.py:618-633`;
`StatementRoute` at `:56`). `status.md`'s sibling `decisions.md` is compiled from exactly those rows
(`platform/api/clue_api/project_status.py:599-609`). Bounded to `MAX_INSPECTION_PAGE` rows with the
card's own cursors (`stage0_inspection_tools.py:15-28`), workspace/project-scoped fail-closed
(`:30-33`).

### `propose_field@2` / `propose_source@1` — LIVE but bypassed by the ARV2 lane

Both write governance proposals under a resolved scope, refusing `proposal_scope_not_found`
(`platform/api/clue_api/proposal_tools.py:181-216`, `:392-416`). Pins resolve: the recipe requests
`proposal_policy` + `field_registry` / `source_registry` (`stage0_recipe.py:523-551`) and the
`brand` pin comes off the trusted top-level `brand_id` body field (`stage0_recipe.py:330-337`;
`ProposeFieldInput.brand_id` at `proposal_tools.py:95-98`). A promoted `client.*` proposal
materializes into the dynamic Client-KB (`proposal_tools.py:227-236`).

They are alive and skill v26 §6 still routes "a novel field or source" through them
(`SKILL.md:168`). But **ARV2's research agents never use them**: the lenient claim-write gate
"registers an unknown key as a proposed field" itself, calling `register_field` directly
(`platform/api/clue_api/arv2/claim_writer.py:5`, `:38-42`). So a proposal made here is a
human-conversation artefact, not how ARV2 fields actually get born.

### `submit_ingestion@1` — LIVE, unrelated to ARV2 research

C3 upload ingestion: `submit_ingestion` takes an `artifact_key` plus `DeclaredMaterialInput` and
drives the `IngestionEngine` (`platform/api/clue_api/ingestion_tools.py:118-127`, class at `:144`;
module docstring at `:1`). Pinned on `ingestion_policy` (`stage0_recipe.py:553-559`). Skill §6:
"An **upload** already captured in the workspace goes through `submit_ingestion` with its material
context" (`SKILL.md:169`). It is a *material capture* path into the claim store, not part of any
ARV2 run, and nothing in `clue_api/arv2/` references it.

---

## 4. Observability the Head of ABM can use

## 4.1 `read_arv2_account_research_run@1`

`platform/api/clue_api/arv2/account_research_launch.py:1337-1399`.
Effect-free (`READ` / `EFFECT_FREE`, `:1352-1356`); "it never starts, resumes or changes research"
(`:1340-1344`).

Input: `{run_id}` (`:1112-1113`). Output (`ReadArv2AccountResearchRunOutput`, `:1116-1123`,
materialized at `:1385-1399`):

```
run_id, status, icp_artifact_key, product_selection_version, effort, committee_cap,
jobs: [ { job_id, account_entity_id, status, failure_code } ]
```

Absence is a **typed refusal**, not an empty success: a run in another workspace, or none,
raises `arv2_account_research_run_not_found` — "an empty run projection is a lie about a run that
may be running elsewhere" (`:1372-1382`; workspace check at `:1069-1073`).

Job statuses the agent will see: `not_started`, `in_progress`, `needs_review`, `completed`,
`suspended` (`account_research_store.py:67`). Only `needs_review` carries a `failure_code`, and the
constraint is biconditional — "flagged with no code" is not a row the database will take
(`account_research_store.py:79-83`). A `suspended` job is a **pause**, not a terminal
(`account_research_store.py:77`) — the driver suspends every in-flight job on a stop request or lost
lease, i.e. **on every worker restart** (`arv2/research_progress.py:31-35`).

Run status is *derived* from its jobs in one statement, never set by whoever finished one
(`account_research_store.py:96-120`): any `in_progress` → `in_progress`; a mix of `not_started` with
anything finished → `in_progress`; any `suspended` → `suspended`; any `needs_review` →
`needs_review`; else `completed`.

**Not in this output:** the finalization receipt, the job's stage, the claim count, the cost, the
model rounds, the tool calls, `subject_type`, the account's name.

## 4.2 The `status.md` research section

Compiled from rows, never from a model; the renderers are pure and "every timestamp is a row's own,
so two attempts of one turn compile identical bytes"
(`platform/api/clue_api/project_status.py:1-6`). It is seeded into the agent's workspace on every
turn and pinned for that turn (`platform/api/clue_api/agent_turn_fleet_wiring.py:600-631`).

Renderer: `render_status_markdown` (`project_status.py:515-596`). **Every section always renders —
an empty one says so rather than disappearing** (`:516`). Sections: Confirmed ICP, Products, Plan,
Accounts (count), Discovery, Research, Personas, Project documents.

The **Research** section (`project_status.py:567-578`):

```
## Research
- Run `<run_id>`: <status>, effort <effort>, <finished>/<total> finished (created <iso>)
  - <Account name>: <status> (<stage>), <n> person jobs
```

- newest 5 runs only — "older runs are history, not status" (`:63`, `_RESEARCH_RUNS_SHOWN = 5`);
- "finished" counts `completed` + `needs_review`; "the seam-1 vocabulary has no separate 'failed': a
  job that could not finish lands in needs_review" (`:65-67`);
- the **stage** and the **person-job count** appear here and **nowhere else the agent can read**.

The **Discovery** section (`project_status.py:555-566`) prints the latest run only, with
`asked / found / verified / shown / approved` computed by `_LATEST_DISCOVERY`
(`project_status.py:138-165`) — and the "verified"/"shown" arithmetic is deliberately bound from
`discovery_store`'s public constants rather than retyped, "so a seventh disposition cannot leave
status.md quietly reporting a different number than the UI" (`project_status.py:141-150`).

The **Personas** section (`project_status.py:579-587`) is the *only* window onto
`request_persona_synthesis` runs (§3.4e).

## 4.3 The claim/statement inspection surfaces

There are three distinct things called "inspector"; only two are the agent's.

**(i) `read_account_research@1` — the claim inspector.**
`platform/api/clue_api/arv2/read_tools.py:993-1053`. Two sections:

- `section="overview"` → the written overview blocks as stored: `section_key`, `body_text`
  (`display_block.body_json` serialized, capped at `BODY_CHARS = 6000`), `body_truncated`,
  `cited_claim_ids`, `generated_at` (`read_tools.py:273-285`). Refuses `overview_not_written` when
  nothing has been generated — and the read **does not generate it** (§3.1g,
  `read_tools.py:407-412`).
- `section="claims"` → per claim: `claim_id, field_key, value, source_url, evidence` (clipped at
  `EVIDENCE_CHARS = 240`, ending in `…`), `evidence_truncated, tier, verification_status,
  outreach_safe, collected_at` (`read_tools.py:288-309`). Capped at `MAX_CLAIMS = 120` with a
  `truncated` flag. Refuses `account_not_researched` (no claims at all) or `no_claims_under_prefix`
  — "a distinct code: the account IS researched, and saying otherwise because one prefix came back
  empty is a false statement about the account" (`read_tools.py:486-500`).

**The display gate holds claims back and counts them** in
`excluded = {"sensitive": n, "unverified": n, "outreach_unsafe": n}`
(`read_tools.py:318-322`, `:502-512`) — "an empty answer with a count is a fact; an empty answer
alone is a lie." This mirrors the account page's own gate, "so chat cannot state a fact the app
refuses to print" (profile.yaml v49 header).

> **Load-bearing consequence.** The account agent's `account.icp_fit_verdict` claims are born
> `outreach_safe=False` (`arv2/account_research_claims.py:1462`) **and** `LLM_SYNTHESIS` → tier 4
> (`claim_writer.py:50`). So every ICP fit verdict is held back by *two* gate rules
> (`read_tools.py:508-512`) and reaches the agent only as a number in
> `excluded["outreach_unsafe"]`. **The Head of ABM cannot read the fit verdicts its own launch
> produced.** The discovery lane's `fit` float is readable (`read_discovery_run`), the account
> agent's per-gate verdicts are not.

**(ii) `inspect_statement_history@1`** — the interview-statement inspector (§3.6), with lineage and
words, excluded quotes named with their reason.

**(iii) The turn-context "inspector" is NOT the agent's.** `platform/api/clue_api/chat/inspector.py`
is a **dev-lens HTTP surface** for a human tuning prompts: four read views over one assistant turn —
context receipts, plan receipts, model rounds, tool calls, status events. "Zero new storage…
Dev-only by construction": the routes are registered only when `chat_dev_inspector_enabled`
(`libs/clue-config/clue_config/settings.py:684`), and that setting **fails process construction in a
production deployment** (`settings.py:1008`, `_refuse_dev_lens_in_production`). No tool in head-of-abm
v49's grant list reaches it.

## 4.4 What the Head of ABM CANNOT see

Verified by reading the output shape of every granted read.

| Blind spot | Where the data actually lives | Proof no granted tool serves it |
|---|---|---|
| **Cost / spend, USD** | `arv2_research_job.cost_usd`, `credits`, `media_seconds` (`account_research_store.py:181-183`); `provider_call_ledger` rows drained per job (`account_research_driver.py:893-905`); the discovery run's `receipt_json` money block (`discovery_driver.py:25-26`) | `read_arv2_account_research_run` output has no cost field (`account_research_launch.py:1385-1399`); `read_tools.py` contains no `cost`/`usd`/`credits` field on any view model; `status.md` prints no money (`project_status.py:515-596`) |
| **Token spend / prompt caching** | `ModelSpend{calls, usd, prompt_tokens, completion_tokens, cached_prompt_tokens, cost_source}` on the agent outcome (`account_research_agent.py:69-92`) | never surfaces past the job row's `finalization`, which no granted read serves |
| **Budget / remaining allowance** | there is none to see — "Money is *recorded*, never enforced (`over_ceiling` is a row, not a stop)" (`arv2-account/v1/profile.md`); both ARV2 launch `estimate()`s return `cost_cents=0` with only the *shape* of the spend (`discovery_launch.py:786-793`, `persona_request_tools.py:369-375`) | — |
| **Logs / tracebacks** | `clue_obs` structured logs (`arv2.account_job_finished`, `arv2.discovery_candidate_verified`, …) and the dev-lens inspector | logs go to the operator; the inspector routes do not exist in production (`settings.py:1008`) |
| **Latency / elapsed time, live** | `arv2_research_job.started_at`/`finished_at` | not in the run read; `status.md` gives run `created_at` and discovery `started/finished`, but **no per-job timestamps** (`project_status.py:572-578`) |
| **Model rounds / tool calls used** | `arv2_research_job.model_rounds`, `tool_calls` (`account_research_store.py:179-180`) | absent from every granted read |
| **The finalization receipt** — summary, fit verdicts, gaps | `arv2_research_job.finalization` (`account_research_driver.py:1101-1115`) | `AccountResearch` carries only overview/claims/excluded (`read_tools.py:311-323`); the run read carries only status/failure_code |
| **Per-job stage, via a tool** | `arv2_research_job.stage` | **only** via `status.md` (`project_status.py:577`) — not in `read_arv2_account_research_run` |
| **Person vs account job, via a tool** | `arv2_research_job.subject_type` | not in the run read's per-job dict (`account_research_launch.py:1391-1398`); only the `status.md` "n person jobs" tally |
| **Whether a design leg's turn is running / what it cost** | design run rows in the design substrate | head-of-abm's history **excludes every design-role turn** (`design_leg_wiring.py:28-30`); it sees only the close summary |
| **Persona-run detail beyond status** | `onboarding_run` rows | `status.md` `## Personas` only (`project_status.py:579-587`) |
| **Fleet queue depth / worker health** | the fleet plane | no granted tool touches it |

**One exception worth knowing.** `read_account_research(section="overview")` serializes
`display_block.body_json` verbatim into `body_text`, and that stored body is
`{intro, items, checks, cited_flags, cost_usd, call:{ledger_row_id, raw_ref, raw_refs}}`
(`read_tools.py:336-339`; produced at `display/blocks.py:109-120`). So the **only** dollar figure the
Head of ABM can ever observe is the cost of writing *that display section* — not the cost of the
research — and it may be cut off by the 6000-char cap.

## 4.5 The honest summary for the manual

The Head of ABM can see **what state everything is in** (statuses, stages via `status.md`, counts,
dispositions, candidate verdicts, claims with their evidence and tier) and **nothing about what any
of it cost, how long it took, or how hard the sibling worked**. Every number it can report about
money or effort would be invented. The manual should say so in those words.

---

## 5. Error vocabulary — every string the model can receive as a tool result

There are exactly **three** shapes of bad news the Head of ABM can read.

### 5.1 `GovernedToolFailure` — refusals of a governed platform tool

Returned as JSON from the tool (`agent_runtime_wiring.py:300-320`). Two `error` values:

| `error` | Raised from | `reasons` format | Source |
| --- | --- | --- | --- |
| `plan_rejected` | `AgentPlanRejected` out of `validate_plan` — the proposal never obtained execution authority, so **nothing ran**. | `f"{issue.location}: {issue.code}: {issue.message}"`, one per issue | `agent_runtime_wiring.py:762-786` |
| `operation_failed` | The plan validated and executed, but the operation did not complete. | `f"{failure.error_type}: {failure.message}"`, one per failure; falls back to `("the governed operation did not complete",)` | `agent_runtime_wiring.py:787-813` |

`error_type` is literally `type(error).__name__` (`agent_execution_wiring.py:154-163`). `message` is
whitespace-collapsed and truncated to **600 characters** with a trailing `…`
(`agent_execution_wiring.py:136,148-151`). For a `PreconditionFailed` the message is rebuilt as
`"; ".join(f"{failure.reason_code}: {failure.message}")` — "a precondition refusal states its codes
in `str()` and *what to do about it* only in the per-failure messages, which is the half a model can
act on" (`agent_execution_wiring.py:139-145`).

Every `GovernedToolFailure` carries `recorded: false` and the fixed guidance sentence
(§1.6). **What it should make the agent do:** correct exactly what `reasons` names and call again,
or tell the human what is blocking — and never describe the operation as having happened.

#### `plan_rejected` issue codes (complete list)

All `AgentPlanIssue.code` values in the repo. Twelve come from the package policy, three from the
composition root.

| Code | `location` | Message | Source |
| --- | --- | --- | --- |
| `execution_scope` | `plan.execution_id` | proposal execution differs from the trusted constitution | `execution.py:254-256` |
| `role_scope` | `plan.role` | proposal/profile role differs from the trusted constitution | `execution.py:262-264` |
| `workspace_scope` | `plan.goal_ref` | plan goal belongs to another workspace | `execution.py:270-272` |
| `node_ceiling` | `plan.steps` | `{n} nodes exceed the ceiling {max_nodes}` (48) | `execution.py:278-280` |
| `tool_not_allowed` | `plan.steps.{node}.tool` | `{address} is absent from exact effective authority` | `execution.py:293-295` |
| `delegation_not_allowed` | `plan.steps.{node}.role` | `role {role} is not delegated by this profile` | `execution.py:303-305` |
| `workspace_scope` | `plan.steps.{node}` | delegation inputs cross the trusted workspace | `execution.py:313-315` |
| `path_grant` | `plan.steps.{node}.granted_paths` | `path {path!r} exceeds parent readable authority` | `execution.py:325-327` |
| `delegation_ceiling` | `plan.steps` | delegation count exceeds the effective profile ceiling (6) | `execution.py:334-336` |
| `delegation_depth` | `plan.steps` | delegation depth is exhausted (1) | `execution.py:342-344` |
| `depth_ceiling` | `plan.steps` | `dependency depth {d} exceeds {16}` | `execution.py:352-357` |
| `fanout_ceiling` | `plan.steps` | `ready fanout {f} exceeds {8}` | `execution.py:360-365` |
| `pin_resolution_failed` | `plan.steps.{node}` | `str(exc)` from pin resolution | `agent_execution_wiring.py:1489-1491` |
| `c5_pin_kind_not_allowed` | `plan.steps.{node}` | `resolved pins exceed the active interaction slot: {kinds}` | `agent_execution_wiring.py:1507-1512` |
| `budget_ceiling` | `plan.steps` | `estimated {n} millicents exceeds {limit}` | `agent_execution_wiring.py:1596-1600` |
| `no_binding` | (raised as `CapturedTurnUnavailable`, reason code) | `{key!r} is served from this turn's captured input, which is unavailable` | `agent_execution_wiring.py:305-309` |

Issues are sorted by `(location, code, message)` before the model sees them
(`execution.py:368`).

#### `operation_failed` — `PreconditionFailed` reason codes

A precondition refusal is the most common thing the Head of ABM will actually read. The codes are
tool-owned; the complete set of literals currently constructed under `platform/api/clue_api/`
(grep `reason_code="`), grouped by what they mean:

| Family | Codes |
| --- | --- |
| Research view / statements | `research_view_not_configured`, `research_view_feature_disabled`, `research_view_workspace_not_admitted`, `research_view_subject_not_found`, `research_view_snapshot_not_found`, `statement_evidence_missing`, `unbindable_field` |
| Turn binding / capture | `no_binding`, `capture_not_utf8`, `artifact_digest_mismatch` |
| Products | `product_catalog_unavailable`, `product_catalog_empty`, `product_set_turn_not_found`, `product_set_project_unavailable`, `product_set_no_candidates`, `product_set_addressee_missing`, `product_selection_turn_not_found`, `product_selection_scope_unavailable`, `product_selection_addressee_missing`, `project_product_already_confirmed`, `exact_set_user_confirmed` |
| ICP | `icp_turn_writes_from_files_only`, `icp_key_unknown`, `icp_authoring_not_composed`, `persona_synthesis_not_composed` |
| Gates / human authority | `human_required`, `human_resume`, `human_reprioritize`, `gate_subject_malformed`, `gate_turn_ref_malformed`, `gate_turn_not_found`, `gate_project_run_not_found`, `gate_addressee_missing`, `insufficient_proposal_authority` |
| Design legs | `design_leg_already_open`, `design_leg_not_open`, `design_leg_runtime_not_configured`, `design_leg_storage_not_configured`, `design_leg_turn_not_found`, `design_leg_turn_ref_malformed`, `design_leg_turn_execution_missing`, `design_leg_replay_closed`, `design_leg_reopen_not_found`, `design_leg_reopen_not_closed`, `design_leg_reopen_wrong_thread`, `design_leg_exit_wrong_turn`, `design_leg_exit_no_user_message`, `design_leg_doc_kind_required`, `design_document_not_found`, `design_document_pin_stale`, `design_document_pin_incomplete`, `design_bundle_too_large` |
| Legacy / old-lane research | `research_directive_not_found`, `research_directive_not_draft`, `research_directive_invalid`, `account_discovery_not_started`, `account_discovery_not_sealed`, `account_discovery_seal_invalid`, `account_quarantined`, `selected_launch_not_admissible`, `launch_action_ref_missing`, `entity_research_agent_not_composed`, `project_run_paused`, `project_conversation_no_autonomous_research` |
| Exa / deep acquisition | `exa_deep_acquisition_in_progress`, `exa_deep_source_manifest_unavailable`, `exa_deep_snapshot_required_but_not_ready`, `exa_deep_pinned_icp_unavailable`, `exa_deep_not_authorized_by_effective_directive`, `exa_deep_effective_source_plan_missing`, `exa_deep_effective_field_schema_missing`, `exa_deep_confirmed_directive_pin_required`, `exa_deep_account_not_resolved_in_workspace`, `exa_terminal_enrichment_null`, `exa_import_did_not_resolve_identifier`, `sumble_terminal_field_absent`, `sumble_native_value` |
| Ingestion | `ingestion_not_found`, `ingestion_not_configured`, `ingestion_not_retryable`, `ingestion_context_invalid`, `ingestion_artifact_not_found`, `ingestion_artifact_erased` |
| Brand kit | `brand_kit_pin_not_found`, `brand_kit_pin_incomplete` |
| Project / thread scope | `project_not_found`, `project_documents_not_composed`, `thread_project_mismatch`, `thread_owner_unresolved`, `contact_selection_not_found`, `trial_manual_conversation_only` |
| Fleet / canary | `child_failed`, `operation_failed`, `stop_requested`, `agent_cancelled_or_crashed`, `canary_source_health_failed`, `canary_source_affected_account`, `canary_health_gate_passed`, `canary_health_failed` |

Sources: grep of `reason_code="…"` across `platform/api/clue_api/**/*.py`. The set is open —
any tool may add one — so the manual should teach the *shape*, not memorisation: a precondition
code plus a sentence naming what to satisfy.

**What a precondition refusal should make the agent do:** report the exact missing precondition to
the human and stay `awaiting_input`. It must not retry the identical call — a durably `BLOCKED`
operation refuses with "invoke a new operation after satisfying its prerequisite"
(`invoker.py:199-208`), and three refusals in a turn kill it.

### 5.2 deepagents file-tool errors (the virtual workspace)

These do **not** go through the governed path; they come back inside the framework file tool's own
result object, as a prefixed string produced by one mapper:

```python
if isinstance(exc, WorkspaceQuotaExceeded):  return f"quota_exceeded: {exc}"
if isinstance(exc, WorkspaceConflict):       return f"conflict: {exc}"
return f"permission_denied: {exc}"
```
`platform/agents/clue_agents/workspace.py:729-737`. Applied by `ls`/`read`/`write`/`edit`/`glob`/
`grep`/`upload_files`/`download_files` (`workspace.py:739-844`).

| Prefix | Concrete messages | Source | What it should make the agent do |
| --- | --- | --- | --- |
| `quota_exceeded:` | "file exceeds the per-file workspace quota"; "workspace file-count quota would be exceeded"; "workspace total-byte quota would be exceeded"; "workspace file-count quota is already exceeded"; "workspace contains a file over its per-file quota"; "workspace total-byte quota is already exceeded"; "workspace file exceeds its read quota" | `workspace.py:383-399`, `:535-538` | Write less, or read a narrower slice. The quota envelope is immutable for the turn; retrying the same write cannot succeed. |
| `conflict:` | "workspace file already exists"; "workspace file changed during edit"; "edit source text was not found"; "edit source text is not unique"; "snapshotted outputs are immutable"; "workspace resources cannot be frozen in the current state"; "reopened workspace policy differs from its original authority" | `workspace.py:182-194`, `:286`, `:431`, `:460`, `:490`, `:563-565`, `:679` | Re-read the file and redo the edit against current bytes. "not found"/"not unique" means copy the span exactly or disambiguate — never reword it. |
| `permission_denied:` | The catch-all for every other `WorkspaceError`, incl. `WorkspaceSecurityError` ("a logical path, filesystem object, or permission violates isolation") and path rejections. Also the hard-coded `"permission_denied: replace_all is not available"`. | `workspace.py:737`, `:780`; `workspace_policy.py:34` | Stop. This is a capability the agent does not have; do not try a variant path. Use a relative path inside the virtual workspace. |
| `invalid_encoding` | Upload of non-UTF-8 bytes (no prefix — a bare code). | `workspace.py:827` | The file cannot be uploaded as text. |

Exception hierarchy: `WorkspaceError(RuntimeError)` → `WorkspaceConfigurationError`,
`WorkspaceSecurityError`, `WorkspaceQuotaExceeded`, `WorkspaceConflict`
(`workspace_policy.py:26-43`).

### 5.3 `finalize_turn` refusals — a SEPARATE budget of 2

`finalize_turn` refusals do **not** come out of the 3-refusal governed-tool budget. They have their
own counter in `ExactAgentToolSurfaceMiddleware._finalize_rejections`, bounded by
`_MAX_FINALIZE_REPAIRS = 2` (`runtime.py:57-68`, `:119-120`, `:189-250`).

The mechanism is unusual and worth stating exactly. `finalize_turn` is `return_direct=True`, so the
graph ends the instant the tool node produces a message — right for a *committed* finalization,
"exactly wrong for a *refused* one: the model never saw the rejection, so the turn died as
`missing_finalize` with no feedback (the live Stage-0 defect)" (`runtime.py:190-196`). So a refusal
**temporarily clears `return_direct`** for that one call, lets the corrected proposal come back, and
restores it before every attempt. Once the budget is spent `return_direct` simply stays on, the
final refusal ends the graph, and the runtime reports `missing_finalize` — "nothing was committed,
so that remains the honest code" (`runtime.py:200-204`).

The catch is the whole `ValueError` family, not just pydantic's `ValidationError`, because the
platform's own finalize guards raise plain `ValueError` and "their messages are precisely what the
model needs" (`runtime.py:212-223`). Every swallowed error is logged as `agent.finalize_refused`
with type, message and rejection ordinal.

Two fixed guidance suffixes are appended to the error text (`runtime.py:61-69`):

| Budget state | Appended text |
| --- | --- |
| repairs remain | "Nothing was committed and this turn is not finished. Call finalize_turn again with a terminal shape that satisfies the status contract in its description. Keep the content you already wrote; change only what the error above names." |
| exhausted | "Nothing was committed and no further finalize attempt will be accepted for this turn." |

The budget is 2 because "a finalization is refused by two unrelated authorities — the shape contract
(`ModelFinalizeRequest`) and the surface's `CompletionGuard` — and a turn can legitimately trip both
once each while converging… A model that proposes a dishonest terminal shape a *third* time has not
misread the schema; it is refusing the contract, and the turn must die rather than loop"
(`runtime.py:49-56`).

What can be refused:

| Refusal | Condition | Source |
| --- | --- | --- |
| Pydantic validation of `ModelFinalizeRequest` | `user_message` > 65,536 chars; `assumptions`/`next_actions` > 64 items; `failure_code` not matching `^[a-z0-9_.-]+$` or > 128 chars; a `failure_code` on a non-`failed` status; a `failed` status with none. | `agent_runtime_wiring.py:322-346`, `contracts.py:91-99` |
| "completed specialist turn requires its non-empty role output file" | A specialist profile with a `required_output_path` finalizing `completed` with an empty/absent output file. **Not applicable to Head of ABM on the production path** (`required_output_path` is not set there). | `agent_runtime_wiring.py:1098-1105` |
| `NO_ROUTING_RECEIPT` (long corrective paragraph) | `Stage0RoutingReceiptGuard`: a substantive turn finalizing `completed`/`awaiting_input` with zero routing receipts for this turn's captured input. **Only wired on the trial surface — see §6.** | `stage0_trial.py:187-197`, `:212-253`, wired at `:793` |

An unrepaired finalize refusal still ends the turn `missing_finalize`
(`stage0_trial.py:222-226`, `runtime.py:392-405`).

### 5.3b Two more strings the middleware can produce

| String | When | Source |
| --- | --- | --- |
| `Tool {name!r} is structurally unavailable to this exact agent profile.` (as an error `ToolMessage`) | The model calls a tool name outside `profile.tools ∪ {finalize_turn} ∪ framework file tools`. | `runtime.py:177-185` |
| A `HumanMessage`: "Your previous response is not committed because it did not call finalize_turn. Call finalize_turn now and no other tool. Preserve the previous response exactly as user_message. Use awaiting_input when it asks the human for information or confirmation and include one next_actions item describing that requested response; otherwise use completed. Do not add new content." | The model returns a plain-text stop despite `tool_choice="required"` (some OpenAI-compatible gateways do). Exactly **one** bounded finalize-only recovery call, with `tools=[finalize_turn]` and `tool_choice="finalize_turn"`. A second non-tool stop is still `missing_finalize`. | `runtime.py:152-176` |

### 5.4 What the agent never sees as an error

| Not surfaced | Why | Source |
| --- | --- | --- |
| The turn-level `failure_code` | It is written *after* the graph has already ended. The model cannot read its own `agent_timeout` / `missing_finalize` / `runtime_error`. | `runtime.py:358-405` |
| The 4th refusal | The original exception is re-raised instead of being returned, so the model's last observation is refusal #3. | `agent_runtime_wiring.py:914-915` |
| Host paths | `PreparedWorkspaceRoot` "is never placed in model state or agent-facing errors". | `workspace_policy.py:73-76` |
| A stop | `before_work` raises `asyncio.CancelledError`; no tool result is produced. | `head_of_abm_wiring.py:260-268` |

---

## What the agent is never told

Checked against the two things the model actually reads — the system prompt
(`platform/agents/catalog/prompts/head-of-abm/v8/SYSTEM.md`, 82 lines) and the skill
(`platform/agents/catalog/skills/stage0-interview/v26/SKILL.md`, 245 lines). Neither file contains
the words *round*, *timeout*, *retry*, *crash*, *frozen*, *parallel*, *token*, *stream*, or *KiB*
(verified by case-insensitive grep). The word "budget" appears once, in the prompt, only as an
authority statement ("cross a budget/checkpoint gate"). The word "queue" appears as "queued jobs",
never as "your thread has a queue".

| # | Runtime fact | Why it changes the agent's behaviour | Source |
| --- | --- | --- | --- |
| 1 | **The refusal budget is 3, shared across every governed tool.** The 4th refusal in a turn kills the turn with no user-facing answer. | An agent that treats a refusal as a free retry ("let me try re-quoting a few ways") can burn the whole turn on one stubborn `record_interview_answer`. It should treat refusal #2 as its last cheap attempt and refusal #3 as the moment to stop and tell the human. | `agent_runtime_wiring.py:92`, `:908-916` |
| 2 | **`finalize_turn` has its own, smaller budget of 2.** | Two bad terminal shapes and the turn dies `missing_finalize` — the human gets **nothing at all**, not even the prose the model wrote. | `runtime.py:57`, `:238-250` |
| 3 | **Parallel tool calls each spend the refusal budget separately.** | Firing five governed writes in one assistant message is not free: three refusals among them exhausts the turn in a single round. | `agent_runtime_wiring.py:728-730` (counter incremented per invocation) |
| 4 | **Every governed receipt's `reference_values` is hard-capped at 16 KiB of canonical JSON.** | The agent has no idea a tool result could be refused for size, and no rule about asking for narrower reads. | `execution.py:143-150` |
| 5 | **Tool-failure messages are truncated to 600 characters.** | A long precondition explanation arrives clipped with `…`; the agent may be reading half a reason. | `agent_execution_wiring.py:136,148-151` |
| 6 | **52 supersteps and a hard 300-second wall clock.** `asyncio.wait_for` cuts the graph mid-thought and the turn ends `agent_timeout`. | Reading twelve files serially, then researching, then writing a plan, in one turn, can hit the wall. The skill's own instruction to "issue every `read_file` call together in a single turn" is the right shape but is justified only as tidiness, never as a budget. | `runtime.py:270-280`, `:352-365`; `profile.yaml:252-253` |
| 7 | **Only text passed to `finalize_turn(user_message=...)` ever reaches the human.** Plain model `content` outside that argument is discarded on this surface as "provider chatter". | An agent that writes a careful explanation as ordinary assistant prose and then calls `finalize_turn` with a terse summary has silently thrown the explanation away. | `turn_stream.py:1230-1233`; `conversation_turns.py:404-412` |
| 8 | **A failed turn produces no assistant message at all.** `_result_from_outcome` only reads a message when a `finalization_ref` exists. | The user sees a failure with zero explanation. This raises the stakes on always finalizing, which the prompt states as a rule but never as a consequence. | `conversation_turns.py:403-419` |
| 9 | **The model is forced to call a tool every round** (`tool_choice="required"`), and a plain-text stop gets exactly one scripted recovery prompt. | The agent cannot "just think out loud for a round". | `runtime.py:142-147`, `:152-176` |
| 10 | **One turn at a time per thread; a message the human sends while it is working is queued and is not in its context.** | The agent will answer the *previous* message while a newer one waits. It has no way to know a follow-up is pending, and should not promise "I'll also handle X" on the strength of something it cannot see. | `agent_turn_fleet_wiring.py:1322-1331`, `:1466-1470`; history loaded once at `conversation_turns.py:325-329` |
| 11 | **`status.md`, `decisions.md`, the brand documents and the ICP pin are frozen for the whole turn** (compiled on the first attempt, then pinned). | The skill says "re-read `status.md` before answering any question about where the project stands" — but re-reading inside one turn returns the *same bytes*. A research job that settled thirty seconds ago will not appear until the next turn. The live read tools (`read_arv2_account_research_run`, `read_project_accounts`, `read_discovery_run`) *are* current — so the correct move for "is it done yet?" is a read tool, never a re-read of `status.md`. Nothing tells the agent these two sources have different freshness. | `agent_turn_fleet_wiring.py:600-676` (`load_or_create_project_files_pin`), `:556-596` (knowledge + ICP pins) |
| 12 | **A committed turn is never re-executed.** A crashed turn is retried by a *different worker* as a distinct attempt against the same `execution_id`, and the workspace's frozen bytes are re-verified before the model resumes. | The agent may find governed operations already `replayed: true` that it does not remember performing. Nothing in the prompt explains the `replayed` field on a receipt. | `conversation_turns.py:225-281`, `:299-305`; `head_of_abm_wiring.py:229-240`; `agent_turn_fleet_wiring.py:1337-1340` |
| 13 | **Stop cancels only this generation attempt; committed tool effects stay committed.** | If the human stops a turn after a `record_interview_answer` receipt, the statement is still recorded. The next turn's agent has no note of the interruption and may re-record. | `agent_turn_fleet_wiring.py:1051-1055` |
| 14 | **The budget ceiling is a per-plan *estimate*, not a running total.** Each governed call is its own one-step plan, so 1,000,000 millicents is checked against one tool's estimate, never against cumulative turn spend. Only delegation spend is summed per execution. | The agent has no per-turn cost pressure it can reason about — and equally, nothing stops it making fifty cheap calls. | `agent_execution_wiring.py:1560-1600`, `:1901-1930`; constant `agent_turn_fleet_wiring.py:190` |
| 15 | **Delegation is withheld on the production surface** — but this one IS disclosed, in a third place the brief did not name. The profile grants three delegation roles; `PROJECT_CONVERSATION_SURFACE` withholds all of them and the registry zeroes the counts; and the *generated resource map* appended to the system prompt says `- withheld delegation: content_drafter, research, reviewer`, `- delegate_specialist: unavailable in this profile`, and `none of the above is installed, so there is nothing here to decline`. | So the model reads a prompt paragraph teaching delegation (`SYSTEM.md:45-50`) and, a few hundred tokens later, a generated block saying it cannot. Not hidden — **contradictory**. The manual should resolve it explicitly rather than leave the model to arbitrate. | `agent_registry_wiring.py:541-559`; `registry.py:636-639`, `:275-300`, `runtime.py:136-140`; `conversation_turns.py:150-166` |
| 16 | **The Stage-0 routing-receipt guard does NOT run in production.** The skill states flatly: "The platform refuses a `completed` or `awaiting_input` finalization of a substantive turn that produced no routing receipt, and the refusal is visible to you" (`SKILL.md:182`). `Stage0RoutingReceiptGuard` is wired **only** at `stage0_trial.py:793`; the production fleet path never passes a `completion_guard` (default `None`), so the guard cannot fire. | The skill promises a safety net that is not there. The honesty discipline is entirely on the model. **This is a documentation/wiring divergence worth escalating, not just a manual note.** | `stage0_trial.py:212-253`, `:793`; `conversation_turns.py:291`, `:376`; `agent_turn_fleet_wiring.py:855-864`; exact grep shows no other construction site |
| 17 | **The routing rule that hands the thread to Design is a single indexed DB read, with no LLM in the loop.** | While a design leg is open the Head of ABM does not run at all — it cannot "check in". The prompt says it "resumes when the leg closes" but never that it is structurally absent meanwhile. | `agent_turn_fleet_wiring.py:406-431` |
| 18 | **Its own failure code is written after it is gone.** `agent_timeout`, `missing_finalize`, `graph_recursion_error` are decided by the runtime after the graph ended; the model never observes them. | The agent cannot learn from its own failures within a thread. | `runtime.py:358-405` |
| 19 | **The reasoning trace, when enabled, is a dev-only lens that a production process structurally cannot hold.** | Anything the agent "thinks" is invisible to the human in production. Only `user_message` communicates. | `turn_stream.py:374-424`; `.env.example:412-414` |
| 20 | **Its conversation history is silently evicted.** The L6 conversation layer has a 96,000-unit budget walked **newest-first**, so the oldest messages of a long thread fall out of context with no marker. A `required` candidate that will not fit fails the turn outright. | On a long thread the agent will confidently believe the transcript it holds is complete. `decisions.md` exists precisely to survive this, but nothing tells the agent *why*. | `agent_turn_fleet_wiring.py:228-246`; `context.py:71`, `:677-698` |
| 21 | **Its own output is capped at 8,192 tokens per model call**, and the whole `user_message` at 65,536 characters. | A very long plan written straight into `finalize_turn` can be cut off mid-sentence by the provider. | `profile.yaml:200`; `agent_runtime_wiring.py:325` |
| 22 | **It cannot read the ICP fit verdicts its own launch produced.** `account.icp_fit_verdict` claims are born `outreach_safe=False` and tier-4 synthesis, so `read_account_research`'s display gate holds them back twice; they reach the agent only as a number in `excluded["outreach_unsafe"]`. | The skill tells it to launch research and report what was found. The single most decision-relevant output of that research is structurally invisible to it. | `arv2/account_research_claims.py:1462`; `claim_writer.py:50`; `arv2/read_tools.py:502-512` |
| 23 | **Three of its 21 granted tools are dead or dead-ended.** `get_research_view@1` is flag-disabled (`CLUE_C7_RESEARCH_VIEW_READ_ENABLED=false` in `.env.example` and `.env`); `draft_account_research_directive@5` and `open_directive_confirmation_gate@1` write and confirm rows that **no tool granted to v49 ever reads** — every consumer is an M8D-lane launch, and the ARV2 launch explicitly forbids depending on them. | The agent will spend turns — and ask the human to sign a confirmation gate — on a directive nothing will execute. The ARV2 launch takes free-text `directive_text` instead. | `.env.example:347`, `.env:85`; `research_view_tools.py:345-352`; `arv2/account_research_launch.py:17-19`, `:1088` |
| 24 | **The run read it is told to use cannot distinguish a person job from an account job**, and does not carry the stage. `read_arv2_account_research_run@1` returns `{job_id, account_entity_id, status, failure_code}` only; committee person jobs appear as extra rows sharing the account's id. The stage and the person-job count exist **only** in `status.md`. | An agent asked "how's the research going" will miscount jobs unless it reads `status.md` — which the skill tells it to do for other reasons, never this one. | `arv2/account_research_launch.py:1391-1398`; `project_status.py:576-578` |
| 25 | **A `suspended` job is a pause, not a failure — and every worker restart suspends every in-flight job.** | The agent will report "suspended" as if something went wrong. | `arv2/account_research_store.py:77`; `arv2/research_progress.py:31-35` |
| 26 | **A design leg it opens may never hand the thread back.** The exit judge is built with the design profile's `timeout_s: 120.0`, which the gateway (default 30.0) refuses, so the judge always raises and the fail-safe turns every exit intent into CONTINUE. "Lock it in" does not close the leg. | The prompt tells the agent it "resumes when the leg closes with the summary it hands back". Today that may not happen. | `docs/superpowers/plans/2026-08-19-chat-driven-website-generation.md:3-28` |
| 27 | **Host paths, costs, token counts, model latency and logs are all withheld by design.** | The agent should never claim or estimate spend, duration, or system health; it has no instrument for any of them. | `workspace_policy.py:73-76`; see §4 |

### A third place the agent is told things: the generated resource map

The brief named two sources (prompt, skill). There is a third, and it is authoritative:
`ResolvedAgentProfile.generated_resource_map`, appended to the system prompt by
`ExactAgentToolSurfaceMiddleware` on every model call (`runtime.py:136-140`, built at
`registry.py:298-315`). It carries the surface framing, withheld tools/roles, pinned resources,
progressively disclosed skills, the governed tool list, and the framework file tools. Rows above
were checked against the prompt and the skill; anything the map discloses is flagged as such (row
15). The map does **not** mention rounds, timeouts, the two repair budgets, the receipt bound,
per-thread queueing, turn-level pinning, or replay.

### Two things the prompt/skill say that the runtime does not back

1. **The routing-receipt refusal** (row 16) — asserted flatly in `SKILL.md:182`, wired only on the
   trial surface (`stage0_trial.py:793`). The production fleet never passes a `completion_guard`.
2. **Delegation to specialists** (row 15) — taught at length in `SYSTEM.md:45-50`, contradicted a
   few hundred tokens later by the generated resource map.

Neither is a runtime bug the agent can work around. Both belong in the manual as "what you were
told that is not currently true", and both should be raised with the profile owner.
