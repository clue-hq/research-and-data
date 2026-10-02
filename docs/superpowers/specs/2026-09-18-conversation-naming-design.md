# Conversation naming — design

**Status:** approved 2026-09-18; implemented on branch research-streaming-v3 per docs/superpowers/plans/2026-09-18-conversation-naming.md.

## 1. The problem

Every project a user starts from Home is called "Untitled project" forever unless a human renames
it. The chat that Home opens is titled with the first 80 characters of the user's message, which is
long, ugly and no help in the sidebar. A chat started inside an existing project has no title at
all and shows the "New chat" fallback forever. ChatGPT's approach — a separate, tiny, cheap model
call that names the conversation from its opening exchange and stores the name as metadata — is
what the founder wants here, for both chats and projects.

## 2. What exists (verified 2026-09-18)

- `POST /api/v1/projects` (`platform/api/clue_api/chat/router.py`, `bootstrap_project_route`)
  creates the project with `name = "Untitled project"` (`_UNTITLED_PROJECT`) and the first thread
  with `title = _first_thread_title(message)` — the contract's "R0" rule (frontend
  `docs/api-contracts/projects.md` §4: trim, collapse whitespace, cut at a word boundary within 79
  code points, append `…`). The idempotency replay check compares the stored thread title with the
  recomputed one.
- `POST /projects/{id}/threads` births a thread with `title = null`; the frontend shows
  `UNTITLED_THREAD_LABEL = "New chat"` (`features/projects/model/chat-thread.ts`).
- `agent_thread.title` is nullable; `project.name` is `text NOT NULL`. Both are mutated only by
  `set_thread_title` (`thread_store.py`) and `set_project_name` (`clue_spine/spine.py`), behind the
  governed `rename_thread` / `rename_project` tools, which are granted to **no** agent role — they
  back the manual rename menus only.
- No model names anything today. The nearest precedent for a cheap one-shot call is the ARV2
  display layer: `LunaSectionRunner` (`arv2/display/runner.py`) builds an OpenRouter chat request
  (`openrouter_chat_request`) and sends it through `clue_spend.ProviderCaller`, model
  `settings.arv2_display_model = "openai/gpt-5.6-luna"`.
- The turn runs on the fleet worker: `AgentTurnWorkHandler.handle` → `ProjectConversationTurnRunner.run`
  → `ConversationTurnEngine` (`conversation_turns.py`). At the end of a head-of-abm turn the engine
  reads the assistant reply back from the artifact store, then `_project_turn_close` emits the
  gate/plan/task parts, reconciles the text and emits the terminal event through
  `stream.turn_finished(status=…)`. The user's message for the turn is read from the submission's
  message artifact (`message_artifact_ref`).
- The frontend's per-turn SSE stream carries only `turn.*` (and `design.*`/`leg.*`) events. The
  composer lock (`chat-shell/model/agent-run-lock.ts`) lifts on the terminal turn event. The
  sidebar list and the project workspace loader refetch when `useProjectCatalogInvalidation()`'s
  `revision` changes or on navigation; nothing refetches on a turn event today.
- Model knobs are environment settings (`.env.example` "Agent model configuration" block and the
  per-feature `CLUE_*_MODEL` knobs), never profile versions; every flag the code reads appears in
  `.env.example` at the moment it is introduced.

## 3. Rulings (founder, 2026-09-18)

1. **Project name after the first agent reply** (option B): the reply usually restates the goal
   and brand/product are known by then. The project sits as "Untitled project" during the turn.
2. **Chat title at the same moment** (option A): one call at the end of the first completed turn
   produces both names on the Home path and the chat title alone for a new chat in an existing
   project. The fixed labels "Untitled project" and "New chat" are the placeholders; the
   80-character message prefix is retired.
3. **The hook lives in the turn worker** (option 1): no new fleet task kind, no new SSE event
   type, no migration; the frontend refetches on the terminal turn event.
4. Generate once; never drift-regenerate; a manual rename always wins.
5. "First **completed** turn", not first turn: a failed or cancelled turn leaves the placeholder
   and the next completed turn names it. Existing untitled chats and projects are named on their
   next completed turn — no backfill script.
6. Model is an env knob defaulting to `openai/gpt-5.6-luna`; call timeout **60 s**; the feature
   switch defaults **on**.
7. Names are 2–5 words in the conversation's language; the chat title names the task, the
   project name names the motion; the chat title never restates the project name.

## 4. Design

### 4.1 Trigger and placement

The namer is a small service object, `ConversationNamer`, injected into `ConversationTurnEngine`
through `build_conversation_turn_engine(...)` on the fleet worker (`agent_turn_fleet_wiring` /
`fleet_main`). The API process composes none and never calls it. It is a service step with no
agent authority: it is not a tool, not a profile, and it never appears in a manifest.

The engine invokes it in the head-of-abm turn-close path, at the point where the assistant reply
has been read back from the artifact store and before `_project_turn_close` emits the terminal
event. Preconditions, all evaluated there:

