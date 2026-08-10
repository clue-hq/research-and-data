# 2026-08-10 — live frontend chat-flow audit

Scope: read-only live browser walkthrough of the authenticated Home and project-chat
surfaces on `platform/lane-d-chat-launch`. No application source was changed.

## Intended flow confirmed with the founder

1. A Home-composer submission atomically creates a real project, its first thread,
   and its first user turn, then opens that project and immediately starts the main
   platform Deep Agent response. It must not route through fixture project/thread ids
   or require the user to press Send a second time.
2. Inside an existing project, each chat thread is a normal durable conversation with
   the main platform Deep Agent: the user message appears immediately, the assistant
   response streams, durable parts/tools/gates render in order, and a reload rehydrates
   the canonical transcript.
3. `Stop` is visible only while the same-thread model turn is live. A terminal turn
   immediately clears the busy state even if the SSE transport remains connected.
4. The project header hamburger controls the persistent application sidebar. It does
   not navigate Home. On desktop, hover temporarily overlays the expanded sidebar;
   click pins it open and reflows the workspace. Mobile uses the separate drawer.
5. A same-thread submission made during an active turn is durably queued and shown as
   queued; the composer does not silently drop it or block the normal conversation flow.

## Verified live defects

1. **Home bootstrap is fixture-only.** Submitting from Home routes to
   `/projects/10m-landing-page-campaign?...&thread=thread-primary`; it does not create a
   backend project, thread, or turn. The carried prompt is only prefilled. Pressing Send
   then fails with `no such thread in this project`. The live backend exposes thread/turn
   routes but no `POST /api/v1/projects`; the signed-in workspace still had only the
   pre-existing `Chat Demo Project` after the test.
2. **The project shell is hybrid.** A real project id can drive the real chat repository,
   while the page title, workspace payload, Gallery, artifacts, and sidebar project catalog
   remain fixture-backed. This makes a working real chat appear inside a dummy project.
3. **Connect-generated SSE frames violate the frontend envelope.** `stream.hello` omits
   the JSON `type` required by `EnvelopeSchema`; connect-time `stream.reset` omits the
   standard envelope fields as well. The frontend ignores the SSE `event:` name and parses
   only `data:`, producing the visible `malformed turn-stream frame` warning.
4. **Terminal live reconciliation is stuck.** The transcript reducer receives
   `turn.completed` and renders the final answer, but the controller derives `busy` from a
   stale turn-list snapshot. That list refreshes only from `onClosed`; the backend live-tail
   SSE generator stays open after the terminal event, so `Working` and `Stop` remain until a
   reload. Cold reload correctly restores the transcript and clears the stale busy state.
5. **The project hamburger has navigation semantics.** It is labelled `Go to home` and
   calls `router.push("/")`. Project routes do not mount `ApplicationShell`, so the control
   has no shared sidebar state to toggle.

## Scope/ownership note

Lane D/D5 owns the production chat repositories, streaming lifecycle, durable chat UI,
threads, controls, gates, and rehydration. Its ratified scope excluded project
creation/deletion and project Gallery/artifact integration. The Home atomic-bootstrap gap
therefore needs an explicit owner/join slice rather than being silently treated as already
completed by D5.

## Founder-ratified product decisions (2026-08-10)

1. A new project is initially named **`Untitled project`**. Its first thread receives a
   short title based on the user's first message.
2. Same-thread messages submitted during an active turn are durably queued and visibly
   represented as queued.
3. For now, a brand-new project opens an empty Gallery in the right pane. It shows no
   fixture artifacts and no project-overview substitute.
4. On desktop, hovering the hamburger temporarily overlays the main sidebar; clicking it
   pins the sidebar open and reflows the project workspace. Mobile remains a drawer.

## Verification performed

- Authenticated browser submission from Home through the resulting project page.
- Manual second Send to expose the fake project/thread refusal.
- Read-only OpenAPI inspection confirmed no project-create route.
- Read-only Postgres inspection confirmed no new project in the signed-in workspace.
- Earlier real-project turn proved Deep Agent execution, token streaming, durable message
  persistence, and cold-reload rehydration are functional beneath the lifecycle/UI defects.
