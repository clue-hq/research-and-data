# Chat Stop discussion — 2026-09-12

Discussion stage only; do not implement until cancellation scope and the plan are agreed.

User requirements:
- Running turn + empty draft: composer action becomes Stop.
- Running turn + draft: Send remains enabled and queues the new message.
- Match the Gallery tab corner radius (verified 4px; current Send is 999px).
- Stop must preserve context/progress and stop the current design job.
- User asks whether detached account research should stop too; decision pending.

Recommended policy, not yet ratified: chat Stop cancels only the active response and
its associated design work; detached account research continues and gets a separate
run-level Stop action. Never terminate shared worker processes or unrelated jobs.
Sent an optional preference question with this recommendation and the alternative
of also stopping account research launched by the current turn.

Verified current implementation:
- `chat/stream.py` Stop endpoint writes an idempotent request (202), scoped to the
  running turn. `chat/turn_controls.py` explicitly excludes detached research and
  committed tool effects. `agent_turn_fleet_wiring.py` polls at 0.25 seconds by default.
- `chat/turn_stream.py::turn_cancelled` flushes partial emitted text, marks it failed,
  and emits cancelled. It does not finalize a durable assistant body. Do not promise
  that all partial text survives cold reload without implementing/verifying that path.
  Accepted context and committed work remain durable; raw reasoning stays ephemeral.
- `design_fleet.py::InlineDesignLaneDriver` explicitly permits launched design work
  to finish detached after a chat Stop. The synchronous design body can outlive its
  cancelled async wrapper. User's desired design cascade is therefore a real backend gap.
- Design already has `/agent/runs/{run_id}/cancel`, a durable cancellation stamp and
  `CancellationProbe`; next-model-call boundary, not immediate abort of an in-flight
  synchronous provider request. Accepted authoring rounds are checkpointed. Need to
  connect the exact turn's run through the existing seam and verify no auto-redrive.
- ARV2 account driver suspends/requeues on stop/lease-loss. Killing a fleet worker is
  not a durable user Stop. Any future research Stop must cover the chosen run/child
  jobs and prevent requeue/new fan-out without undoing stored research.

Proposed acceptance topics: whitespace-only vs real drafts (attachments/mentions count
as content), queue acceptance and clearing, idempotent Stop/stopping state, completed-turn
races, partial response retention across refresh, linked design cancellation with preserved
document state, and unrelated research/tasks/workspaces left running.

No application code, configuration, server, database or model-call changes this turn.

## Founder decisions and implementation plan — subsequent planning turn

The founder selected:
- Normal cancellation has button states only: enabled Stop -> disabled Stop while
  pending -> default Send after acknowledgement. No visible Stopping/Stopped copy.
- Account/contact research already launched continues after chat Stop.
- Stop cancels associated design work and retains accepted context, committed
  work and durable partial assistant answers.
- Queued messages wait after Stop; add a compact count/Resume bar above the
  composer. No automatic restart of the next queued response.
- Include the missing provider-reasoning adapter repair in the same plan.

Detailed canonical plan added to `apps/frontend/docs/api-contracts/projects.md`
§6A (`#chat-polish-delivery-plan`), with reasoning technical detail in
`apps/frontend/docs/architecture/ai-elements-and-reasoning.md`
(`#provider-reasoning-delivery-repair`). Both explicitly remain proposed; no
implementation authorization is inferred from the request to make this plan.

Plan decisions include an atomic Stop/thread queue hold, exact-turn design
cancellation through the existing design DAL, cancellation/normal-finalization
serialization, durable partial answer history before terminal acknowledgement,
pending-control hydration, scoped idempotent Resume, and unchanged research
fleet lifecycle. Sending while held adds to the waiting FIFO; Resume consumes
no draft. An empty hold clears after acknowledgement under the thread lock.
The existing successful-finalization truth wins only if committed before Stop;
otherwise accepted Stop blocks later successful finalization.

Verified further gaps: stop observation currently depends on a non-null stream
emitter; normal history append and cancellation writes use separate transactions;
the design inline wrapper can leave its synchronous body active; the shared
dispatcher currently has no queue hold. Design scene mode preserves checkpointed
rounds; web mode persists at the end and must retain its prior document on Stop.

Reasoning adapter proposal uses maintained ChatOpenRouter after wire-shape and
governed-wrapper compatibility tests; no dependency installed or upgraded now.
Official LangChain/OpenRouter docs checked for streaming, reasoning blocks and
tool-continuation metadata. Acceptance must prove real trace delivery separately
from durable partial-answer retention. Production trace visibility/retention
remain outside this amendment.

This turn changes planning docs/memory only. No servers, databases, model calls
or application code changed. Final documentation verification/commit recorded
in the closing entry below.

Closing verification: documentation diff/whitespace checks passed; cross-document
anchors and code fences validated; primary implementation/test paths checked.
Reviewed the plan for the normal-finalization/Stop race and made the first durable
authority commit the winner. CP0–CP7 are this amendment's own slice IDs, avoiding
confusion with the older R0–R9 and hardening slices. Application tests were not run
because this turn changes documentation only. Plan/diagnostic notes are grouped
for a local documentation checkpoint; no remote publication or runtime change.
