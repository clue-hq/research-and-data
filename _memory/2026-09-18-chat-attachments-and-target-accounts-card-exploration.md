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
   in the transcript, ~~`attachments/brief.md` under Gallery → Documents,~~ and a reply that quotes
   the file. (The Gallery half is **struck 2026-09-19**: the text-document route is retired, so an
   attachment is a file in the agent's `attachments/` mount and never a project document.)
2. Attach a screenshot, send "What is in this image?" Expect: an image chip and an answer that
   describes the image.
3. Two messages later, ask "What colour was the button in the screenshot I sent earlier?" Expect:
   an answer from the image, not a request to re-send.
4. Drag a `.txt` onto the chat: a dashed outline appears, and a chip appears on drop.
5. ~~Upload `brief.md` again with one edited line: the Gallery shows version 2.~~ **STRUCK
   2026-09-19** — the text-document route is retired (no project document, no versioning). Do not
   walk this step; newest-upload-of-a-name-wins is covered by the 2026-09-19 walk below.
6. Open an ad, attach one image: it lands as a design reference (existing chip style), not as a
   chat attachment.
Record each outcome and any defect here.

## Closing entry (controller, 2026-09-18 evening)
- Final whole-branch review done by the controller (read every new module and every diff); ONE
  fix wave landed: `f3724455d` (index `agent_turn_submission_attachment_artifact`, migration
  `d659c2d2b537` amended in place), `0ae7fd281` (bytes route 404 `UPLOAD_NOT_FOUND` on an erased
  artifact), `c96a43829` (early workspace guard for attachment refs in `insert_submission`),
  `208abe72f` (ruff format). Scoped re-review clean: 15 covering tests, one alembic head,
  down/up reversible, `make lint` / `make typecheck` (871 files) / `make contracts` (28/0) clean;
  frontend untouched by the wave (last gate 3184 tests / 0 fail, lint 0 errors, build green).
- Lane DB `clue_damascus` migrated to `d659c2d2b537` (index present), so the owed live walk can
  run on this lane once the stack is brought up per `DEV_STACK.md`. `.artifacts/` already holds
  the san-salvador copy.
- Parked at the final review (UX papercuts, not correctness): with an ad leg open the design cap
  disables the `+` input for text files too (drop still works); no combined per-turn ceiling
  across design refs + chat attachments; the artifact pane is not a drop target; whole-body
  buffering before the size refusal on the upload route (edge body limit before a public
  origin); one no-row presentation query on pages carrying next_action/assumption refs.
- Branch `add-attachment`, 26 local commits from `1c629c040`; nothing pushed.

## Rebase onto research-streaming (2026-09-18, after PR #64 opened)
- `git rebase origin/research-streaming` (16 incoming commits: the conversation-naming feature,
  PR #63, plus the trenton lane wrapper). One conflict, in `chat/router.py`'s imports (incoming
  dropped `import re`, mine added `Sequence`); resolved to the union without `re` (unused). The
  other ten overlapping files auto-merged; spot-checked that the Home path carries both the
  untitled-thread birth (`title=None`) and the attachment validation/materialization, and that
  `settings.py` / `.env.example` hold both feature blocks. Branch is still 29 commits over the
  new base; force-push of `add-attachment` needed to update PR #64.

## 2026-09-19 — after PR #64 merged: rebase, then the next feature
- Workspace switched by Conductor to `damascus-v1` → renamed `rebase-and-expand-attachment-types`;
  fast-forwarded onto `origin/research-streaming` (PR #66 design/account-binding, PR #67 design
  agent account-context transfer). The only obstacle: PR #67 committed 87 files under
  `.context/attachments` that existed here untracked (12 macOS screenshots carry a narrow no-break
  space in the name — plain `git diff --name-only` escapes it, use `-z`); moved aside, all 77 local
  copies byte-identical to the tracked ones, backup deleted. Lane DB and `.env` parity unchanged.
- Founder ask: agent should comprehend PDF/DOCX/XLSX/CSV attachments, using the reference skills
  under `attachments/` (XLSX/DOCX/PDF, sandbox-based). Founder REJECTED converters-only and chose
  option 1: a governed `run_python@1` tool in a Docker sandbox over the thread workspace, plus the
  converters as the fast path. Spec written:
  `docs/superpowers/specs/2026-09-19-agent-code-execution-and-document-attachments-design.md`
  (assumed defaults recorded in it: no network, 60 s / 1 CPU / 1 GB / 10 runs per turn / 1 MB
  output; `CLUE_SANDBOX_ENABLED` ships off). Key verified facts: workspace is a real anchored dir
  per thread; mounts are read-only dirs beside the root and exempt from quota; seeds/library are
  UTF-8-only; `ToolContext` has no workspace handle (registry keyed by execution id, bound where
  the spill sink is bound in `head_of_abm_wiring.py`); `read_file` refuses >1 MiB files (twin cap
  set to 1 MiB); Docker Desktop present on the founder's host, no LibreOffice.
- Next: founder reviews the spec → implementation plan → SDD.

## 2026-09-19 (afternoon) — ruling: no markdown step anywhere; the text route is retired

Founder question: "why are we complicating our add attachment process by adding a separate
convert to markdown step at all? why can't we keep it simple like Lightfield does?" Re-read the
reference skills under `attachments/`: Lightfield mounts the raw file at a path, the sandbox has
the libraries preinstalled, the skill teaches reading with code; there is no conversion step.
Assessment given and accepted: the converter (five modules, a migration, a refusal code, twin
materialisation, a markdown cap, a chip note) served a fast path the agent does not need, plus a
Docker-missing fallback that is a deployment concern. Second question "why do we have to keep it
markdown first?" — the PR #64 text route (text uploads as versioned project documents) is also a
second mechanism; founder agreed to retire it.

**Rulings recorded in the spec (second ruling block):** no conversion, no twin, no index file;
every attached file of every family is synced by the worker into `<ws>/projects/<project>/
attachments/<filename>` and mounted read-only as `attachments/`; text opens with `read_file`,
binaries with `run_python`, images also ride as image parts; newest upload of a name wins;
binaries are unreadable without the sandbox (accepted). Retired: `materialize_text_attachments`,
`_wrote_attachment_documents`, the describer's store lookup, the text-documents DB test, the
"re-upload → v2" walk step. Settings drop to 8 (no OCR / sheet-rows / markdown-cap switches). No
migration in this plan (head stays `d659c2d2b537`).

Spec and plan rewritten in place (plan: 20 → 16 tasks). Execution not started; the founder still
has to choose subagent-driven vs inline.

## Execution record (SDD, 2026-09-19 — code sandbox and document attachments)

Spec `docs/superpowers/specs/2026-09-19-agent-code-execution-and-document-attachments-design.md`,
plan `docs/superpowers/plans/2026-09-19-agent-code-execution-and-document-attachments.md`
(16 tasks), executed subagent-driven on branch `rebase-and-expand-attachment-types` in the
`damascus` worktree, base `7a548e110`. Controller = Fable; implementers Opus only; every review
done by the controller first-hand (no reviewer subagents). The SDD ledger and per-task reports were
git-ignored scratch under `.superpowers/sdd/` and are deleted at plan close, so this note plus the
plan are the durable record. DB suites ran on the throwaway `clue_damascus_test` only; nothing pushed.

### What the feature is, in one paragraph
Every attached file of every family is synced by the fleet worker into
`<ws>/projects/<project>/attachments/<filename>` and mounted read-only as `attachments/` on every
turn of that project. Text opens with `read_file`; PDF/DOCX/PPTX/XLSX open by the agent writing
Python against them with the new governed `run_python@1` tool, which runs in a no-network Docker
container over the thread's workspace; images additionally ride the message as image parts. No
conversion step, no markdown twin, no index file, no project document, no migration.

### Per task (commit range → what shipped → review verdict)
- **Task 1** `7a548e110..934e66a0b` — eight `Settings` fields (`chat_attachment_document_max_bytes`
  + seven `sandbox_*`), `.env.example` and local `.env` at full parity. Review clean (6/6 tests,
  parity 8/8).
- **Task 2** `934e66a0b..292cb4095` — the `document` family in upload validation: six media types,
  six extensions, per-family size limits, magic/UTF-8/JSON checks, `UPLOAD_NOT_A_DOCUMENT`.
  Review clean (10/10; `ValidatedAttachment.family` pre-widened as authorised).
- **Task 3** `292cb4095..74243a8be` — retired the PR #64 text-document route
  (`materialize_text_attachments`, `_wrote_attachment_documents`, both call sites, the post-commit
  refresh, the text-documents DB test). Review clean (grep empty, contracts 28 kept).
- **Task 4** `74243a8be..0c0cda005` — `ATTACHMENTS_DIR`, `MountRequest.attachments`, the optional
  read-only `attachments` mount, and the factory/lease host-path accessors. Review clean (2/2).
- **Task 5** `0c0cda005..807a1da85` — `project_attachments.py`: worker-side sync of every family
  (`DISTINCT ON (filename)` newest-first → newest upload of a name wins; erased/purged artifacts
  skipped, so erasure propagates), fd-anchored `O_NOFOLLOW` writes, non-regular entries purged;
  wired in `agent_turn_fleet_wiring` before `workspaces.acquire`. Review clean (DB test green).
- **Task 6** `807a1da85..fffe1df21` — L7 names each attachment's one workspace path and the tool
  that opens it (family-driven, one sentence); the describer no longer looks anything up in a
  store. Review clean (2/2).
- **Task 7** `fffe1df21..e25c225ca` — `SandboxMounts`, the lock-guarded per-execution
  `SandboxWorkspaces` registry with its per-turn run budget, and `sandbox_mounts_for_lease`.
  One fix round (1 addressed). Review clean (4/4).
- **Task 8** `e25c225ca..278d2e130` — the Docker runner: locked-down argv (`--network none`,
  `--read-only`, `--cap-drop ALL`, `--user 65534`, pids/cpu/memory caps, tmpfs `/tmp`),
  bounded output capture, timeout with kill-by-label, `docker_available` with a 10 s daemon cap.
  Review clean (7 passed / 1 skipped).
- **Task 9** `278d2e130..da649d776` — the post-run policy sweep: lstat-only walk, symlinks
  unlinked never traversed, extension/size/quota enforcement over only this run's new files.
  Review clean (18 passed / 1 skipped).
- **Task 10** `da649d776..17961623c` — `run_python@1`: five refusals before any container, budget
  spent once, one thread hop for snapshot/run/sweep, `O_NOFOLLOW` spill of oversized output,
  registered ungranted. Review clean (16/16; four count sites bumped).
- **Task 11** `17961623c..eb694b04c` — the registry threaded through `fleet_main`, the platform
  components and `ConversationTurnEngine.execute`: register before the adapter build, release in a
  `finally` on every path, mounts taken from the lease's own `MountRequest`. Review clean (4/4).
- **Task 12** `eb694b04c..d01588d8b` — `docker/agent-sandbox/{Dockerfile,README.md}` and
  `make sandbox-image`. Review clean (image present, real-container test passes on this host).
- **Task 13** `d01588d8b..46c376e0e` — what the agent is taught: `code-execution/v1` skill,
  workspace manual chapter v5, `stage0-interview` v34, prompt v11. Review clean (20/20 catalog +
  drift tests; refusal strings verified against the tool source).
- **Task 14** `46c376e0e..f42eb7411` — `profile:head-of-abm@v58` grants `run_python@1` (both
  schema digests), adds `attachments` to `workspace.readable_prefixes`, moves every skill/prompt/
  manual pin together; Recipe #0 v29 = v28 + one address at all four sites; manual v5 generated.
  Review clean (515 tests).
- **Task 15** `f42eb7411..1bb4eb1d8` — frontend: accept list, `document` family and the 25 MB
  limit mirrored from the backend, routing unchanged. Review clean (3194 frontend tests, lint 0
  errors, build compiled).
- **Task 16** — this entry, the `projects.md` contract section and the CLAUDE.md bullets.

### Rulings taken during execution (verbatim from the ledger)
- Preflight scan — `Ruling: none needed — scan clean.`
- Task 7 — `Ruling: `sandbox_mounts_for_lease` must honour `MountRequest.project_library_name` (the
  fleet sets `pinned-<turn>` for replayed turns; `_open_mounts` opens
  `<ws>/projects/<project>/<project_library_name>`) — add kwarg `project_library_name: str =
  LIBRARY_DIR` mirroring MountRequest; Task 11 passes `mounts.project_library_name`. Cost if wrong:
  none (default keeps today's path); cost of not doing it: a replayed turn's sandbox reads a
  library generation the model's own tools do not see.`
- Task 9 — `Ruling: two deviations from the brief stand — directories are walked not removed
  (write_file creates parents; nested trees are legitimate), and `.clue-tmp-*` names are removed as
  `atomic_write_residue` (the backend's walk raises on them and would brick the thread). Cost if
  wrong: an extra reason string in receipts; none structural.`
- Task 12 — `Ruling: the sandbox image pins `cryptography==46.*` (transitive dep of
  pypdf/pdfplumber; ≥47 SIGILLs on this host's linuxkit 5.15 Docker VM). Accepted — the pin is
  inside an offline, no-network container where cryptography does no TLS; README records the bisect
  and the exit condition. Cost if wrong: none functionally; a newer host may drop the pin. Founder
  to confirm at the end.`
- Task 13 — `Ruling: tool_notes `run_python` lists the three refusal codes the tool actually raises
  (code_too_large is a pydantic validation error, project_not_found is never raised by this tool) —
  the drift test scans reachable literals, so listing phantom codes would fail Task 14's gate.
  Cross-references in stage0 v34 / manual-workspace v5 point at manual v5 because Task 14 pins every
  chapter at v5. Cost if wrong: none.`
- Task 13 also carries a standing-rule note: the skill text is agent-facing content and is owed to
  the founder for review before merge.

### Deferred minors
- Task 3: four pre-existing `ruff` errors in `platform/api/clue_api/design_leg_wiring.py` (arrived
  with merge `f2a9a41d8`, untouched by this branch) — final review triages whether to fix here.
- Task 5: a live artifact row whose blob is missing from storage makes `artifacts.read` fail the
  turn — repo norm, same as every other read; recorded, not changed.
- Task 12: the image is hand-built per host and not reproducible over time (`*` pins, unpinned
  apt), and no record says which build a turn ran under. A CI build + registry is future work.
- Task 14: `manual-index/v5` is a literal copy whose workspace row does not name `attachments/`
  (the chapter itself does) — a wording touch for the next manual mint.
- Task 14: four pre-existing failures attributed in `task-14-report.md` (recipe contiguity gaps
  16–18 / 20–21 that predate v29; the C5 recipe-0 fixture; projections settings under the lane
  `.env`) — skipped in a plain env, not ours; final review confirms.

### The retired text route (why the diff deletes more than it adds)
PR #64 made a `.md`/`.txt` upload a versioned project document at `attachments/<name>` (Gallery,
project-library mount, `project_document` ref). That was a second mechanism beside the workspace
mount, and the founder retired it on 2026-09-19 ("why do we have to keep it markdown first?").
Consequences to remember: an attachment no longer appears in the Gallery, no longer versions, and
no longer produces an L5 focus card — it is a file in `attachments/` named on L7, nothing more.

