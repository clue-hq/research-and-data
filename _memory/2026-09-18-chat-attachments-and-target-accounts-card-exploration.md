# 2026-09-18 — Chat attachments (md/txt/images) + target-accounts gallery card — exploration

Lane: `damascus` worktree, branch `add-attachment` (cut at `1c629c040`, the workspace-display-names
merge). No `.env` in this worktree yet; no stack has been brought up here. Planning only — no code
changed, nothing committed.

## The ask (founder, 2026-09-18)
1. Chat attachments: `.md`/`.txt` and any image (png/jpg/jpeg/webp…) via a `+` button left of `@`
   in the composer AND drag-and-drop onto the chat. The attachment must reach the deepagent's
   context so it reads and works on it, and must persist on the platform (claude.ai-style).
2. A thumbnail card for the project's target accounts in the Gallery; clicking it opens the
   target-accounts surface.

## What already exists (verified first-hand)
- **Composer `+` button exists** (`apps/frontend/src/features/projects/components/project-composer.tsx`):
  a `<label>` with a file input, `ProjectIcon name="plus"`, left of the `@` button, plus the
  attachment chip strip (`project-composer-attachment.tsx`, AI-Elements `Attachments`). Today it is
  wired ONLY as design reference images: `chat-surface.tsx` enables it when `chat.designLegOpen &&
  shell.artifactKind === "ad" && sceneSession.activeDocumentId !== null`
  (`useDesignReferenceAttachments` → `uploadWebAsset` → design API `POST /assets`, 10 MB,
  `LUMEN_ASSET_MAX_BYTES`) and the turn carries `design_asset` context refs (max 4). The Home
  composer hides attachments in HTTP mode (`use-project-home-controller.ts`: "HTTP mode has no
  durable upload receipt endpoint"). Backend `_composer_capabilities()` returns
  `attachments=False` (`chat/router.py:657`).
- **No drag-and-drop on the chat surface.** Drop handlers exist only on the scene canvas
  (`scene-artifact-canvas.tsx`, image files) and the accounts toolbar (CSV).
- **The durable slot for attachments already exists and is refused at the router**:
  `AttachmentRefRequest {artifact_key, sha256, media_type, byte_count}` on `MessageRequest` /
  `HomeProjectRequest` (`chat/schemas.py:232`), refused with 409 `CAPABILITY_UNAVAILABLE`
  "this deployment does not accept attachments" (`chat/router.py:836`, `:2231`).
  `AgentTurnRequest.attachment_refs: tuple[ArtifactRef, ...]` (`clue_agents/contracts.py:584`);
  `agent_turn_wiring.py:546` records each as an `agent_artifact_ref` with `ref_role='attachment'`
  (already in the `agent_artifact_ref_role` CHECK, migration `7e9269ed8a81`). L7
  (`clue_agents/context.py:562`) emits "Attachment reference only: artifact_key=… sha256=…
  media_type=… byte_count=…" per attachment — pointer only, by design ("may later use an
  authorized tool to inspect"). Nothing reads `attachment` refs back on the transcript read.
- **Agent workspace constraints**: `WorkspaceSeedFile` must be UTF-8 text under `context/` or
  `inputs/` (`clue_agents/resources.py:102-109`); `LibraryFile` content is UTF-8 text
  (`library_tree.py:97`); framework tools `ls/read_file/write_file/edit_file/glob/grep`
  (`runtime.py:37`). So text attachments can be workspace files; image bytes cannot.
- **No image input anywhere in the model path**: `clue_gateway.openrouter` builds
  `input_text` parts only; the agent runtime is `ChatOpenAI(use_responses_api=True,
  output_version="responses/v1")` over OpenRouter (`agent_model.py:1099`); Head-of-ABM model is
  `x-ai/grok-4.6` (`.env.example:317`). Whether grok-4.6 accepts image parts through OpenRouter is
  UNVERIFIED (needs one paid probe).
- **Gallery "files" = project documents**: `brand_knowledge_document` rows with `project_id`
  (`arv2/project_documents.py`), markdown only (`_DOCUMENT_MEDIA_TYPE = "text/markdown"`), versioned,
  kind/title from front matter, `write_project_document` (agent) / `save_project_document` (human
  PUT); listed by `GET /frontend/v1/projects/{id}/documents`; mounted read-only for every thread of
  the project at `project/<path>` via the project library (`project_library.py`); a
  `project_document` context ref → L5 focus card naming the mount path
  (`account_research_turn_wiring.py:302`); transcript chips resolve label/kind at read time
  (`composer_context.context_ref_presentations`). Gallery renders them as "Documents" cards
  (`documentGalleryCards`).
- **Ingestion policy precedent**: `clue_config/ingestion.py` allows text/markdown/pdf/docx/pptx/
  png/jpeg/webp/tiff, 25 MB, with a Tesseract `ImageOcrDocumentAdapter` in
  `clue_research/ingestion/adapters.py` (old lane; not composed for chat).
- **Target-accounts card**: the dummy (`clue-frontend/port-of-spain`, `def7344`) designs it — a
  `type: "table"` artifact titled "target accounts", `collateralType: "account-list"`, thumbnail
  `/projects/gallery/target-accounts.png`, click → `controller.openTargetAccounts()`. This repo
  already has the routing rule (`chat-shell/model/gallery-card-target.ts`: `table` →
  `target-accounts` surface), the icon, the PNG under `apps/frontend/public/projects/gallery/`, but
  NO feed ever emits a `table` card (`loadGalleryFeed` maps only leg-derived design artifacts).
  Instead a fixed "Target accounts" tab sits beside "Gallery" in the tab strip
  (`artifact-tabs.tsx:181`), and discovery launch auto-opens the surface (ruling 2026-09-12).
  Membership is `project_account (workspace_id, project_id, account_entity_id)`; the project read
  is `GET /frontend/v1/accounts?projectId=` (`frontend_read/accounts_list.py:200`).

## Founder rulings (2026-09-18, later in the session)
1. Images go to the model as image parts with the message (ChatGPT-style). 2. Images stay in the
conversation on later turns. 3. Uploaded images do NOT appear in the Gallery for now. 4. While an ad
leg is open, images keep going to the design agent as reference images; text goes the new way.
5. Drag-and-drop = dashed outline on the composer, drop adds a chip. 6. Ten files per message,
150 MB total, 10 MB per image, 5 MB per text file. 7. **Target-accounts Gallery card DROPPED** —
"leave it as is for now".

## Spec written (uncommitted, awaiting founder review)
`docs/superpowers/specs/2026-09-18-chat-attachments-design.md`. Key design facts verified for it:
history messages carry `turn_id` (`agent_turn_wiring.py:1385`), so prior turns' image attachments
can be looked up from `agent_artifact_ref` (`ref_role='attachment'`); the transcript read already
surfaces those rows as `flavor: "attachment"` refs (`clue_projections/threads.py:653`) and the
frontend ref schema already has the flavor (`chat-message.ts:15`); `ContextCandidate.body` is a str
and `_message` builds text-only messages (`context.py:118`, `:645`) — image parts need a contract
delta; the BFF catch-all forwards raw multipart bodies; the `artifact` table has no filename column
(a `chat_upload` row will carry it); the design subsystem already sends `image_url` data URLs to
`LUMEN_INGESTION_VISION_MODEL=x-ai/grok-4.5`, a precedent for the data-URL shape.
Assumption stated in the spec for the founder to change: `CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX=20`.
First build step: one paid vision probe against grok-4.6 through the Responses API; if it refuses
images, stop and report (no silent OCR fallback — ruling 1 chose none).

## Design proposed to the founder before the rulings — see the chat message of this session
Summary: one workspace-scoped upload endpoint returning the existing `AttachmentRefRequest` shape;
submissions accept `attachment_refs`; text uploads become project documents at
`attachments/<file>` (persisted, Gallery, mounted at `project/attachments/…`, L5 card via a
`project_document` ref); images are durable turn attachments shown as transcript thumbnails and
sent to the model as image parts on the sending turn (pending the vision probe; OCR sidecar as
fallback); drag-and-drop over the chat pane; the gallery gains one real-data target-accounts card.

## Open rulings requested
R1 image delivery to the model (image part vs OCR sidecar vs tool); R2 later-turn visibility of
images; R3 Gallery slot for uploaded images (none designed in the dummy); R4 `+` behaviour while an
ad leg is open; R5 drop-zone visual; R6 limits; R7 target-accounts card thumbnail (static mock PNG
vs real-logo tile vs empty frame); R8 keep or drop the fixed "Target accounts" tab; R9 when the card
appears (always vs ≥1 account).

## Vision probe (Task 1) — 2026-09-18 — AMBIGUOUS, founder/controller ruling needed

Command (lane `damascus`, branch `add-attachment`, one paid call):

    set -a; source .env; set +a; uv run python scripts/probe_chat_image_input.py

Script: `scripts/probe_chat_image_input.py`. It sends one `HumanMessage` whose content is an
array of a text part plus an `{"type": "image_url", "image_url": {"url": "data:image/png;base64,…"}}`
part — a 64x64 PNG, left half pure red, right half pure blue — and asks the model to name the left
colour then the right colour.

Full output:

    catalog_supports_image_input=True
    model_call_usage cached_prompt_tokens=128 call_kind=agent_completion completion_tokens=274
      cost_cents=Decimal('0.193200') duration_ms=11828.954 prompt_tokens=240
      requested_model=x-ai/grok-4.6 role=head_of_abm served_model=x-ai/grok-4.6 total_tokens=514
    model=x-ai/grok-4.6
    reply='The left color is blue and the right color is red.'
    RESULT: IMAGE NOT SEEN

**The printed verdict is a left/right-ordering artifact, not evidence of blindness.** The script's
pass test requires "red" to appear before "blue"; the model named *both and only* the two colours
actually in the image, but mirrored the sides. Supporting evidence that the image was transmitted
and perceived:

- The call was accepted on the wire — no `invalid_union: expected string, received array` 400. The
  array-shaped content part survives the platform's model path end to end.
- OpenRouter's own catalog reports `x-ai/grok-4.6` accepts image input (`supports_image_input=True`,
  a free pre-spend catalog read).
