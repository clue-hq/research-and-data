# Lane D slice D5 — implementation brief: the frontend chat rebuild at the repository seam

**Charter (binding):** `docs/specs/FI-lane-D-production-chat-and-launch.md` §2 (the verified
frontend baseline — every defect listed there is yours to remove), §3-P6, **§3.1 (the AI
Elements map)**, §§3.2–3.6 (the wire contract you consume), the "Frontend contract deltas"
paragraph after P6, slice D5's AC, §5's browser expectation.
**The wire truth:** the founder-ratified **"As-built thread-shell contract"** section at the end
of `apps/frontend/docs/api-contracts/projects.md` — where it conflicts with the older proposal
text above it, the as-built section wins. The SSE contract is charter §§3.2–3.3 as implemented
by D3 (`platform/api/clue_api/chat/turn_stream.py`, `turn_events.py`, `turn_controls.py` —
read the implementations; they are the source of truth for event shapes, the stream-token mint,
`Last-Event-ID`, and stop/retry).
**Identity:** Lane B's B3 session layer is in-tree and REAL (`apps/frontend/src/auth/**`,
`apps/frontend/src/app/api/clue/**` BFF, provider wrapping). You consume it; you never build
auth UI. Read `_memory/2026-08-09-bd-join-verdict.md` for what the backend now guarantees.
**Design intent:** `apps/frontend/docs/figma/projects-chat-flow.md` (the research-execution
component library, :39–99) and `apps/frontend/docs/architecture/frontend.md` (the repository
seam doctrine). Frontend toolchain gate: `npm run design-system:build && npm run lint &&
npm run build` (run inside `apps/frontend/`).

## Mission

Replace the fixture facade with the real thing: the projects/chat feature talks to the D0–D4
backend through typed repositories with fixture + HTTP + stream adapters, renders genuine
token streaming and typed parts through the §3.1 adapters, drives the gate card from the
durable gate object, implements the Figma research-execution components, and deletes every
client-side manufacture the charter §2 catalogued.

## Deliverables

### 1. Tear-out (charter §2's defect list, removed)

Delete `build-project-messages.ts` (the 6-value phase-enum transcript manufacture) and every
consumer of its manufactured shape; the fixture-authored `previewTimeline`/`reasoningTrace`
timer blobs leave the validated payload; the hardcoded plan-approval card dies (replaced by the
gate part); the sidebar's repository bypass (fixture imported directly in the hook) is fixed;
thread switching stops being cosmetic. `submitMessage()` becomes a real turn submission.

### 2. Model layer (Zod) — the ratified deltas

Amend `src/features/projects/model/**` per the charter's "Frontend contract deltas" paragraph
and the as-built contract: parts with stable ids + revisions; messages with
`threadId`/`turnId`/`createdAt`/typed `refs[]` (the six-flavor closed vocabulary); `plan`/
`sources` as payload-carrying message-scoped parts; `agent_activity` first-class; tool parts
with `toolName`/`toolCallId`/structured input/output/error + the seven AI Elements states; the
`task` part with the §3.4 semantic states + counts; the `gate` part carrying the durable
confirmation snapshot incl. `{amount_cents, currency}` (client formats — D-5 rule); credits as
numbers; `text`/`parts` tolerating streaming-start emptiness; the D-4 absence vocabulary
(nullable/optional per the accounts-flow precedent in `features/accounts/model` — read for
house style, NEVER edit). Thread status enum = the pinned precedence vocabulary
(`archived > approval > needs-input > running > idle`).

### 3. Data layer — repositories with three adapters