- the turn is not a replay;
- the outcome status is `completed` or `awaiting_input` (a gate turn still has a real reply);
- the reply is non-empty;
- at least one slot still holds a placeholder: `agent_thread.title IS NULL`, and/or
  `project.name = 'Untitled project'` (one read, inside the namer).

Design-leg turns are out of scope: a leg never owns a thread's first turn, so the head-of-abm path
covers every naming moment.

**Off the critical path.** The composer unlocks only on the terminal event, so the namer must not
delay it by its full budget. The engine starts the namer as an `asyncio` task the moment the reply
is known, lets `_project_turn_close` do its other work, and then waits for the namer for at most
`NAMING_GRACE_S = 3.0` seconds (a code constant, documented at its site — it is *not* the call
timeout) before emitting the terminal event. A fast call lands before the event and the frontend's
one refetch shows the names. A slow call keeps running with its full 60 s budget, detached from
the turn: it is kept in a per-engine set of pending tasks (so it is neither garbage-collected nor
awaited by the handler), it writes its names when it finishes, and its completion or failure is
logged. It never delays `WorkQueue.finish` or `dispatch_next_thread_turn`, so a follow-up message
the user sends immediately is not queued behind naming. Worker shutdown cancels a pending namer;
the placeholder stays and the next completed turn retries.

### 4.2 The naming call

One OpenRouter chat-completions request, built with the same `openrouter_chat_request` +
`ProviderCaller` pair the ARV2 display runner uses (`HttpxTransport`; the call is metered — §4.9).

Inputs:

| input | source | bound |
|---|---|---|
| user message | this turn's submission message artifact | first 2,000 characters |
| assistant reply | this turn's reply artifact | first 2,000 characters |
| brand name | `brand.name` for the project's `brand_id` | — |
| product name | the project's confirmed product, when one exists | — |
| project name | `project.name`, only when it is **not** the placeholder | — |
| what is needed | `needs_chat_title`, `needs_project_name` (from the placeholder read) | — |

Request shape: the system prompt of §4.3; one user message carrying the inputs as labelled
sections; `reasoning: {"effort": "none"}`; `temperature: 0.2`; `max_tokens: 60`;
`response_format` = JSON schema with `chat_title` (string) and `project_name` (string), each
required only when asked for; `max_attempts = 1` (the next turn is the retry); timeout =
`conversation_naming_timeout_s`.

### 4.3 Prompt (founder review)

```
You name conversations for a B2B account-based-marketing workspace.
You are given the first exchange of a chat and asked for one or two names.

chat_title: 2 to 5 words naming the task the user is doing in this chat.
project_name: 2 to 5 words naming the overall marketing motion this project
is about — who is being targeted, for what, or with what product. Only when asked.

Rules:
- Write in the language the user wrote in.
- Sentence case. No trailing punctuation, no quotes, no emoji, no hashtags.
- Never repeat the project name inside the chat title.
- Never invent company, product or segment names that do not appear in the exchange;
  when the exchange names an account or a segment, prefer it.
- Return only the JSON object with the fields requested.
```

The labelled user message reads, in order: `Brand:`, `Product:` (when known), `Project:` (when
already named), `Needed:` (the field list), `User wrote:`, `Assistant replied:`.

### 4.4 Normalisation and validation

Each returned name passes through one pure function, `normalize_generated_name(raw) -> str | None`:

1. collapse all Unicode whitespace to single ASCII spaces and trim;
2. strip one layer of wrapping quotes/backticks and any trailing `.`, `!`, `?`, `:` or `…`;
3. reject (return `None`) when empty, longer than 60 code points, more than 8 words, or equal
   (case-insensitively) to a placeholder label ("Untitled project", "New chat", "Untitled").

A rejected name is dropped, never truncated: a bad model output leaves the placeholder rather than
a mangled title. Both names are validated independently; one may land while the other is dropped.

### 4.5 Persistence and the manual-wins rule

Two conditional store functions, added beside the existing writers, each one `UPDATE … RETURNING`:

- `set_thread_title_if_unset(conn, workspace_id, thread_id, title)` —
  `UPDATE agent_thread SET title=:title WHERE workspace_id=:ws AND id=:id AND title IS NULL`.
- `set_project_name_if_untitled(conn, workspace_id, project_id, name)` —
  `UPDATE project SET name=:name WHERE workspace_id=:ws AND project_id=:id AND name='Untitled project'`.

