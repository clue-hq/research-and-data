# Projects, threads, generations, and artifacts API contract

Status: **R0 ratified; repair slices R1-R9 implemented. Later slices remain pending where noted.**

Owner for backend integration: Aaryan.

The durable thread/turn/gate/stream surface, atomic Home bootstrap, complete
project workspace read, and tenant-scoped sidebar catalog are implemented.
In HTTP mode those repositories all use authenticated backend data and never
fall back to fixtures. Artifact integration is not yet available, so a real
project deliberately returns and renders an empty Gallery.

Authority order inside this document is:

1. **Executable integration contract (2026-08-10)** below.
2. **As-built thread-shell contract (2026-08-08)** for endpoints the executable
   section does not amend.
3. Earlier read/write/preview proposals, retained only as design history.

When `CLUE_PROJECTS_API_BASE_URL` is configured, every projects repository must
use the same-origin authenticated BFF and validate the corresponding wire
schema. HTTP mode never falls back to fixtures after a refusal, parse error, or
network failure. Presentation components do not call the API directly.

### R3 implementation status (2026-08-10)

- `GET /api/v1/projects/{project_id}` returns the real tenant-scoped project
  shell, honest composer capabilities, and `artifacts: []` until artifact
  integration lands.
- `GET /api/v1/projects/sidebar` returns real tenant-scoped projects and their
  thread summaries through a batch-hydrated projection. Busy and gate status
  are resolved in batches; the endpoint does not fetch each project's threads
  separately.
- The frontend project and sidebar repositories validate these wire payloads.
  HTTP mode neither combines them with fixture records nor accepts fixture URL
  parameters for model, phase, prompt, or context.
- Project rename, pin, delete, and other unsupported project mutations are
  hidden in HTTP mode. Fixture preview mode keeps its local-only controls.
- The project-header hover/click sidebar interaction is intentionally outside
  R3 and remains a later repair slice; this read slice does not claim it.

### R4 implementation status (2026-08-10)

- R4 reuses the atomic Home endpoints implemented in R2; it does not add a
  second project-creation API. Home read, bootstrap request, bootstrap response,
  and refusal envelopes are validated at the frontend repository seam.
- One exact Home draft has at most one request in flight. An unchanged failed
  draft reuses its idempotency key, while editing the message or brand rotates
  that retry identity. A different draft is not disabled by an older request.
- A successful latest submission clears only the submitted draft and navigates
  using only the backend-returned `href`. Network completion order cannot
  navigate an older concurrent draft over a newer one.
- A thread query is resolved only against the real tenant/project-scoped thread
  page. A mismatched thread is never read; the route selects an allowed thread
  and replaces the query with its canonical id, or renders a controlled
  unavailable state when the project has no allowed thread.

### R5 implementation status (2026-08-10)

- The frontend derives three separate values from the effective durable turn
  page: `threadBusy`, the exactly-`running` turn, and queued turns in submission
  order. Stop renders and posts only for the running turn; a queued-only thread
  remains visibly busy without presenting Stop.
- Stream lifecycle transitions temporarily override a stale turn-list response.
  The override is discarded when the canonical read reaches the same or a later
  terminal state, so a delayed `running` response cannot resurrect Stop after a
  terminal frame.
- One exact message request may be in flight only once, while a different
  message remains submittable. This duplicate-click guard does not disable the
  conversation composer while the thread is busy.
- The Stop endpoint now derives the target state from the same submissions-union
  projection used by `GET …/turns`. A new Stop request for a queued or terminal
  turn returns `409 TURN_NOT_RUNNING`; an already-recorded Stop remains an
  idempotent replay.
- Three-turn database acceptance proves A running with B/C queued, Stop A,
  B then C dispatch in order, and the same A/B/C state reconstructs through the
  cold turn-list route during B.

### R6 implementation status (2026-08-10)

- The protected route layout owns one persistent application shell for Home,
  the project catalog, and project workspaces. Those screens no longer mount
  independent sidebars; account routes retain their separately-owned existing
  shell until their lane is joined.