### The sandbox image
- `docker/agent-sandbox/Dockerfile` + `README.md`; built with `make sandbox-image` (which honours
  `CLUE_SANDBOX_IMAGE`, default `clue-agent-sandbox:latest`). **It must be built on every host that
  runs a fleet worker** — there is no CI build and no registry push.
- Size on this host: **611,816,512 bytes (612 MB)**. Build host: macOS arm64, Docker Desktop server
  20.10.22, container VM `linuxkit` 5.15.49 aarch64.
- **`cryptography==46.*` is pinned.** With 47/48/49/50 the container dies at import with exit 132
  (SIGILL) and no output; bisected to `pypdf/_crypt_providers/_cryptography.py` →
  `cryptography.hazmat.bindings._rust`. Not seccomp (`--security-opt seccomp=unconfined` and
  `--privileged` both still SIGILL) — the newer Rust bindings emit instructions the Dec-2022
  linuxkit 5.15.49 VM kernel does not tolerate. The pin is safe because the container has no
  network and cryptography does no TLS there; the README records the bisect and the exit condition
  (drop the pin once the build host has a newer Docker VM kernel).
- Without the image (or with `CLUE_SANDBOX_ENABLED=false`, the default), `run_python` refuses
  `sandbox_unavailable` and names `make sandbox-image` — and a PDF/Office attachment is simply
  unreadable to the agent. Accepted by ruling.