The `WHERE` clause is the whole manual-wins guarantee: a human rename that lands during the call
turns the auto-update into a no-op (zero rows), which the namer logs as `lost_to_manual_rename`.
No origin column, no timestamp column, no migration. The namer writes through the store, not
through the governed `rename_*` tools (it has no tool authority; Doc A's "no fake agency").

The untitled sentinel already exists as `_UNTITLED_PROJECT` in the router; it moves to
`clue_spine` (one constant, imported by the router, the store and the namer) so the three cannot
drift.

### 4.6 Home bootstrap change

`bootstrap_project_route` births the first thread with `title = None`. `_first_thread_title` and its
tests are deleted. The idempotency replay check drops the thread-title comparison (a replay after
naming or after a manual rename must not raise `IDEMPOTENCY_CONFLICT`); the project/brand/status
comparison and the submission's message digest already prove the request is the same. The
contract's §4 ("Deterministic first-thread title") is rewritten: the Home thread is born untitled;
both names are generated after the first completed turn; a manual rename is never overwritten.

### 4.7 Frontend

- `ProjectBootstrapWireSchema.thread.title` becomes `z.string().min(1).nullable()`; the Home
  path's optimistic thread label is `UNTITLED_THREAD_LABEL`. The project title literal stays.
- In `use-project-chat-controller.ts`, a terminal turn event (`turn.completed`,
  `turn.awaiting_input`) calls the catalog's `invalidate()`. That bumps the `revision` the sidebar
  list and the project workspace loader already watch, so the sidebar and the chat header refetch.
- **Bounded catch-up poll** for the detached case: after that first invalidate, while the active
  thread's `title` is still `null` or the project's title is still the untitled sentinel, the
  controller invalidates again every 5 s, at most 12 times (60 s, matching the call budget), and
  stops as soon as both names are present or the user navigates away. Only first turns ever poll.
- No new UI, no new event type, no new copy. Placeholders keep their existing labels.

### 4.8 Configuration

Three settings on `clue_config.Settings`, mirrored in `.env.example` in a new block next to the
ARV2 display block (parity rule 2026-08-31):

```
# --- Conversation naming (chat titles and project names after the first reply) ----
# One cheap call names the chat (and, on the Home path, the project) once the first agent
# reply exists. Off = placeholders stay ("Untitled project" / "New chat").
CLUE_CONVERSATION_NAMING_ENABLED=true
# OpenRouter model id for the naming call.
CLUE_CONVERSATION_NAMING_MODEL=openai/gpt-5.6-luna
# Call timeout in seconds. The turn never waits this long (see NAMING_GRACE_S).
CLUE_CONVERSATION_NAMING_TIMEOUT_S=60.0
```

The subsystem `.env` of each lane gets the same three lines with the same values.

### 4.9 Spend and tracing

The call is recorded the way the ARV2 display records its Luna calls: `ProviderCaller` with the
worker's raw and ledger sinks, `label = "conversation_naming"`, `operation = "chat_completion"`,
`job_id = turn_id`, so the row lands on `provider_call_ledger` attributed to the workspace, project
and thread through the turn, and the existing cost read covers it. The Langfuse observation nests
under the turn's trace (the worker's run context is already bound). The implementation plan
verifies `GET /cost/report` shows the naming rows.

### 4.10 Failure handling

Every non-success path — provider error, timeout, non-JSON or schema-invalid response, both
names rejected by validation, zero-row update — logs one structured event
`conversation_naming.skipped` with `reason`, `turn_id`, `thread_id`, `project_id`, bumps the
counter `chat.conversation_naming.skipped{reason}`, and leaves the placeholder. Success logs
`conversation_naming.applied` with which slots were written. Nothing on this path can raise into
the turn: the namer's `run` is wrapped so any exception becomes a skip.

### 4.11 Not changed / out of scope

- No drift-based re-titling. A deliberate re-name at ICP or product confirmation (option C) is a
  possible V2 and is not designed here.
- No live SSE event for names; the refetch + bounded poll is the V1 delivery path.
- The head-of-abm agent gains no naming tool; the next turn's card simply shows the new project
  name through the scope pin, as it does after a manual rename.
- Trial/fixture project creators (`stage0_trial.py`, `trial/discovery_fixture.py`,
  `arv2/answer_key_loader.py`) are untouched; they set their own names.

## 5. Environment

`CLUE_CONVERSATION_NAMING_ENABLED`, `CLUE_CONVERSATION_NAMING_MODEL`,
`CLUE_CONVERSATION_NAMING_TIMEOUT_S` (§4.8). Requires `CLUE_OPENROUTER_API_KEY` on the fleet
worker, which it already has. No new dependency.

## 6. Acceptance

1. Home: send a first message; when the reply finishes, within one refetch the sidebar shows a
   2–5-word project name and a 2–5-word chat title; neither is the 80-character prefix; the chat
   title does not restate the project name.
2. New chat in a named project: only the chat title is generated; the project name is untouched.
3. Rename the chat by hand while the first turn runs: the manual title survives; the log shows
   `lost_to_manual_rename`.
4. Kill the provider (bad key): the turn completes normally, the composer unlocks on time, the
   placeholder stays, `conversation_naming.skipped{reason=provider_error}` increments; the next
   completed turn names the chat.
5. A naming call slower than the grace window: the terminal event is not delayed beyond the
   grace; the names appear within the poll window without navigation.
6. `POST /projects` replayed with the same key after naming → 200 replay, not 409.
7. `CLUE_CONVERSATION_NAMING_ENABLED=false`: no call, placeholders stay, no ledger row.
8. `GET /cost/report` attributes the naming rows to the turn's project.
9. Tests: `normalize_generated_name` table test; engine test with a `ScriptedTransport` proving
   both names land before the terminal event on a fast call and after it on a slow one, and that
   a pre-titled thread is skipped; bootstrap route test for the null title and replay; frontend
   test for invalidate-on-terminal-event and the bounded poll; contract doc updated.