- The desktop project-workspace control implements the ratified
  `collapsed | hover-preview | pinned-expanded` state table. Hover/focus opens
  an overlay without changing content width, click pins and reflows, click while
  pinned collapses, delayed pointer/focus departure dismisses preview, and
  Escape closes preview and restores focus to the trigger.
- The project-header control is a real button with `aria-controls`, truthful
  `aria-expanded` and action labels. It never navigates Home and never exposes
  the former misleading `Go to home` label. Mobile keeps the modal drawer.
- The one mounted sidebar controller re-reads the real tenant-scoped catalog on
  pathname changes. A project created by Home is therefore present after the
  client-side navigation without a full browser restart or fixture fallback.

### R7 implementation status (2026-08-10)

- The real project workspace model contains only durable project metadata,
  advertised composer capabilities, and the exact pre-integration
  `artifacts: []` contract. Fixture-only plan, questionnaire, prompt, phase,
  model, agent-profile, and context-catalog fields are no longer accepted as
  project shell state.
- The project workspace always renders the designed empty Gallery while no
  artifact read contract exists. Fixture cards, artifact-editor controls,
  Target accounts, plan, and questionnaire surfaces are unreachable from the
  project route in both HTTP and fixture transport modes.
- Configuring `CLUE_PROJECTS_API_BASE_URL` selects the HTTP project, Home, and
  sidebar adapters as one set. A backend refusal or network failure remains an
  error state; none can recover through fixture project metadata or artifacts.
- Guessed artifact-detail URLs return not found until a real project-artifact
  read is separately contracted and integrated.

### R8 implementation status (2026-08-10)

- Home and project reads advertise a real, workspace-scoped account/contact
  catalog from Lane C. Ordinary messages and atomic Home bootstrap accept those
  references in user-authored order, validate ownership/current revision and
  applicable contact/account relationships, then persist immutable receipts on
  the submission.
- The fleet worker rehydrates the receipts into `AgentTurnRequest.focus_refs`.
  L5 context assembly retains the submitted ordering, and durable transcript
  reads project the same ordered references back onto the user message after a
  reload.
- The composer keeps one visible model selector, as explicitly ruled for R8.
  Its only option is the server-advertised promoted profile
  `head-of-abm@v23`, labelled **GPT-5.6 Terra** and backed by
  `openai/gpt-5.6-terra`. The chosen profile id is accepted, persisted, and
  checked by the detached worker before the promoted profile is executed.
- Attachments remain unavailable because this deployment has no durable upload
  receipt endpoint. Both Home and project reads advertise `attachments=false`,
  the frontend hides the control in HTTP mode, and the backend refuses any
  attempted attachment receipt instead of accepting a browser-local URL.

### R9 implementation status (2026-08-10)

- L7 context assembly treats the accepted submission body as the one current
  user instruction and places it last. Capture receipts and attachment
  metadata are system context; queued turns cannot inherit a prior turn's
  prompt as the model-facing instruction.
- A user-requested Stop records a durable `cancelled` journal state after the
  worker has stopped. The submissions-union read reconstructs that terminal
  state after reload, and terminal rendering closes any still-active reasoning
  or activity rows instead of leaving `Thinking` visible.
- `GET …/turns?include=submission_bodies` projects a workspace-scoped
  `submission_message` only until that turn's canonical user message exists.
  Home and ordinary submissions therefore show the exact accepted text before
  the detached worker materializes thread history, without rendering it twice.
- Stream transitions update the selected thread summary immediately. Terminal
  reconciliation refreshes messages, turns, threads, and the shared sidebar
  catalog, so `running` and newly-created project summaries do not wait for a
  browser reload.
- The desktop sidebar trigger remains above its hover overlay, so pointer click
  can pin the preview. Enter and Space invoke the same pin/collapse transition;
  Escape still dismisses an unpinned preview.

### Post-R9 storage-lifecycle repair (2026-08-10)

