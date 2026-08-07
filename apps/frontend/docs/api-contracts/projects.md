# Projects, threads, generations, and artifacts API contract

Status: frontend shell ready; proposed backend contract.

Owner for backend integration: Aaryan.

The frontend is fixture-backed until `CLUE_API_BASE_URL` is configured. The
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

- `POST /api/v1/projects` — atomically create a Project, its first Thread, the
  first Message, and optionally a Generation run.
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
