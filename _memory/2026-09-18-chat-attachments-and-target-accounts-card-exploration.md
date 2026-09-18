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

### Fix round 1 — open-question probe with a real screenshot — **RESOLVED: IMAGE SEEN**

The round-1 ambiguity is settled. Controller ruling: rerun once with an unguessable ground truth.
`scripts/probe_chat_image_input.py` gained an optional `--image PATH` mode (closed extension map
png/jpg/jpeg/webp; an unknown extension exits 2 *before* spending) that asks an open question —
"Describe what this image shows in two sentences. Name any words you can read in it." — and prints
`RESULT: SEE REPLY` with exit 0, because no heuristic can honestly grade an open answer. The default
synthetic-PNG colour mode and its pass/fail test are unchanged. `.text()` also became the `.text`
property, keeping the `str(reply.content)` fallback.

Command (one paid call):

    set -a; source .env; set +a
    uv run python scripts/probe_chat_image_input.py --image apps/frontend/public/projects/gallery/target-accounts.png

Full output:

    catalog_supports_image_input=True
    model_call_usage cached_prompt_tokens=128 call_kind=agent_completion completion_tokens=933
      cost_cents=Decimal('1.02900') duration_ms=17240.144 prompt_tokens=2442
      requested_model=x-ai/grok-4.6 role=head_of_abm served_model=x-ai/grok-4.6 total_tokens=3375
    model=x-ai/grok-4.6
    image=apps/frontend/public/projects/gallery/target-accounts.png (286513 bytes, image/png)
    --- reply (verbatim) ---
    The image shows a table listing medical companies with columns for company name, contact, and
    tier. Readable words include Capital Digestive Care LLC, Synergy Medical Group, Wilmington
    Health PLLC, anterior_digestive_alpha, GI Alliance of Illinois, Neurological Surgery,
    Intercolumbia, SIERRA NEUROSURGERY GROUP, Washington Gastroenterology PLLC, Richard Simpson,
    Sofia Petrov, Amara Osei, Rachel Brooklyn, Core, Basic, and Elite.
    --- end reply ---
    RESULT: SEE REPLY

**Verified against the actual file (read visually, no spend): every single string the model reported
is verbatim correct, and it reported nothing that is not there.** The screenshot is a target-accounts
table with columns `Company name` / `Contact` / `Tier`; the rows are Capital Digestive Care, LLC
(Richard Simpson, Core); Synergy Medical Group (Basic); Wilmington Health, PLLC (Sofia Petrov,
Elite); anterior_digestive_alpha (Amara Osei, Basic); GI Alliance of Illinois (Elite); Neurological
Surgery (Rachel Brooklyn, Basic); Intercolumbia (Core); SIERRA NEUROSURGERY GROUP (Basic);
Washington Gastroenterology, PLLC (Rachel Brooklyn, Elite). The model even got the three column
headers and the odd snake_case row. Only deviation: a dropped comma in "Capital Digestive Care, LLC".

**Correction to the task instruction:** the controller described this file as listing "OpenAI,
Anthropic, Cursor, Perplexity, Mistral AI, Cohere". It does not — it lists the healthcare/GI accounts
above. The model read the file correctly and the brief's description was wrong; anyone grading this
reply against that description would wrongly score a perfect OCR pass as a hallucination.

**Conclusion — the Task-1 gate passes.** `x-ai/grok-4.6` receives an `image_url` data-URL content
part through the platform's own `OpenRouterAgentModelProvider` path, and it genuinely sees the
image, down to reading small rendered text. Round 1's `IMAGE NOT SEEN` was the colour test's
left/right ordering artifact, exactly as suspected. Tasks 8/9 are unblocked; no OCR fallback is
needed (matching ruling R1).

Token/cost note for planning: the 1710x1304 / 286 KB screenshot cost **2442 prompt tokens and
1.029 cents** in one turn, versus 240 tokens / 0.19 cents for the 64x64 synthetic PNG. Real
screenshots are not free, which is what `CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX` exists to bound.

## Execution record (SDD, 2026-09-18)