### Owed (founder-triggered) — the live walk, NOT run
Nothing below was executed by any agent: no image was built for a walk, no `.env` was edited, no
stack was started or restarted. Preconditions, then six steps in a project chat.

Preconditions: build the image on the host that runs the workers (`make sandbox-image`); set
`CLUE_SANDBOX_ENABLED=true` in the lane `.env` (it ships `false`); restart the workers so the flag
and the registry are composed. No migration is needed — this plan added none; the lane DB stays at
head `d659c2d2b537`.

1. Attach a spreadsheet (`.xlsx`) and ask for a column total. Expect a `run_python` receipt in the
   inspector and a number in the reply with the sheet named.
2. Attach a PDF and ask for a figure on page 3. Expect the figure, read inside the run.
3. Attach a scanned (image-only) PDF and ask what it says. Expect OCR inside the run — the agent's
   own call, not a platform step.
4. Attach a `.md` and ask about it. Expect a `read_file` and **no** sandbox run.
5. Ask for a CSV derived from the spreadsheet. Expect `outputs/<name>.csv` in `files_written`.
6. Upload a file whose magic bytes contradict its extension. Expect the composer chip to fail with
   the reason (`UPLOAD_NOT_A_DOCUMENT`).

Record each outcome, and any defect, in this note.

