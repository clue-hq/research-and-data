# 2026-08-19 — Ad-design (scene) editor integration: study + plan authored

## What happened
Founder asked for a thorough study and a plan of action for integrating the CanvasKit/SkParagraph
**scene (ad-design) editor** into the platform, merged with the dummy frontend's ad inspector —
the sibling of the W0–W5 website-editor integration. Three parallel Opus scouts swept (1) the
W0–W5/chat-flow precedent on this branch, (2) the scene editor stack in
`subsystems/clue-design`, (3) the dummy ad editor at
`/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain` (branch `codex/chat-shell`,
HEAD `c7f2bc5`). Synthesis written as
**`docs/superpowers/plans/2026-08-19-ad-editor-integration.md`** (DRAFT — gated on the founder
ruling its D1–D12 decision register). No code changed.

## Load-bearing findings (verified by the scouts, anchors in the plan doc)
- Dummy ad editor = a mode of the same chat shell (`kind=ad` / `?surface=ad`); its canvas is a
  **deliberately empty div** (`artifact-stage.tsx`, "Empty ad output canvas") — the designed
  CanvasKit mount hole. ~90% chrome shared with web; `image-inspector.tsx` + export menu already
  lifted in W0 and inert in `apps/frontend`. The dummy has **no ad data model** at all; a tool
  palette (icons/CSS/`editor.*` events) was authored but never built; zoom is a decorative
  string.
- Scene editor: CanvasKit wasm (no COOP/COEP, no workers — embed-friendly), authoritative Rust
  hit-testing, SVG selection overlay, `editQueue` CAS richer than the web controller, 21-op
  vocabulary, TTF-only fonts with measure-then-inject + heuristic fallback banner, engine-stamp
  handshake couples browser wasm to `lumen-api-helper` commit. Scene API = unprefixed
  `/documents/*` routes; export formats Svg|Png|Pdf|FigmaManifest (**no JPEG** — dummy offers it).
- Platform today: Part II fully covers scenes (tables/toolbelt/fleet/stream). Part III: scene
  legs dispatch `agent_turn` but the **proposal is dropped on the floor** (accept seam lives
  only in the standalone editor's `useAgentTurn`; scene turns are propose→accept, web turns
  commit server-side — the biggest structural asymmetry). Legs refuse scene creation
  (`design_leg_scene_creation_unsupported`). Gallery feed SQL-filtered `doc_kind='web'`
  (`design_leg_wiring.py:458`). Frontend has zero scene modules, no canvaskit dep.
- Three conflicting ad size-preset vocabularies (dummy / PageRail / Rust `PagePreset`) need one
  ratified set.

## Plan shape
AD-R (control inventory → frozen `ad-inspector-mapping-contract.md`, the 42-item exercise for
ads) → AD0 (shell completion: CSS/icon audit, hoist RadiusControls, trim option sets) → AD1
(extract scene engine slice + canvaskit/lumen-wasm/fonts vendor pipeline + next.config
fallbacks + stamp preflight) → AD2 (read path: scene canvas in the artboard chrome, hitTest
selection, real layers, `useSceneEditingSession`, kind-aware gallery) → AD3 (text write flow
over editQueue CAS + undo/redo) → AD4 (fan-out lanes: canvas/gradients substrate, image,
arrange/stroke/position, D1-gated direct manipulation, export binding) → AD5 (acceptance).
Chat-loop for ads (accept path, scene birth, focus_refs) is an explicit separate follow-on plan.
~8–12 focused days.

## Follow-up same day: disparity inventory authored
Founder asked for the AD-R item-1 study itself before any ruling:
**`docs/specs/ad-editor-integration/ad-editor-disparity-inventory.md`** — a decisions-free,
control-by-control comparison of the dummy ad inspector (verified byte-identical to the inert
`apps/frontend` copies) against the clue-design scene editor + `lumen-core` model. Headlines:
no link/href concept exists on any node (dummy Link-to = NO-BACKING); no button node kind; no
visibility field; dummy image fit Stretch/Tile unmapped (engine = contain/cover/crop+focal);
the dummy's gradient editor is RICHER than the real editor's UI (engine supports gradients,
editor UI is read-only); no opacity/W/H/content/line-height/etc. in the dummy (big NO-SLOT
list); neither side has working insert tools; three conflicting size-preset vocabularies incl.
a 1200×628 vs 1200×627 off-by-one; export JPEG+transparency in dummy vs Svg/Png/Pdf engine
contract; text-wrap UI-vs-model default divergence (`no_wrap`). Founder will annotate rulings
over this inventory.

## 2026-08-20 close-out: contract FROZEN
The founder ruled everything across three passes (table annotations → OQ-1…8 → the final
rulings message): tool palette out of v1; direct manipulation = select + drag-move +
corner-resize (handles mockup-gated); color policy = brand-first + custom hex with detach note;
Background edits the ROOT FRAME's fill; button schema hidden + both Link-to sections removed;
image Mode = Fit/Fill/Crop + focal dot (mockup-gated) + in-inspector upload kept beside the AI
suite; JPEG dropped v1; plain Frame = auto-layout schema minus its AutoLayout section; W/H
modes Fixed/Hug/Fill (fixed inputs only in Fixed; no fill weights); opacity %↔0–1 at the seam;
Layout section does NOT extend to text/image/button; editor semantics for all Arrange controls;
group has no Shape/Stroke; lock real / eye omitted; **multi-select = MERGED panel (founder
override — net-new designed UI, mockup-gated)**; single artboard 100%; canvas name label
display-only; preset values corrected (LinkedIn square → 1200×1200), labels kept; fit-on-open
zoom; versions flyout inert v1. All folded into
**`docs/specs/ad-editor-integration/ad-inspector-mapping-contract.md` (v1, RATIFIED, FROZEN)**.
Pending: the co-founder commits/pushes the 23-file dummy delta (contract has a blank for the
pin hash); AD1 architecture rulings D7–D10 (recs on file); §8 has one conditional engine-change
candidate (PNG transparency flag, verify first). One interpretation to flag to the founder:
item-5 answer quoted only "remove both" (the Link sections) — button-schema hiding was the same
block's other rec and is recorded as ratified; correct if unintended.

## Open / next
- **All of D1–D12 await founder rulings** — D1 (on-canvas direct manipulation in v1) is the big
  scope call; D2 button semantics; D3 size presets; D5 gallery inclusion; D7 drop Konva; D8
  asset/font serving via headerless BFF passthrough; D12 drop JPEG.
- Unverified residuals from the scouts, to close during AD-R: whether a leg-dispatched scene
  turn has ever actually run since Part III (suspected dead code in practice); cost of
  `/export-preview` as a thumbnail source; whether `apps/editor/public/{canvaskit,wasm,fonts}`
  are gitignored build outputs (inferred yes).
