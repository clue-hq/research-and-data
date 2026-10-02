# Scene-ad editor clipboard — copy/cut/paste/duplicate + external image ingestion: design + implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task-by-task (subagent dispatch is revoked by standing founder rule 2026-08-27 — one
> accountable agent, inline execution). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Copy, cut, paste and duplicate scene nodes (images, text boxes, shapes, containers with
their subtrees) inside and across scene documents, plus paste/drop of external PNG/JPG/JPEG/SVG
images and plain text onto the canvas — all riding the document's real undo/redo.

**Architecture:** A versioned clipboard DTO (Figma/tldraw-style) serialized from the scene's flat
node map, carried on the OS clipboard inside a `text/html` envelope (`data-clue-scene` attribute)
with `text/plain` and (for image nodes) `image/png` sibling representations; paste runs a
classifier (internal > envelope > image files > SVG markup > plain text), then validation → id
re-mint → placement planning → one `applyOps` batch. External images reuse the shipped
`POST /assets` ingestion verbatim. No engine (Rust) changes; no API changes; no migrations.

**Tech Stack:** TypeScript (apps/frontend), existing `Operation`/`StructuredEdit` write channels,
ClipboardEvent + async Clipboard API, vitest.

**Spec:** Founder rulings 2026-09-01 (this doc §"Founder rulings") + the clipboard-architecture
research note (`.context/attachments/8vTXI2/pasted_text_2026-09-01_22-03-23.txt`, non-durable —
its load-bearing conclusions are restated in §Design so this plan stands alone).

## Global Constraints

- Platform editor only (`apps/frontend/src/features/design-editor`); the design subsystem's own
  editor copy is untouched (standing practice, rich-text lane precedent).
- Scene (ad) documents only; web documents out of scope.
- Single-node selection is the shipped selection model (`selectedNodeId`); multi-select is NOT in
  scope and nothing here may assume it arrives.
- All writes go through `SceneManualEdits.applyOps(operations, intent)` /
  `applyEdit(StructuredEdit)` (`hooks/use-scene-manual-edits.ts:78-181`) — never a bespoke
  transport. One user action = one batch = one undo frame.
- Keyboard interception follows the `scene-arrange.ts` pattern: pure event→intent functions,
  `isTypingTarget` guard mandatory (chords must never steal from inspector fields or the
  rich-text overlay/textarea).
- Clipboard payloads are UNTRUSTED input always (even with our marker): decode → size check →
  schema validation → semantic validation (asset existence) → THEN model objects. Never
  `innerHTML` pasted HTML; parse with `DOMParser` and read attributes only.
- External image formats: `image/png`, `image/jpeg` (.jpg/.jpeg), `image/webp`, `image/svg+xml` — enforced
  client-side for honest early refusal; the server's `ingest_asset` sniff remains authoritative.
- Frontend gate per task: focused vitest files, then
  `npm run design-system:build && npm run lint && npm run build` at rung close (suite baseline
  2246 pass / 0 fail — from the rich-text close-out; must not regress).
- Local commits only; no push; no AI attribution trailers.

## Ground truth (verified in-session 2026-09-01, file+line)

- `engine/scene/operations.ts:218` `insertNode(parent: ParentRef, index: number, node: Node)` and
  `:312` `removeNode(nodeId)` exist with ZERO production callers — this lane is the first manual
  node-lifecycle surface. `ParentRef = {kind:"page",id} | {kind:"node",id}` (`contracts.ts:884`).
- `contracts.ts:165` `Node { id, name, kind, transform, size, children: NodeId[], fills, strokes,
  … }` — the scene is a FLAT node map; children are id arrays. Subtree copy = closure over ids;
  subtree paste = parents-before-children `insertNode` ops in one batch.
- `contracts.ts:317` `ImageNode { asset_id, alt }`; `:342` `AssetKind` includes `raster_image`
  and `vector`. Assets are workspace-scoped (uploaded via BFF, no document id) → same-workspace
  cross-document paste reuses `asset_id` with no re-upload; cross-workspace paste must refuse.
- `data/assets.ts:41` `uploadWebAsset(file, {fetchImpl}) → Promise<AssetRecord>` posts multipart
  to `${DESIGN_API_BFF_PREFIX}/assets`; server route `lumen_api/main.py:6544` size-caps and
  mime-sniffs (PNG/JPEG/WebP/SVG named at `:1968`).
- `canvaskit/imageCache.ts:20-41` rasterizes SVG assets in-browser (power-of-two buckets, 4096
  cap) — pasted SVGs paint with zero new render work.
