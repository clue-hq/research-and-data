---
schema_version: "1"
kind: skill
name: manual-errors
version: v18
summary: "Manual: every error string a governed tool, a file tool or finalize_turn can hand back, and the one next move for each."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Errors: every string you can be handed, and what to do about it

Three shapes of bad news reach you, and only three. A governed tool refuses with a typed
JSON object. A file tool returns a prefixed string on its own result. `finalize_turn`
raises a plain message with its own guidance appended. Nothing else is an error you can
read: a turn's own failure code is written after the graph ends, and you never see it.

## The governed refusal

A refused governed call comes back as a tool result, not an exception, so you can repair
it. Its fields:

| Field | What it says |
| --- | --- |
| `governed_repair_budgeted` | Whether this refusal spends a repair round. False only for a precondition refusal from an effect-free read. |
| `error` | `plan_rejected` (nothing ran) or `operation_failed` (it ran and did not complete). |
| `address` | The exact `name@version` you called. |
| `node_key` | The call's identity. The same provider call id addresses the same operation. |
| `recorded` | Always false. No durable state changed and this operation did not happen. |
| `reasons` | One line per issue. This is the half you repair. |
| `guidance` | Fixed text, the same on every refusal. |

`guidance` is always the same sentence: "No successful receipt was returned. Preserve successful sibling results. Correct what the reasons name and retry only the failed work. For an executed failed attempt, supply its node_key in retry_of (include earlier failed attempts of that same work too). Plan rejections have no execution node: omit retry_of for them. Do not claim success without a receipt; a late infrastructure error may occur after tool effects."

Read `recorded: false` literally. Nothing was written, no run was queued, no money
was spent. Saying otherwise to the human is the one failure this shape exists to
prevent.

`error` is `plan_rejected` when the proposal never obtained authority, so nothing
ran at all, and `operation_failed` when it ran and did not complete. Each entry of
`reasons` is one issue, whitespace-collapsed and cut at 600 characters, so a long message may end mid-sentence.

## Plan-rejection codes

A `plan_rejected` reason reads `<location>: <code>: <message>`. The codes are the platform's, not a tool's, and none of them is repaired by calling the same tool again with the same arguments.

| String | Next move |
| --- | --- |
| `execution_scope` | Do not retry. The proposal names another execution, which is a platform fault to report. |
| `role_scope` | Do not retry. The proposal names another role, which is a platform fault to report. |
| `workspace_scope` | Do not retry. The call reaches outside this workspace; name only objects your own reads returned. |
| `node_ceiling` | Ask for less in one call, or split the work across turns. |
| `tool_not_allowed` | That tool is not yours on this surface. Read your capability map and use one that is, or tell the human what you cannot do. |
| `delegation_not_allowed` | That role is not delegated here. Do the work yourself or tell the human it is out of reach. |
| `path_grant` | Ask only for paths inside your own readable prefixes. |
| `delegation_ceiling` | Delegate fewer specialists, or do the remaining work yourself. |
| `delegation_depth` | The chain is already as deep as it goes. Do the work at this level. |
| `depth_ceiling` | Flatten the plan; a chain this long is not something one turn should attempt. |
| `fanout_ceiling` | Start fewer steps at once and let the first batch finish. |
| `pin_resolution_failed` | Satisfy exactly the pin the message names, which usually means confirming something at a gate first. |
| `c5_pin_kind_not_allowed` | That call needs pins this interaction does not carry. Tell the human what is missing. |
| `budget_ceiling` | The estimate exceeds this turn's ceiling. Ask for a smaller set and tell the human why. |
| `no_binding` | Do not retry. The turn's captured input is unavailable, which is a platform fault to report. |

## Precondition refusals

An `operation_failed` reason reads `<error_type>: <message>`. The common one is `PreconditionFailed`, whose message is `<code>: <what to satisfy>` for each unmet precondition. The code set is open: every tool owns its own, and the codes you can actually receive are listed per tool in `.deepagent/skills/manual-tools/v18/SKILL.md`. What matters is the shape, so read the code, satisfy exactly what it names, and if you cannot, say so to the human and stay `awaiting_input`.

| String | Next move |
| --- | --- |
| `PreconditionFailed` | Read the codes in the message and satisfy exactly what they name; the next move for each is listed with its tool. |
| `ValueError` | An argument was malformed in a way the tool did not type. Fix the value the message names and call again. |
| `RuntimeError` | Something on this deployment is not wired. Tell the human plainly, and do not retry. |
| `this logical operation is durably blocked` | Do not repeat the identical call. Satisfy the prerequisite the message names, then make a new call. |

## File-tool errors

These never go through the governed path. They arrive as a string on the file tool's own result, under one of three prefixes.

| String | Next move |
| --- | --- |
| `quota_exceeded:` | Write less or read a narrower slice. The quota is fixed for the turn, so the identical write cannot succeed on a retry. |
| `conflict:` | Re-read the file and redo the work against its current bytes; for an edit, copy the span exactly or make it unique, never reword it. |
| `permission_denied:` | Stop. This is something you cannot do here. Do not try a variant path, and tell the human if it matters. |
| `invalid_encoding` | The file is not UTF-8 text and cannot be read as text; say so rather than guessing at its contents. |

## finalize_turn refusals

A refused finalization is not committed and the turn is not over. The message names exactly what is wrong, and one of two fixed sentences is appended to it.

| String | Next move |
| --- | --- |
| `status 'failed' must carry a stable snake_case failure_code` | Add a lowercase failure_code that names why the turn failed, and finalize again. |
| `cannot carry a failure_code; only 'failed' may` | Remove the failure_code, or change the status to failed if the turn really did fail. |
| `status 'completed' must carry a user_message` | Write the message the human should read, and finalize again. |
| `must identify what it is waiting for` | Add a next_actions item, an open_gate_refs entry, or a user_message that asks the human for what you need. |
| `completed specialist turn requires its non-empty role output file` | Not reachable in this role, which has no required output file; if you ever read it, write that file and finalize again. |

## Two strings the runtime itself produces

Neither is a tool's refusal; both come from the surface that wraps every model call.

| String | Next move |
| --- | --- |
| `is structurally unavailable to this exact agent profile` | Call only tools your capability map lists; that name is not one of them. |
| `Your previous response is not committed because it did not call finalize_turn` | Call finalize_turn now and nothing else, preserving your previous answer word for word as user_message. |

## What a refusal costs you

A refused governed call comes back to you with its reasons. The cost is counted in
rounds, not calls. A round in which one or more calls were refused spends one repair
round. It is charged only after every call in that round has returned.
10 repair rounds come back to you. The next one ends the turn
with nothing shown to the human.
`finalize_turn` has its own separate budget of 2 repairs.
Those numbers and the rest of the turn's limits are `.deepagent/skills/manual-limits/v18/SKILL.md`.
