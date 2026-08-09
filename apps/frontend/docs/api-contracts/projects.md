# Projects, threads, generations, and artifacts API contract

Status: frontend shell ready; proposed backend contract.

Owner for backend integration: Aaryan.

The frontend is fixture-backed, and **pinned** there until phase 2: no backend
serves these endpoints yet, so the projects repositories deliberately read no
environment variable at all (they used to flip on `CLUE_API_BASE_URL`, which
meant configuring the accounts flow broke the home and project routes). When
this contract is implemented, these repositories get their own variable. The
fixture and HTTP adapters both validate responses with the schemas under
`src/features/projects/model/project-workspace.ts`. Presentation components do
not call the API directly.

## Ownership model

```text
Project
├── Thread
│   ├── Message
│   └── Generation run
└── Artifact
    ├── originThreadId
    └── originRunId
```

A Home submission creates a Project and its first Thread atomically. Messages
and generation runs belong to a Thread. Artifacts belong to the Project, so
they stay visible in the Gallery when the user changes threads. Origin IDs keep
every output traceable to the request and run that produced it.

### Ratified first-interaction behavior (2026-08-10)

- The Home submission creates the project with the initial title **`Untitled
  project`**. Its first thread receives a short title derived from the user's
  first message; it is not called `New chat` unless no usable message is
  available.
- Creation is one user action: the project, first thread, first user message,
  and first platform-Deep-Agent turn are accepted atomically. The frontend then
  opens that real thread and begins rendering the response without requiring a
  second Send.
- A new project with no artifacts opens on **Gallery** with an explicit empty
  state. It never borrows fixture artifacts or another project's outputs.
- If a same-thread model turn is active, later user submissions are durably
  accepted in order and shown as **queued**. The composer does not silently
  discard them or disable the product's conversation flow.
- On desktop, hovering the project-header hamburger temporarily overlays the
  expanded main sidebar without resizing the project workspace. Clicking the
  hamburger pins the sidebar open and reflows the workspace; clicking again
  returns it to the collapsed state. Mobile keeps the separate drawer behavior.

## Read endpoints

### `GET /api/v1/projects/sidebar`

Returns the compact project/thread hierarchy used by the persistent product
sidebar. It is intentionally smaller than the complete Project workspace
resource so account, contact, and Home routes do not fetch artifact payloads.

```json
{
  "data": [
    {
      "id": "10m-landing-page-campaign",
      "title": "10x revenue campaign",
      "href": "/projects/10m-landing-page-campaign",
      "expanded": true,
      "pinned": true,
      "conversations": [
        {
          "id": "thread-primary",
          "title": "Landing page concepts",
          "href": "/projects/10m-landing-page-campaign?thread=thread-primary",
          "status": "idle"
        }
      ]
    }
  ],
  "meta": { "total": 1 }
}
```

Conversation status is one of `idle`, `running`, `review`, `approval`, or
`needs-input`. These values express workflow meaning; the frontend owns their
icons, badge copy, and colors. `expanded` is an initial preference only—the
current frontend shell keeps expand/collapse state locally until user
preferences are connected.

### `GET /api/v1/home`

Returns the Home composer configuration, selectable account/contact entities,
available models, and three recommendation prompts. The Home response no longer
contains a project collection; Projects are intentionally absent from this
surface.

File attachments are browser-owned draft state until submission. The eventual
`POST /api/v1/projects` request should use `multipart/form-data` when files are
present and send the prompt, model ID, entity IDs, and attachments together.
The draft view model follows AI SDK `FileUIPart` fields (`type`, `mediaType`,
`filename`, and `url`) plus frontend-only `id` and upload `status` fields. Blob
URLs are preview-only and must never be sent as backend file identifiers.

### `GET /api/v1/projects/:projectId`

Returns the complete project shell:

```json
{
  "id": "10m-landing-page-campaign",
  "title": "10m+ landing page campaign",
  "prompt": "design a landing page",
  "defaultModelId": "gpt-5.5",
  "models": [],
  "contextEntities": [
    {
      "id": "openai",
      "label": "OpenAI",
      "type": "account",
      "imagePath": "/logos/openai.svg",
      "secondaryLabel": "www.openai.com"
    }
  ],
  "threads": [
    { "id": "thread-primary", "title": "ad design" }
  ],
  "generationSteps": [],
  "artifacts": [
    {
      "id": "landing-page-sharper-abm",
      "title": "Landing page sharper ABM - OpenAI",
      "type": "website",
      "imagePath": "/projects/gallery/abm-anthropic-light.png",
      "editedLabel": "Last edited today",
      "originThreadId": "thread-primary",
      "originRunId": "run-abm-001"
    }
  ]
}
```