- A durable artifact row whose physical blob is gone is a per-message
  `artifact_missing` state. The thread read remains `200`, preserves every
  readable message, and tells the user to resend in a new chat; it never
  invents bytes from a title, label, log, digest, or adjacent prompt.
- A wider storage backend failure is `503 ARTIFACT_STORAGE_UNAVAILABLE`, not
  `artifact_missing` and not a generic internal error.
- If the missing blob is required current/history input, the worker records
  terminal failure code `required_context_artifact_missing`, emits
  `turn.failed`, does not invoke the model with incomplete context, marks the
  fleet task failed, and dispatches the next accepted turn.
- Local API and worker processes that share a database must also share one
  explicit persistent artifact root. Both report the normalized root at
  startup; database clones cannot be reused independently of their blobs.

### Pilot budget-controls — gate amount is optional (2026-08-11)

- The gate amount is **optional on every human-visible surface**. With the
  deployment switch `CLUE_BUDGET_CONTROLS_ENABLED` off (the pilot posture,
  `docs/specs/FI-pilot-budget-controls.md`), `GET …/threads/:threadId/gates`
  serves `max_spend_cents: null` and the rich `gate` stream part omits
  `amount_cents` and `currency`. The amount is withheld, not missing: it stays
  on the immutable gate row for audit and integrity.
- Null rather than `"0"` or `""`, deliberately — a withheld amount must never be
  readable as a real one. The frontend schema accepts null/absent and the
  approval card renders **no cost row at all**: no `$0.00`, no empty currency,
  no dash standing in for a number nobody may see.
- The amount does not gate answerability. `expected_subject_sha256` is the one
  field that makes a card answerable in both postures; a card missing only the
  amount stays clickable.
- The answer still sends `expected_estimated_cost_cents` (the field is required
  by `GateResponseRequest` and no tool/route schema changed), but with controls
  off the server does **not** validate it — `GATE_AMOUNT_STALE` is unreachable
  in that mode. The `expected_subject_sha256` digest check remains armed in both
  modes and is the load-bearing stale-approval guard. When the amount was
  withheld the client sends `0` purely as the courier value.

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

## Executable integration contract — founder-ratified 2026-08-10 (R0)

**This section is authoritative over every earlier proposal in this file.** It
defines the target for the frontend/backend repair slices. Existing endpoints
remain authoritative where this section explicitly says "as built"; every
other item is an implementation obligation, not a claim that the route exists.

### 1. Wire, authority, and error conventions

- API JSON uses `snake_case`. Frontend Zod adapters map it once to camel-case
  view models; components never parse or reshape transport payloads.
- Request bodies reject unknown keys. A misspelled or unsupported field is a
  `422 VALIDATION_ERROR`, never a silent no-op.
- The browser calls the origin-relative BFF prefix (normally `/api/clue`). The
  BFF supplies the authenticated session and selected workspace. Browser bodies
  never contain `workspace_id`, `user_id`, `membership_id`, `actor_id`,
  `action_ref`, provider tokens, or provider identity claims.
- Every route re-checks its permission and scopes every read/write by the
  authenticated workspace. A foreign project, thread, brand, turn, context
  object, or attachment returns a scoped `404`; the response does not reveal
  whether that object exists elsewhere.
- Project creation requires the new internal permission `project.write` plus
  `thread.write`. `operator`, `admin`, and `owner` receive `project.write`;
  `viewer` does not. Adding it requires an explicit Lane-B policy-version bump.
- All non-2xx JSON responses use the existing envelope and request header:

```json
{
  "error": {
    "code": "STABLE_MACHINE_CODE",
    "message": "Safe user-facing explanation",
    "requestId": "request-correlation-id"
  }
}
```

The response also carries `X-Request-Id`. Raw provider errors, tool arguments,
private reasoning, stack traces, and prompt bodies never appear in this
envelope.

The stable errors this integration branches on are:

