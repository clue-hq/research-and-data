# Head of ABM: continuation, prompt caching and compaction across turns

Date: 2026-09-29 · Status: approved (founder); revised same day: compaction for every agent, harness profile never overrides
Branch: `codex/ai-ark-committee-discovery-spec-v1`

## 1. Why

The founder wants the project chat to behave like Claude Code and Codex across turns: a new
message on an existing thread continues the same conversation, re-sending it cheaply, and a long
thread is compacted once instead of growing without bound.

What the code does today (verified 2026-09-29 against `clue_dubai`):

- Every Head-of-ABM turn starts a **fresh** deepagent state. The opening messages are rebuilt from
  seven layers in fixed order (`platform/agents/clue_agents/context.py`,
  `DeterministicAgentContextAssembler.assemble`): L1 system prompt, L2 workspace/product cards,
  L3 project card, L4 memory, L5 focus, L6 conversation history, L7 the new message.
- L6 is every stored user message and final assistant reply of the thread
  (`DbAgentHistoryStore.load`, `platform/api/clue_api/agent_turn_wiring.py`). Tool calls, tool
  results and reasoning of earlier turns are **not** carried.
- L2–L5 change every turn and sit **before** the history, so the provider's prompt cache stops at
  the system prompt. Measured: the first model call of each turn is cached for a flat 41,472 tokens
  (or 0 after a pause) while the prompt grows; the history is billed at full price every turn.
  Within a turn, later calls are 92% cached.
- Nothing is ever dropped: layer budgets are logged, never enforced (ruling 2026-09-14,
  `project_conversation_context_policy`). No compaction exists across turns.
- deepagents' `SummarizationMiddleware` is already inside the graph (`create_deep_agent`), with the
  no-profile defaults (trigger 170k tokens, keep 6 messages), but its state dies with the turn, and
  its offload path `/conversation_history/` is **not** an allowed workspace prefix of the profile
  (`readable_prefixes`/`writable_prefixes`), so its first compaction would fail.
- The runtime already supports **continuation** (`DeepAgentTurnRuntime(continuation_config=…)`,
  `platform/agents/clue_agents/runtime.py`): a new turn resumes a settled saved graph state,
  including `_summarization_event`, and appends new input. Research quality jobs use it
  (`quality_research_wiring.py`); the Head of ABM does not.
- Head-of-ABM graph checkpoints are retained in Postgres (`postgres_agent_checkpointer`).

## 2. Goals and non-goals

Goals:

1. **Append-only prompt.** Everything before this turn's appended input is byte-identical to the
   previous turn's prompt, so it is a prompt-cache hit.
2. **Claude-Code-faithful history.** Earlier turns' tool calls and tool results stay in the
   conversation.
3. **Compaction across turns,** sized to the model's real context window, done once and reused;
   evicted history is kept in a file the agent can re-open; a `compact_conversation` tool.
4. **Large tool results offloaded to files** (unchanged; already works).

Non-goals: the design agent's runtime and history; research agents (already continue); onboarding
and the Stage-0 developer trial surface; changing what the cards contain.

## 3. Design

### 3.1 How a turn starts