Valid artifact types are `table`, `website`, `canvas`, and `presentation`.

The current project response also includes `conversationActivity.tools` and
`conversationActivity.sources`. These fixture-backed records supply tool names,
parameters, results, and external evidence to the typed message adapter. They
must be backend-owned in production; presentation components do not create
them.

`contextEntities` is the searchable account/contact catalog available to the
project composer. Selected entities are atomic inline references in the prompt
editor, but they remain ordered structured IDs in draft state; the visible logo,
avatar, and label are presentation only. The message endpoint should accept
`contextEntityIds: string[]` alongside the plain prompt so Aaryan can resolve
fresh CRM context without parsing visible mention text.

Messages render as ordered, validated parts. The current frontend contract
supports `text`, `reasoning`, `action`, `tool`, `plan`, `task`, and `sources`
parts. Each part requires a stable ID so streamed updates can replace a part in
place rather than append duplicate status UI.

## Write endpoints

- `POST /api/v1/projects` — atomically create an `Untitled project`, its first
  Thread (short title derived from the first user message), the first Message,
  and the first platform-Deep-Agent turn. Return the real project/thread/turn
  identities needed to open the conversation and stream immediately.
- `POST /api/v1/projects/:projectId/threads` — create another thread inside the
  existing Project.
- `PATCH /api/v1/projects/:projectId` — rename the project or update its pinned
  state from the sidebar.
- `DELETE /api/v1/projects/:projectId` — remove the project after confirmation.
- `POST /api/v1/projects/:projectId/threads/archive` — archive the project's
  visible chat history without deleting its artifacts.
- `POST /api/v1/projects/:projectId/threads/:threadId/messages` — append a user
  or assistant message. User messages may include `contextEntityIds` alongside
  the text and file attachments.
- `POST /api/v1/projects/:projectId/runs` — start artifact generation from a
  message and return the run ID.
- `GET /api/v1/projects/:projectId/runs/:runId` — return generation state and
  step progress. This can become an SSE endpoint without changing the UI.
- `GET /api/v1/projects/:projectId/artifacts` — list the project Gallery,
  independent of the active thread.
- `PATCH /api/v1/projects/:projectId/artifacts/:artifactId` — update artifact
  metadata or editable canvas content.
- `PATCH /api/v1/projects/:projectId/artifacts/:artifactId/nodes/:nodeId` —
  update the selected canvas node properties shown by the inspector.

### Sidebar mutation payloads

The sidebar currently performs these mutations through its fixture controller.
The HTTP implementation should preserve the same response shapes so the
presentation tree can switch repositories without changing its components.

Create a thread:

```http
POST /api/v1/projects/:projectId/threads
Content-Type: application/json

{ "title": "New chat" }
```

Return `201` with the created sidebar conversation:

```json
{
  "data": {
    "id": "thread_01J...",
    "title": "New chat",
    "href": "/projects/project_01J...?thread=thread_01J...",
    "status": "idle"
  }
}
```

Rename or pin a project:

```http
PATCH /api/v1/projects/:projectId
Content-Type: application/json

{ "title": "Enterprise account research", "pinned": true }
```

Both fields are optional, but at least one must be present. Return `200` with
the updated project summary using the `SidebarProjectSchema` fields.

Archive visible chat history:

```http
POST /api/v1/projects/:projectId/threads/archive
Content-Type: application/json

{}
```

Return `202` when archival is asynchronous or `204` when it is complete.
Artifacts, artifact versions, account context, and run lineage must remain
attached to the Project. Archiving chat history is not project deletion.

Remove a project:

```http
DELETE /api/v1/projects/:projectId
```

Return `204` after the backend applies the agreed retention policy. The
frontend requires an explicit confirmation before calling this endpoint.

Mutation failures use the shared error envelope and must include a stable
`requestId`. Return `404` for an unknown project, `409` for a stale or invalid
state transition, and `422` for schema validation errors.