| HTTP | `error.code` | Meaning |
|---|---|---|
| 400 | `IDEMPOTENCY_KEY_REQUIRED` | A required write omitted a usable idempotency header. |
| 401 | `AUTHENTICATION_REQUIRED` / `SESSION_INVALID` | No valid authenticated session. |
| 403 | `WORKSPACE_FORBIDDEN` / `PERMISSION_DENIED` / `MEMBERSHIP_STATE_CHANGED` | The internal principal cannot act in the selected workspace. |
| 404 | `BRAND_NOT_FOUND` / `PROJECT_NOT_FOUND` / `THREAD_NOT_FOUND` / `TURN_NOT_FOUND` / `CONTEXT_REF_NOT_FOUND` / `ATTACHMENT_NOT_FOUND` / `AGENT_PROFILE_NOT_FOUND` | The scoped object cannot be used; foreign-object existence is not disclosed. |
| 409 | `IDEMPOTENCY_CONFLICT` / `CAPABILITY_UNAVAILABLE` / `THREAD_ARCHIVED` / `TURN_NOT_RUNNING` / `GATE_ALREADY_ANSWERED` / `GATE_SUBJECT_STALE` / `GATE_AMOUNT_STALE` | The request is valid JSON but conflicts with durable state or advertised capability. |
| 422 | `VALIDATION_ERROR` / `INVALID_CURSOR` | The request shape, value, or pagination cursor is invalid. |
| 500 | `INTERNAL_ERROR` | An unexpected server failure; details stay in correlated logs. |
| 503 | `BODIES_UNAVAILABLE` | This deployment cannot hydrate transcript bodies. |

Unknown future codes remain displayable through their safe `message`, but the
frontend only branches behavior on codes it knows.

### 2. Home read

`GET /api/v1/home` returns the authenticated workspace's configuration for a
new conversation. It returns no suggested project/thread ids and creates
nothing. It requires `project.read`.

```json
{
  "data": {
    "brands": [
      { "id": "brand_01J...", "name": "Clue Demo Brand" }
    ],
    "default_brand_id": "brand_01J...",
    "context_entities": [
      {
        "object_type": "account",
        "object_id": "de305d54-75b4-431b-adb2-eb6b9e546014",
        "label": "Northstar Labs",
        "secondary_label": "northstar.example",
        "image_url": null,
        "version": null
      }
    ],
    "agent_profiles": [
      {
        "id": "head-of-abm@v23",
        "label": "GPT-5.6 Terra",
        "short_label": "GPT-5.6 Terra",
        "description": "Clue's governed GPT-5.6 Terra conversation profile",
        "model_id": "openai/gpt-5.6-terra"
      }
    ],
    "default_agent_profile_id": "head-of-abm@v23",
    "composer_capabilities": {
      "context_refs": true,
      "attachments": false,
      "agent_profile_selection": true
    },
    "suggestions": [
      "Find target accounts for our new campaign"
    ]
  }
}
```

Contract rules:

- `brands` contains only active brands in the selected workspace.
- `default_brand_id` is non-null only when exactly one brand is usable or a
  separately persisted workspace preference names a usable brand. The backend
  never chooses the first row or a lexicographically convenient brand.
- When multiple brands exist and there is no valid default, the frontend must
  obtain a real brand selection before project creation.
- `suggestions` contains zero to three plain-text suggestions. They are not
  project identities or commands.
- A composer control is interactive only when its capability is `true`.
  Unsupported attachment/model/context controls are hidden or explicitly
  disabled; the frontend cannot simulate success.
- When `agent_profile_selection` is false, `agent_profiles` is empty,
  `default_agent_profile_id` is null, and the backend uses its governed default.
- This deployment intentionally advertises one selectable profile. Per the R8
  product ruling, the selector remains visible with exactly the one real
  **GPT-5.6 Terra** option; it is not a decorative multi-model menu.
- When `context_refs` is false, `context_entities` is empty. When it becomes
  true, each entry has the exact `object_type`, `object_id`, `label`,
  `secondary_label`, and nullable `image_url` shape shown in §3's reference
  semantics; the account/contact source remains Lane C's real read layer.

### 3. Atomic Home bootstrap