- **First Head-of-ABM turn on a thread:** unchanged — layers assembled as today, state saved.
- **Every later turn** (continuation):
  1. **Resume point** = the thread's latest Head-of-ABM turn whose outcome is **completed** and
     whose graph state is settled (no pending node). Its checkpoint holds the whole conversation so
     far, tool calls, tool results and compaction state.
  2. **Gap messages:** every thread message stored after that turn which its state does not hold
     (design-leg exchanges, a stopped or failed turn's messages, derived turns) is appended as plain
     messages, in `sequence` order, from `agent_thread_message` — the same bodies L6 uses today.
  3. **This turn's cards** (L2–L5, assembled exactly as today) are appended as one context-update
     message, then **the user's message** (L7) last. Earlier cards stay in history as snapshots
     (founder: keep snapshots); nothing earlier is rewritten.
  4. The turn runs with `DeepAgentTurnRuntime(continuation_config=<resume point>)` and its state is
     saved as today.
- **Fresh rebuild instead of continuation** (today's path, one cache miss) when:
  - the resolved profile, prompt or tool surface differs from the resume point's (`profile_ref`
    and resource manifest digest recorded on the constitution) — the old system prompt is baked
    into the saved state;
  - the resume point's checkpoint is missing, unreadable or unsettled;
  - `CLUE_HEAD_OF_ABM_CONTINUATION_ENABLED=false`.
  Continuation resumes from the next turn after a rebuild.

### 3.2 Compaction (every governed agent, by default)

Founder rulings 2026-09-29: compaction is on **by default for every agent** built through
`DeepAgentTurnRuntime` (Head of ABM, research, onboarding synthesis, specialists — the single
`create_deep_agent` call in `platform/agents/clue_agents/runtime.py`), and **no deepagents harness
profile may disable or replace this strategy at any point**.

- **Our summariser, not the default.** The runtime adds `ClueSummarizationMiddleware` (a subclass
  of deepagents' `SummarizationMiddleware`, distinct class) and `SummarizationToolMiddleware`
  (`compact_conversation`) to every graph. deepagents' built-in instance is removed by one harness
  profile registered for our governed model provider that excludes **by exact class**
  (`_DeepAgentsSummarizationMiddleware`) — never by the name string "SummarizationMiddleware", which
  would also match ours. A guard test builds each governed agent and fails unless its final stack
  holds exactly one summariser (ours) and the `compact_conversation` tool.
- **Carried across turns.** `_summarization_event` lives in graph state, so continuation (3.1)
  carries it: a thread compacts **once** and later turns build on the summary.
- **Model-aware threshold.** The model's context window is resolved at start-up from OpenRouter's
  public model catalogue (`context_length` for the configured model id), with an override:
  - `CLUE_AGENT_COMPACT_TRIGGER_FRACTION` = **0.90** (450k on Grok 4.6's 500k window);
  - `CLUE_AGENT_COMPACT_KEEP_FRACTION` = **0.10** (the most recent ~50k tokens kept whole);
  - `CLUE_AGENT_CONTEXT_WINDOW_TOKENS` overrides the catalogue for every agent (blank = catalogue).
  - Window unknown: fixed fallback `CLUE_AGENT_COMPACT_TRIGGER_TOKENS` = **170,000**,
    `CLUE_AGENT_COMPACT_KEEP_MESSAGES` = **6**. It never runs without a limit.
- **Evicted history** goes to `work/conversation_history/<thread>.md` in the agent's workspace
  (deepagents' fixed `/conversation_history/` path is remapped by a thin backend wrapper to the
  already-writable `work/` prefix, so no role needs a new folder). The summary names the path so the
  agent can re-open it. A role whose workspace cannot write `work/` (onboarding synthesis,
  specialists) still compacts — deepagents treats a failed offload as non-fatal — it just keeps no
  file.
- **Overflow retry:** a provider "context too long" rejection compacts and retries.
- **Manual compaction:** `compact_conversation` joins the runtime's framework tools (with the file
  tools), so no profile needs to grant it.
- The summarisation call uses the agent's own governed model, so it is metered in
  `agent_model_call` like every other call.
- **Head of ABM v69:** `max_file_bytes` 1 MB → **4 MB** (one eviction is ~400k tokens ≈ 1.6 MB on a
  500k window); prompt, skills and tools otherwise unchanged; manual re-minted. Other roles keep
  their limits (an oversized eviction file is skipped, non-fatally).

### 3.3 Receipts, replay, crashes and stops

- **Context receipt** for a continued turn records: the resume point (turn id, execution id,
  checkpoint id), the gap message ids, and the appended layers (L2–L5, L7) as today. "What did the
  model see" = resume state + recorded additions.
- **Crash before finish:** the retry finds the turn's own half-run state and continues it without
  re-adding history (runtime continuation already does this: redelivery → `state = None`).
- **Completed turns** are never re-executed (existing committed-replay path, and the leg-opener
  fix 761942996).
- **Stopped or failed turns** are never resume points; their messages arrive as gap messages.
- **Existing threads:** no migration. Their first turn after release rebuilds (no continuation
  state yet); continuation takes over from the next turn.

### 3.4 Other paths

- While a design leg is open, turns go to the design agent (unchanged). When the Head of ABM next
  runs, the leg's exchanges are gap messages.
- The design agent, research agents, onboarding and the Stage-0 trial surface are untouched.

### 3.5 Settings (all in `.env.example` with defaults, per the parity rule)

| Setting | Default |
|---|---|
| `CLUE_HEAD_OF_ABM_CONTINUATION_ENABLED` | `true` |
| `CLUE_AGENT_CONTEXT_WINDOW_TOKENS` | blank (catalogue) |
| `CLUE_AGENT_COMPACT_TRIGGER_FRACTION` | `0.90` |
| `CLUE_AGENT_COMPACT_KEEP_FRACTION` | `0.10` |
| `CLUE_AGENT_COMPACT_TRIGGER_TOKENS` | `170000` (window unknown) |
| `CLUE_AGENT_COMPACT_KEEP_MESSAGES` | `6` (window unknown) |

## 4. Measurement and tests

- **Per turn:** log the cached share of the turn's first model call (`cache_read_input_tokens /
  input_tokens`). Target for turns within the cache lifetime: ≥ ~90% (today: flat 41k).
- **Compaction events:** logged with before/after token counts; cost visible in `agent_model_call`.
- **Tests:**
  - continuation assembly: resume point selection, gap-message order, cards + message appended
    last, prior messages byte-identical; fallback on profile change / missing checkpoint / flag off;
  - DB: two real turns on one thread — the second turn's opening state begins with the first turn's
    full saved state, tool calls included;
  - compaction with a tiny window override: compacts once, writes `conversation_history/…`, the
    next turn reuses the summary and does not compact again;
  - crash redelivery continues without duplicated history; a stopped turn is skipped as resume
    point; a completed turn only replays;
  - receipts record resume point and gap messages;
  - catalogue resolution: context length read, override wins, unknown falls back to fixed values.
- **Live proof (founder; spends money):** two turns on one chat; check the second turn's first-call
  cached share in `agent_model_call`.

## 5. Risks

- **Storage:** checkpoints grow faster (tool results kept). Compaction bounds the prompt, not the
  store; existing retention applies. Measure after the live proof.
- **Checkpoint namespace:** Head-of-ABM runs set `checkpoint_ns="agent-turn:<turn>"`, while the
  existing continuation reads `checkpoint_ns=""`; stored rows for a Head-of-ABM execution showed an
  empty namespace. The plan verifies which namespace the resume read must use before building on it.
- **Cache behaviour is the provider's:** xAI via OpenRouter caches prefixes automatically (observed
  `cached_prompt_tokens` today); the append-only prompt is what makes hits possible, not a
  guarantee of them after the cache's lifetime.
