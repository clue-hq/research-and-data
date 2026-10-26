# Design session continuity — one artifact, one design session

**Status:** design note for founder review (2026-09-18). No plan, no code.
**Supersedes:** the per-turn restart shape ruled in Part II slice D5 ("resume-as-restart",
`lumen_agent/checkpoint.py`) and the per-turn workspace folder (`tools/substrate.py` mints a run id
and a trace directory per construction).

## 1. The ruling this note implements

Founder, 2026-09-18:

1. **One design artifact means one design session.** As long as the user works on the same
   design document, the design deepagent keeps the same workspace folder and the same continued
   model context. Nothing is created fresh for a later turn. Edits happen in the original folder.
2. **The session persists**, and is never cold-started. Previous turns' reasoning, tool calls,
   results, previews and reviewer critiques stay in the agent's context for the next turn.
3. **Compaction and offloading use the deepagents library's own mechanisms.** No new mechanism.
4. Rulings confirmed the same day: session per **document** (not per thread); the session folder is
   **synced to storage at turn end** rather than assumed to be on one host; compaction keeps user
   and agent exchanges verbatim and summarizes tool chatter; the model's **reasoning text is
   stored in the record always**, and feeding it back into context is decided per provider.

## 2. What is true today (why this note exists)

- Every design turn creates a new run id, a new context window, and a new scratch folder
  `run_<id>`. The LangGraph checkpointer is keyed to that run id, so it only restarts a crashed
  turn from the top; it carries nothing between turns (`lumen_agent/checkpoint.py`).
- The next turn is handed a package instead of memory: the delegation brief, the leg's prior
  user/assistant messages as plain text (`clue_design.leg_context.render_leg_turn_prompt`), the
  document at its current version, the selection chips, and the leg's pins.
- Therefore the agent re-reads its skills and knowledge into context on every turn, re-reads the
  scene, and re-derives what it did last time from its own reply text. Its previous reasoning, tool
  calls, previews and critiques are not carried at all. Small edits pay a full re-orientation.
- The skill/knowledge *files* are not re-copied on a warm turn (content-stamped materialization),
  which is irrelevant to the agent because its context is empty.

## 3. Target model

### 3.1 Session identity

- A **design session** is keyed by `(workspace_id, document_id)`. It is born the first time a
  design leg pins that document and lives until the document is archived or erased.
- The session owns: one workspace folder, one LangGraph thread (the continued message history), and
  a pointer to the document version the agent last wrote.
- A design **leg** (per thread, one open per thread, unchanged) attaches to the document's session.
  With the same-document queue ruled earlier (a second thread on a driven document queues), two
  legs never drive one session at the same time.
- A design **run** per turn stays exactly as it is: the fleet work id, the lease, the cost
  receipts, the incident bookkeeping and the run-event stream all key on it. The run is the unit of
  work; the session is the unit of memory.

### 3.2 The workspace folder

- One folder per session: `<root>/session_<document_id>/`, replacing `run_<id>/`.
- Skills, knowledge and `AGENTS.md` are materialized into it once (the existing stamp logic keeps
  it current if the authored sources change between turns).
- Each turn writes its rounds, previews, operations ledger and `final.json` under
  `turns/<run_id>/` inside the session folder. Nothing is deleted between turns.
- At turn end the folder is synced to platform storage under the workspace; at turn start a worker
  that does not have the folder restores it before materialization. Previews are the bulk of the
  bytes; everything else is small text.

### 3.3 The continued context (the library's own mechanisms)

- The LangGraph Postgres checkpointer already used per turn is keyed to the **session** instead of
  the run: `thread_id = session id`. A new user message is appended to the existing thread and the
  graph is invoked; the checkpointer restores the full message list, including every tool call,
  tool result, sub-agent result and reviewer critique from earlier turns.