`POST /api/v1/projects` is the only Home submission route. It requires a
non-blank `Idempotency-Key` header, `project.write`, and `thread.write`, and
accepts:

```json
{
  "brand_id": "brand_01J...",
  "message": "Start an ABM project for Northstar Labs",
  "context_refs": [
    {
      "object_type": "account",
      "object_id": "de305d54-75b4-431b-adb2-eb6b9e546014",
      "version": null
    }
  ],
  "attachment_refs": [],
  "agent_profile_id": "head-of-abm@v23"
}
```

Field rules:

- `brand_id` is required and must name an active brand in the authenticated
  workspace.
- `message` is 1–32,000 characters and must contain non-whitespace text.
- `context_refs` is ordered. The server supplies workspace scope, validates
  each `object_type`/`object_id`/optional positive `version`, and persists the
  same order with the accepted submission. When enabled, one entry is
  `{ "object_type": "account", "object_id": "acct_01J...", "version": null }`;
  `object_type` is exactly `account | contact` for this composer.
- `attachment_refs` is ordered and may contain only durable, workspace-scoped
  upload receipts: `artifact_key`, 64-character lowercase `sha256`,
  `media_type`, `byte_count`, and `filename`. Browser blob URLs and local paths
  are structurally forbidden.
- `agent_profile_id` is allowed only when `GET /home` advertised it and
  `agent_profile_selection=true`.
- `context_refs` and `attachment_refs` default to `[]` when omitted;
  `agent_profile_id` defaults to null.
- A non-empty optional capability field sent while its capability is false is
  refused with `409 CAPABILITY_UNAVAILABLE`.
- The client cannot supply the project id, project title, thread id, thread
  title, turn id, phase, run id, `actor_id`, or `action_ref`.

The server performs one transaction, in this order:

1. Resolve and authorize the internal principal and selected workspace.
2. Validate the brand, context references, attachments, and agent profile.
3. Resolve the workspace-scoped idempotency identity and request fingerprint.
4. Create the Project with the exact title `Untitled project`.
5. Create its first Thread with the deterministic message-derived title below.
6. Capture the exact user-message bytes as the content-addressed artifact and
   `onboarding_input` required by capture-before-use.
7. Insert the immutable `agent_turn_submission` receipt with that body
   reference, the authenticated internal user/membership, and every ordered
   reference. Together the capture + submission are the durable accepted user
   message while queued; the fleet worker later materializes the canonical
   `agent_thread_message` row under the existing two-phase turn contract.
8. Append `turn.accepted` and persist the dispatch/queue intent.
9. Commit; only then may the fleet worker observe and execute the turn.

No model/gateway call occurs in the HTTP process. A failure before commit makes
no partial Project, Thread, Message, submission, or dispatch visible.

The first request returns `201`; an exact idempotent replay returns `200` with
the same ids and `replayed=true`:

```json
{
  "data": {
    "project": {
      "id": "prj_01J...",
      "title": "Untitled project",
      "brand_id": "brand_01J...",
      "href": "/projects/prj_01J...",
      "created_at": "2026-08-10T12:00:00Z"
    },
    "thread": {
      "id": "thr_01J...",
      "title": "Start an ABM project for Northstar Labs",
      "href": "/projects/prj_01J...?thread=thr_01J...",
      "status": "running",
      "pinned": false,
      "project_id": "prj_01J...",
      "created_at": "2026-08-10T12:00:00Z",
      "updated_at": "2026-08-10T12:00:00Z"
    },
    "turn": {
      "turn_id": "019f...",
      "thread_id": "thr_01J...",
      "requested_at": "2026-08-10T12:00:00Z",
      "replayed": false
    },
    "href": "/projects/prj_01J...?thread=thr_01J..."
  }
}
```

The frontend navigates only to `data.href`. It does not append `prompt`,
`phase`, `model`, `entities`, or fixture identities, and the project route does
not submit the message again.

Idempotency is scoped to the authenticated workspace and this operation:

