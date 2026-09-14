# FI Lane D — The production chat surface + conversation-mediated research launch (D-9 Option B)

**Status: RATIFIED CHARTER — every §6 decision is founder-resolved (2026-08-08); R0's executable Home/project/chat join contract was added 2026-08-10. §6-D1 async worker-executed turns; §6-D2 genuine, complete token streaming; §6-D3 durable generic `agent_gate` substrate (immutable gate + insert-once answer record); §6-D4 real Clue-owned authenticated user principal under `FI-lane-B-authenticated-principal-contract.md`; §6-D5 estimate tool DEFERRED post-V1 (server-derived maximum-spend on the gate instead); §6-D6 trial surface kept as dev-only harness. Full end-to-end scope per the founder's 2026-08-08 no-shortcuts directive: speed comes from parallel worktrees, never from cutting designed features.**

Date: 2026-08-08. Branch: `platform/frontend-integration`.
Parent rulings: FI-1 §9 — **D-9 RESOLVED Option B** (research launch is a deepagent tool call inside the project conversation, authorized by the user's confirming turn; the production chat surface **S6 enters MVP scope**). Doc A (`clue-hq-platform-agent-runtime.md`) is the binding vocabulary; the harness doc's REQ-18–22 define the agent-workspace surface and the project/thread/tab shell.
Method: two read-only Opus code studies (2026-08-08: agent-turn substrate + launch authority chain; frontend chat contract). Every baseline fact carries a file:line citation from them.
Scope boundary: this lane is bound by **`docs/specs/FI-lane-demarcation.md` §2.4** — it never touches `frontend_read/**`, `apps/frontend/src/features/accounts/**`, `api-contracts/accounts.md`, or any FI-2 slice-2/3 file; its frontend territory is `features/projects/**` + `api-contracts/projects.md` only. Its identity dependency is the provider-neutral `RequestPrincipal` and internal-id contract in **`docs/specs/FI-lane-B-authenticated-principal-contract.md`**; Lane D never imports/interprets Clerk identity, organization, role, session, or token claims.

**2026-08-10 join amendment.** The observed Home-to-chat failure crosses the
original D5 boundary because D5 deliberately did not own project lifecycle.
The founder-ratified repair therefore introduces a bounded **chat-integration
join slice** in this worktree. It owns only `GET /home`, atomic
`POST /projects` bootstrap, project/sidebar reads, the shared project shell,
and their `features/projects/**` repositories. Lane D continues to own the
turn/queue/stream/Stop behavior the join consumes. This amendment does not pull
project rename/delete/pin, artifact generation, Gallery artifact reads, the
design subsystem, or any Lane E/F/G file into Lane D; new projects render an
empty Gallery until the separately governed artifact integration exists. The
complete executable shapes and authority order live in
`apps/frontend/docs/api-contracts/projects.md` § "Executable integration
contract" and are not duplicated here.

---

## 0. The one-paragraph verdict

The **doctrine and the substrate agree with Option B** — Doc A already prescribes exactly this shape ("fleet work is LAUNCHED, never performed, in-thread: the tool enqueues to the detached worker; the narrator streams progress back", Doc A:219-220), the turn substrate (C6) is durable, append-only-by-trigger, and replay-safe, and the launch tool's entire authority chain exists as governed tools. What is missing is the **connective tissue at every seam**: no thread/tab entity (REQ-21 is spec-only), no production conversational route (the trial is loopback + file-tenancy + per-request full recomposition), no `action_ref` on any of the 10 production `ToolContext` construction sites (making every human-receipt gate — including the directive confirmation Option B depends on — uninvocable), no streaming of any kind (`graph.ainvoke` is a single blocking call), an un-flavoured `open_gate_refs` as the only durable approval hook, and a frontend whose transcript is 100% client-manufactured from a phase enum with zero transport, zero message repository, and zero estimate/confirmation surface. One latent blocker found: **`draft_account_research_directive@2` is un-callable through the agent seam today** (its `TRUSTED_TURN_FIELD`s aren't `CapturedTurn` fields) — Option B's first step is broken before its famous missing piece (`action_ref`) is even reached.

---

## 1. Verified baseline — backend

### 1.1 The turn substrate is real and doctrine-locked (build on it, never around it)

- Migration `7e9269ed8a81`: `agent_turn` (+event ledger), `agent_thread_message` (one content-addressed blob per message, `UNIQUE(workspace_id, thread_id, sequence)`, roles system/user/assistant/tool), `agent_artifact_ref` (closed `owner_kind`/`ref_role` vocabularies — a typed-part design must fit them or migrate), `agent_artifact_subject` (DSAR reachability without body inspection), `agent_artifact_tombstone`, the seven-layer `agent_context_*` receipts (ordinal↔name CHECK-locked; `token_count <= token_budget` in SQL), `agent_model_call`, `agent_finalization` (+`ref_role ∈ ('output','open_gate')`). **Append-only is a DB trigger on all 13 tables**, not a convention.
- No part-level identity: a turn yields two thread rows (user+assistant), ids derived `uuid5(turn_id, role)`; tool calls have durable identity (`agent_plan_operation.operation_id`, `agent_tool_result`) but are not thread messages — nothing joins them into transcript order.
- **`thread_id` is a plain text column; no `thread` table, no `tab` table, no `campaign_artifact` catalog exists.** REQ-21's shell ("threads belong to projects", typed object-ref vocabulary, per-tab edit contracts) is specified only (`harness doc:1043-1082`).
- Doctrine constraints on any streaming/typed-parts design: the context window is a cache, never a store; tool results return receipts, not goods (Doc A §3a:301-333); L6 is append-only thread history — "mutated/rewritten history" is in the never-includes cell (Doc A:288). **A streamed typed part is therefore a projection of durable receipts, never a new store.**
- **Correctness hazard for production threads:** L6 assembly iterates ascending `sequence` and stops at budget — long threads silently drop the **newest** messages (`platform/agents/clue_agents/context.py:449-454,614-641`; trial budget 96k bytes). Must be inverted (newest-first-retained) or windowed before production chat.
- Defect L6 (FI-1): `agent_turns_for_project` has no LIMIT/cursor (`platform/projections/clue_projections/agents.py:205-227`).