The current inspector shell exercises text `color`, `fontFamily`, `fontSize`,
`fontWeight`, and `textAlign`; button `label`; and image `fit`, `radius`, and
replacement-file fields. The frontend keeps these edits local until the node
PATCH endpoint is connected.

## Frontend-only preview state

The `thread`, `phase`, `prompt`, `model`, and comma-separated `entities` query
parameters exist so approved
Figma states can be opened directly. Valid phases are `conversation`,
`questionnaire`, `agent-running`, `planning`, `generating`, and `complete`.
Preview transition timing and progress milestones live in the fixture-backed
`previewTimeline` field rather than presentation components. They demonstrate
interaction and motion only; replace them with the generation-run resource when
the backend is connected.

---

## As-built thread-shell contract — founder-ratified 2026-08-08 (Lane D D0–D2)

**This section is authoritative where it conflicts with the proposal above.** It records the
founder's ratification of the nine as-built deviations from Lane D slice D0 (the durable thread
shell) plus the D2 turn-submission contract. Owner: Lane D
(`docs/specs/FI-lane-D-production-chat-and-launch.md`); implementation in
`platform/api/clue_api/chat/` behind `CLUE_CHAT_ENABLED` (default off).

1. **Rename/pin are per-thread.** `PATCH /api/v1/projects/:projectId/threads/:threadId`
   `{title?, pinned?}` → `200` with the updated thread. The proposal's
   `PATCH /projects/:projectId` (project rename/pin) mutates the project table, which is outside
   the chat shell's ownership; it stays unimplemented here.
2. **Archive is per-thread.** `POST …/threads/:threadId/archive` → `200` with the updated
   thread. Archive is a reversible status flip, so the response says what happened; the
   proposal's bulk archive-all endpoint does not exist.
3. **`GET /api/v1/projects/:projectId/threads`** — first-class paginated thread list
   (the embedded sidebar payloads remain for composite views).
4. **Cursor pagination everywhere.** List endpoints take `?limit`/`?cursor`; responses carry
   `meta.next_cursor`. Cursors are keyset (stable under concurrent inserts), backed by
   composite indexes.
5. **Thread `status` is `idle | archived` today.** The proposal's richer vocabulary
   (`running | review | approval | needs-input`) is *derived* state — latest turn status + open
   gates — and lights up with slices D3/D4. Single change point:
   `platform/api/clue_api/chat/schemas.py::thread_status`.
6. **Create returns `201` with a superset:** `{id, title, href, status, pinned, project_id,
   created_at, updated_at}`.
7. **`title` is optional on create** (an unnamed thread is `title: null`); a blank/whitespace
   title is refused.
8. **Message reads are body-free.** The paginated message list returns role, sequence,
   `body_artifact_key`, `body_sha256`, and typed `refs[]` (closed flavor vocabulary:
   `attachment, output, open_gate, next_action, assumption, workspace_output`). Bodies hydrate
   through the D3 rehydration read and stream live via SSE — never inline in list responses.
9. **Not implemented in the thread shell (deliberate):** `POST /projects`,
   `DELETE /projects/:projectId` (project lifecycle — phase-2 / separate owner), the proposal's
   `POST …/threads/:threadId/messages` (**superseded** by the turn endpoint below), and the
   runs/artifacts endpoints (phase-2, gated on the design-integration branch merge).

**The turn endpoint (D2, replaces `POST …/messages`):**
`POST /api/v1/projects/:projectId/threads/:threadId/turns` accepts exactly one of an ordinary
`{message}` or (from D4) a structured `gate_response`; plus idempotency identity. It persists the
user message + an immutable `agent_turn_submission` receipt (real authenticated principal
identity; never client-supplied `actor_id`/`action_ref`) **before** enqueueing detached
execution, and returns `202 {data:{turn_id}}`. Duplicate submission under one idempotency
identity returns the same turn. A queued-not-yet-executing turn is visible as a submission;
read surfaces union submissions with turn events (founder-acked two-phase turn identity,
2026-08-08). Streaming/live transcript arrives via the D3 SSE contract
(charter §§3.1–3.6); `GET …/runs/:runId` polling in the proposal is superseded by that stream
for chat-visible progress.