Plan `docs/superpowers/plans/2026-09-18-chat-attachments.md` (15 tasks), executed subagent-driven
on branch `add-attachment` in the `damascus` worktree. Controller = Fable; implementers Opus only;
every review done by the controller first-hand. Ledger:
`.superpowers/sdd/2026-09-18-chat-attachments/progress.md` (per-task reports beside it).

### Lane setup (controller, before Task 1)
- Lane DB `clue_damascus` on localhost:55040, a `pg_dump` copy of `clue_san-salvador` (dumped with
  `docker exec clue-pg-istanbul pg_dump`, because the local pg_dump is v15 against a v16 server),
  24 projects, migrated to head `be968ae45500`.
- `.artifacts/` copied from the san-salvador worktree (923 MB).
- Throwaway test DB `clue_damascus_test`, migrated to head. Every DB suite ran against
  `CLUE_DATABASE_URL=postgresql+asyncpg://clue:<pw>@localhost:55040/clue_damascus_test` only —
  never the lane DB.

### Commits per task
- Plan: `a6e410649` docs(plan) — BASE for Task 1.
- Task 1 (vision probe): `06febda26` probe accepts image parts; `542fc4121` open-question probe
  with a real screenshot. Two paid calls, 1.22¢ total.
- Task 2 (settings): `381e42df9` five `CLUE_CHAT_ATTACHMENT_*` settings + `.env.example`;
  fix `d0c3fd392` tests isolate from the lane `.env` (`Settings(_env_file=None)`).
- Task 3 (migration): `d54a3c77c` `chat_upload` + `agent_turn_submission_attachment`
  (revision `d659c2d2b537` ← `be968ae45500`); fix `22c49735c` named FKs, workspace anchor +
  composite FK, append-only UPDATE trigger, 4 DB tests.
- Task 4 (upload validation + row): `ee4123cfd`.
- Task 5 (`/frontend/v1/uploads` routes): `3536f4d06`.
- Task 6 (submission takes `attachment_refs`): `dae98ffc1`; fix `f72bd947e` unknown receipts are
  refused 404.