## 2026-09-20 — ruling: the sandbox is ON by default

Founder flipped `.env.example` to `CLUE_SANDBOX_ENABLED=true` (f724a3971) and asked for on-by-default.
Aligned: `Settings.sandbox_enabled` default → `True`, the settings test, the `.env.example` comment,
the sandbox README, spec §3.4, the `[chat×sandbox]` CLAUDE.md bullet, the frontend contract note.
Consequence accepted: a worker host without the image gets `sandbox_unavailable` refusals rather
than a silently-off feature; `make sandbox-image` is part of bringing up a worker host. Earlier
lines in this note that say "ships off" describe the draft, not the current default.

## 2026-09-20 — the document/sandbox live walk (DONE) and what it found

Stack: `./scripts/dev_stack_damascus.sh down && up` on `04f646611` with the new sandbox preflight
(`sandbox: enabled, image clue-agent-sandbox:latest present`). The dev Clerk login
(`user_3IKQVDrelC8L14jV0dQ5KaIbgqF`) had no `auth_identity` row in `clue_damascus` (API answered
`IDENTITY_NOT_PROVISIONED`, app looped to /onboarding/profile); mapped it by hand to
`usr_f73d28c95a32407ca0c4beaae8f5623a` (workspace "Insight Health AI", 5 projects) — same
treatment as hangzhou. Fixtures generated inside the sandbox image (`/tmp/damascus_walk`).
Walk in one new Home-composer project ("Q3 pipeline acceleration", thread thr_0a861a54…):