### 1.2 The trial surface: right substrate, wrong everything-else

`POST /v1/trials/{id}/turns` (loopback-only, `trial_enabled=False` default, tenancy from a local `session.json`, mandatory `Idempotency-Key`): per request it rebuilds storage + gateway + the whole toolbelt + recipe seeding + context assembler + runtime (`stage0_trial.py:600-731`), runs recipe0 to its interaction gate, executes the deepagent graph **in-process, blocking** (`await asyncio.wait_for(graph.ainvoke(...))`, `runtime.py:311-327`, LangGraph `AsyncPostgresSaver`), and returns one JSON body. Deterministic ids (`turn_id = uuid5(session, seq)`), committed-outcome replay short-circuit, user message persisted (artifact + DSAR binding + `onboarding_input actor='human'`) **before** model spend, `actor_id` a hardcoded literal (`"stage0-trial-user"`). Its surface (`STAGE0_CONVERSATION_TRIAL_SURFACE`) **withholds `launch_account_research`/`launch_contact_research`**; an undeclared surface raises at resolve (surface policy is a ceiling: same profile, subtracted addresses — `agent_registry_wiring.py:167-190`).

### 1.3 HITL is turn-terminal; the approval hook is under-specified

No LangGraph `interrupt()` anywhere. `finalize_turn` is `return_direct=True` with up to 2 bounded repair rounds; `awaiting_input`/`blocked` must carry `open_gate_refs` or `next_action_refs` (`contracts.py:938-942`) — but `open_gate_refs` is an un-flavoured `DomainObjectRef` (no gate kind, prompt, options, expiry) that **nothing reads back**. The human answers in a brand-new turn. `_HUMAN_ONLY_TOOLS` (11 tools incl. `confirm_account_research_directive`, `submit_tier_checkpoint`, `adjust_budget`) are structurally absent from every model surface and today are invocable only via `POST /tools/{name}` — which builds `ToolContext` with **no `actor_id`, no `action_ref`** → `422 trusted_human_receipt_required` — or via trial slash commands that bypass tools entirely.

### 1.4 The `action_ref` seam: doctrine present, plumbing absent, plus one latent blocker

- Doctrine at `ToolContext` (`envelope.py:234-236`): human gates derive receipts from ambient `actor_id`/`action_ref`; caller-authored arguments never choose who approved. Enforced per-tool (directive confirm v2 deleted the caller-authored fields entirely; `launch_account_research@1` → `launch_action_ref_missing`; the launcher re-asserts and persists `source_action_ref` durably into `entity_research_run` and the launch `request_sha`).
- **All 10 production `ToolContext` construction sites set neither field** (C5 executor ×3, agent execution wiring, projections `POST /tools`, supervisor, ingestion, research-view ×2); the only site that does is a manual acceptance script. The platform has an actor *class* (human/agent enum) but no actor *identity* at the tool boundary.
- The right extension seam exists: turn-binding (PC-C8 §6) — `TRUSTED_TURN_FIELD` markers stripped from model-visible schemas, values **derived** from the turn's own artifact + `onboarding_input(actor='human')` join, plan-supplied values rejected (`turn_binding.py:157-210`, `agent_execution_wiring.py:235-282`). `CapturedTurn` serves 5 fields; `value_for` raises `unbindable_field` for others.
- **Latent blocker:** `draft_account_research_directive@2` marks `user_instruction` and `source_turn_ref` as `TRUSTED_TURN_FIELD` (`research_directive_tools.py:72-81`), neither is a `CapturedTurn` field, and `head-of-abm/v22` pins the tool — so the agent-plan path raises `CapturedTurnUnavailable` today. Every existing test drives it via toolbelt/HTTP, never the agent seam.

### 1.5 The launch authority chain — exists vs missing (Option B step map)

| Step | State |
|---|---|
| Project run (`start_confirmed_project_run@1`) | exists, agent-callable |
| Tier checkpoint per account | **Superseded by the 2026-08-19 founder ruling:** signal tier is prioritization metadata, not explicit Account-launch authority. The attributable user turn + exact directive Account scope authorizes research; `high`, `low`, absent, or effort-tier vocabulary mismatch cannot refuse it. |
| Agent drafts directive (`draft_…@2`) | tool exists, agent authority — **un-callable through the agent seam (§1.4 blocker)** |
| Estimate presented | partial: directive preview carries counts; the estimate is Σ per-account `effort_policy.budget_cap_cents` computed *inside the launcher*; **no first-class agent-callable estimate tool** (`estimate_project` is reserved `post_stage0_not_admitted`) |
| User confirms directive (`confirm_…@2`) | tool exists, human-only, requires ambient `actor_id`+`action_ref` → **uninvocable in production** |
| Confirming turn supplies `action_ref` | **missing entirely** |
| Agent launches (`launch_account_research@1`) | blocked three ways: withheld on the only conversational surface; `entity_research_runtime_enabled=False`; composed only into the fleet worker (`fleet_main.py:427-436`; the HTTP process gets `entity_research_agent_not_composed`) |
| Approval-card gate object | missing (`open_gate_refs` un-flavoured, unread) |
| Per-account status read-back | missing (L2 index, L3 projection columns — owned by Lanes B/C) |
| Post-launch narration | run identity is deterministic (`request_sha` → `research_run_id`), `approval_refs = (source_action_ref, directive.confirming_turn_ref)` already first-class; canary policy (first 10 jobs) is data |

### 1.6 Streaming and process reality