- Undo: `applyOps` batches and `StructuredEdit.inverse_operations` both land in the document's
  persisted undo stacks (`use-scene-editing-session.ts` depth wiring; menu rows disable off real
  depths). Nothing extra to build for "part of undo/redo".
- `structuredEdits.ts:104` `deleteEdit(target)` exists (cut's second half); `:167-172` is the
  id-minting precedent (`grp-` + `crypto.randomUUID().slice(0,8)` with collision retry).
- `scene-arrange.ts:289,359` — the chord-intent pattern + `isTypingTarget` guard to replicate.
- AD4.C lesson (CLAUDE.md backlog): pointer coordinates are PAGE-space; a node inserted under a
  non-page parent needs rebasing against `parentComputedOrigin`. Drop placement must pin this.
- Rich-text overlay (`scene-artifact-canvas.tsx` rung-C block): `beforeinput` predict-then-verify
  + diff-remap already covers `insertFromPaste` for the text session — Task 11 pins it with
  tests rather than building anything.

## Founder rulings (2026-09-01, all binding)

1. **Placement:** drop point for drag-drops; offset cascade (+10,+10 per repeat) for ⌘V/⌘D;
   viewport center for external-file ⌘V (no pointer in paste events).
2. **Paste with an auto-layout container selected inserts INTO it** (child at end, index insert —
   no transform authored; C-9/freeze rules inherited as-is). Otherwise: source's parent when
   pasting into the same page, else page root, freehand transform.
3. **Cross-document paste: YES** (same workspace; the OS-clipboard envelope makes cross-tab free;
   cross-workspace asset refs refuse honestly).
4. **Outbound to other apps:** shapes/polygons/vector nodes — OUT of v1. Image nodes (png/jpg/
   jpeg/svg assets) must paste into external apps as an image; text nodes as plain text.
5. **External SVG: both** file paste/drop AND `<svg` markup sniffed from text clipboards.

## The ladder

- **Rung A** — internal clipboard: DTO, serializer, envelope codec, ⌘C/⌘X/⌘V/⌘D, placement,
  undo. Ships alone (feature-complete for internal work).
- **Rung B** — external ingestion: image files via paste + drag-drop, SVG markup sniff, plain-text
  paste, refusal surfaces.
- **Rung C** — outbound representations (readable `text/plain` always; `image/png` for image-node
  copies) + text-session paste pinning + live walk.

## Design

### The DTO (rung A)

`adapter/scene-clipboard.ts`:

```ts
export const SCENE_CLIPBOARD_KIND = "clue.scene/clipboard";
export const SCENE_CLIPBOARD_MIME = "application/vnd.clue.scene+json";
export interface SceneClipboardPayloadV1 {
  kind: typeof SCENE_CLIPBOARD_KIND;
  version: 1;
  workspaceHint: string | null;   // display/debug only — NEVER trusted for auth
  roots: NodeId[];                // v1: exactly one root (single selection)
  nodes: Node[];                  // root + full descendant closure, verbatim contracts.Node
  assetIds: AssetId[];            // referenced by any ImageNode in `nodes` (workspace-scoped refs)
  bounds: { x: number; y: number; width: number; height: number }; // root's page-space box
  readableText: string;           // pre-extracted text-node contents, for text/plain
}
```

Deliberately a DTO, not the live store: `Node` is already a serializable contract type, so the
DTO reuses it verbatim (DRY) but the envelope carries `version` + `kind` so a future contract
drift becomes a migration, not a crash (tldraw lesson). Spans ride inside `TextNode` untouched.

### Envelope + representations (rungs A/C)

- `text/html`: `<span data-clue-scene="{base64(JSON.stringify(payload))}"></span>` — the
  Figma-style carrier that survives OS clipboards, tab closes, and cross-tab paste.
- `SCENE_CLIPBOARD_MIME` via `setData` — best-effort same-browser fast path.
- `text/plain`: `payload.readableText` (human-readable — NEVER the JSON; the Excalidraw
  Safari-leak lesson).
- Image-node copy additionally writes `image/png` via ONE async
  `navigator.clipboard.write([ClipboardItem{html, png, plain}])` inside the copy gesture
  (activation present), falling back to sync `setData` (no png) when the async write rejects.
  JPEG/SVG assets rasterize to PNG through an offscreen canvas / the imageCache SVG path.
- Size cap on the envelope: 1 MiB of JSON (a scene subtree is structure, not pixels; anything
  larger is a bug). Refusal message on overflow, copy still writes text/plain.

### Paste classifier (rung B)

Priority: `SCENE_CLIPBOARD_MIME` > `data-clue-scene` in text/html > `clipboardData.files` with an
allowed image mime > `text/plain` starting (after trim/XML-prolog skip) with `<svg` > bare
`text/plain`. Snapshot ALL of `clipboardData` synchronously BEFORE any await (Firefox drops the
DataTransfer after async boundaries — Excalidraw lesson), then `event.preventDefault()` only when
we actually own the paste (guards below), then the async import.

### Guards (rungs A/B)

A copy/cut/paste handler runs only when the editor owns the interaction: edit mode is on, a scene
document is armed, and `!isTypingTarget(event.target)` (the overlay textarea and every inspector
field keep their native clipboard). Cut and paste additionally require `canApply()`. Refusals that
have a reason speak through the existing `reportError` channel (no silent-refusal repeats of the
rich-text residual).

### Import pipeline (rungs A/B)

decode → size check → `validateClipboardPayload` (shape + version + kind) → semantic validation
(every `assetIds` entry must resolve in this workspace's asset store — refuse the paste with a
named reason if any is missing, do not strip silently) → `remintSubtree` (fresh ids via the
`grp-` precedent pattern generalized to `node-`; children arrays rewritten; `name` suffixed
`_2`-style on collision with sibling names) → placement plan → `Operation[]` (parents-first
`insertNode`s) → one `applyOps(ops, "clipboard.paste")`.

### Placement planner (rung A; the AD4.C-sensitive part)

```ts
export type PastePlacement =
  | { kind: "into-layout"; parent: ParentRef & { kind: "node" }; index: number }        // ruling 2
  | { kind: "freehand"; parent: ParentRef; transform: Transform };                       // rebased
export function planPastePlacement(args: {
  scene: Scene; pageId: PageId;
  selectedNodeId: NodeId | null;
  payloadBounds: SceneClipboardPayloadV1["bounds"];
  mode: { kind: "paste-cascade"; generation: number }        // ⌘V/⌘D: +10*(g) x/y from source
       | { kind: "drop-point"; pagePoint: { x: number; y: number } }
       | { kind: "viewport-center"; center: { x: number; y: number } };
  parentComputedOrigin: (nodeId: NodeId) => { x: number; y: number };  // injected, like AD4.C tests
}): PastePlacement
```

Freehand transforms are authored PARENT-RELATIVE: page-space targets are rebased against
`parentComputedOrigin` before they enter a transform (the F9 lesson, pinned with the same
injected-origin test style AD4.C-3a used). Inserting into an auto-layout is an index insert and
authors NO transform.

### External image ingestion (rung B)

One path for paste-files, drop-files, and sniffed SVG markup (synthesized into a
`File(["<svg…"], "pasted.svg", {type:"image/svg+xml"})`): client allowlist check → size cap
mirror → `uploadWebAsset(file)` → refuse loudly if the returned `AssetRecord.status` ≠ `ready` →
`insertNode` with `ImageNode { asset_id, alt: file.name }`, sized to the asset's intrinsic
`media` box scaled to fit within 60% of the page's short side (deterministic, no magic), placed
per ruling 1. Drop wiring: `dragover` (preventDefault + copy effect) + `drop` on the stage
element; drop point converted stage→page through the existing viewport model, then rebased.

### Plain-text paste (rung B)

- Text node selected (no session open): `updateTextNode` content replacement, spans remapped via
  the shipped `spansVectorForContentEdit` (rich-text machinery, reused not rebuilt).
- No/other selection: a new kit-styled `TextNode` at viewport center (founder-visible default;
  matches every canvas tool studied).
- Session open / inspector focused: NOT ours — `isTypingTarget` already routed it natively.

### Error handling (all rungs)

Every refusal is loud and specific through `reportError`: unsupported file type (names the
allowlist), payload too large (names both caps), corrupt/foreign envelope ("not a Clue scene
clipboard"), missing assets on cross-workspace paste ("this image belongs to another workspace"),
upload failure (server detail passed through), not-armed/read-only (reuses the write-gate's
existing vocabulary). A refused paste never half-applies: validation completes before the first
op is enqueued (single batch = atomic by construction).

### Testing

Pure logic (serializer, codec, classifier, re-mint, placement) gets exhaustive vitest coverage
including: subtree closure with spans preserved byte-identical; id collision retry; children
rewrite; name suffixing; envelope round-trip; truncated/oversized/foreign/malicious payloads
(extra keys, wrong kinds, script-bearing HTML around the span); classifier priority matrix;
placement rebase red-cases (the F9-style page-absolute-into-parent-relative wrong answer pinned);
cascade generations. Event wiring gets jsdom ClipboardEvent/DataTransfer tests where jsdom
allows, pure-intent tests elsewhere (the scene-arrange precedent). The live walk (Task 12) covers
what jsdom cannot: real OS clipboard, real cross-tab, real drops, Figma-interop spot-check.

## Founder-visible defaults — ALL RATIFIED by founder 2026-09-01 (second pass)

1. New-text-node-on-plain-paste when nothing suitable is selected (vs. refusing).
2. Pasted-image sizing: fit within 60% of the page's short side at intrinsic aspect —
   DOWNSCALE-ONLY: an image already smaller than that box pastes at natural size, never upscaled.
3. Envelope cap 1 MiB / external file cap mirrors the server's `asset_max_bytes`.
   (WebP admitted to the inbound allowlist by founder ruling 2026-09-01 — second pass; outbound
   external-app copies still convert to PNG via `rasterToPngBlob`, so WebP needs no outbound work.)
4. Duplicate (⌘D) bypasses the OS clipboard entirely (internal fast path, no clipboard mutation).
5. `workspaceHint` rides the payload for debuggability but is never trusted; asset resolution is
   the actual cross-workspace gate.

## Out of scope (recorded)

Multi-select copy; outbound rendering of shape/vector nodes as images (ruling 4); web-document
editor; clipboard-history UI; `web application/…` custom formats (progressive enhancement
later — WebKit/Firefox support is not there yet, per the research note).

---

## Implementation plan (each task: TDD, focused tests, then the frontend gate; local commit per task)

### Task 1: Clipboard DTO + serializer (`serializeSubtree`)

**Files:**
- Create: `apps/frontend/src/features/design-editor/adapter/scene-clipboard.ts`
- Test: `apps/frontend/src/features/design-editor/adapter/scene-clipboard.test.ts`

**Interfaces:**
- Consumes: `Scene`, `Node`, `NodeId`, `AssetId` from `../engine/scene/contracts`.
- Produces: `SCENE_CLIPBOARD_KIND`, `SCENE_CLIPBOARD_MIME`, `SceneClipboardPayloadV1` (shape in
  §Design), `serializeSubtree(scene: Scene, pageId: PageId, rootId: NodeId): SceneClipboardPayloadV1 | null`
  (null when the root id resolves to no node), `extractReadableText(nodes: Node[]): string`
  (text-node contents, document order, newline-joined).

- [x] **Step 1: failing tests** — root+descendants closure (a group with two children serializes 3
  nodes, `roots:[groupId]`); an ImageNode contributes its `asset_id` to `assetIds` exactly once;
  a TextNode with spans serializes spans byte-identically; `readableText` joins two text nodes in
  document order; unknown root → null; bounds equal the root's page-space box (use the fixture
  `engine/scene/__tests__/__fixtures__/minimal_scene.json` the rich-text tests already use).
- [x] **Step 2: run — expect FAIL** (ran `npx tsx --test …/scene-clipboard.test.ts` — the app's real
  runner per `package.json` "test"; the vitest name here was a plan drift. FAILED as expected.)
- [x] **Step 3: implement** (pure functions; closure via iterative stack over `children`)
- [x] **Step 4: run — expect PASS** (12/12 green; eslint clean)
- [x] **Step 5: commit** `feat(design-editor): scene clipboard DTO + subtree serializer` (`e60891231`)

### Task 2: Envelope codec (`encodeClipboardHtml` / `decodeClipboardHtml`)

**Files:**
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-clipboard.ts`
- Test: extend `scene-clipboard.test.ts`

**Interfaces:**
- Produces: `encodeClipboardHtml(payload: SceneClipboardPayloadV1): string | null` (null when the
  JSON exceeds `CLIPBOARD_ENVELOPE_MAX_BYTES = 1_048_576`),
  `decodeClipboardHtml(html: string): SceneClipboardPayloadV1 | null`,
  `validateClipboardPayload(value: unknown): SceneClipboardPayloadV1 | null`.

- [x] **Step 1: failing tests** — round-trip identity; decode uses `DOMParser` and reads ONLY the
  `data-clue-scene` attribute (a payload wrapped in `<script>`-bearing HTML round-trips without
  any element being live-injected — assert no side effects, parse-only); foreign HTML → null;
  wrong `kind`/`version`/shape → null; extra unknown top-level keys → null (strict); oversized →
  encode returns null; base64 garbage → null (no throw). (Plus: UTF-8-byte cap measurement,
  non-ascii round-trip, non-self-contained node graphs refused. jsdom added as devDependency —
  the runner is node:test with no DOM; Tasks 6–7 need it regardless.)
- [x] **Step 2: run — FAIL** (13 new red) → **Step 3: implement** → **Step 4: PASS** (25/25; eslint clean)
- [x] **Step 5: commit** `feat(design-editor): clipboard html envelope codec with strict validation` (`09af583c6`)

### Task 3: Subtree re-mint (`remintSubtree`)

**Files:**
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-clipboard.ts`
- Test: extend `scene-clipboard.test.ts`

**Interfaces:**
- Consumes: the `grp-` minting precedent (`engine/scene/structuredEdits.ts:167`).
- Produces: `remintSubtree(payload: SceneClipboardPayloadV1, existingIds: ReadonlySet<string>,
  siblingNames: ReadonlySet<string>): { nodes: Node[]; rootId: NodeId }` — fresh `node-XXXXXXXX`
  ids for every node, `children` arrays rewritten through the old→new map, root `name` suffixed
  (`headline` → `headline_2`, `_3`, … against `siblingNames`), descendants keep names.

- [x] **Step 1: failing tests** — every output id is fresh and absent from `existingIds`;
  children arrays reference only re-minted ids; deterministic structure (same shape, new ids);
  name collision suffixes correctly incl. an existing `_2`; id collision with `existingIds`
  retries (inject a colliding-first fake `randomUUID` like the structuredEdits tests do —
  done via node:test `mock.method`, this suite's native equivalent of the vitest-shim spy;
  plus batch self-collision retry, null-name root, payload-not-mutated).
- [x] **Steps 2–4: FAIL (6 red) → implement → PASS (31/31; eslint clean)** — **Step 5: commit**
  `feat(design-editor): clipboard subtree re-mint with reference rewrite` (`4384e4154`)

### Task 4: Placement planner (`planPastePlacement`)

**Files:**
- Create: `apps/frontend/src/features/design-editor/adapter/scene-clipboard-placement.ts`
- Test: `apps/frontend/src/features/design-editor/adapter/scene-clipboard-placement.test.ts`

**Interfaces:**
- Consumes: `Scene`, `ParentRef`, `Transform` contracts; injected
  `parentComputedOrigin(nodeId)` (test-injectable, AD4.C style).
- Produces: `PastePlacement` union + `planPastePlacement(args)` — exact signature in §Design.

- [x] **Step 1: failing tests** — (a) selected auto-layout container → `into-layout` at
  `children.length` with NO transform; (b) cascade generation g → source position +10g/+10g,
  parent = source's parent, transform PARENT-RELATIVE; (c) drop at page point under a non-page
  parent → rebased by injected origin, and the RED case pins that the un-rebased page-absolute
  answer is wrong (F9's exact failure shape); (d) viewport-center mode centers `payloadBounds`;
  (e) locked/managed selected node falls through to page-level freehand.
- [x] **Steps 2–4: FAIL → implement → PASS** (11/11; SDD Opus implementer, review Approved) —
  **Step 5: commit** `feat(design-editor): paste placement planner (rulings 1-2, F9 rebase pinned)`
  (`863c6b6ca`; orchestrator rulings R2–R5 in the SDD ledger settle parent derivation, drop
  centering, into-layout-never-on-drop, and position-only transforms)

### Task 5: Materialization (`materializeClipboardPayload`) — payload → ops

**Files:**
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-clipboard.ts`
- Test: extend `scene-clipboard.test.ts`

**Interfaces:**
- Consumes: `remintSubtree` (Task 3), `PastePlacement` (Task 4), `insertNode` from
  `../engine/scene/operations`.
- Produces: `materializeClipboardPayload(scene: Scene, payload: SceneClipboardPayloadV1,
  placement: PastePlacement, knownAssetIds: ReadonlySet<string>):
  { ops: Operation[]; rootId: NodeId } | { refusal: string }` — parents-before-children
  `insertNode` ops; root gets the placement (transform or index); refusal when any
  `payload.assetIds` entry is missing from `knownAssetIds` (message names the count).

- [x] **Step 1: failing tests** — 3-node subtree → 3 insertNode ops parents-first, root op carries
  placement; into-layout root op has the container ParentRef + index and NO transform patch;
  missing asset → `{refusal}` naming "1 image"; empty-payload → refusal.
- [x] **Steps 2–4** — **Step 5: commit** `feat(design-editor): clipboard materialization to insertNode batches`
  (`7921a3e25` + fix round `f5e95f73c`: task review caught that populated `children` arrays on
  inserted nodes trip lumen-core's `op.child_missing` and void every ≥2-node paste — ops now
  emit CHILDLESS nodes, tree expressed purely by parent ref + index, invariant pinned in test.
  Rulings R7 (position-only root transform merge) and R8 (computed:null; absolute_box shifted
  by paste delta on freehand) in the SDD ledger. 45/45 green.)

### Task 6: Paste classifier

**Files:**
- Create: `apps/frontend/src/features/design-editor/adapter/scene-clipboard-classify.ts`
- Test: `apps/frontend/src/features/design-editor/adapter/scene-clipboard-classify.test.ts`

**Interfaces:**
- Produces: `ClipboardSnapshot { internal: string; html: string; text: string; files: File[] }`,
  `snapshotClipboardData(dt: DataTransfer): ClipboardSnapshot` (synchronous, copies everything),
  `classifyPaste(snap: ClipboardSnapshot): PasteIntent` where `PasteIntent =
  {kind:"internal"; payload: SceneClipboardPayloadV1} | {kind:"image-files"; files: File[]} |
  {kind:"svg-markup"; svg: string} | {kind:"plain-text"; text: string} | {kind:"none"}`,
  `ALLOWED_IMAGE_MIMES = ["image/png","image/jpeg","image/webp","image/svg+xml"]`.

- [x] **Step 1: failing tests** — priority matrix: internal mime beats envelope beats files beats
  svg-text beats plain; envelope decode failure falls THROUGH to the next class (never dead-ends);
  file list filtered to allowlist (a .gif among a .png → only the png, refusal note for later);
  `<?xml…?><svg` and BOM-prefixed `<svg` both classify as svg-markup; whitespace-only text → none.
- [x] **Steps 2–4** — **Step 5: commit** `feat(design-editor): paste classifier with fall-through priority`
  (`cbfeb38f7` + fix round `08ba8471c` pinning envelope-beats-files, mutation-verified. 27/27.
  Intent extended with `rejected: string[]` per orchestrator ruling so Task 7 refuses dropped
  files loudly.)

### Task 7: Copy/cut/paste/duplicate wiring (`use-scene-clipboard`)

**Files:**
- Create: `apps/frontend/src/features/design-editor/hooks/use-scene-clipboard.ts`
- Modify: `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx`
  (register the hook beside the space-pan/arrange listeners; pass `selectedNodeId`, the manual-edits
  surface, and the viewport model)
- Test: `apps/frontend/src/features/design-editor/hooks/use-scene-clipboard.test.ts`

**Interfaces:**
- Consumes: Tasks 1–6; `SceneManualEdits.applyOps/applyEdit/canApply/reportError`;
  `deleteEdit` from `../engine/scene/structuredEdits`; `isTypingTarget` (export it from
  `adapter/scene-arrange.ts` — it is module-local today; one-line export, keep the single copy).
- Produces: `useSceneClipboard(options)` registering real `copy`/`cut`/`paste` window listeners +
  a `keydown` for ⌘D only (copy/cut/paste come from the semantic events, NEVER keydown — research
  §7); exports pure helpers `shouldOwnClipboardEvent(target, editing, armed)` and
  `buildCopyRepresentations(payload) → {internal, html, plain}` for testing.

- [x] **Step 1: failing tests** — pure halves: `shouldOwnClipboardEvent` false for typing targets
  /ungated docs/view mode; `buildCopyRepresentations` emits all three with readable plain text;
  cut composes copy + `deleteEdit(root)` only when `canApply()`; ⌘D produces a cascade-placement
  materialization WITHOUT touching any clipboard API (spy); paste with internal intent produces
  ONE `applyOps` call (single undo frame); refusals route through `reportError` with the exact
  messages from §Error handling; jsdom ClipboardEvent round-trip for copy→paste where jsdom
  permits (skip-with-comment where its DataTransfer is incomplete — the web-toolbar tests set the
  precedent).
- [x] **Steps 2–4** — **Step 5: commit** `feat(design-editor): scene clipboard events — copy/cut/paste/duplicate`
  (`097350bf4` + fix round `c935cb814`. SEAM DRIFT RECORDED (SDD ruling R16): the hook is composed
  in `use-scene-editing-session.ts` beside `useSceneArrange` — NOT `scene-artifact-canvas.tsx` —
  per the AD4.A precedent (sessions compose handler hooks; arrange registers its own window
  listeners). Fix round closed the files-only R9 hole, pinned read-only-vs-allowlist precedence,
  and made copy/cut yield to a live DOM text selection. Suite 39 (38+1 jsdom skip); full
  frontend `npm test` 2396/2395/0.)

### Task 8: External image ingestion (paste-files + drop + SVG markup)

**Files:**
- Create: `apps/frontend/src/features/design-editor/hooks/use-scene-image-paste.ts`
- Modify: `hooks/use-scene-clipboard.ts` (route `image-files`/`svg-markup` intents here);
  `components/scene-artifact-canvas.tsx` (stage `dragover`/`drop` listeners → drop-point placement)
- Test: `apps/frontend/src/features/design-editor/hooks/use-scene-image-paste.test.ts`

**Interfaces:**
- Consumes: `uploadWebAsset` (`data/assets.ts:41`, mock in tests); `planPastePlacement`;
  `insertNode`; `ALLOWED_IMAGE_MIMES`.
- Produces: `ingestExternalImages(files: File[], placement: PastePlacement, deps) →
  Promise<{inserted: number; refusals: string[]}>`; `svgMarkupToFile(svg: string): File`;
  `pastedImageNodeSize(media: {width:number;height:number}, page: {width:number;height:number})`
  (fit-within-60%-short-side rule, downscale-only).

- [x] **Step 1: failing tests** — png file → upload called once, one insertNode ImageNode with
  returned `asset_id` and `alt` = filename; `status:"pending"` record → refusal naming the label,
  NO insert; disallowed mime → refusal naming the allowlist, upload NOT called; svg markup →
  synthesized File with `image/svg+xml` routed down the same path; sizing rule: 4000×2000 image on a 1080×1080
  page → 648-wide fit; a 200×100 image pastes at 200×100 (downscale-only, never upscaled); multi-file paste inserts with per-file cascade; upload rejection surfaces
  the server detail verbatim.
- [x] **Steps 2–4** — **Step 5: commit** `feat(design-editor): external image paste/drop ingestion`
  (`a381e2618` + fix round `ba7f06162`. Review caught that the batch never REGISTERED the uploaded
  asset — a plan-interface omission — so every pasted image would have been a blank dangling
  ref; ops are now `upsert_asset` + `insert_node` per file in ONE batch. Ground-truth correction:
  intrinsic dimensions live in `raster.pixel_width/height` / `vector.width/height`, not `media`.
  Rulings R20–R25 + R21a–c (scene-unit coordinates via `descriptorToScene`, unbounded
  off-artboard drops, both ArtifactStage mounts wired) in the SDD ledger. 26/26; frontend
  `npm test` 2420/2419/0.)

### Task 9: Plain-text paste behavior

**Files:**
- Modify: `hooks/use-scene-clipboard.ts`
- Test: extend `use-scene-clipboard.test.ts`

**Interfaces:**
- Consumes: `updateTextNode` (`engine/scene/operations.ts`) and `spansVectorForContentEdit`
  (rich-text machinery in `engine/scene/textSpans.ts`) — reuse, do not re-implement.
- Produces: plain-text intent handling per §Design; `newTextNodeFromPaste(text, placement,
  kitDefaults): Node`.

- [x] **Step 1: failing tests** — selected TextNode → one updateTextNode op whose spans vector
  came from `spansVectorForContentEdit` (spy on the real fn) — never a raw spread; spanned node +
  full replacement → spans remap per that function's own contract; nothing selected → one
  insertNode with a TextNode carrying the pasted characters at viewport center; selected
  ImageNode → falls through to new-text-node (not a content write on an image).
- [x] **Steps 2–4** — **Step 5: commit** `feat(design-editor): plain-text paste — replace selected text or mint a text node`
  (`f7912cc8c`, review approved first pass. Plain text is now the hook's own — the Task-7
  `onPlainText` seam is removed (R26). The minted node rides the SAME plan→materialize pipeline as
  internal paste (R28: Inter/16/400, 60%-short-side fixed width, hug height, solid #111111 fill);
  the spans function is injected-with-real-default because ESM bindings cannot be spied (R27).
  45-test suite; frontend `npm test` 2428/2427/0.)

### Task 10: Outbound representations for image nodes (ruling 4)

**Files:**
- Modify: `hooks/use-scene-clipboard.ts`; `adapter/scene-clipboard.ts`
- Test: extend both test files

**Interfaces:**
- Consumes: asset bytes via the existing BFF asset URL (`DESIGN_API_BFF_PREFIX`), offscreen
  canvas rasterization; the imageCache SVG-rasterize approach (replicated minimally for export —
  a pure `rasterToPngBlob(source: Blob, mime: string): Promise<Blob>`).
- Produces: copy of a selection whose root is an ImageNode attempts ONE
  `navigator.clipboard.write([ClipboardItem({"text/html": …, "image/png": …, "text/plain": …})])`
  inside the copy event (activation window), and on ANY rejection falls back to the Task-7 sync
  `setData` path (envelope + plain only) — the internal payload must never be lost to a png
  failure.

- [x] **Step 1: failing tests** — representation builder returns all three blobs for a png asset;
  jpeg/webp/svg route through `rasterToPngBlob`; `clipboard.write` rejection → sync fallback invoked,
  envelope intact (spy sequence); non-image roots never call `clipboard.write` (ruling 4 scope).
- [x] **Steps 2–4** — **Step 5: commit** `feat(design-editor): image-node copies carry image/png for external apps`
  (`b86d3dd81` + fix round `7bae72643`. DESIGN AS BUILT (ruling R31): the sync `setData` trio is
  the baseline and is written FIRST; the async `ClipboardItem` write (html/plain/promise-png) is
  additive, issued synchronously inside the copy event, and every failure — rejection OR
  synchronous constructor throw (Firefox) — is swallowed, so the internal payload can never be lost
  to a png failure. Known, accepted cost: a successful async write replaces the custom-mime fast
  path with the envelope (browsers allowlist ClipboardItem types; fidelity preserved). Decode
  branches of `rasterToPngBlob` are un-testable offline — Preview/Slack spot-check owed at Task 12.
  55-test hook suite; frontend `npm test` 2440/2439/0.)

### Task 11: Text-session paste pinning (probably already green)

**Files:**
- Test: extend the overlay/session test files beside
  `components/scene-artifact-canvas.tsx`'s existing rung-C coverage (same suites the rich-text
  lane used — `adapter/scene-text-edit.test.ts` and the session tests).

- [x] **Step 1: write the pinning tests** — `insertFromPaste` beforeinput inside a styled range
  grows/remaps spans exactly as `insertText` does (the session transition treats them
  identically); paste replacing a cross-span selection normalizes per the span algebra; a paste
  while the session is open never reaches the canvas clipboard handler (guard test).
- [x] **Step 2: run** — expected PASS (machinery shipped in the rich-text lane). PASSED on first run
  (4 pins + 1 positive control; each mutation-verified to be falsifiable). No rich-text defect.
- [x] **Step 3: commit** `test(design-editor): pin text-session paste span remap` (`a043dded4`)

### Task 12: Rung close — frontend gate + live walk

- [x] **Step 1: frontend gate** — `npm run design-system:build && npm run lint && npm run build`
  + full vitest suite; baseline 2246 must not regress; zero new lint errors. (design-system:build 0;
  lint 0 errors / 2 pre-existing warnings; `next build` completed; `npm test` 2462/2461/0/1 skip.)
- [x] **Step 2: live walk on the colombo stack** (3033, Apollo workspace, the Cursor ad), — RAN ON THE
  NASHVILLE stack (3023, clone DB) instead; every item below verified via the persisted document
  except the Preview/Slack external-app spot-check (headless cannot do it — founder-owed). Two walk
  findings fixed in `23bbd2f75` (W1 pasted-node names, W2 cross-document asset carriage).
  checklist: ⌘C/⌘V a text box (cascade lands, undo removes, redo restores); ⌘X removes + ⌘V
  restores with fresh ids; ⌘D twice cascades twice; copy a GROUP → paste → subtree intact with
  spans; paste with the card auto-layout selected → child appended (C-9 behavior observed and
  noted); drop a real .png at a point (lands at the point, correct parent rebase); paste a
  screenshot from the OS clipboard; paste `<svg>` markup copied as text; paste plain text onto a
  selected headline (content replaces, spans sane) and onto empty selection (new text node);
  cross-document: copy in the Cursor ad, paste in the Apollo ad (same workspace — assets
  resolve); copy an image node → paste into Preview/Slack as a real image; copy a text node →
  paste into a text editor as plain text; every refusal path exercised once (bad file type,
  foreign envelope) — message visible, nothing half-applied.
- [x] **Step 3: close-out memory note** (`_memory/2026-09-01-scene-clipboard-close-out.md`):
  commits, walk verdict, residuals, founder-visible defaults exercised.
- [x] **Step 4: commit** `docs(memory): scene clipboard close-out`

## Self-review (run at plan close)

Spec coverage: rulings 1–5 → Tasks 4 (1,2), 5+2 (3), 10 (4), 6+8 (5); undo requirement →
single-batch construction (Tasks 5,7); text-box paste requirement → Tasks 9,11. Placeholder scan
and type-consistency pass done 2026-09-01 (signatures cross-checked Tasks 1↔5↔7, 4↔5↔8).
