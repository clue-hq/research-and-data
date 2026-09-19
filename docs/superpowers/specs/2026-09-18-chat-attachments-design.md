# Chat attachments: markdown, text and image files in the project chat

Status: DRAFT for founder review, 2026-09-18. Branch `add-attachment`.

## 1. What we are building

A person in a project chat can attach files to a message, by clicking the `+` button left of `@`
in the composer or by dragging files onto the chat. Two families of file are accepted:

- text: `.md` and `.txt`
- images: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`

The agent (Head-of-ABM) can read every attachment and work on it. Attachments are kept on the
platform for good, like on claude.ai: they stay visible on the message in the transcript, and text
files also become project documents that show up in the Gallery.

### Founder rulings (2026-09-18)

1. **Images go to the model as images**, attached to the message the way a screenshot is pasted
   into ChatGPT. No OCR, no separate "look at the picture" tool.
2. **Images stay in the conversation.** A picture sent three messages ago is still seen by the
   model on later messages of the same thread.
3. **Uploaded images do not appear in the Gallery** for now. (Text uploads do, because they
   become project documents, which the Gallery already lists.)
4. **While an ad is being edited, `+` keeps its current behaviour for images**: they go to the
   design agent as reference images. Text files attached at the same time go the new way.
5. **Drag-and-drop shows a dashed outline** on the message box while a file is dragged over the
   chat. Dropping adds the file as a chip, exactly like clicking `+`.
6. **Limits**: ten files per message; 150 MB total per message; each image up to 10 MB; each text
   file up to 5 MB.
7. The target-accounts Gallery card is **out of scope**. Nothing about it changes.

## 2. What exists today (verified 2026-09-18)

- The composer already has the `+` button, the file input and the chip strip
  (`apps/frontend/src/features/projects/components/project-composer.tsx`,
  `project-composer-attachment.tsx`). It is enabled only for design reference images while an ad
  leg with a scene document is open (`chat-surface.tsx`, `useDesignReferenceAttachments`). The
  Home composer hides it in HTTP mode. The backend advertises `composer_capabilities.attachments =
  false`.
- The turn submission already carries `attachment_refs` (`AttachmentRefRequest {artifact_key,
  sha256, media_type, byte_count}` in `platform/api/clue_api/chat/schemas.py`). The router refuses
  any submission that has them with 409 `CAPABILITY_UNAVAILABLE`.
- The agent turn contract already has `AgentTurnRequest.attachment_refs`; the turn wiring records
  each as an `agent_artifact_ref` row with `ref_role = 'attachment'`; the L7 context layer already
  emits one "Attachment reference only: artifact_key=… sha256=… media_type=… byte_count=…" line per
  attachment; the transcript read already returns those rows as message refs with
  `flavor: "attachment"`, and the frontend ref schema already has the `attachment` flavor.
- The agent's workspace holds text only (`WorkspaceSeedFile` and `LibraryFile` both require UTF-8).
  The agent has `ls`, `read_file`, `glob`, `grep`. Project documents (Gallery files) are markdown
  rows in `brand_knowledge_document` with a `project_id`, written by
  `write_project_document` (`platform/api/clue_api/arv2/project_documents.py`), and mounted
  read-only for every thread of the project at `project/<path>`.
- Nothing sends an image to a model on the platform side. The agent runtime builds text-only
  LangChain messages (`clue_agents/context.py::_message`) and calls `ChatOpenAI` over OpenRouter
  with `use_responses_api=True` (`libs/clue-gateway/clue_gateway/agent_model.py`). Head-of-ABM runs
  `x-ai/grok-4.6`. The design subsystem does send `image_url` data URLs to a vision model, so the
  data-URL shape has a precedent in the repo.
- The frontend BFF catch-all (`apps/frontend/src/app/api/clue/[...path]/route.ts`) forwards the
  raw request body and headers, so a multipart upload passes through unchanged.
- The `artifact` table has no filename column; the original filename has to be stored elsewhere.

## 3. Design

### 3.1 Upload

`POST /frontend/v1/uploads` on the platform API, multipart with one `file` field. Workspace-scoped
through the normal principal. The route:

1. Refuses a media type outside the two families above (checked from the declared type and the
   file extension; a text file must decode as UTF-8, an image must start with the matching magic
   bytes). Refuses an image over 10 MB or a text file over 5 MB with 413.
2. Stores the bytes content-addressed through `DurableAgentArtifactStore.persist_body` (the same
   store every turn artifact uses, key `<workspace>/<sha256>`, tombstone-aware).
3. Inserts one `chat_upload` row: `upload_id`, `workspace_id`, `uploaded_by_user_id`, `filename`,
   `media_type`, `artifact_key`, `sha256`, `byte_count`, `created_at`. This is where the filename
   lives. New migration, hash id, chained off the current head.
4. Returns `{upload_id, filename, media_type, byte_count, artifact_key, sha256}`.

An upload that no message ever uses is just an unreferenced artifact; the existing orphan sweep
and erasure paths already handle that class of row. No new cleanup job.

`GET /frontend/v1/uploads/{upload_id}/bytes` serves the bytes back to the browser for the transcript
thumbnail, workspace-checked, session-authenticated, with the stored media type.

### 3.2 Submission

`AttachmentRefRequest` gains `upload_id` and `filename`. Both the thread turn request and the Home
project request accept up to ten of them. The router validates fail-closed before anything is
written:

- every `upload_id` exists in this workspace and its row matches the supplied `artifact_key`,
  `sha256`, `media_type`, `byte_count` and `filename` exactly;
- at most ten; total `byte_count` at most 150 MB; no duplicate `upload_id`;
- the media type is in one of the two families.

Refusal codes: `ATTACHMENT_NOT_FOUND` (404), `ATTACHMENT_MISMATCH` (409),
`ATTACHMENT_LIMIT_EXCEEDED` (422). `composer_capabilities.attachments` becomes true whenever the
deployment has a storage backend.

The accepted refs are passed to the turn as `AgentTurnRequest.attachment_refs` in the order sent,
and the existing wiring records them as `agent_artifact_ref` rows with `ref_role = 'attachment'`.
Nothing about that ledger changes.

### 3.3 Text attachments become project documents

At submit time, after the refs validate and inside the router's submission transaction (the one
that records the submission and enqueues the turn), each text upload is written as a project document at `attachments/<filename>` through
`write_project_document`, with the turn as author and these front-matter fields stamped by the
platform: `kind: attachment`, `title: <filename>`, `source: user_upload`, `upload_id`. Rules:

- the filename is sanitised to one path segment (no slashes, no leading dots, whitespace kept);
- the same filename with the same bytes at that path is a no-op (the writer's replay already
  returns the existing row);
- the same filename with different bytes appends a new version of that path, which is what happens
  when someone uploads a corrected copy.

For the Home composer the project is created in the same act as the first turn; the document
writes happen right after the project row exists, in that transaction.

This is the whole persistence story for text: the file is versioned, listed by the documents
endpoint, shown in the Gallery under Documents, and readable by the agent at
`project/attachments/<filename>` on every later turn of every thread in the project, through the
mounted project library. No new context card is needed.

### 3.4 What the agent sees

**Text.** The L7 layer's pointer line for a text attachment becomes specific:
`Attachment "<filename>" (text/markdown, 12,340 bytes) is readable at
project/attachments/<filename>.` The agent opens it with `read_file`. To produce that line the
turn layer gets an injected describer, the same pattern `CapturedTurnDescription` already uses,
which resolves filename and mount path from the `chat_upload` row and the document row by
`artifact_key`. `AgentTurnRequest.attachment_refs` stays a tuple of `ArtifactRef`.

**Images on the sending turn (ruling 1).** The current user message becomes a multi-part
`HumanMessage`: the typed text as the text part, then one `image_url` part per image attachment,
in order, as a base64 data URL with the stored media type. Changes:

- `ContextCandidate` gains an optional `image_refs: tuple[ArtifactRef, ...]` (empty for every
  existing candidate, so nothing else changes shape);
- `_message` builds content parts when `image_refs` is non-empty, reading the bytes through the
  artifact reader;
- the assembler's "the final message is the current instruction" check compares the text part;
- the token counter counts the text bytes plus a fixed per-image allowance (reporting only; the
  founder ruling of 2026-09-14 that budgets never fail a turn stands);
- the L7 pointer line for an image says
  `Attachment "<filename>" (image/png, 1,204,332 bytes) is attached to this message as an image.`

**Images on later turns (ruling 2).** `HistoryMessageRef` gains `attachment_refs: tuple[ArtifactRef,
...]`, filled by the history loader from the turn's `agent_artifact_ref` rows with
`ref_role = 'attachment'` joined to `artifact.media_type LIKE 'image/%'`. The history layer attaches
those as image parts to the corresponding prior user message, so the model sees the same picture
it saw before. Tool and assistant messages are untouched.

One bound, stated as an assumption the founder can change: `CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX`
(default 20). When a thread carries more images than that, only the most recent ones ride history
as image parts; older ones degrade to their pointer line. `0` means no cap. This exists because
every history image is re-sent on every turn and costs tokens each time.

**The vision probe comes first.** Before any of this is built, one paid call sends a small image to
`x-ai/grok-4.6` through the OpenRouter Responses API the way `ChatOpenAI` will send it, and asks
for a description. If the model refuses images, the build stops and the founder is told; ruling 1
did not choose a fallback, so none is built silently.

### 3.5 While an ad is being edited (ruling 4)

The chat surface keeps its existing gate for design reference images. When that gate is active,
files chosen through `+` or dropped on the chat are split by family: images go through the
design-reference hook as today (`design_asset` refs, max 4), text files go through the new
attachments hook. Both sets travel on the same turn. When the gate is not active, everything goes
through the new hook.

### 3.6 Frontend

- **`useChatAttachments`** hook, generalising `useDesignReferenceAttachments`: local chips with
  `uploading | ready | failed`, an object URL preview for images, upload through the BFF to
  `/api/clue/frontend/v1/uploads`, per-file and per-message limit errors shown in the existing
  `attachmentError` slot, submission blocked until every chip is ready, and a synchronous snapshot
  of `attachment_refs` at send time (the same discipline as the design-reference snapshot).
- **Home composer** enables the handlers in HTTP mode; the fixture-only timer path goes away.
- **Drag-and-drop**: the chat pane handles `dragenter/dragover/dragleave/drop` for file drags only
  (`dataTransfer.types` includes `Files`); while a drag is over the pane the composer form gets a
  `data-drop-target` state rendered as a dashed outline; drop calls the same `onFiles`.
- **Transcript**: refs with `flavor: "attachment"` render as chips. An image chip shows the image
  through the bytes route; a text chip shows the filename with the file icon. The label is joined
  at read time from the `chat_upload` row, the same way file and design labels are joined today
  (`context_ref_presentations` gains the attachment branch; the live stream's pending-submission
  shape carries the same fields).
- **Contract notes** recorded in `apps/frontend/docs/api-contracts/projects.md`: the upload
  endpoint, the bytes endpoint, the extended `attachment_refs` item, and the refusal codes.

### 3.7 Settings and environment

New settings, each in `.env.example` with its default the day it is introduced:

```
CLUE_CHAT_ATTACHMENT_MAX_FILES=10
CLUE_CHAT_ATTACHMENT_MAX_TOTAL_BYTES=157286400
CLUE_CHAT_ATTACHMENT_IMAGE_MAX_BYTES=10485760
CLUE_CHAT_ATTACHMENT_TEXT_MAX_BYTES=5242880
CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX=20
```

### 3.8 Erasure and tenancy

Uploads are workspace artifacts cited by a turn; the existing agent artifact tombstone and DSAR
paths apply. A text upload's project document carries the project binding every project document
carries. Every read of a `chat_upload` row is workspace-scoped; an upload from another workspace is
absent, never an error that names it.

## 4. Testing

- Backend unit and DB tests: upload accept and refuse (type, size, non-UTF-8 text, wrong magic
  bytes); submission validation for each refusal code and the limits; text upload becomes a
  project document, replay on identical bytes, new version on changed bytes; L7 pointer lines;
  multi-part current message with image parts; history image parts and the cap; transcript refs
  carry filename and media type; Home path writes documents after the project row.
- Frontend tests: the hook's state machine, the limit errors, the drop handling, the transcript
  chips, the split between design references and attachments while an ad is open.
- The vision probe, run once and recorded.
- A live walk on a lane stack, founder-triggered: attach a markdown file and ask the agent to
  summarise it; attach a screenshot and ask what it shows; ask about that screenshot two messages
  later; drop a file onto the chat; upload the same file again with a change and see the second
  version in the Gallery.

## 5. Out of scope

Gallery cards for uploaded images; paste-to-attach; PDF, DOCX and other document types;
generated thumbnails for images; any change to the target-accounts tab or card; any change to the
Head-of-ABM prompt (the L7 pointer lines already say where each file is).