- **Nothing streams in the agent plane.** The gateway chat model has `_astream` with fallback + cost annotation — **uncalled**. The pinned LangGraph 1.2.6 offers `astream`/`astream_events` — unused. The natural attachment point without touching the graph invocation is the already-installed per-turn LangChain callback (`DurableAgentModelCallHandler` — today `on_chat_model_start`/`on_llm_end` only; `on_llm_new_token`/`on_tool_start`/`on_tool_end` are open). Note `tool_choice="required"`: assistant prose exists **only** inside `finalize_turn.user_message` — that bounds what a streamed "text part" means on this surface.
- B4 SSE: token store reusable verbatim (nullable `run_id` already means workspace-wide tokens); `Last-Event-ID`/`plan_replay`/`_sse_frame` reusable; **the `run_event` outbox is not** (`run_id uuid NOT NULL`) — a turn stream needs its own outbox (or a migration widening `run_event`).
- Off-HTTP agent execution precedent exists: the entity-research fleet runs full deepagent turns in the worker (`account_research_turn_wiring.py:488-560` — same substrate: `turns.create`, replay short-circuit, context assembly, checkpointer). There is **no `AGENT_TURN` fleet task kind** yet. Doc A: "the thread session never executes long-running work… sessions attach/detach" (:226-228).

---

## 2. Verified baseline — frontend (`apps/frontend`)

- One chat feature (`features/projects`). The transcript is **manufactured client-side from a 6-value phase enum** (`build-project-messages.ts`); `submitMessage()` clears the prompt and jumps phase — **a user's follow-up turn is unrepresentable**. No message/thread/run repository exists (only `getHome`/`getProject`); the sidebar bypasses its own repository (fixture imported directly in the hook, violating `frontend.md:95`).
- Part union (7 kinds, `project-workspace.ts:232-275`): `text`/`reasoning`/`action`/`tool`/`plan`/`task`/`sources`. **`plan` and `sources` parts carry only an id** — they point at project-singleton blobs (a second plan or per-message sources is unrepresentable). Tool part: 7-state machine in schema, hardcoded `output-available` in fixtures, collapsed to a Completed/Running binary in the UI; `output` is `z.string().min(1)` (structured results must be pre-rendered to prose); no `toolName`/`toolCallId`.
- **Zero transport.** No SSE/WebSocket/fetch-stream code; streaming is `setTimeout` on fixture-authored delays that are **part of the validated backend payload** (`previewTimeline` — a real backend must ship fake timer data or the route 500s). The authored envelope proposal (`ProjectMessagePartEvent` with `partId`/`sequence`/`type: part.created|updated|completed|failed`, `ai-elements-and-reasoning.md:161-173`) exists in prose only; no Zod schema has `sequence`/`threadId`/`messageId`.
- **Approval/confirmation:** plan-approval card is hardcoded (`state="approval-requested"`, id `"plan-approval"`), is not a message part, leaves no durable record when answered (responded/denied branches of the vendored primitive unwired). **No cost/estimate surface exists anywhere** — credits appear only as post-hoc display strings (`"6,048 credits spent"`). `needs-input`/`review`/`approval` exist only as sidebar badges; the sidebar's 5-status vocabulary and the workspace's 6-phase vocabulary never meet.
- D-4-class parse hazards specific to chat: `text.min(1)` (an empty-then-filled streamed part is unrepresentable), `parts.min(1)` (no empty message to stream into), `tools.min(2)` arity trap, required fixture-only subtrees (`previewTimeline`, `reasoningTrace`, `questionnaire`, `plan`), reasoning `label` as backend-authored display copy ("Thought for 5 seconds"), credits as strings not numbers.
- **The design intent for Option B already exists on paper, uncoded:** `docs/figma/projects-chat-flow.md:39-99` specifies the research-execution component library — 8 activity states (Scoping → Light research → Checkpoint → Deep research → Synthesizing → Complete/Partial/Needs-input), run aggregation ("one visible research task whether it covers one account or 500"), and "Production progression is event-driven. Prototype timeouts … must not become the backend lifecycle model."
- The frontend's approved agent-state vocabulary is broader and more precise than the current seven-part wire proposal: `ai-elements-and-reasoning.md:26-35` approves `Reasoning`, `Shimmer`, `ChainOfThought`, `Tool`, `Task`, `Plan`, `Confirmation`, and `Sources`, behind Clue-owned adapters. `Shimmer` is presentation-only; the other seven need explicit domain-part mappings. `ChainOfThought` means a safe structured activity summary, never private raw model chain-of-thought. Normal assistant text remains Clue-owned document text, but streaming LLM Markdown still needs the vendored `MessageResponse`/`MessageMarkdown` renderer rather than a raw `<p>`.
- Thread shell: `ProjectThreadSchema = {id, title}` only; thread switching doesn't change the transcript; all thread CRUD is local-memory; no pagination anywhere; REQ-21's typed `refs[]` on messages has no frontend counterpart (nearest: the 2-value `action` part).

---

## 3. Design — six pillars