1. `q3-pipeline.xlsx` + "total ACV?" → one `run_python` (507 ms), answered 509,000 USD from sheet
   Pipeline C2:C6 and correctly said C8's `=SUM` had no cached value. PASS.
2. `review.pdf` + "figure on page 3?" → quoted the page-3 sentence verbatim from the text layer. PASS.
3. `scanned-invoice.pdf` (no text layer) → OCR'd inside the run (rendered 1667×556, tesseract),
   returned invoice 7731 / 4,250 USD / 30 Sep 2026 with the "OCR can misread" caveat. PASS.
4. `brief.md` → answered from the file with NO sandbox run (run_python count unchanged). PASS.
   One "Complete a project step: Failed" chip on this turn = `agent.tool_repair` (a mis-argued
   tool call the runtime repaired), not an attachment issue.
5. "write a CSV under outputs/" → FIRST ATTEMPT FAILED THE TURN: the script wrote
   `outputs/q3-pipeline-accounts-by-acv.csv` correctly but finalize's `snapshot_outputs` walk
   raised `WorkspaceSecurityError: workspace file permissions are not private` — the container
   writes 0644 files / 0755 dirs (daemon umask; Docker Desktop maps the owner to the host user)
   and the backend demands 0600/0700. Fix `04f646611`: the sweep now chmods every surviving file
   to 0600 and every walked directory to 0700, removes hard links (`hard_linked`) and un-chmod-able
   files (`not_private`); two tests. Re-run after `restart-workers`: turn finalized, outputs/
   snapshotted and emptied, agent reported path + 5 rows. PASS.
6. `not-really.pdf` (text bytes) → API 422 `UPLOAD_NOT_A_DOCUMENT`, chip rendered red, send
   disabled. PASS.

Residuals seen: (a) on a LINUX worker host the container's files are owned by uid 65534, the
worker cannot chmod them, and the sweep will delete them as `not_private` — pass `--user <host
uid>` there or add a userns remap before relying on outputs; (b) `outputs/` reaches the human only
as artifacts at finalize, nothing renders it; (c) the runbook preflight is in `dev_stack.sh`, so
every lane wrapper on THIS branch inherits it — other worktrees' copies get it when they merge.