- same key + byte-equivalent canonical request → same project/thread/turn;
- same key + different brand/message/ref/profile bytes →
  `409 IDEMPOTENCY_CONFLICT`;
- a network failure after commit is recovered by replaying the same key;
- concurrent requests under one key produce exactly one project and one turn.

Missing/blank keys return `400 IDEMPOTENCY_KEY_REQUIRED`.

### 4. Deterministic first-thread title

For the Home-created thread, the server:

1. trims leading/trailing Unicode whitespace from `message`;
2. collapses each internal Unicode-whitespace run to one ASCII space;
3. if the normalized value is at most 80 Unicode code points, uses it exactly;
4. otherwise takes a word-boundary prefix that fits within 79 code points and
   appends `…`, for a maximum of 80 code points. If the first 79 code points
   contain no word boundary, it uses those 79 code points plus `…`.

Because Home rejects a blank message, this title is non-null. `New chat` is
only a presentation fallback for a separately created unnamed thread; it is
not the Home-created thread's stored title. A later manual rename is never
overwritten by automatic title derivation.

### 5. Project and sidebar reads

`GET /api/v1/projects/:projectId` requires `project.read` and returns the real
project shell:

```json
{
  "data": {
    "id": "prj_01J...",
    "title": "Untitled project",
    "brand_id": "brand_01J...",
    "product_id": null,
    "status": "active",
    "created_at": "2026-08-10T12:00:00Z",
    "context_entities": [
      {
        "object_type": "account",
        "object_id": "de305d54-75b4-431b-adb2-eb6b9e546014",
        "label": "Northstar Labs",
        "secondary_label": "northstar.example",
        "image_url": null,
        "version": null
      }
    ],
    "agent_profiles": [
      {
        "id": "head-of-abm@v23",
        "label": "GPT-5.6 Terra",
        "short_label": "GPT-5.6 Terra",
        "description": "Clue's governed GPT-5.6 Terra conversation profile",
        "model_id": "openai/gpt-5.6-terra"
      }
    ],
    "default_agent_profile_id": "head-of-abm@v23",
    "composer_capabilities": {
      "context_refs": true,
      "attachments": false,
      "agent_profile_selection": true
    },
    "artifacts": []
  }
}
```

The project response does not contain fixture-only `prompt`, `phase`, `plan`,
`questionnaire`, `previewTimeline`, `reasoningTrace`, or client-manufactured
conversation activity. Threads, transcript, turns, gates, and streams load from
their first-class Lane-D endpoints.

A project with no real artifacts returns `artifacts: []`; the frontend renders
the explicit empty Gallery. It never borrows fixture cards. Until the design
artifact read contract lands, every artifact shown in HTTP mode must come from
a real backend record or not be shown.

`GET /api/v1/projects/sidebar?limit=...&cursor=...` requires `project.read` and
`thread.read` and returns a tenant-scoped, batch-hydrated hierarchy. `limit`
defaults to 50 and is constrained to 1–100:

```json
{
  "data": [
    {
      "id": "prj_01J...",
      "title": "Untitled project",
      "href": "/projects/prj_01J...",
      "conversations": [
        {
          "id": "thr_01J...",
          "title": "Start an ABM project for Northstar Labs",
          "href": "/projects/prj_01J...?thread=thr_01J...",
          "status": "running",
          "pinned": false,
          "updated_at": "2026-08-10T12:00:00Z"
        }
      ]
    }
  ],
  "meta": { "next_cursor": null }
}
```

Project expansion/collapse and desktop pinning are frontend shell state and are
not serialized by this endpoint. Project-level `pinned` is absent because no
project-pin mutation exists. Thread `pinned` is the real as-built thread field.
Thread title may be null for a separately created unnamed thread; the frontend
then renders `New chat` without pretending it is stored.

Conversation status is `idle | running | approval | needs-input | archived`.
Both queued and executing turns derive `running`; `approval` and `needs-input`
derive from unanswered durable gates. This sidebar status is informative and
does not decide whether Stop is available.

### 6. Turn submission, queueing, and controls

