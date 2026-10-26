---
schema_version: "1"
kind: skill
name: manual-turn
version: v24
summary: "Manual: what one turn is, how it ends, what actually reaches the human, what is frozen while you work, and which of those rules code enforces."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
<!-- sources: research/2026-09-13-head-of-abm-manual/E-runtime-and-sibling-agents.md §1.2-1.11 and "What the agent is never told" rows 1-3, 6-14, 18-21; research/2026-09-13-head-of-abm-manual/D-authority-gates-and-human-surfaces.md §4 -->
# The turn: one message in, one finalization out

A turn is one human message, one execution, one workspace, and exactly one call to
`finalize_turn`. Nothing else ends a turn successfully. Every rule below is marked
`(enforced)` when code refuses you, or `(asked of you)` when only this manual, the prompt or
a skill asks.

- You must call a tool every round; you cannot think out loud for a round and stop `(enforced)`.
- The turn is over the moment `finalize_turn` returns; it stops the graph `(enforced)`.
- A turn that ends without a committed finalization ends `missing_finalize`, and the human
  sees nothing at all, not even prose you wrote `(enforced)`.

## The four honest terminals

| Status | Use it when | Shape |
| --- | --- | --- |
| `completed` | the requested outcome is durably complete | must carry `user_message`; must not carry `failure_code` `(enforced)` |
| `awaiting_input` | you need a human answer or confirmation | must say what you are waiting for: a next action, an open gate ref, or a `user_message` `(enforced)` |
| `blocked` | an external gate prevents progress | same shape as `awaiting_input` `(enforced)` |
| `failed` | the turn honestly failed | must carry a lowercase snake_case `failure_code` `(enforced)` |

A launch, a queue acknowledgement, a provider wait, or a normal model stop is never completed
research `(asked of you)`.

`awaiting_input` is a terminal status, not a suspension. The thread's next submission is
offered immediately, and the human answers you in a brand new turn `(enforced)`.

## What actually reaches the human

| Thing | Reaches the human? |
| --- | --- |
| `finalize_turn(user_message=...)` | yes, and it is the only prose that does `(enforced)` |
| ordinary assistant text outside that argument | no; it is discarded as provider chatter `(enforced)` |
| `domain_refs` of type `research_directive`, `agent_plan`, `plan`, `project_document` | yes, as a plan card `(enforced)` |
| `domain_refs` of any other type | no; silently dropped, with no error `(enforced)` |
| `open_gate_refs` | yes, as the gate card the human clicks `(enforced)` |
| `assumptions` | no. They are stored on the finalization and shown to nobody. Anything the human must see belongs in `user_message` `(enforced)` |
| anything at all, on a `failed` turn | no. A failed turn produces no assistant message `(enforced)` |

Because of this, write the explanation itself into `user_message`, not around it `(asked of you)`.

## The routing receipt

A skill may tell you the platform refuses a `completed` or `awaiting_input` finalization of a
substantive turn that recorded no routing receipt. That guard is installed only on the
developer trial surface. **The production conversation you are running on never refuses an
unrouted finalization.** So routing what the human told you before you finish is
`(asked of you)`, and the honesty is entirely yours. How to record one is
`.deepagent/skills/manual-documents-decisions/v24/SKILL.md`.

## Turn statuses and failure codes

Statuses a turn can be in: `requested`, `context_ready`, `running`, `awaiting_input`,
`completed`, `failed`, `cancelled`, `abandoned`, `privacy_tombstoned`.

Failure codes the runtime can end a turn with: `agent_timeout` (the wall clock, when the
deployment sets one), `missing_finalize` (no committed finalization), `graph_recursion_error`
(the superstep ceiling; only a broken loop reaches it, because your round limit ends the turn
through `finalize_turn` instead), `runtime_error` / `value_error` / `type_error` and other exception names,
`agent_cancelled_or_crashed`, `required_context_artifact_missing`, `stop_requested`, and any
code you yourself pass to `finalize_turn`. You never observe your own code: it is written
after the graph has ended `(enforced)`, so you cannot learn from a failure inside the thread.

## Budgets that end the turn

- A refused governed call comes back to you with its reasons. The cost is counted in rounds,
  not calls. A round in which one or more calls were refused spends one repair round, charged
  only after every call in that round has returned. Ten repair rounds come back to you. The next
  one ends the turn with nothing shown to the human `(enforced)`.
- `finalize_turn` has its own separate budget of two repairs; the third bad shape ends the turn
  `missing_finalize` `(enforced)`.
- A precondition refusal from an effect free read does not spend the repair budget `(enforced)`.
- The round limit and the time limit are set by the deployment. Near either one, a platform
  notice tells you to wrap up, and then only `finalize_turn` is offered. Output is capped at
  8,192 tokens per call. All of it is in `.deepagent/skills/manual-limits/v24/SKILL.md`
  `(enforced)`.

## Receipts, and the ones you do not remember

A successful governed call returns a bounded receipt: `node_key`, `operation_id`, `kind`,
`address`, `status`, `replayed`, `artifact_refs`, `domain_refs`, `reference_values`,
`failure_code`. Substantive output stays behind references, and `reference_values` is capped at
16 KiB of canonical JSON `(enforced)`.

If a worker crashed mid turn, another worker resumes the same execution id against re-verified
workspace bytes. A committed turn is never executed twice. So you may find receipts marked
`replayed: true` for operations you do not remember performing; they happened, and repeating
them is not needed `(enforced)`.

A human Stop cancels only the current generation attempt. Committed tool effects stay
committed and a detached research run keeps running `(enforced)`. Do not assume a statement you
recorded before an interruption needs recording again `(asked of you)`.

## What is frozen, and what is live

- `project/status.md`, `project/decisions.md`, the brand documents and the project's ICP pin
  are compiled once and pinned for the whole turn `(enforced)`. Re-reading them inside one turn
  returns the same bytes. A job that settled thirty seconds ago will not appear there until
  your next turn.
- The read tools are live. For "is it done yet", call the read, never re-read `status.md`
  `(asked of you)`. Which read to call is `.deepagent/skills/manual-siblings/v24/SKILL.md`.
- `scratch/` persists across the turns of this chat; `inputs/` and `context/` are rewritten
  every turn. See `.deepagent/skills/manual-workspace/v24/SKILL.md`.

## One turn at a time, and what you cannot see

- A thread runs one turn at a time. A message the human sends while you are working is queued
  and is not in your context `(enforced)`. Do not promise to also handle something you cannot
  see `(asked of you)`.
- Your conversation history is evicted oldest first under a byte budget, with no marker where
  it was cut `(enforced)`. On a long thread, what you hold is not the whole transcript. This is
  why durable decisions belong in the project's own records, not in your memory of the chat
  `(asked of you)`.
- You cannot see cost, tokens, latency, logs, or host paths. The budget number you are given is
  a per plan estimate ceiling, not a running total of spend `(enforced)`. Never claim or
  estimate spend, duration or system health `(asked of you)`.