**P1 — The durable shell (REQ-21 lands).** A real `thread` table (`id, workspace_id, project_id FK, created_by_user_id` FK to Lane B's Clue-owned `platform_user`, `created_via_membership_id`, status, title, created_at), turn/message pagination (fixes L6-defect), and the typed object-ref vocabulary on messages (`refs[]` as `DomainObjectRef`+flavor) so chat can open tabs. No provider identifier is stored or referenced. `agent_turn.thread_id`/`agent_thread_message.thread_id` gain FK validation for new writes (legacy rows grandfathered; text column stays, constraint added `NOT VALID`+validate). Thread CRUD as governed tools + endpoints per the frontend's authored contract (`POST /projects`, `POST …/threads`, rename/pin/archive).

**P2 — Actor identity + turn-derived `action_ref`.** Two halves, two owners: **(a)** Lane B authenticates the external session, maps it to an internal `platform_user`, authorizes the Clue-owned `workspace_membership`, returns the closed `RequestPrincipal`, and threads its internal `user_id` into every relevant `ToolContext` construction site. Clerk is authentication-only; no Clerk value reaches the turn/domain/tool contracts or a database foreign key. **(b)** Lane D's turn half persists the principal's internal user/membership on the turn, extends `CapturedTurn` with the turn's durable identity, and threads `constitution.actor_id` + a derived `action_ref` into the C5 executor's `ToolContext` sites — the binding stays *derived, never passed* (the PC-C8 security model). The canonical value is an opaque `turn-action:<turn_id>` reference; the server resolves it against the workspace-scoped persisted human turn, its captured `onboarding_input`/artifact integrity join, and (for a gate answer) the `agent_gate` answer record. The artifact/capture triple is derivation evidence, not the client-facing reference. Neither `actor_id` nor `action_ref` appears in a client request or model-visible tool schema. Fix the §1.4 blocker by making `CapturedTurn` serve `user_instruction` from the exact decoded turn bytes and `source_turn_ref` from the derived turn-action ref, with a test driving `draft_account_research_directive@2` through the agent seam. A confirming turn then *is* the receipt: `confirmed_by = actor_id`, `confirming_action_ref = action_ref`, exactly what the launcher already persists as `approval_refs`.

**P3 — Turn execution architecture (the big structural decision — §6-D1).** Recommended: **async, worker-executed turns.** `POST /v1/projects/{id}/threads/{tid}/turns` (production app; Lane B `RequestPrincipal` + internal workspace-membership authorization) validates, persists the user message + turn row (the substrate already does this before spend), enqueues a new `AGENT_TURN` fleet task containing internal principal references but no browser/provider token, and returns `202 {turn_id}`; the fleet worker — authenticated separately as a service principal, and already composing the gateway, toolbelt, launch services, and entity-research turns — executes the graph; the client attaches to the turn stream (P4). This matches Doc A (:226-228), reuses the committed-outcome replay short-circuit for crash-safety, kills the per-request recomposition (composition happens once at worker startup), and — decisively for Option B — **the launch tools are already composed in that process**. The alternative (compose the gateway into the HTTP process and run blocking turns) is recorded and rejected: it contradicts Doc A, duplicates fleet composition, and blocks HTTP workers on model latency.

**P4 — Complete streaming + typed parts as projections of durable receipts.** A turn-scoped event outbox (`agent_turn_event_stream` — new table mirroring `run_event`'s shape; token store + replay machinery reused verbatim) emits turn lifecycle, part lifecycle, and genuine assistant-text token events. Parts are **projections, never stores** (Doc A §3a): `tool` parts from `agent_plan_operation`/`agent_tool_result` via `on_tool_start`/`on_tool_end`; safe `reasoning` and `agent_activity` parts from model-round/tool/run receipts; `task` parts from fleet/run projections; `plan`, `gate`, and `sources` from their durable objects; and `text` from the streamed `finalize_turn.user_message` field. Because `tool_choice="required"` places user-visible prose inside a streamed tool-call argument, D3 must include a provider-neutral incremental `FinalizeTextDeltaExtractor`: it consumes tool-call chunks, emits only newly decoded bytes of that one string field, and never exposes the surrounding JSON, other tool arguments, or provider reasoning. Post-hoc animation of a completed string does **not** satisfy this contract. Token batches are appended to the outbox while generation is active, reconnectable by cursor, and reconciled on completion so concatenated deltas are byte-identical to the durable assistant message. A generation-attempt id prevents a crash/retry from splicing two different continuations into one part; a superseded partial attempt closes with `part.reset`/`turn.retrying`, and the new attempt uses a new stable part id. Stream loss never changes the durable turn outcome; canonical message rehydration repairs any projection failure.

**P5 — The Option B kickoff flow, end-to-end.** (a) **Flavored gate objects (per ratified §6-D3)**: a durable, generic two-record `agent_gate` substrate — an **immutable gate row** written at presentation time (kind ∈ {directive_confirmation, plan_approval, budget_approval, …}, subject refs, the server-derived maximum-spend payload, expected subject revision/hash, addressee, created-at) plus an **insert-once answer record** (answering `turn_id`+`action_ref`, decision, actor, timestamp; uniqueness enforced so a gate is answerable exactly once). `open_gate_refs` points at the gate row; "open vs answered" is derived from the presence of the answer record, never a mutated status column — matching the agent plane's append-only doctrine. The approval card reads a durable, auditable object; a gate never expires silently. (b) **Maximum-spend amount, server-derived at gate creation (per ratified §6-D5 — no estimate tool in V1)**: when the backend creates the directive-confirmation gate it computes exactly the launcher's number — Σ per-account `effort_policy.budget_cap_cents` for the drafted directive + account set — stores it durably on the immutable gate row, and verifies it again at launch (`expected_estimated_cost_cents` exact-match). No `estimate_account_research@1` is introduced; `estimate_project@1` stays reserved; V1 offers no conversational estimates or cost breakdowns — the one number the user confirms on the gate is the one number the launcher verifies. A richer estimation tool and cost-explanation surface are post-V1. (c) **A gate click is a structured human turn, not a side-channel mutation**: the normal turn endpoint accepts a mutually exclusive `message` or `gate_response={gate_id, decision, expected_subject_sha256, expected_estimated_cost_cents}` body; auth supplies the actor; the server persists the human turn/action first, derives `action_ref`, invokes the human-only confirmation tool outside the model surface, records the gate answer, and then enqueues the platform-deepagent turn over that same captured action. Approve, reject, and revise all leave visible transcript records. (d) The conversational sequence: agent drafts directive → presents gate card (server-derived maximum-spend + account set + directive summary) → turn ends `awaiting_input` with the gate ref → user's structured confirming turn → engine invokes `confirm_account_research_directive@2` with ambient human authority → platform deepagent observes the confirmed gate and invokes `launch_account_research@1` with that turn-derived `action_ref` → launch narration streams as `task` parts fed by fleet projections. A non-confirming ordinary turn, a stale digest/max-spend amount, a different actor, or a replay with different bytes cannot launch. (e) A **new declared surface** for the project conversation grants the drafting/launch tools but keeps human-only tools structurally absent from model surfaces; every skill's `required_tools` is re-checked (the C8 regression trap). (f) `entity_research_runtime_enabled` flips on for the worker as part of this lane's rollout gate.

**P6 — Frontend chat rebuilt at the repository seam.** Real repositories (threads, messages, turns, gates, runs) with fixture + HTTP + **stream** adapters; the part schemas amended per the contract deltas below; the approval card wired to the gate object (requested/responded/denied states all rendered — answered approvals leave a visible record); the Figma research-execution component library implemented against the run/fleet projections; the two status vocabularies unified (thread status derives from the latest turn's status + open gates); phase-enum transcript manufacturing deleted. AI Elements remains vendored presentation source behind Clue adapters, not the backend transport contract and not a runtime Vercel dependency. The stream adapter reduces Clue events into ordered project-message parts; `MessageResponse`/`MessageMarkdown` renders incremental assistant Markdown without adopting the catalog's `Conversation`, `Message`, or `PromptInput` shells.

**Frontend contract deltas** (recorded into `apps/frontend/docs/api-contracts/projects.md` on landing, per the branch charter): parts gain stable ids and part-local sequence/revision; messages gain `threadId`/`turnId`/`createdAt`/`refs[]`; `plan`/`sources` become payload-carrying message-scoped parts (singletons retired); `agent_activity` becomes a first-class structured part rather than `reasoning.showTrace` pointing at a project singleton; tool parts carry `toolName` + `toolCallId` + structured input/output/error + the full seven-state AI Elements lifecycle; task parts carry semantic state, aggregate counts, steps, exceptions, and run refs rather than `complete: boolean`; credits/estimates become `{amountCents,currency}` numbers + client formatting (D-5); `previewTimeline`/`reasoningTrace`/display-copy blobs leave the wire (D-4/D-5 vocabulary); `text.min(1)`/`parts.min(1)` gain explicit streaming-start shapes; a dedicated `gate` part carries the durable confirmation snapshot; sidebar repository bypass fixed.

### 3.1 The backend/UI boundary — Clue events, AI Elements presentation

AI Elements does not dictate the backend protocol. The canonical contract is the Clue turn/message/event schema because it must carry durable project/thread/turn identity, gates, run refs, detached-task progress, replay cursors, and domain-object refs. `useChat`/the Vercel UI-message protocol is not required for D5; introducing it would add a second lifecycle vocabulary over the already-required Clue outbox. The frontend's project stream repository owns the one mapping from Clue events to feature parts, and Clue adapters map those parts to the approved local primitives:

| Clue domain part | AI Elements/Clue renderer | Wire responsibility |
|---|---|---|
| `text` | Clue document text + `MessageResponse`/`MessageMarkdown` | genuine `start/delta/end`; incremental Markdown |
| `reasoning` | `Reasoning` + `Shimmer` while active | short safe status/summary; never private chain-of-thought |
| `agent_activity` | `ChainOfThought` | structured observed steps with stable ids and `pending/active/complete/error` |
| `tool` | `Tool` | `toolName`, `toolCallId`, structured input/output/error, seven lifecycle states |
| `task` | `Task` | one aggregate visible task per research run; state/counts/steps/exceptions |
| `plan` | `Plan` | message snapshot plus durable plan/directive ref and revision |
| `gate` | `Confirmation` | requested/responded/denied decision snapshot and permitted actions |
| `sources` | `Sources` | message-scoped source ids, titles, URLs, evidence refs |
| `action` | Clue-owned navigation card | typed tab/object action only; never approval authority |

`Shimmer` has no wire part: it is a presentation effect derived from an active part state. The backend sends semantic status, not animation timing, icons, labels such as “Thought for 5 seconds,” or Figma motion values.

### 3.2 Canonical turn event and replacement semantics

Every SSE frame is one versioned event; `event_id` is the `Last-Event-ID` cursor and `sequence` is monotonic within the turn. Part lifecycle events carry a **full current part snapshot** unless they are explicit text deltas; no JSON Patch dialect is introduced. The minimum envelope is:

```text
schema_version, event_id, sequence, occurred_at,
project_id, thread_id, turn_id, generation_attempt_id,
message_id?, part_id?, run_id?,
type, part?, delta?, error?
```

The closed event vocabulary is:

```text
turn.accepted | turn.started | turn.awaiting_input | turn.completed |
turn.failed | turn.cancelled | turn.retrying |
part.created | part.updated | part.completed | part.failed | part.reset |
text.start | text.delta | text.end |
stream.hello | stream.reset
```

`text.delta` is append-only and carries `{part_id, delta_index, delta}`. A consumer must see `text.start` before deltas and exactly one `text.end` for a successful attempt. `part.updated` replaces the prior snapshot for the same `(message_id, part_id)`; it never appends a duplicate card. Unknown event/part versions fail at the repository boundary with the shared request id rather than rendering guessed UI.

### 3.3 Complete token-streaming contract (founder-ratified §6-D2)

Complete means all of the following:

1. The first safe assistant-text delta reaches the frontend while the model is still generating `finalize_turn.user_message`; replaying or animating a completed string is forbidden.
2. The provider-neutral extractor incrementally decodes only that JSON string field across arbitrary chunk boundaries, including escaped quotes, backslashes, Unicode escapes, and split multibyte UTF-8; no partial surrounding JSON or other tool arguments are emitted.
3. Deltas are micro-batched only for bounded transport/database efficiency (a short time/byte threshold); batching may reduce frame count but may not wait for model completion.
4. Token/delta batches are appended to the turn outbox with generation-attempt and delta indices, so disconnect/reconnect replays the same bytes in the same order.
5. On successful finalization, `join(delta)` must byte-equal the durable assistant message. A mismatch fails the stream projection loudly, emits `stream.reset`, and rehydrates the canonical durable message; it does not rewrite the durable turn.
6. A crash/retry closes or resets the incomplete attempt and creates a new attempt/part identity; deltas from two generations are never spliced together.
7. Backpressure is bounded. A slow or disconnected client never blocks model execution; the outbox is the buffer and the replay-retention policy is explicit.
8. Stop/cancel produces a terminal event and preserves the already-emitted partial attempt for audit/recovery, but it cannot masquerade as a completed assistant message.

This contract covers the user-visible final response. `reasoning` remains a safe summary/activity surface, not raw provider reasoning tokens.

### 3.4 Part payload floors

- **`agent_activity`:** `id`, `title`, ordered `steps[]`; each step has stable `id`, semantic `kind`, `status`, safe label/description, optional source/object refs, and timestamps. Worker-fleet transcripts and private model reasoning never ride this part.
- **`tool`:** AI Elements states stay exact: `input-streaming`, `input-available`, `approval-requested`, `approval-responded`, `output-available`, `output-denied`, `output-error`. `output` is structured JSON/refs, not pre-rendered prose; the adapter chooses disclosure copy.
- **`task`:** state is `queued|scoping|light_research|checkpoint|deep_research|synthesizing|needs_input|partial|completed|failed|suspended`; counts include total/queued/running/completed/partial/blocked; expandable steps and exception refs are optional. One run stays one visible task at 1 or 500 accounts.
- **`plan`:** carries `plan_ref`, `revision`, `title`, safe summary, ordered steps, status, and subject refs. It never dereferences a project-wide singleton.
- **`gate`:** carries `gate_id`, kind, state, title/summary, subject refs, expected revision/hash, optional `{amount_cents,currency}`, addressee, permitted decisions, and answered decision/actor/time when closed. A closed gate remains in history with buttons disabled.
- **`sources`:** carries actual message-scoped source items (`source_id`, title, URL when externally navigable, evidence/artifact refs, source kind); the backend never sends display-only “Used N sources” copy.

### 3.5 Turn submission, concurrency, and user controls

- The turn POST accepts exactly one of an ordinary message or a structured gate response. It also accepts stable client/idempotency identity, ordered context entity/object refs, and attachment refs; it never accepts `actor_id` or `action_ref`.
- **One active platform-deepagent turn per thread.** Later ordinary turns may be durably queued in submission order; they never execute concurrently against the same thread history. Detached research runs do not lock the thread, so the user can keep asking questions while research proceeds.
- **Stop turn** records durable intent for the active chat turn and its associated design run. It preserves committed tool effects, accepted scene versions/prior website output, and already-launched account/contact research. Acknowledgement follows owned-design termination and immutable partial-answer/history persistence; it is separate from the HTTP 202 intent receipt.
- **Queue hold and Resume (2026-09-12 amendment):** Stop atomically holds later accepted turns. They remain FIFO across refresh/restart until explicit `POST …/threads/:threadId/queue/resume` with the observed hold ID. Sending while held appends; Resume consumes no draft. Stale Resume cannot release a newer hold. Normal completion without Stop still advances automatically. Empty holds clear on acknowledgement under the thread lock.
- **Composer:** running plus empty draft shows Stop; running plus valid draft shows Send and queues. Pending cancellation shows disabled Stop; acknowledgement restores normal Send. No normal Stopping/Stopped copy or duplicate standalone Stop strip. The queue count/Resume sits above the composer.
- **Interrupted history:** only the accepted finalize-answer prefix is stored, with interruption provenance carried separately into model context. Provider reasoning is excluded. Stop and successful finalization serialize so only the first durable authority wins. Detailed payloads, implementation and evidence live in [Projects §6A](../../apps/frontend/docs/api-contracts/projects.md#chat-polish-delivery-plan).
- **Suspend/resume run** invokes the governed supervisor tool and has its own task state. It is not represented as a stream abort.
- **Gate approve/reject/revise** is a new human turn and durable gate answer. It is not a client-only AI Elements callback.
- **Retry turn** creates a new generation attempt tied to `retry_of_turn_id`; it never mutates or overwrites the prior transcript.

The composer may remain available during detached work. While a same-thread model turn is active, the UI either queues the submitted turn visibly or disables submission with an explicit reason; it must not silently drop or race it.

### 3.6 Reconnect, rehydration, and errors

Initial/cold load comes from paginated durable messages plus current gate/run projections, not replaying the entire SSE history. Live attach starts from the returned cursor; reconnect sends `Last-Event-ID`. If the cursor is outside retention or an attempt was reset, `stream.reset` instructs the repository to re-fetch the canonical message/turn projection and then attach at the new cursor. At-least-once delivery is deduplicated by `event_id`; part identity/revision prevents duplicate UI. Transport errors use the shared `{error:{code,message,requestId}}` envelope and never surface raw provider exceptions, tool arguments, or private reasoning.

### 3.7 R0 executable Home/project/chat join (founder-ratified 2026-08-10)

The authoritative wire schemas, idempotency/error matrix, title algorithm,
capability rules, sidebar state machine, and fixture prohibition are in
`apps/frontend/docs/api-contracts/projects.md` § "Executable integration
contract". This charter freezes the architectural obligations that contract
must preserve:

1. **One Home act, one durable transaction.** `POST /api/v1/projects` creates
   the `Untitled project`, its message-titled first thread, the captured human
   message, immutable submission, `turn.accepted`, and dispatch intent before
   returning the real route. No second Send and no client-authored ids.
2. **Same turn engine.** Bootstrap factors through the existing capture,
   submission, event, single-flight, and dispatch services; it does not create
   a second Home-only execution path. The HTTP process never composes/calls the
   gateway.
3. **Explicit project authority.** Creation adds `project.write` to Lane B's
   internal permission vocabulary (operator/admin/owner, not viewer), bumps the
   policy version, and still requires `thread.write`. The client supplies no
   workspace or actor authority.
4. **No arbitrary brand.** The request names a workspace-scoped brand. Home may
   expose a default only when unambiguous or separately persisted; row order is
   never business authority.
5. **Finite turn streams.** Synthetic `stream.hello`/connect-time
   `stream.reset` carry the same version/type/project/thread/turn identity the
   frontend parser requires. The SSE `event:` equals JSON `type`; terminal
   backlog/live events are emitted and the turn stream closes. The client
   finalizes on the terminal frame rather than waiting for EOF.
6. **Queue and Stop are different state.** Queued and running both make the
   thread busy, but only the exactly-running turn is stoppable. Later messages
   remain durably visible in acceptance order and dispatch after every terminal
   outcome, including cancel/failure/awaiting-input.
7. **A real shell, not a hybrid.** Home, project, sidebar, and chat repositories
   share the same transport choice. HTTP errors cannot fall back to fixture
   project ids, titles, threads, models, artifacts, or timeline phases.
8. **Honest capability surface.** Context refs, attachments, and agent-profile
   selection are interactive only when advertised and durably accepted. Until
   then their controls are absent/disabled. A new project has a real empty
   Gallery; fixture artifacts never stand in for an unimplemented backend.
9. **Hamburger controls layout.** Desktop hover previews as an overlay; click
   pins and reflows; mobile remains a drawer. No sidebar toggle navigates Home.

This is a cross-seam integration amendment, not a reopening of D1–D6 and not an
authorization to implement the design/artifact subsystem on this branch.

---

## 4. Slices (each independently landable; per-slice sign-off per the branch charter)

- **R0 — executable integration contract freeze (documentation only).** Add
  §3.7, reconcile `FI-lane-demarcation.md` §2.4, and make
  `apps/frontend/docs/api-contracts/projects.md` authoritative for the atomic
  Home bootstrap, exact titles, project/sidebar reads, finite SSE lifecycle,
  queue-vs-Stop state, shared sidebar behavior, empty Gallery, capability
  honesty, error codes, and no-fixture-fallback rule. No runtime, schema, or
  migration change is part of R0.
- **D0 — durable shell.** P1: `thread` table + internal-user/membership FKs + pagination + `refs[]` vocabulary + thread CRUD tools/endpoints. D0's ownership migration chains after Lane B B1; its remaining thread/message work proceeds in parallel. Also: L6-truncation inversion (newest-retained) + the missing `get_onboarding_input_for_artifact` index. AC: thread CRUD round-trips over HTTP with an injected internal test principal; no provider id enters a row; turn list paginates; a 200-message thread keeps its newest messages in L6; db-smoke green.
- **D1 — identity + action_ref (with Lane B).** P2 incl. the directive-tool blocker fix and canonical `turn-action:<turn_id>` resolver. AC: `confirm_account_research_directive@2` succeeds end-to-end from a turn on a dev workspace, `confirmed_by`/`confirming_action_ref` equal the ambient turn values; a plan/client-supplied `action_ref` is structurally absent/rejected; the ref resolves only inside its workspace and actor/gate scope; `draft_…@2` drives through the agent seam in a test.
- **D2 — async turn execution.** P3: `AGENT_TURN` task kind, worker composition (once, at startup), the production turn route, per-thread single-flight + visible queueing, replay short-circuit honored, stop/retry attempt semantics, trial surface retired to dev-only. AC: concurrent turns on two workspaces execute without cross-talk; two turns on one thread execute in submission order; a worker crash mid-turn starts a distinct retry attempt and reaches one committed outcome; the HTTP process never touches the gateway; detached research does not block a new chat turn.
- **D3 — complete streaming.** P4 + §§3.1–3.6: turn outbox + SSE endpoint + part projections + real incremental `finalize_turn.user_message` extraction and rendering. AC: the frontend receives at least one non-empty text delta before the durable turn finalizes; arbitrary JSON/UTF-8 chunk boundaries reconstruct byte-identically; no raw finalize JSON/private reasoning leaks; disconnect/reconnect replays identical deltas by `Last-Event-ID`; crash/retry resets the partial attempt without splicing; slow consumers do not block generation; every non-token emitted part id resolves to its durable receipt/object; stream loss never changes the durable outcome.
- **D4 — the kickoff flow.** P5: gate objects (immutable gate + insert-once answer), structured gate-response turns, the server-derived maximum-spend on the gate (no estimate tool — §6-D5), the new surface, launch narration. AC (the Option-B acceptance): in one conversation on a two-account fixture with approved tier checkpoints — agent drafts, presents the exact server-derived maximum-spend, turn ends `awaiting_input` with a readable gate; Approve creates a visible human turn and invokes the human-only confirm tool with server-derived authority; the platform deepagent then launches; `entity_research_run.source_action_ref` equals the confirming turn's ref; `approval_refs` carries both refs; reject/revise leave closed/updated gate records; a non-confirming turn or stale hash/estimate does *not* launch; the canary policy surfaces in narration.
- **D5 — frontend rebuild.** P6 + contract deltas + §3.1 AI Elements map. AC: fixtures→HTTP flip streams a real multi-tool turn and tokenized final message end-to-end; streamed Markdown renders without raw syntax/flicker; independent reasoning/activity disclosures preserve scroll position; the approval card renders requested/responded/denied from the gate object; the research task aggregates N accounts into one visible task per the Figma spec and covers partial/needs-input/suspended states; cold reload rehydrates transcript/gate/task state; no phase-enum manufacturing remains.

R0 precedes every 2026-08-10 join-repair implementation slice. Historical
ordering after Lane B B0 remains: D0’s non-FK work ∥ D1’s Lane-D half ∥ D3
scaffolding; D0 ownership FKs join after B1; D2 may execute with a deterministic
injected `RequestPrincipal`; production D1 joins B2/B4; D3 ∥ D4 follows, then
D5 (joining B3). D4 cannot pass production acceptance before the Lane-B
principal join. D4's status read-back needs Lane C's L2/L3; nothing here
touches Lane E/F/G files. Chokepoints per FI-3 discipline: api composition
root, alembic single-head.

---

## 5. Testing strategy

The canonical fixture is **one project, one thread, one confirmed directive, two accounts with human tier checkpoints**. Durable-outcome assertions are receipt-based (turn journals, gate rows, `approval_refs`, A9/idempotency ledgers), never log-based; the stream has its own contract suite and is never used to prove the domain outcome. Adversarial cases from the studies: plan/client-supplied `action_ref`/`confirmed_by` (must be structurally absent/refused), model self-selecting a capture record (the PC-C8 scoping), duplicate turn submission under one `Idempotency-Key`, gate answered by a different actor than the gate's addressee, launch with a stale estimate (`expected_estimated_cost_cents` mismatch must refuse), and two same-thread turns racing.

The streaming suite is not a superficial “received some SSE” test. It must cover: first delta before finalization; `finalize_turn.user_message` split before/inside/after escapes and multibyte Unicode; empty and malformed streamed tool arguments; multiple model/tool rounds; tool start/end/error; a disconnect at every event boundary followed by cursor replay; duplicated SSE delivery; slow-client backpressure; stop; worker death after partial text; `part.reset` + distinct retry attempt; final delta/message byte equality; Markdown constructs split across tokens; and a negative assertion that no raw provider reasoning, surrounding finalize JSON, or non-display tool arguments reach the client. D5 then exercises the same fixture in a browser with the actual Clue adapters and AI Elements primitives.

---

## 6. Decision register

- **D1 — turn execution architecture: RATIFIED 2026-08-08.** Async worker-executed turns (§3-P3): the production turn route persists and enqueues an `AGENT_TURN` fleet task; the fleet worker executes the graph; the client attaches to the turn stream. Gateway-in-HTTP blocking turns are rejected.
- **D2 — streaming granularity: RATIFIED 2026-08-08.** Lane D ships complete token streaming in the initial production path alongside part-level events. It must stream the in-progress model-produced `finalize_turn.user_message`, persist/replay deltas, reconcile them to the durable final message, and handle crash/reset/retry as §3.3 specifies. Post-hoc typing animation or a part-only first release is not acceptable.
- **D3 — the gate object: RATIFIED 2026-08-08.** A new durable, **generic** `agent_gate` substrate, implemented as an **immutable gate row plus an insert-once answer/event record** (open/answered derived from the answer record's presence, never a mutated status column — §3-P5(a)). Flavoring `open_gate_refs` in place is rejected.
- **D4 — user identity: RATIFIED 2026-08-08.** `actor_id` is the Clue-owned `platform_user.user_id` resolved from a real authenticated session and authorized through a Clue-owned `workspace_membership`, exactly as `FI-lane-B-authenticated-principal-contract.md` specifies. Clerk is the initial authentication adapter only. No Clerk id/organization/role/session claim is a Clue foreign key or authorization key; the per-workspace trusted-header option is rejected for production.
- **D5 — estimate tool: RATIFIED 2026-08-08 — DEFERRED for V1.** No `estimate_account_research@1` is introduced and `estimate_project@1` stays reserved. V1 provides no conversational estimates or detailed cost breakdowns; the backend computes one server-derived maximum-spend amount when creating the directive-confirmation gate, stores it durably on the gate, and verifies it again at launch (§3-P5(b)). A richer estimation tool and cost-explanation surface are post-V1.
- **D6 — trial surface disposition: RATIFIED 2026-08-08.** Keep the stage-0 trial as the dev-only harness, unchanged; it never becomes a production surface.

---

*Ratification log: 2026-08-08 — D2 complete token streaming ratified by founder; under-specified contract recommendations from §§3.1–3.6 added at founder request. D4 real authenticated Clue principal ratified by founder and formalized in `FI-lane-B-authenticated-principal-contract.md`, including the no-provider-FK rule and Clerk authentication-only boundary. Later the same day, founder resolved the remaining register: D1 async worker-executed turns; D3 durable generic `agent_gate` as immutable gate + insert-once answer record; D5 estimate tool deferred post-V1 in favor of a server-derived maximum-spend amount stored on the gate and re-verified at launch; D6 trial kept dev-only. The §6 register is fully resolved; the charter is build-ready.*

*As-built amendments (founder-ratified 2026-08-08, after slices D0–D2 + the B1-join landed): (1) the nine thread-shell contract deviations are ratified and recorded authoritatively in `apps/frontend/docs/api-contracts/projects.md` ("As-built thread-shell contract"). (2) **P3's persist step is two-phase**: the HTTP route persists the user message + an immutable `agent_turn_submission` row (NOT NULL internal submitter identity, capture-before-spend FK; `turn_id` derived from the idempotency identity) and enqueues; the fleet worker creates the `agent_turn` row, copying the submitter from the durable submission row — never from the queue payload. Rationale: creating the full turn row in HTTP would compose the model provider there, violating the gateway-isolation rule. Consequence: a queued-not-yet-executed turn is visible as a submission; D3/D5 read surfaces union submissions with turn events. (3) Ownership/submitter columns are nullable with FKs to the B1 tables (machine turns have no human submitter; fabricating one violates Lane B ruling 8); a NULL-submitter turn can never anchor an `action_ref`.*

*R0 join-contract amendment (founder-ratified 2026-08-10): after live browser
verification exposed fixture Home routing, malformed connect frames, a
non-terminating turn stream, stale Stop targeting/state, a hybrid sidebar and a
hamburger that navigated Home, the founder fixed the intended behavior:
`Untitled project`; first-message-derived thread title; one atomic Home action;
empty new-project Gallery; visible durable same-thread queueing; desktop hover
overlay/click reflow sidebar. The executable contract is recorded in
`apps/frontend/docs/api-contracts/projects.md`; §3.7 records the Lane-D
architectural obligations. R0 changes documentation only.*

*R8 composer-capability amendment (founder-ratified and implemented
2026-08-10): Home and project conversations accept ordered, workspace-validated
account/contact refs, persist them beside the immutable submission, pass them
through L5 deterministic context assembly, and project them back onto the user
message after reload. The model control intentionally remains visible with one
real option only: `head-of-abm@v23`, labelled GPT-5.6 Terra and pinned to
`openai/gpt-5.6-terra`; the detached worker verifies that submitted profile
against the promoted profile before execution. Attachments remain unavailable
and hidden because no durable upload-receipt endpoint exists; browser-local
object URLs are never accepted.*
