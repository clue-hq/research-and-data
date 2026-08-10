# R0 chat-integration executable contract freeze

Date: 2026-08-10
Branch: `platform/lane-d-chat-launch`

## Scope completed

Documentation-only R0. No frontend/backend/runtime/schema/migration code changed.

- Made `apps/frontend/docs/api-contracts/projects.md` authoritative for the
  2026-08-10 Home/project/chat repair.
- Added exact Home read, atomic project-bootstrap request/response,
  idempotency, permissions, error codes, first-thread title algorithm,
  project/sidebar reads, queued-submission hydration, queue/Stop state,
  finite SSE control/terminal behavior, sidebar layout state, capability
  honesty, and HTTP no-fixture-fallback rules.
- Preserved the earlier frontend proposal as explicitly non-authoritative
  history and kept the 2026-08-08 as-built thread-shell contract underneath the
  new executable section.
- Added the bounded R0 join amendment to the Lane-D charter and demarcation
  registry. Lane D still owns chat turn/queue/stream/Stop; the join owns only
  Home bootstrap, project/sidebar reads, and shared-shell wiring.

## Frozen engineering decisions

- Home `POST /api/v1/projects` is one idempotent transaction producing an
  `Untitled project`, first-message-derived thread title, durable captured
  message/submission, `turn.accepted`, and dispatch intent.
- The accepted queued user message is the existing two-phase capture +
  `agent_turn_submission`; the worker later materializes
  `agent_thread_message`. The turns union gains an explicit bounded
  `include=submission_bodies` hydration for reload-safe queued messages.
- Project creation adds internal `project.write` through a future Lane-B policy
  version bump; it also requires `thread.write`.
- Home never chooses an arbitrary brand. `brand_id` is explicit, with a default
  only when unambiguous or separately persisted.
- `stream.hello` and connect-time `stream.reset` are cursorless but must carry
  schema/type/project/thread/turn identity; `event:` equals JSON `type`; turn
  streams close after terminal and clients finalize on the terminal frame.
- Queued and running make a thread busy; only exactly-running is stoppable.
- Context refs, attachments, and profile selection are hidden until advertised
  and durably implemented. New project Gallery is honestly empty.
- The desktop hamburger owns shell state: hover overlay, click pin/reflow;
  never Home navigation.

## Verification

- `git diff --check` — clean.
- Parsed all 13 JSON code fences in the projects contract with `JSON.parse` —
  all valid.
- Cross-checked the contract against current `chat/schemas.py`, `router.py`,
  `stream.py`, `turn_events.py`, the frontend Zod/event/repository seams, the
  internal permission policy, and the two-phase submission implementation.
- No repository documentation-specific linter is configured.

## Next implementation boundary

R1 may repair the SSE control envelopes and terminal lifecycle. R0 does not
authorize any application code change by itself; each later remediation slice
retains its own implementation and acceptance gate.
