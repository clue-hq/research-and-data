---
schema_version: "1"
kind: skill
name: manual-limits
version: v6
summary: "Manual: the turn's hard numbers. Rounds, supersteps, wall clock, output tokens, the two repair budgets, receipt and read bounds, quotas, retention."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Limits: what bounds one turn of head-of-abm@v59

Every number here is enforced. None of them is advisory, and none of them is visible to
you at run time, so plan the turn against them rather than discovering them.

## The turn

| Limit | Value | What happens at the edge |
| --- | --- | --- |
| Model rounds | 100 | A round is one model call. |
| Graph supersteps | 204 | Two a round plus headroom. This, not any plan ceiling, is what actually stops a chat turn: every governed call you make is its own one-step plan. |
| Wall clock | 1800 s | A hard timeout around the whole turn. Nothing is finalized, so the human sees nothing. |
| Output tokens per call | 8,192 | A longer answer is cut. Say less per round rather than more. |
| Plan nodes | 48 | A proposal over the ceiling is rejected before it runs. |
| Delegations | 6, depth 1 | Whether delegation is installed at all is decided by the surface, not by this number: read your capability map. |
| Estimated spend per plan | 1,000,000 millicents | A ceiling on the estimate, not a running total. You cannot see what has been spent, and must not guess at it. |

## The two repair budgets

| Budget | Value | What the last one does |
| --- | --- | --- |
| Refused governed calls | 3 per turn, shared by every tool | The next refusal is not returned to you: the turn ends and the human sees nothing. Parallel calls each count, so three refusals in one round spend the whole budget. |
| Refused finalizations | 2 per turn, counted separately | The last refusal ends the turn with nothing committed. |

Once the finalize budget is spent the runtime appends: "Nothing was committed and no further finalize attempt will be accepted for this turn."

## What one answer may carry

| Field | Bound |
| --- | --- |
| `user_message` | at most 65,536 characters; the only thing the human reads |
| `assumptions` | at most 64 items; stored as artifacts, never shown to the human |
| `next_actions` | at most 64 items; one line per thing you are waiting for |
| `failure_code` | at most 128 characters; matches `^[a-z0-9_.-]+$`; lowercase, and only on a failed status |

## Bytes

| Bound | Value | Why it bites |
| --- | --- | --- |
| One governed receipt's `reference_values` | 16,384 bytes | Substantive output stays behind references: a tool that would return a lot hands back refs, and you read the file or the row. |
| One read tool's served rows | 12,288 bytes | The reads page themselves to fit. A page that was cut says so, and carries the offset to continue from. |
| Workspace total | 20,971,520 bytes across at most 400 files | The envelope is fixed for the turn, so a write that exceeded it cannot be retried into success. Delete or shorten first. |
| One workspace file | 1,048,576 bytes | Reading a file over the bound is refused too, not truncated. |

## The workspace envelope

- Readable: `.deepagent`, `inputs`, `context`, `scratch`, `reads`, `work`, `outputs`, `brand`, `project`, `attachments`.
- Writable: `scratch`, `work`, `outputs`, `project`.
- Allowed file types: `.json`, `.md`, `.txt`, `.yaml`.
- Retention class: `agent-ephemeral-v1`. The directory belongs to the chat thread, not to one turn. It is purged when the human archives the thread, or 86,400 seconds (`CLUE_AGENT_WORKSPACE_RETENTION_S`) after the thread's newest turn reached a terminal status. A turn still running, or awaiting input, keeps it.

Everything a path means is `.deepagent/skills/manual-workspace/v6/SKILL.md`; the errors these bounds produce are
`.deepagent/skills/manual-errors/v6/SKILL.md`.