- Task 7 (text attachments become project documents): `02d64e166`.
- Task 8 (turn carries attachments; L7 names each file): `79ae370ae`.
- Task 9 (sending turn's images ride the user message): `bddc584a0`.
- Task 10 (history images, capped by setting): `1a346c6d5`.
- Task 11 (transcript refs carry filename/media type/upload id; chips): `2375bcdd4`.
- Task 12 (frontend model, upload adapter, hook, turn request refs): `1a86b73cb`.
- Task 13 (chat and Home composers upload; ad-leg images keep the design route): `37e26d282`.
- Task 14 (drop files on the chat; dashed composer outline): `8d45f475a`; fix `2ad23284d` drop gate
  matches the `+` button, pure drag helpers tested.
- Task 15 (this note + the frontend contract section): the commit carrying this entry.

### Gates
- Backend: the named suites of each task, re-run by the controller after every task, always on
  `clue_damascus_test`. Counts as run: Task 3 4/4 DB (plus downgrade -1 / upgrade head); Task 4
  5/5; Task 5 27; Task 6 28, then 18 after the fix; Task 7 12; Task 8 3 + 22; Task 9 6 + 27 pure +
  6 DB; Task 10 5 + 30 pure + 6 DB; Task 11 2 DB + 47 stream. `ruff` and `mypy` clean on the
  touched files at every task; the agent contracts suite 28 passed / 0 failed at Tasks 8, 9, 10.
  `alembic heads` returned the single head `d659c2d2b537` after Task 3.
- Frontend: `npm test` grew 3173 → 3178 → 3180 → 3181 → **3184 tests / 0 fail**; `npm run lint`
  **0 errors**; `npm run build` **green** (run at Tasks 13 and 14).

### Rulings taken during execution (in order)
1. The plan named the alembic head `fffa2a8ba17c` (an mtime-sorted guess); the real single head was
   `be968ae45500`, and Task 3's `down_revision` had to be the output of `uv run alembic heads` at
   execution time.
2. There is no `tests/config/`; the settings test lives at `tests/test_chat_attachment_settings.py`
   and itself asserts every new key is in `.env.example` with its default.
3. Task 1's first probe (synthetic red/blue PNG) printed `IMAGE NOT SEEN` on a left/right ordering
   artifact; one more run with a real screenshot and an open question decides. It resolved to
   IMAGE SEEN (the model transcribed the table verbatim). The controller's description of
   `target-accounts.png` as an AI-companies table was wrong — it is a healthcare-accounts table.
4. Task 5's test header is `X-Workspace-Id` (the plan wrote `X-Clue-Workspace-Id`).
5. Task 7's identical-bytes replay check finds the row via `list_project_documents` filtered on
   `path`, then `read_project_document` to compare bodies (`current_document_version` returns
   `int|None`).
6. `write_project_document` renders `.txt` bodies under the store's constant
   `text/markdown`; keep the filename as-is, the path keeps the real extension.
7. Task 8 uses `tests.agents.conftest.constitution(workspace_id=WS, ...)` as the constitution
   builder.
8. Filenames longer than 255 characters are REFUSED, not truncated. Task 5's route order is
   sanitize → resolve_media_type → validate_upload_bytes → persist → record.
9. Task 3 fix: close cross-workspace citation at the substrate, not only in the Task 6 validator —
   `chat_upload_workspace_anchor UNIQUE (upload_id, workspace_id)` plus a composite upload FK on
   the attachment table. Append-only UPDATE trigger on `agent_turn_submission_attachment` only; no
   DELETE block and no trigger on `chat_upload`, so erasure can still remove upload rows.
10. Refusal shape: the route keeps `HTTPException(detail={"code","message"})` like every sibling;
    the projections app's envelope middleware renders `{"error": {code, message, requestId}}`. The
    Task 15 contract note must say refusals arrive as the FI-1 envelope.
11. Task 6 replay must also compare `tuple(a.upload_id for a in attachment_refs)` against the
    stored `submission_attachment_refs` and raise `SubmissionConflict` on mismatch.
12. `test_lane_d2_turn_submission_db`: first ruled "expect 503"; **withdrawn** — that app has
    storage and the 503 branch is unreachable over HTTP (both submission routes register only with
    storage). Final: the test expects `404 ATTACHMENT_NOT_FOUND` for a receipt the workspace never
    made, and the §3.2 503 rule is asserted at unit level on the helper.
13. Task 9: `_message(candidate)` → `_message(candidate, images)`; update any caller, `images`
    defaults to `{}`. (No existing test called it.)
14. Task 10: `AgentPlatformComponents.history_images_max` gets default 20 so trial/test builders
    keep working. `turn_image_refs` also filters `purged_at IS NULL` and the
    `agent_artifact_tombstone` NOT EXISTS — an unreadable history image would raise
    `ArtifactNotFound` and kill every later turn on the thread.
15. Task 11: `ThreadMessageWire.refs` is `tuple[dict[str, Any], ...]`, so presentation keys need no
    schema field — the brief's "add `upload_id` to the ref wire model" step is a no-op.
16. Task 12 absorbs the Home schema/adapter `uploadId` addition (the Home HTTP repository still
    mapped the OLD five fields), so Task 13 only wires hooks. The upload adapter posts `FormData`
    without a hand-set `Content-Type` and reads the FI-1 envelope on failure.
17. Task 13: the Home controller's fixture upload timer path goes; fixture transport gets
    `enabled:false` and any test asserting the timer moves to the hook.
18. Task 14: the drop gate is `designReferencesEnabled || composerCapabilities.attachments`,
    matching the `+` button — the earlier "attachments alone" ruling was narrower than the button
    and is withdrawn. Drag-depth/drop helpers extracted into `file-drag.ts` and unit-tested (no
    jsdom for the hook).

### Deferred minors
- **→ FINAL FIX WAVE:** add index `agent_turn_submission_attachment_artifact ON
  agent_turn_submission_attachment (workspace_id, artifact_key)` by amending migration
  `d659c2d2b537` in place (no second revision). The lane DB `clue_damascus` has NOT applied that
  migration yet; only `clue_damascus_test` has, and it can be downgraded/upgraded.
- Task 3: `chat_upload` rows cannot be deleted while an attachment cites them (no `ON DELETE`
  rule). Fine for this plan — erasure keeps rows as audit and tombstones the artifact (spec §3.8);
  the erasure owner decides the rule if row deletion is ever wanted.
- Task 5: no test for the 503 (no storage) / 401 (no principal) branches of the upload route.
- Task 5: `await file.read()` buffers the whole body before the size refusal (Starlette spools to
  disk); an edge/ASGI body limit is wanted before a public origin. Candidate CLAUDE.md backlog
  bullet.
- Task 6: `insert_submission` has no early workspace guard for attachments (context refs have one);
  fail-closed today via the composite FK. One-line hardening.
- Task 6: the 503 branch of `_validated_submission_attachments` is unreachable over HTTP — a
  defensive guard, unit-covered.
- Task 8: the design-leg turn path passes no `attachment_refs`, so a text file attached while an ad
  leg is open becomes a project document (Gallery, mounted at `project/attachments/…`) but no
  turn's L7 names it; the user can `@`-tag it later. Accepted for v1 — spec §3.5 only promises the
  file travels on the turn.
- Task 9: no per-turn ceiling on total image bytes to the model beyond the upload limits (10 × 10 MB
  worst case) — a product decision. `IMAGE_TOKEN_ALLOWANCE=1000` is a flat reporting-only guess.
- Task 10: an erased history image vanishes silently (no placeholder); the design-leg transcript
  loader carries no attachments, so leg turns never re-show images.
- Task 11: `"artifact"` in `PRESENTED_REF_TYPES` triggers one extra no-row query on pages carrying
  next_action/assumption/workspace_output refs. The label for one artifact key attached twice under
  different filenames is the newest filename.
- Task 13: with an ad leg open, the design cap (4 images) and the chat cap (10 files) apply
  separately — no combined per-turn ceiling; the design error is shown first.
- Task 14: a file dropped on the artifact/editor pane falls through to the browser default (it
  navigates to the file); only the chat pane is a drop target.

### Pre-existing reds, confirmed unrelated
- `tests/api/test_project_read_surfaces_db.py::test_composer_context_prepares_an_existing_active_thread`
  — differs in composer `context_entities` fields, not attachments (Task 6).
- `tests/api/test_reference_images_contract.py::test_scene_leg_envelope_snapshots_reference_asset_ids`
  — proven pre-existing by the implementer via a stash A/B (Task 11).

### Other execution notes
- The Opus session limit (429) was hit at the Task 13 commit and reset at 18:50 IST; implementers
  stayed Opus-only and the Task 14 dispatch waited for the reset.
- Task 13's implementer stalled on the stream watchdog (600 s) with edits on disk and no report;
  the same agent was resumed (round 0, not a fix round) to finish gates, commit and report.
- Plan defect fixed by the Task 8 implementer: the brief's L7 snippet reused the local name `body`
  for the attachment line, which would have made the last attachment's text the final user
  instruction.

### OWED — live walk (founder-triggered; NOT run)
Task 15 Step 2 was not executed: the walk is the founder's to trigger on the lane stack
(`scripts/dev_stack*.sh` per `DEV_STACK.md`). Note that the lane DB `clue_damascus` has not had
migration `d659c2d2b537` applied — migrate it (and apply the deferred index amendment first, if the
final fix wave lands it) before walking. Six steps, in a project chat:
1. Attach `brief.md` via `+`, send "Summarise the attached brief in three bullets." Expect: a chip
   in the transcript, `attachments/brief.md` under Gallery → Documents, and a reply that quotes the
   file.
2. Attach a screenshot, send "What is in this image?" Expect: an image chip and an answer that
   describes the image.
3. Two messages later, ask "What colour was the button in the screenshot I sent earlier?" Expect:
   an answer from the image, not a request to re-send.
4. Drag a `.txt` onto the chat: a dashed outline appears, and a chip appears on drop.
5. Upload `brief.md` again with one edited line: the Gallery shows version 2.
6. Open an ad, attach one image: it lands as a design reference (existing chip style), not as a
   chat attachment.
Record each outcome and any defect here.