- **Compaction** is deepagents' `SummarizationMiddleware`, which the harness already installs
  (`create_summarization_middleware(model, backend)`). When token usage crosses its threshold it
  summarizes the oldest messages by an LLM call, appends the summary, and offloads the full evicted
  history to the backend at `/conversation_history/<thread_id>.md` (media written beside it). This
  is append-only, which is what the harness's cache-stability invariant requires. Its
  `trigger` / `keep` settings are configuration on the existing middleware, not new code. The
  library's `compact_conversation` tool may be exposed so the orchestrator can compact on demand.
- **Offloading of large tool results** is deepagents' filesystem middleware behaviour (tool
  message eviction to the backend above a size threshold) and stays as is.
- Because the offloaded history lives in the session folder's backend, "keep user and agent
  exchanges verbatim" is met at the record level by the library. Whether the summary prompt keeps
  user turns verbatim inside the window is a prompt setting on the same middleware; if the default
  summarizer compresses user messages too aggressively, the summary prompt is adjusted, not the
  mechanism.

### 3.4 The tool layer becomes session-bound (the one structural change)

- `LumenDesignTools` / `LumenWebTools` stop minting a run id in their constructor. They take the
  session folder and the current run id, write per-turn state under `turns/<run_id>/`, and on a
  continued turn **load the scene from the document's current version**, never from memory.
- `final.json` stays the authority for a turn's outcome, now under its turn directory.
- `checkpoint.py`'s restart branch becomes the resume branch: a thread that already carries state
  is continued, not deleted. A crashed turn (lease lost, takeover) resumes from the last checkpoint
  with the scene reloaded from the document, which is the reconstructible-substrate condition that
  module named as the prerequisite for true resume.

### 3.5 Document drift between turns

- The session records the document version the agent last wrote.
- At turn start the executor compares it with the current version. If a human edited the document
  in between, the turn gets a short system note ("the document moved from vN to vM; changes: …",
  built from the operations history the API already keeps) and the scene is reloaded. The message
  history is untouched.

### 3.6 Sub-agents

- The orchestrator's context persists. The author and reviewer sub-agents are spawned per task as
  today; their results are already in the orchestrator's history and their transcripts are kept
  under the turn directory. They are not kept alive across turns in the first cut.

### 3.7 The model's reasoning text

- The design side requests reasoning effort but keeps no reasoning text. The session record will
  store the provider's reasoning output per model call (in the turn directory and in the trace),
  always. Whether it is re-sent as context is a per-provider setting, default off, because most
  providers do not accept prior reasoning as input.

## 4. What stays as it is

One run per turn; the version compare-and-set at save; one open leg per thread; the delegation
brief and the leg history block on the first turn of a session (later turns no longer need the
history block, the thread carries it); the exit judge; the cost receipts and Langfuse trace per
turn; the run-event stream and the editor lock.

## 5. What changes for the user

- A small edit becomes one or two model calls: no re-reading of skills, no re-reading of the scene
  unless it moved, no re-derivation of the previous turn.
- The agent can answer "why did you do that" from its own history.
- The first turn of a session is unchanged in cost and time.

## 6. Open points for the plan

- The exact `trigger` / `keep` values for the summarization middleware for the design models in
  use (start from the library's model-aware defaults).
- Session folder sync: whole-folder tar versus per-file content-addressed upload (the platform
  storage is content-addressed; per-file is the natural fit).
- Erasure: a session's offloaded history and folder must be deleted with the document (the
  erasure lane).
- The web harness composes the same way and gets the same treatment in the same plan.

## 7. Acceptance (to be proven live, spends money)

1. Two consecutive turns on one ad: the second turn's trace shows the continued thread (prior tool
   calls present), no skill reads, and fewer model calls than the first.
2. A hand edit between turns: the second turn's opening context carries the drift note and the
   agent edits the moved document without a version conflict.
3. A forced context overflow across several turns: the library's summary appears in the thread,
   the offloaded history file exists in the session folder, and the agent still answers a question
   about the first turn correctly.
4. A worker restart between turns on a different worker: the session folder is restored from
   storage and the thread continues.