The as-built ordinary endpoint remains:

```text
POST /api/v1/projects/:projectId/threads/:threadId/turns
```

It requires `Idempotency-Key`, accepts exactly one of `message` or
`gate_response`, and returns `202` with the as-built `TurnAcceptedWire`.
`context_refs`, `attachment_refs`, and `agent_profile_id` use the same shapes
and capability rules as Home bootstrap, but are valid only with an ordinary
`message`; a gate response plus any of them is `422 VALIDATION_ERROR`.

The submissions-union read adds an explicit hydration opt-in so a queued user
message survives a reload before the worker has materialized its canonical
history row:

```text
GET /api/v1/projects/:projectId/threads/:threadId/turns?include=submission_bodies
```

Each not-yet-materialized turn item then includes the same user-message wire
shape used by the canonical transcript read:

```json
{
  "submission_message": {
    "id": "...",
    "turn_id": "...",
    "thread_id": "...",
    "sequence": 0,
    "role": "user",
    "body_artifact_key": "sha256/...",
    "body_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "body": "Start an ABM project for Northstar Labs",
    "body_unavailable_reason": null,
    "created_at": "2026-08-10T12:00:00Z",
    "refs": []
  }
}
```

Without the opt-in, `body` is null. Hydration is workspace-scoped,
media-type checked, byte-budgeted, and digest verified exactly like the message
body read. Once the canonical user message exists, the frontend deduplicates
the submission projection and message row by `(turn_id, role=user)`; it never
renders the same human message twice.

Queue rules are binding:

- The public turn-state vocabulary is exactly `queued | running | completed |
  awaiting_input | failed | cancelled`; retry is a new linked turn/generation
  attempt, not mutation of a terminal state.
- At most one platform-Deep-Agent turn has durable state `running` per thread.
- Later accepted turns remain durable `queued` submissions in exact acceptance
  order; reads and reloads must show them before worker execution begins.
- Submission remains available while another turn runs. Per-request duplicate
  protection must not disable the whole conversation composer.
- `thread_busy` means any queued or running turn exists.
- `running_turn` means the one turn whose state is exactly `running`.
- Stop is rendered only for `running_turn`; it never targets a queued turn.
- A terminal `completed`, `failed`, `cancelled`, or `awaiting_input` event
  releases the thread and makes the next queued turn dispatchable.

`POST …/turns/:turnId/stop` records cancellation of the running model attempt
and returns `202`:

```json
{
  "data": {
    "turn_id": "019f...",
    "control_id": "019f...",
    "requested_at": "2026-08-10T12:00:03Z",
    "already_requested": false
  }
}
```

A repeated Stop returns the same durable request with
`already_requested=true`. A queued or terminal target returns
`409 TURN_NOT_RUNNING`. Stop does not undo committed tool effects or suspend a
detached research run.

### 7. SSE control frames and terminal lifecycle

Every SSE frame carries an `event:` name and one JSON `data:` object. The
`event:` name must byte-equal `data.type`. The frontend treats disagreement as
a protocol failure and rehydrates from durable state; it never guesses.

Durable frames keep the as-built envelope:

```text
schema_version, event_id, sequence, occurred_at,
project_id, thread_id, turn_id, type,
generation_attempt_id?, message_id?, part_id?, part_kind?, run_id?,
delta_index?, part?, delta?, reason?, status?, failure_code?, replayed?
```

Connect-generated frames are deliberately cursorless but still carry the
common identity and discriminator:

```json
{
  "schema_version": "1",
  "project_id": "prj_01J...",
  "thread_id": "thr_01J...",
  "turn_id": "019f...",
  "type": "stream.hello"
}
```

```json
{
  "schema_version": "1",
  "project_id": "prj_01J...",
  "thread_id": "thr_01J...",
  "turn_id": "019f...",
  "type": "stream.reset",
  "reason": "cursor_older_than_horizon",
  "rehydrate": "transcript"
}
```

Synthetic frames never invent `event_id`, `sequence`, or `occurred_at`.
A durable reconciliation `stream.reset` keeps its real durable cursor.