Repositories (interfaces + fixture + HTTP adapters, per `frontend.md`'s seam): threads
(paginated list/create/rename/pin/archive per the as-built contract), messages (paginated,
body-free + `?include=bodies` hydration), turns (`POST …/turns` with `{message}` |
`gate_response`, idempotency identity, `202 {turn_id}`; stop/retry via D3's control routes),
and the **stream repository** — the one place Clue SSE events become ordered message parts:
mint the stream token through the authenticated BFF (Lane B §5.5; D3 built the mint — follow
its shape exactly), attach by cursor, `Last-Event-ID` reconnect, dedup by `event_id`,
part-snapshot replacement semantics, `text.delta` accumulation per attempt,
`stream.reset` → refetch canonical + reattach (§3.6). All HTTP rides the same-origin BFF
(`app/api/clue/**`) — add project-chat BFF routes following Lane B's existing pattern; never
call FastAPI cross-origin from the browser; never touch a provider token. The projects flow
gets **its own** env flag for fixtures→HTTP (the contract doc requires it; name it consistently
with the accounts flow's pattern and record the name in your report). Fixtures update to the
new schemas and stay the default when the flag is unset.

### 4. Presentation — the §3.1 adapters + Figma components

Clue-owned adapters map domain parts to the vendored primitives in
`src/components/ai-elements` exactly per the §3.1 table (text → `MessageResponse`/
`MessageMarkdown` incremental Markdown — no raw syntax flashes or flicker; `Shimmer` derived
from active part state, never a wire value; `ChainOfThought` = safe structured activity only).
The **gate card** renders requested/responded/denied from the gate part; Approve/Reject/Revise
submit the structured `gate_response` turn; answered gates persist in history with disabled
controls and the recorded decision. The **research-execution components** per the Figma doc:
the 8 activity states, ONE visible task per run aggregating N accounts (counts, expandable
steps, exceptions), covering `partial`/`needs_input`/`suspended`; progression strictly
event-driven — no timers as lifecycle. Composer stays usable during detached work; a queued
turn is visibly queued (the submissions-union serves it); Stop/Retry per §3.5 semantics.
Cold load = paginated messages (+bodies) + current projections, then live attach (§3.6) —
reload mid-stream must rehydrate to a consistent transcript.

### 5. Session integration (consume, don't build)

Screens live under Lane B's protected shell; repositories obtain auth through Lane B's
server/BFF helpers (`src/auth/**`). Session-expiry and `WORKSPACE_FORBIDDEN`/`PERMISSION_DENIED`
map to the access states Lane B's contract §6 defines — never to empty transcripts. You never
edit `src/auth/**`, `app/(auth)`, provider wrapping, or `package.json`'s auth dependency.

## Acceptance criteria (charter slice D5)

With the flag on against the local stack: a turn streams live — tokenized final message +
tool/activity parts — into the transcript; the approval card round-trips a gate (approve path
reaches the launch narration task part; reject leaves the recorded decision); cold reload
rehydrates transcript/gate/task state; thread CRUD + switching + status precedence work over
HTTP; no phase-enum manufacture remains (grep-proof it). Component/adapter tests: the stream
adapter against synthetic SSE streams conforming to D3's event schema (incl. reconnect-replay,
duplicate delivery, `part.updated` replacement, `stream.reset`, attempt isolation — mirror the
§5 streaming cases at the consumer end); schema round-trips for every amended model; gate-card
state machine; task aggregation. Toolchain gate green (`design-system:build && lint && build`)
plus the feature's unit tests. **Browser verification:** if a full local stack (projections app
+ fleet worker + dev auth + model key) is runnable in your environment, drive the canonical
two-account fixture in a real browser and report what you saw; if any piece is unavailable
(e.g. no model key), deliver everything else, STOP short of faking it, and hand the manual
browser pass back to the orchestrator as an explicit open item — never simulate results.

## Hard exclusions

`apps/frontend/src/features/accounts/**` and `api-contracts/accounts.md` (FI-2's);
`src/auth/**`, `app/(auth)/**`, provider/session internals, auth deps (Lane B's — consume
only); `api-contracts/projects.md` (report deviations; the orchestrator records them);
ALL backend Python (if the backend needs a change — a missing read, a CORS/BFF gap — STOP and
report; do not edit the platform); no new runtime dependency on Vercel AI SDK (`useChat` etc.)
— AI Elements stay vendored presentation (§3.1's explicit ruling).

## Process

Test-first where practical; commit locally at coherent checkpoints by explicit path; NEVER
push; no AI attribution. The backend tree is quiet (no parallel agents this round) but touch
only `apps/frontend/**` regardless. Honor every STOP above. Finish with a `_memory/` entry and
a full report: files, the env-flag name, the stream-adapter design, every contract deviation
found while integrating (exact list for founder review), test + toolchain results, what the
browser pass covered or why it's handed back, open items.
