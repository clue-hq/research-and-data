# 2026-09-02 — scene-ad editor clipboard: lane CLOSE-OUT (Tasks 1–12 + walk fixes)

Plan: `docs/superpowers/plans/2026-09-01-scene-clipboard.md` (all 12 tasks ticked). Branch
`design/scene-ad-clipboard` (nashville worktree), 30 local commits from `52b6f6bf9`; nothing pushed.
Process: Tasks 1–3 inline (Fable); Tasks 4–11 + walk fixes via SDD with Opus implementers only;
from Task 10 on, every review/verification/decision was Fable's personally (founder ruling).

## What shipped (platform editor only, `apps/frontend/src/features/design-editor/`)
- `adapter/scene-clipboard.ts` — V1 DTO (kind/version-marked, carries `nodes` + `assets` records),
  serializer, html envelope codec (DOMParser parse-only, 1 MiB UTF-8 cap, strict validator),
  re-mint (fresh `node-` ids, children rewrite, readable names — null-named copies take the source id),
  materialization (childless `insert_node` batch, `upsert_asset` for records the target lacks,
  R7 position-only root transform, R8 stale-geometry hygiene, refusals before any op), and
  `rasterToPngBlob` for outbound png.
- `adapter/scene-clipboard-placement.ts` — planner: into-layout vs freehand, cascade/drop/
  viewport-center, PARENT-relative rebase (F9 pinned with the harvested group children).
- `adapter/scene-clipboard-classify.ts` — sync DataTransfer snapshot + fall-through classifier.
- `hooks/use-scene-clipboard.ts` — semantic copy/cut/paste + ⌘D keydown; composed by the SESSION
  beside `useSceneArrange` (not the canvas — AD4.A precedent); plain-text native (replace or mint);
  cross-doc asset probe via BFF; outbound `image/png` ClipboardItem offer (baseline-first, all
  failures swallowed incl. Firefox's synchronous ClipboardItem throw).
- `hooks/use-scene-image-paste.ts` — paste-files / drop / svg-markup → upload → register+insert,
  one batch per gesture, 10 MiB client cap, downscale-only 60%-short-side sizing.
- Canvas: `viewportPageCenter()` on controls + dragover/drop (scene-unit conversion via the shipped
  `descriptorToScene` divide). Session/chat-shell: pass-through wiring only. `isTypingTarget` exported.

## Gates
- Frontend `npm test`: 2462 tests / 2461 pass / 0 fail / 1 skip (jsdom cannot host ClipboardEvent);
  baseline at plan time was 2246. eslint: 0 errors (2 pre-existing warnings in canvasOperations.ts).
  `design-system:build` exit 0; `next build` completed (full route table emitted).
- Live walk on the nashville stack (3023/8013/8023, DB clue_nashville, Apollo account, Cursor ad):
  ⌘C/⌘V cascade, ⌘Z/⌘⇧Z, ⌘X+⌘V, ⌘D×2, multi-node (4-node) paste accepted by the live engine,
  into-layout append, plain-text replace + mint, PNG paste, PNG DROP at a point (coordinate
  conversion correct), SVG markup, GIF refusal sentence rendered, mixed gif+png, foreign envelope
  fall-through, cross-document text AND image paste (after W2). All verified via BFF GET of the
  persisted document. Not verifiable headless: copy image node → paste into Preview/Slack
  (Task 10 async path) — FOUNDER SPOT-CHECK OWED.

## Walk findings fixed (23bbd2f75)
- W1: pasted nodes showed "text node-XXXXXXXX" — agent nodes have null names + readable ids;
  copies now take the source id as name (root collision-suffixed against sibling display names).
- W2: same-workspace cross-document IMAGE paste refused — materialize gated on the target
  document's `scene.assets` (per-document). Payload now carries `AssetRecord`s; missing records are
  probed via `GET /api/clue/design/assets/{id}` (server tenancy = the honest cross-workspace gate,
  founder ruling 3) then upserted in the same batch.

## Residuals (all recorded; none load-bearing)
- Founder spot-check: image-node copy → Preview/Slack paste as a picture.
- Stale comment `use-scene-image-paste.ts:31-33` still names the removed `onPlainText` seam.
- Repeated plain-text pastes with no selection stack at the identical viewport center (no cascade
  in viewport-center mode) — v1 UX nit.
- `writeCopy`'s `setData` calls are unguarded after `preventDefault` (read side guards getData).
- Allowlist sentence can drift from `ALLOWED_IMAGE_MIMES` (no pairing test).
- `rasterToPngBlob` decode branches untestable offline (jsdom); png passthrough + no-DOM reject pinned.
- `EXPORT_SVG_FALLBACK_SIDE` restates imageCache's constant (deliberate, avoids the CanvasKit import).
- Canvas controls object re-created per pan frame while artboard is null (consumers read `.current`
  in handlers — safe). Test-only fixture `vectorRecord()` still labelled "pasted-image.svg".
- Design-subsystem's own editor copy untouched (standing practice).
- Plan-text drift recorded in the plan: runner is `tsx --test` not vitest; the hook's seam is the
  session not the canvas; intrinsic image dims live in `raster.*`/`vector.*` not `media`.

## Nashville workspace facts
See `_memory/2026-09-01-nashville-workspace-setup.md` (ports, DB clone, blob-store gap). Stack left
RUNNING for the founder's spot-check. The Cursor ad document carries the walk's pasted test nodes.