The turn stream is finite:

- backlog containing a terminal event is emitted through that event and closes;
- a live batch containing a terminal event is emitted through it and closes;
- the frontend finalizes immediately when it parses the terminal event, aborts
  its reader, hides Stop, and refreshes the canonical transcript; it does not
  wait for socket EOF to update the UI;
- reconnect occurs only while durable state remains queued/running;
- `stream.reset` causes transcript/turn rehydration before any new attach.

Malformed non-terminal frames are diagnostic telemetry, not transcript
messages. An unsupported schema version or identity mismatch stops the stream,
shows a controlled recovery state, and re-fetches durable data. Raw strings
such as `malformed turn-stream frame` never appear as chat content.

### 8. Sidebar interaction state

The project header hamburger controls one shared authenticated application
shell; it is not a navigation link. Desktop states are:

```text
collapsed | hover-preview | pinned-expanded
```

- Pointer hover or keyboard focus from `collapsed` enters `hover-preview`.
- `hover-preview` is an overlay and does not change workspace width.
- Pointer/focus departure returns to `collapsed`; Escape also closes preview.
- Click from collapsed/preview enters `pinned-expanded` and reflows the project
  workspace.
- Click while pinned returns to `collapsed`.
- Mobile uses the existing modal drawer and does not reuse desktop reflow.

The button exposes its true action through `aria-label` and `aria-expanded`.
It never calls `router.push("/")` and never uses the label `Go to home`.

### 9. Capability honesty and fixture prohibition

In HTTP mode:

- Home, project, sidebar, threads, messages, turns, gates, and stream adapters
  all use HTTP repositories behind the same transport selection.
- An error stays an error. No repository catches it and substitutes fixture
  projects, threads, artifacts, messages, models, accounts, or contacts.
- Attachments stay hidden until a durable upload/capture endpoint returns the
  attachment receipt defined in §3.
- Model selection is visible because the backend advertises the one real Terra
  profile and persists the chosen `agent_profile_id` on every message
  submission. No second/decorative option is rendered.
- Context chips are visible because the backend advertises the real Lane C
  catalog and persists/rehydrates the ordered references.
- Project rename/pin/delete and project-wide archive controls stay hidden until
  their real endpoints are separately contracted and implemented. Thread-level
  rename/pin/archive remain available through the as-built thread endpoints.
- Fixture-only phase simulation and query parameters are allowed only in
  explicitly fixture/dev preview routes, never in an HTTP-backed project URL.

Fixture adapters may remain for isolated visual tests, but they must implement
the same repository interfaces and lifecycle semantics. They are not a
production fallback.

### 10. R0 acceptance obligations for later slices

Implementation is conformant only when contract tests prove:

1. One Home action creates one durable project/thread/capture/submission.
2. Idempotent retry cannot duplicate any of those rows.
3. Cross-workspace brand/project/thread/ref/attachment access reveals nothing.
4. The response route contains only backend-returned project/thread ids.
5. A new project renders an empty Gallery with no fixture cards.
6. Queued turns survive reload and execute in order.
7. Stop is offered only for the running turn and disappears on terminal.
8. `stream.hello`/`stream.reset` parse and every turn stream closes on terminal.
9. Sidebar hover overlays, click reflows, and neither action navigates Home.
10. Every visible composer control either completes its durable contract or is
    absent from HTTP mode.

---

The sections below preserve the original frontend proposal and the 2026-08-08
as-built amendments for history. Where they conflict with the executable
contract above, the executable contract wins.

## Historical frontend proposal — read endpoints (non-authoritative)

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

## Historical frontend proposal — write endpoints (non-authoritative)

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

## Historical frontend-only preview state (non-authoritative)

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

**This section is authoritative over the historical proposal above and subordinate only to the
2026-08-10 executable integration contract.** It records the founder's ratification of the nine
as-built deviations from Lane D slice D0 (the durable thread shell) plus the D2 turn-submission
contract. Owner: Lane D
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