- Token accounting leans image, not text: the data URL is only 206 chars (137-byte PNG), so a
  text-tokenised prompt would be roughly 105–135 tokens; 240 prompt tokens is more consistent with
  the image being charged as image tokens.
- Precedent already in the repo: the design subsystem sends the same data-URL shape to
  `LUMEN_INGESTION_VISION_MODEL=x-ai/grok-4.5`.

Caveat kept honest: from this one reply alone, "red and blue" is also the most likely *guess* for a
blind model, so the reply on its own is not proof. The probe was **not** rerun (brief: do not retry
after a negative), and changing the prompt after seeing the answer would be shopping for a pass.

**Two deliberate deviations from the task brief**, both recorded at the top of the script:
1. The provider is built from `default_gateway_config()`, not a bare `GatewayConfig()`. Only the
   former sets `openrouter_chat_completions_fallback=True`, which is what routes a non-OpenAI model
   off OpenRouter's `/responses` translation — the translation `agent_model.py` documents as 400ing
   on exactly this array-shaped content. A bare `GatewayConfig()` probe would have failed on the
   wire shape and told us nothing about vision.
2. `max_output_tokens=1000` rather than 200. This lane runs the dev reasoning lens
   (`CLUE_CHAT_REASONING_TRACE_MODE=raw` -> `reasoning.effort=medium`), so a tight output budget can
   be spent on reasoning and truncate the visible answer into a false negative. The verdict logic is
   unchanged.

**Owed decision before Task 8/9 start:** treat this as IMAGE SEEN (transport + perception proven,
spatial ordering unreliable), or run one disambiguating probe with an unguessable ground truth
(e.g. a digit or an unusual colour pair rather than left/right red/blue).
