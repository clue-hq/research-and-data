"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import type { CanvasKit, Surface, TypefaceFontProvider } from "canvaskit-wasm";
import { AlertTriangleIcon } from "lucide-react";
import { textareaCommitKey } from "@/features/chat-shell/components/inspector-field-draft";
import { sceneEngineBanners } from "../adapter/scene-engine-banners";
import { scenePagelessNotice } from "../adapter/scene-pageless";
import {
  ARTBOARD_BORDER_COLOR,
  ARTBOARD_SHADOW_COLOR,
  SELECTION_HANDLE_CORNER_RADIUS,
  SELECTION_HANDLE_FILL,
  SELECTION_HANDLE_STROKE,
  SELECTION_HANDLE_STROKE_WIDTH,
  SELECTION_OUTLINE_COLOR,
  SELECTION_OUTLINE_WIDTH,
  WORKSPACE_CANVAS_FALLBACK,
  artboardChromeGeometry,
  formatZoomPercent,
  sceneArtboardModel,
  sceneAssetPassthroughUrl,
  sceneDragPanViewport,
  sceneSelectionOutline,
  sceneViewportModel,
  sceneWheelViewport,
  selectionHandleRects,
  type SceneArtboardModel,
  type ScenePreview,
  type SceneSelectionOutline,
} from "../adapter/scene-canvas-view";
import {
  EMPTY_SCENE_PRESS,
  freezeOperationsToPersist,
  pressArmedAfterFreeze,
  sceneDescriptorPoint,
  sceneGestureEffect,
  scenePressHandleTarget,
  scenePressModifiers,
  scenePressNodeTarget,
  sceneSelectionHandlesVisible,
  shouldFreezeLayoutOnPress,
} from "../adapter/scene-gestures";
import {
  representableHit,
  sceneHitPoint,
} from "../adapter/scene-selection";
import type { ScenePalette } from "../adapter/scene-palette";
import {
  SCENE_TEXT_EDIT_INTENT,
  SCENE_TEXT_STYLE_INTENT,
  sceneDoubleClickEffect,
  sceneTextEditModel,
  textEditCommitOperations,
  type SceneTextEditModel,
} from "../adapter/scene-text-edit";
import {
  textEditFormatState,
  textEditReplacement,
  textEditSessionAfterInput,
  textEditSessionAfterReplacement,
  textEditStyledSpans,
  type TextEditSelection,
  type TextEditSession,
} from "../adapter/scene-text-session";
import type { StylePatch } from "../engine/scene/textSpans";
import { SceneTextToolbar } from "./scene-text-toolbar";
import {
  sceneTextFillPatch,
  sceneTextMarkPatch,
  sceneTextStyleChord,
  type SceneTextFillChoice,
  type SceneTextMarkChannel,
} from "./scene-text-toolbar.logic";
import {
  gestureReducer,
  initialGestureState,
  type GestureAction,
  type GestureEvent,
  type GestureState,
  type PressTarget,
} from "../engine/scene/gestureMachine";
import {
  drawDescriptorTree,
  parseColor,
} from "../engine/scene/canvaskit/drawDescriptors";
import { valignOffset } from "../engine/scene/renderAdapter";
import { getNode } from "../engine/scene/sceneQueries";
import { CanvasKitImageCache } from "../engine/scene/canvaskit/imageCache";
import {
  loadCanvasKit,
  subscribeTextMeasurementStatus,
  textMeasurementStatusSnapshot,
} from "../engine/scene/canvaskit/loadCanvasKit";
import type {
  Diagnostic,
  NodeId,
  Operation,
  PageId,
  Scene,
} from "../engine/scene/contracts";
import {
  freezeLayoutEdit,
  type StructuredEdit,
} from "../engine/scene/structuredEdits";
import type {
  EngineApplyOutcome,
  EngineStructuredEditOutcome,
  HitResult,
} from "../engine/scene/wasmEngine";
import {
  defaultWorkspaceViewport,
  screenToWorkspace,
  type WorkspaceViewport,
} from "../engine/scene/workspaceViewport";
import {
  useSceneDocument,
  type SceneDocumentHistory,
  type SceneEngineStatus,
} from "../hooks/use-scene-document";
import styles from "./scene-artifact-canvas.module.css";

/**
 * AD2.3: a real ad, drawn by the real engine, inside the dummy's designed
 * artboard card.
 *
 * Derived from the design subsystem's `CanvasKitStage`
 * (`subsystems/clue-design/apps/editor/src/components/canvas/CanvasKitStage.tsx`),
 * with its mechanics ported rather than reinvented: one WebGL surface per
 * canvas element (falling back to the software surface), a dirty flag drained
 * by a single rAF (no frame runs while clean), the resize coalesced INTO that
 * same frame (resetting the bitmap blanks it, so wipe and redraw must land
 * together), and a re-armed `matchMedia` resolution watcher because
 * `devicePixelRatio` can change with no size change at all.
 *
 * AD2.10 (founder ruling, 2026-08-20) makes the port faithful where AD2.3
 * departed from it: **the stage is an infinite workspace and the artboard is a
 * page floating on it, bounded by its own edges alone** — Figma's model,
 * "nothing more and nothing less". The `<canvas>` is the whole neutral output
 * area, not the dummy's `.imageCanvas` card; the workspace clears to
 * `--bg-canvas`; the artboard carries a shadow and a hairline; and the viewport
 * pans and wheel-zooms. This RETIRES ruling 17 (fit margin 0, "the card IS the
 * artboard"), which made exactly one zoom level look right and left every other
 * one either padded (below fit) or silently clipped with no way to reach the
 * rest (above fit).
 *
 * Two deliberate departures from the source stage remain:
 *
 * - **One artboard.** The platform mounts a single document, so the workspace's
 *   artboard grid, its active/inactive border and its name labels are gone.
 *   (§1.1's artifact-name label and W×H chip are ratified in the contract but
 *   the AD0.1 dummy delta carries no CSS for them — inventing that styling is
 *   barred, so they wait for Gate G-A's mockup sheet. Nothing here fakes them.)
 * - **Content only.** Selection chrome stays out of the canvas by the source's
 *   own Decision 5 — the selection overlay mounts as a sibling of the
 *   `<canvas>` inside `.stage`, so hover/selection never trigger a wasm redraw.
 *
 * And one re-valuing: the source's `drawArtboard` shell is an opaque `#151920`
 * slab, legible behind a page on its DARK workspace and a hard black frame on
 * our light one. The structure is ported (a shell behind the rect, content
 * clipped to the page box, a border stroked on top); the shell is painted as a
 * real blurred drop shadow and the border keeps the hairline colour the retired
 * card drew. Both are screen-constant (`artboardChromeGeometry`).
 *
 * AD2.5 adds the read path's last leg: pointer-down selects. Gate G-A then
 * ratified the visual (founder, 2026-08-20 — Variant B), so the overlay AD2.5
 * left as a marked empty insertion point is now a real sibling `<svg>`: a
 * 1.5px indigo outline around the selected node's box, fed by
 * `deriveSelectionChromeModel`'s `selectionBox` through `sceneSelectionOutline`.
 * It is a SIBLING of the canvas, never a canvas draw — the source stage's own
 * Decision 5 — so selection can never trigger a wasm redraw, and it is
 * `pointer-events: none`, so every click still reaches the canvas beneath it.
 *
 * The ruling's four corner handles waited for the behaviour they promise — a
 * grabbable handle that does nothing is a fake affordance — and **AD4.C is
 * that behaviour**, so they are drawn now: the overlay below is passed
 * `handles` and nothing else about it changed. `data-scene-selected-node`
 * stays on the canvas as the machine-readable assertion (AD2.5 finding 4,
 * founder-confirmed).
 *
 * AD4.C also adds the write half of the pointer (§1.9's v1 scope: drag-to-move
 * and CORNER resize, no rotate, no marquee, no nudge). Double-click text was on
 * that exclusion list until the founder took it off (2026-08-24); it is now the
 * caret session below — `SceneTextEditOverlay` over
 * `adapter/scene-text-edit.ts`, per
 * `docs/superpowers/plans/2026-08-24-rich-text-editing.md` rung B. The gesture
 * decisions are pure and live in
 * `adapter/scene-gestures.ts`, over the design subsystem's own shared
 * machinery — `gestureReducer`, the transformer math, and the existing
 * operation builders — so the geometry rules are ported, never re-derived.
 * What is here is the DOM plumbing plus two state holders: the machine in a
 * ref, and the in-flight preview in one `useState`. A gesture never touches
 * the scene; it commits through `onOperations` (Ruling C-3), which is the
 * inspector's own AD3.2 write path, so one gesture is one atomic batch and one
 * undo frame — and ⌘Z therefore needs no new code at all (AD3.3's listener
 * already covers the server-owned history).
 *
 * AD3.2 adds the ONE seam the write path needs: `applyOperations` on the
 * controls below, which hands a batch to the live engine and repaints. The
 * canvas still owns no write POLICY — what to write, when to persist it and
 * what a rejection says all live in `hooks/use-scene-manual-edits.ts`.
 *
 * When the wasm stamp handshake fails the scene still renders — from the
 * server's own snapshot — no operation can be applied at all, and
 * `engineDisabled` rides upward. A click in that state is a **no-op**: with no
 * engine there is no hit test, and a guess from descriptors would be a
 * selection the engine never agreed to. Gate G-D (founder, 2026-08-21) closed
 * the last silence around it: `SceneEngineBanners` below now SAYS so, in the
 * MVP editor's own words, instead of leaving the console diagnostic as the only
 * signal that a click did nothing on purpose.
 */

export interface SceneCanvasControls {
  /** The exact design document this imperative surface is currently serving. */
  readonly documentId: string;
  /**
   * AD3.2: apply operations to the LIVE engine and repaint — the optimistic
   * half of the write path, which must land before anything is persisted (the
   * queue reconciles the server's document against the local scene at drain,
   * so persisting first would report divergence on every accepted edit).
   *
   * Null when the engine is unavailable (D9 read-only) — the caller must never
   * persist what the engine never applied. A rejected outcome is returned
   * rather than thrown: the caller shows the engine's own message.
   */
  applyOperations(operations: Operation[]): EngineApplyOutcome | null;
  /**
   * AD4.C-3 / ruling C-12: apply ONE structured edit to the live engine and
   * repaint — the same optimistic half as `applyOperations` above, for the one
   * write the canvas issues that is not a plain operation batch: the
   * freeze-on-grab (`freezeLayoutEdit()`).
   *
   * It returns the outcome because the outcome carries the batch: the engine
   * has ALREADY applied these operations, and they still have to be persisted.
   * That is why the caller must hand `outcome.operations` to the
   * persist-already-applied seam and never to `applyOps` — the ordinary write
   * path would apply them a second time.
   *
   * Null when the engine is unavailable (D9 read-only), same as
   * `applyOperations`: nothing was applied, so nothing may be persisted.
   */
  applyStructuredEdit(edit: StructuredEdit): EngineStructuredEditOutcome | null;
  /**
   * AD4.A step 2: could a batch land right now — i.e. is the live engine
   * available? False is exactly the state in which `applyOperations` returns
   * `null` (D9 read-only).
   *
   * It exists because that refusal is DELIBERATELY SILENT (the canvas's own
   * G-D banner explains the read-only state and a second message would be new
   * failure UI), which is fine for a write that costs nothing to attempt and
   * wrong for one that SPENDS something first: the Replace-image flow uploads
   * the picked file — minting a real asset registry row — before it has any
   * operation to apply. Asking here lets that flow refuse before the spend
   * instead of stranding an orphan asset behind a silent no-op.
   */
  canApply(): boolean;
  /** Point→node hit-test in absolute PAGE space (scene units), straight from
   * the engine. Null when the engine is unavailable — a disabled engine
   * refuses to answer rather than guessing from descriptors (AD2.5 consumes
   * the stack; the coordinate chain into these units is its step 2). */
  hitTest(x: number, y: number): HitResult | null;
  /** Adopt the engine's current scene and repaint. */
  refresh(): void;
  /** The committed version loaded with this canvas snapshot. */
  documentVersion(): number | null;
  /** The scene as rendered right now (the relaid engine scene when the engine
   * is live, the server snapshot otherwise), or null before it loads. */
  sceneSnapshot(): Scene | null;
}

export interface SceneArtifactCanvasProps {
  /** The design document to render. */
  documentId: string;
  /**
   * AD4.C / Ruling C-4 — GATE G-H, canvas-side: while an agent turn is in
   * flight the human's DIRECT MANIPULATION is off. No drag or resize gesture
   * starts (a press still selects, exactly as it does on a locked node) and the
   * corner handles are not drawn, because a handle is a promise the canvas
   * cannot keep while the gate holds.
   *
   * Selection stays live on purpose: looking at the document — and at what is
   * selected in it — is not changing it, which is the whole of what G-H forbids
   * ("we cannot let humans change any value when the agents are at work").
   *
   * The chats route passes `chat.threadBusy`, the same source the inspector's
   * `inspectorDisabled` reads. The artifact route deliberately passes nothing —
   * it has no live turn stream to read, and its net stays the D10 CAS
   * reconciliation (see the comment at that call site).
   */
  gestureDisabled?: boolean;
  /**
   * AD4.C / Ruling C-3: a committed canvas gesture's operations, handed to the
   * shell's write path — `use-scene-manual-edits.ts`'s `applyOps`, the SAME one
   * every inspector row commits through (optimistic engine apply → repaint →
   * edit-queue persist).
   *
   * One committed gesture is ONE call with the whole batch, so it lands as one
   * atomic edit and therefore ONE undo frame — a drag of a container carries
   * its pinned descendants in that same batch. The canvas never calls its own
   * `applyOperations` for a gesture: that seam applies to the live engine and
   * persists NOTHING, so a write through it would be lost on the next load.
   *
   * Absent (the standalone read path, and the ad canvas before a session mounts
   * one) means no gesture is ever committed — the preview simply drops.
   */
  onOperations?: (operations: Operation[], intent?: string) => boolean;
  /**
   * AD4.C-3 / Ruling C-12: persist operations the engine has ALREADY applied.
   *
   * A deliberate SIBLING of `onOperations` rather than a flag on it, because
   * the two carry opposite contracts — `onOperations` means "apply this, then
   * persist it", this means "persist only; the apply already happened" — and
   * conflating them behind one callback would make a wiring slip silently
   * DOUBLE-APPLY the batch. One caller: the freeze-on-grab, whose operations
   * come back from `controls.applyStructuredEdit`.
   *
   * The freeze lands as its own plain operation batch, so it is also its own
   * undo frame (upstream parity): one ⌘Z after a freed drag undoes the drag, a
   * second restores auto-layout.
   *
   * Absent means the freeze applies locally and is never persisted — the same
   * posture `onOperations` takes on the standalone read path.
   */
  onAppliedOperations?: (operations: Operation[], scene: Scene) => boolean;
  /** Receives the canvas's imperative controls while mounted. */
  controlsRef?: RefObject<SceneCanvasControls | null>;
  /**
   * Rung C / §1.6: the document's brand-kit colour vocabulary, for the caret
   * session's formatting toolbar — the SAME palette every inspector colour
   * picker is handed (`sceneSession.palette`), so the two surfaces cannot
   * disagree about which tokens exist.
   *
   * Absent or null means this document has no resolvable brand vocabulary: the
   * toolbar then offers no swatches at all (never the dummy's fixture palette,
   * which would write tokens no kit can resolve) and custom hex still applies.
   */
  palette?: ScenePalette | null;
  /** Bump to refetch the document into the same mounted canvas (the website
   * lane's quiet-swap discipline: no keyed remount, no flash). */
  reloadToken?: number;
  /**
   * A menu-chosen zoom (`"45%"`), applied EXACTLY as chosen.
   *
   * Null/absent is the fit mode (the AD2.3 read path and every freshly-opened
   * artifact): the artboard is contain-fit to the card at its exact scale, not
   * at the nearest menu step, so ruling 17's edge-to-edge fill survives the
   * menu being wired. See `sceneViewportModel` for why the displayed label and
   * the applied scale differ in that mode.
   */
  zoom?: string | null;
  /** The fit-on-open zoom as one of the header menu's own 5% steps — what the
   * menu DISPLAYS while nothing has been chosen. */
  onFitZoom?: (zoom: string) => void;
  /**
   * AD2.10: the zoom a PAN/WHEEL gesture landed on, or null when the canvas
   * falls back to the derived viewport (a fresh document, or an explicit menu
   * choice).
   *
   * A separate channel from `onFitZoom` and from the menu's own choice because
   * it outranks both for DISPLAY only: after a pinch the header must say where
   * the viewport actually is, and where it actually is may be a percentage the
   * 29-step menu does not offer (`formatZoomPercent`, not `snapZoomPercent`).
   * It never feeds back into `zoom` — the gesture already moved the viewport,
   * and re-deriving from a label would re-centre it and undo the pan.
   */
  onGestureZoom?: (zoom: string | null) => void;
  /** Mirrors the wasm stamp handshake upward, so the shell can refuse edits.
   * (The user-facing explanation is the canvas's own G-D banner, which needs no
   * shell plumbing — this stays the shell's machine-readable copy.) */
  onEngineStatusChange?: (status: SceneEngineStatus) => void;
  /**
   * AD3.3: the loaded document's undo/redo stack depths, mirrored up with the
   * generation counter that says when they were last refreshed.
   *
   * A separate channel from `onSceneChange` because it is DOCUMENT metadata,
   * not scene content — the same reason the engine status and the fit zoom have
   * their own. It is what lets the shell disable a history control it cannot
   * honour, without the session fetching a second copy of the document (this
   * lane's "one fetch, one engine, one scene" rule). Fires on every completed
   * load, including a reload-token refetch.
   */
  onHistoryChange?: (
    history: SceneDocumentHistory,
    documentId: string,
    /** The loaded document's committed version — remembered by the session so
     * an edit-target submission can still stamp a version after this canvas
     * unmounts (e.g. from the gallery surface). */
    currentVersion: number | null,
  ) => void;
  /**
   * AD2.7: the RENDERED scene, mirrored up whenever it changes (load, reload
   * token, the measure-then-inject relayout), tagged with the document it
   * belongs to.
   *
   * This is what lets the shared editing session hydrate the inspector and
   * build the layer tree without fetching a second copy of the document: the
   * scene handed up here is the very one `hitTest` answers against, so a
   * selection, its schema and its values can never come from three different
   * snapshots. Fires with `null` while the document is loading or after a
   * failed load.
   */
  onSceneChange?: (
    scene: Scene | null,
    pageId: PageId | null,
    documentId: string,
  ) => void;
  /**
   * AD2.7: the session's primary selection, once the shell owns it. Absent
   * (`undefined`) leaves the canvas on its own AD2.5 selection state, which is
   * what the standalone read path uses.
   */
  selectedNodeId?: NodeId | null;
  /** Fires on pointer-down with the node the press selected, or null when the
   * press cleared the selection (a click off the artboard, or a hit stack with
   * nothing representable in it). Never fires when the engine is unavailable —
   * a disabled engine refuses to answer rather than guessing.
   *
   * AD2.7 lifts the selection out into the editing session (which feeds it
   * back through `selectedNodeId`), so the inspector, the layer tree and the
   * canvas all read one selection. */
  onSelect?: (nodeId: NodeId | null) => void;
}

export function SceneArtifactCanvas(props: SceneArtifactCanvasProps) {
  // Keyed remount per DOCUMENT only: switching artifacts starts from
  // born-loading (never a stale ad under a new title) without a synchronous
  // setState inside an effect. Reload tokens deliberately do NOT remount — the
  // refetch swaps into the same live surface.
  return <SceneDocumentCanvas key={props.documentId} {...props} />;
}

/**
 * Is this key event someone TYPING? The canvas's keyboard shortcuts (space to
 * pan, AD4.C's Escape) never reach into a focused field — an inspector input
 * owns its own Space and its own Escape.
 *
 * Module-level because two listeners need it; it was inline in the space-pan
 * effect until AD4.C's Escape wanted the same rule rather than a second copy.
 */
function typingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
  );
}

function SceneDocumentCanvas({
  controlsRef,
  documentId,
  gestureDisabled = false,
  onAppliedOperations,
  onEngineStatusChange,
  onFitZoom,
  onGestureZoom,
  onHistoryChange,
  onOperations,
  onSceneChange,
  onSelect,
  palette = null,
  reloadToken = 0,
  selectedNodeId,
  zoom = null,
}: SceneArtifactCanvasProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [ownSelectedNodeId, setOwnSelectedNodeId] = useState<NodeId | null>(
    null,
  );
  const {
    currentVersion,
    engine,
    engineStatus,
    fontDiagnostics,
    loadGeneration,
    pageId,
    redoDepth,
    refresh,
    scene,
    tokenGeneration,
    undoDepth,
  } = useSceneDocument(documentId, reloadToken);

  // The engine's own text-measurement status store — `heuristic` means the
  // Skia pass never ran, which is a real rendering difference the G-D banner
  // names (it was silent until then: the ad renders either way).
  const measurementStatus = useSyncExternalStore(
    subscribeTextMeasurementStatus,
    textMeasurementStatusSnapshot,
    textMeasurementStatusSnapshot,
  );

  /* ---------------------------------------------------------------------
   * AD4.C — direct manipulation (drag-move + corner-resize).
   *
   * Two pieces of state, and the split is the whole design:
   *
   *  • the GESTURE MACHINE lives in a ref. It is the source editor's own
   *    pattern (`CanvasKitCanvas.tsx:189,755-761`) and it is not laziness: a
   *    pointer move must not queue a React render just to advance a state
   *    machine, and the reducer is pure, so a ref holds it exactly as well.
   *  • the PREVIEW is the one piece of React state, because it is the only
   *    thing that has to reach the screen — as a render-time descriptor
   *    override and overlay geometry, never a scene mutation (AD4.R: the
   *    engine's scene owns the document's values). Dropping it repaints the
   *    document's own truth, which is what makes Escape and pointer-cancel
   *    free.
   *
   * `gestureArmedRef` is the C-5/R5 gate, held at the SOURCE: moves are
   * dispatched only while it is true, so a press that may not drag (locked,
   * layout-managed, no laid-out box, or an in-flight agent turn) can never
   * promote into a gesture — and an empty press, which is never armed, can
   * never become a marquee (§1.9).
   * ------------------------------------------------------------------ */
  const gestureRef = useRef<GestureState>(initialGestureState);
  const gestureArmedRef = useRef(false);
  const [preview, setPreview] = useState<ScenePreview | null>(null);

  /* ---------------------------------------------------------------------
   * Rung B — the inline text-edit session (rich-text plan, 2026-08-24).
   *
   * ONE piece of state: WHICH node has a caret in it. Everything else the
   * session needs — its box, its style, the string it is editing — is DERIVED
   * per render (`textEdit` below), for the same reason the selection outline
   * is: a stored geometry could go stale against a zoom, a pan or a relayout,
   * and the caret would sit where the text is not.
   *
   * The DRAFT deliberately lives inside the overlay component, not here. It is
   * the AD4.R state model applied to a canvas surface: the engine's scene owns
   * the document's value, the edit surface self-drafts, and one commit reaches
   * the write path. Keeping it here would push a render through the whole
   * canvas on every keystroke.
   * ------------------------------------------------------------------ */
  const [editingNodeId, setEditingNodeId] = useState<NodeId | null>(null);

  // The descriptor tree the draw loop walks. `tokenGeneration` is a real dep:
  // descriptors read the renderAdapter's module-level kit maps, which arrive
  // after the first paint. AD4.C adds `preview`: a gesture in flight rebuilds
  // the tree with the dragged node's box substituted, which is how the moving
  // pixels reach the canvas without the scene being touched.
  // genad2 Task 5: the loaded-but-pageless line, or null. Pure and derived —
  // never a state that could survive the turn that authors the first page.
  const pagelessNotice = scenePagelessNotice(scene, pageId);

  // Rung B adds `editingNodeId`: the node under an open caret paints no glyphs,
  // because the DOM overlay is drawing them. The STATE is passed, not the
  // derived model — the model is built FROM this artboard, so feeding it back
  // in would be circular; a stale id matches no node and suppresses nothing.
  const artboard = useMemo(
    () =>
      scene ? sceneArtboardModel(scene, pageId, preview, editingNodeId) : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tokenGeneration
    [scene, pageId, preview, editingNodeId, tokenGeneration],
  );

  // Fit-on-open (§1.10) is a pure function of the card's size and the page
  // box, so it is derived, never stored: no viewport state can go stale
  // against a resize. AD2.8's menu value rides in the SAME derivation — the
  // fit-vs-chosen rule lives in `sceneViewportModel`, where it is unit-tested
  // (this component's internals cannot be: no DOM, no wasm in the runner).
  const viewportModel = useMemo(
    () =>
      artboard
        ? sceneViewportModel({ rect: artboard.rect, stage: stageSize, zoom })
        : null,
    [artboard, stageSize, zoom],
  );

  // AD2.10: the one piece of viewport STATE — where the user's own pan/zoom
  // gestures have taken the workspace. Null means "nowhere yet", and the
  // derivation above governs; a gesture supersedes it until the next explicit
  // choice.
  //
  // The reset is keyed on the page and the chosen zoom, deliberately NOT on the
  // artboard or the stage size: a relayout (a text measurement landing, a write
  // in AD3) or a panel toggle must not yank the workspace back to centre under
  // someone who has panned. A menu choice must — that is what "re-centre on an
  // explicit choice" means.
  // The reset is React's own adjust-state-on-prop-change pattern (a render-time
  // comparison against the last key), not an effect: an effect would paint one
  // frame of the stale gesture viewport before snapping back.
  const [gestureViewport, setGestureViewport] =
    useState<WorkspaceViewport | null>(null);
  const viewportKey = `${pageId ?? ""}|${zoom ?? ""}`;
  const [lastViewportKey, setLastViewportKey] = useState(viewportKey);
  if (lastViewportKey !== viewportKey) {
    setLastViewportKey(viewportKey);
    setGestureViewport(null);
  }
  const activeGestureViewport =
    lastViewportKey === viewportKey ? gestureViewport : null;

  const viewport: WorkspaceViewport =
    activeGestureViewport ??
    viewportModel?.applied ??
    defaultWorkspaceViewport();

  // The header's zoom control, told where the viewport actually is after a
  // gesture. Keyed on the LABEL, so a pure pan (same zoom) never re-renders the
  // shell — a drag would otherwise push one state update per pointer move
  // through the whole editing session.
  const gestureZoomLabel = activeGestureViewport
    ? formatZoomPercent(activeGestureViewport.zoom)
    : null;
  const onGestureZoomRef = useRef(onGestureZoom);
  useEffect(() => {
    onGestureZoomRef.current = onGestureZoom;
  });
  useEffect(() => {
    onGestureZoomRef.current?.(gestureZoomLabel);
  }, [gestureZoomLabel]);

  // Report the fit as a step the header menu actually offers — the FIT, always,
  // never the chosen zoom: this is the value the menu falls back to, so a
  // choice must not overwrite it. Passive effect (callback only, no state) so
  // it can never fight the derivation above.
  const onFitZoomRef = useRef(onFitZoom);
  useEffect(() => {
    onFitZoomRef.current = onFitZoom;
  });
  const fitZoom = viewportModel?.fitLabel ?? null;
  useEffect(() => {
    if (fitZoom) {
      onFitZoomRef.current?.(fitZoom);
    }
  }, [fitZoom]);

  const onEngineStatusRef = useRef(onEngineStatusChange);
  useEffect(() => {
    onEngineStatusRef.current = onEngineStatusChange;
  });
  useEffect(() => {
    onEngineStatusRef.current?.(engineStatus);
  }, [engineStatus]);

  // AD3.3: the loaded history, mirrored up the same way — a passive-ref effect
  // (callback only, no state) keyed on the three SCALARS, never on a freshly
  // built object, which would re-fire on every render.
  const onHistoryChangeRef = useRef(onHistoryChange);
  useEffect(() => {
    onHistoryChangeRef.current = onHistoryChange;
  });
  useEffect(() => {
    onHistoryChangeRef.current?.(
      { loadGeneration, redoDepth, undoDepth },
      documentId,
      currentVersion,
    );
  }, [currentVersion, documentId, loadGeneration, redoDepth, undoDepth]);

  useEffect(() => {
    const element = stageRef.current;
    if (!element || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      setStageSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // The latch for the scene-change callback below — a ref so neither caller
  // (the apply path, the passive effect) closes over a stale one.
  const onSceneChangeRef = useRef(onSceneChange);
  useEffect(() => {
    onSceneChangeRef.current = onSceneChange;
  });

  // One controls object, used BOTH by the pointer handler below and by the
  // shell through `controlsRef` — so the press path calls the same declared
  // seam an outside caller would, and a change to hit-testing cannot leave the
  // two disagreeing.
  const controls = useMemo<SceneCanvasControls>(
    () => ({
      documentId,
      applyOperations: (operations) => {
        if (!engine) {
          return null;
        }
        const outcome = engine.applyOperations(operations);
        // `refresh()` is BOTH halves of "the canvas owns it": it adopts the
        // engine's post-apply scene as the rendered one (repaint) and, through
        // the effect below, mirrors that same scene up to the session — which
        // rehydrates the inspector and rebuilds the layer tree. A rejected
        // batch changed nothing, so it repaints nothing.
        if (outcome.accepted) {
          refresh();
          // AD4.R: the accepted scene ALSO mirrors up synchronously, so a
          // commit handler's own setState and the session's scene adoption land
          // in one React batch — the inspector's live-derived fields re-read
          // the post-write document on the very next render, with no frame in
          // between showing the pre-write value. The passive effect below still
          // fires afterwards with the final rendered (possibly relaid) scene;
          // that second setLoaded is idempotent. This is the MVP editor's own
          // shape: EditorApp installs result.scene in the accept path.
          onSceneChangeRef.current?.(outcome.scene, pageId, documentId);
        }
        return outcome;
      },
      applyStructuredEdit: (edit) => {
        if (!engine) {
          return null;
        }
        const outcome = engine.applyStructuredEdit(edit);
        // Identical accept path to `applyOperations` above, and for the
        // identical reasons: repaint, and mirror the accepted scene up
        // SYNCHRONOUSLY so the press that fired this sees the post-freeze
        // document on its very next render.
        if (outcome.accepted) {
          refresh();
          onSceneChangeRef.current?.(outcome.scene, pageId, documentId);
        }
        return outcome;
      },
      // The same condition `applyOperations` refuses on, asked without
      // applying anything.
      canApply: () => Boolean(engine),
      documentVersion: () => currentVersion,
      hitTest: (x, y) =>
        engine && pageId ? engine.hitTest(pageId, x, y) : null,
      refresh,
      sceneSnapshot: () => scene,
    }),
    [currentVersion, documentId, engine, pageId, refresh, scene],
  );
  useEffect(() => {
    if (!controlsRef) {
      return;
    }
    controlsRef.current = controls;
    return () => {
      controlsRef.current = null;
    };
  }, [controls, controlsRef]);

  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  });

  // AD2.7: the shell's selection wins when it owns one; the local state is the
  // standalone read path's fallback (and keeps the diagnostic attribute honest
  // for a canvas mounted with no session).
  const activeSelectedNodeId =
    selectedNodeId === undefined ? ownSelectedNodeId : selectedNodeId;

  // Gate G-A: the selection outline, DERIVED per render from the same artboard
  // and the same viewport the draw loop transforms by — never stored, so a zoom
  // change or a stage resize can never leave a stale box behind. The conversion
  // itself lives in the adapter, where it is unit-tested (this component's
  // internals cannot be: no DOM, no wasm in the runner).
  const selectionOutline = useMemo(
    () =>
      artboard
        ? sceneSelectionOutline({
            artboard,
            pageId,
            // AD4.C: while a gesture runs the chrome tracks the LIVE box, so
            // the outline (and its handles) move with the previewed pixels
            // rather than sitting at the pre-drag position.
            preview,
            scene,
            selectedNodeId: activeSelectedNodeId,
            viewport,
          })
        : null,
    [activeSelectedNodeId, artboard, pageId, preview, scene, viewport],
  );

  // AD4.C step 2 (Gate G-A): the four approved corner handles, drawn at last —
  // exactly when the document, the engine and the G-H gate all allow the drag
  // they promise. The outline itself is unconditional; only the grab affordance
  // is gated.
  const selectionHandles = useMemo(
    () =>
      sceneSelectionHandlesVisible({
        engineDisabled: engineStatus.engineDisabled,
        gestureDisabled,
        pageId,
        scene,
        selectedNodeId: activeSelectedNodeId,
      }),
    [
      activeSelectedNodeId,
      engineStatus.engineDisabled,
      gestureDisabled,
      pageId,
      scene,
    ],
  );

  const commitSelection = (nodeId: NodeId | null) => {
    setOwnSelectedNodeId(nodeId);
    onSelectRef.current?.(nodeId);
  };

  /**
   * Rung B: the open session's overlay, derived from the same box model the
   * selection chrome reads and the same render descriptor the painter reads —
   * so the caret sits exactly where the glyphs were, at every zoom and pan.
   *
   * Null is the SESSION-CLOSED signal as well as the no-session one: the
   * derivation answers null when the edited node has left the scene or stopped
   * being text (a D10 reload, an agent turn regenerating the document), so
   * every interlock below reads THIS rather than `editingNodeId` and no stale
   * id can leave the chrome suppressed. The state itself is cleared by the
   * effect after it, which is what discards the draft.
   */
  const textEdit = useMemo(
    () =>
      sceneTextEditModel({
        artboard,
        editingNodeId,
        pageId,
        scene,
        viewport,
      }),
    [artboard, editingNodeId, pageId, scene, viewport],
  );
  // React's own adjust-state-on-change pattern (the same one the viewport reset
  // above uses), not an effect: an effect would paint one frame with the
  // session's interlocks still holding on a node that is no longer there.
  if (editingNodeId && !textEdit) {
    setEditingNodeId(null);
  }

  /**
   * Commit the session: ONE operation batch, so a whole editing session is one
   * atomic edit and one undo frame — the write path every canvas gesture and
   * every inspector row already commits through.
   *
   * The node is re-read from the CURRENT scene rather than captured when the
   * session opened, so a commit against a document that moved underneath is
   * either honest or refused (the batch builder returns null for a node that is
   * gone, locked, or no longer text). A session that changed neither the text
   * nor its styling writes nothing at all: a blur that typed nothing is not an
   * edit.
   *
   * Rung C: BOTH channels ride this one batch. The session always maintains a
   * spans vector (seeded from the node's own), so it is always authoritative
   * here — which is also what lets a formatting action that changed no
   * characters be a real commit.
   */
  const commitTextEdit = useCallback(
    (session: TextEditSession) => {
      const node = scene ? getNode(scene, editingNodeId) : null;
      setEditingNodeId(null);
      const operations = textEditCommitOperations(
        node,
        session.content,
        session.spans,
      );
      if (operations) {
        onOperations?.(operations, SCENE_TEXT_EDIT_INTENT);
      }
    },
    [editingNodeId, onOperations, scene],
  );

  /**
   * Rung C: a FORMATTING action, committed immediately and on its own.
   *
   * Founder-visible item 5 — each formatting action is its own undo frame — so
   * this is the same builder and the same write path as the session commit,
   * with two differences that are the whole point: the session stays OPEN (the
   * caret and its selection are untouched, so the next toggle acts on the same
   * range), and the intent names the styling surface rather than the edit.
   *
   * The dirty draft rides along when there is one: span offsets index the
   * string they were computed in, and committing them against a stale stored
   * content would point them at other text.
   */
  const commitTextEditStyle = useCallback(
    (session: TextEditSession) => {
      const node = scene ? getNode(scene, editingNodeId) : null;
      const operations = textEditCommitOperations(
        node,
        session.content,
        session.spans,
      );
      if (operations) {
        onOperations?.(operations, SCENE_TEXT_STYLE_INTENT);
      }
    },
    [editingNodeId, onOperations, scene],
  );

  const cancelTextEdit = useCallback(() => setEditingNodeId(null), []);

  /* ---------------------------------------------------------------------
   * AD2.10 — the workspace gestures.
   *
   * Ported from the source canvas's own handlers (`CanvasKitCanvas.tsx`
   * :968-1010): ⌘/Ctrl + wheel zooms at the pointer, a plain wheel pans (what a
   * trackpad's two-finger scroll emits), and a held modifier turns a drag into a
   * pan. The decisions themselves live in the adapter, where they are
   * unit-tested; what is here is only the DOM plumbing.
   * ------------------------------------------------------------------ */

  // The gesture handlers are bound once and read their inputs through a ref, so
  // no listener is re-attached mid-drag. What the ref carries is the DERIVED
  // viewport (the fit or the chosen step) — the base a gesture starts from; the
  // gesture's own position is read from the state updater instead, because two
  // wheel events inside one frame would both see the same not-yet-committed ref
  // and the second would discard the first.
  const gestureInputsRef = useRef({
    artboard,
    stageSize,
    baseViewport: viewportModel?.applied ?? viewport,
  });
  useEffect(() => {
    gestureInputsRef.current = {
      artboard,
      stageSize,
      baseViewport: viewportModel?.applied ?? viewport,
    };
  });

  useEffect(() => {
    const element = stageRef.current;
    if (!element) {
      return;
    }
    const handleWheel = (event: WheelEvent) => {
      const current = gestureInputsRef.current;
      if (!current.artboard) {
        return;
      }
      // A NATIVE, non-passive listener rather than React's `onWheel`: React
      // registers wheel at the root as PASSIVE, so `preventDefault` there is a
      // no-op — ⌘+wheel would zoom the browser page over the top of the canvas
      // and a two-finger scroll would scroll the shell instead of panning. The
      // stage is a viewport, so it owns the gesture.
      event.preventDefault();
      const bounds = element.getBoundingClientRect();
      // deltaMode 1 is LINES (Firefox with a mouse wheel): ~16px per line, or a
      // notch would move the workspace by three pixels.
      const lines = event.deltaMode === 1 ? 16 : 1;
      const artboardRect = current.artboard.rect;
      const delta = { x: event.deltaX * lines, y: event.deltaY * lines };
      const point = {
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      };
      const zoomGesture = event.ctrlKey || event.metaKey;
      setGestureViewport((live) =>
        sceneWheelViewport({
          bounds: artboardRect,
          delta,
          point,
          stage: current.stageSize,
          viewport: live ?? current.baseViewport,
          zoomGesture,
        }),
      );
    };
    element.addEventListener("wheel", handleWheel, { passive: false });
    return () => element.removeEventListener("wheel", handleWheel);
  }, []);

  // Space-to-pan, the editor convention. Held space turns the whole stage into
  // a hand tool; a plain press still selects (AD2.5), which is why this is a
  // modifier and not a mode.
  const [spaceHeld, setSpaceHeld] = useState(false);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code !== "Space" || typingTarget(event.target)) {
        return;
      }
      // Space would otherwise page-scroll the shell behind the stage.
      event.preventDefault();
      setSpaceHeld(true);
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code === "Space") {
        setSpaceHeld(false);
      }
    };
    // A window that loses focus mid-hold never delivers the keyup.
    const onBlur = () => setSpaceHeld(false);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  }, []);

  const panDragRef = useRef<{
    pointerId: number;
    origin: { point: { x: number; y: number }; pan: { x: number; y: number } };
  } | null>(null);
  const [panning, setPanning] = useState(false);

  const stagePoint = (event: ReactPointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
  };

  /* ---------------------------------------------------------------------
   * AD4.C — the gesture host: three lines of plumbing over pure decisions.
   * ------------------------------------------------------------------ */

  /** The press, in artboard-local descriptor px — the space the gesture
   * machine, the transformer math and the operation builders all speak. */
  const descriptorPoint = (event: ReactPointerEvent<HTMLDivElement>) =>
    artboard
      ? sceneDescriptorPoint(screenToWorkspace(stagePoint(event), viewport), artboard)
      : null;

  const modifiersOf = (event: ReactPointerEvent<HTMLDivElement>) => ({
    // Shift is the reducer's own aspect lock on a corner resize; meta rides
    // along as the machine defines it. Neither reaches the selection — Ruling
    // C-8 drops `additive`, because multi-select is not this task's.
    shift: event.shiftKey,
    meta: event.metaKey || event.ctrlKey,
  });

  /** Ruling C-2: the hard reset. The reducer has no cancel event — every `up`
   * from a live gesture commits — so a cancelled gesture is undone by throwing
   * the machine and the preview away, which is the source editor's own answer
   * (`CanvasKitCanvas.tsx:1155-1164`). Nothing was written, so nothing is
   * undone: the artboard simply repaints at the document's truth. */
  const resetGesture = () => {
    gestureRef.current = initialGestureState;
    gestureArmedRef.current = false;
    setPreview(null);
  };

  const applyGestureAction = (action: GestureAction) => {
    if (!scene) {
      return;
    }
    const effect = sceneGestureEffect(action, scene, pageId);
    switch (effect.kind) {
      case "select":
        commitSelection(effect.nodeId);
        break;
      case "preview":
        setPreview(effect.preview);
        break;
      case "commit":
        setPreview(null);
        // A write that changes nothing is not a write: the builders answer
        // with an empty batch for a node they refuse, and an empty batch is
        // not handed to the write path at all.
        if (effect.operations.length > 0) {
          onOperations?.(effect.operations, effect.intent);
        }
        break;
      case "none":
        break;
    }
  };

  const dispatchGesture = (event: GestureEvent) => {
    const reduced = gestureReducer(gestureRef.current, event);
    gestureRef.current = reduced.state;
    applyGestureAction(reduced.action);
  };

  /**
   * Ruling C-9 (founder): a human dragging on this canvas is NEVER refused by
   * auto-layout. The agent works in auto-layout; the human does not know what
   * auto-layout is. So the first grab of a solver-owned node bakes the whole
   * document's layout to free placement — silently, moving nothing — and the
   * SAME press then continues as an ordinary free drag.
   *
   * Everything about the ordering is load-bearing, and all of it is upstream's
   * (`CanvasKitCanvas.tsx:1056-1076`):
   *
   *  • BEFORE `beginPress`. The press target was resolved against the
   *    pre-freeze scene, and that is correct: the freeze is zero-motion, so
   *    the box this gesture starts from is numerically identical either side
   *    of it (proven against the real engine in `wasmEngine.artifact.test.ts`).
   *    By the time the drag commits, React has re-rendered on the post-freeze
   *    scene and the operation builders take the node.
   *  • Fire-and-forget on a click that never drags. The edit is idempotent —
   *    an empty batch once nothing is left to freeze — so the cost of a
   *    needless freeze is one no-op, which is upstream's own posture.
   *  • Persist WITHOUT re-applying. `applyStructuredEdit` already applied
   *    these operations to the engine; `onAppliedOperations` is the seam that
   *    only enqueues them. Routing them through `onOperations` would apply the
   *    batch twice.
   *
   * The `engineDisabled` guard is inherited from `handlePointerDown`'s own
   * early return (a freeze needs solved geometry, which a dead engine has
   * none of), and G-H rides in `shouldFreezeLayoutOnPress`'s `gesturesEnabled`
   * — a freeze is a write, so mid-turn none fires and managed nodes keep
   * today's select-only behaviour.
   *
   * RETURNS whether this press may go on to arm, which is not always true —
   * see the locked-CONTAINER case below.
   */
  const freezeLayoutForPress = (target: PressTarget): boolean => {
    if (!scene || !shouldFreezeLayoutOnPress({
      gesturesEnabled: !gestureDisabled,
      scene,
      target,
    })) {
      // No freeze needed, so nothing here can block the press. Whether it arms
      // is entirely the caller's own (pre-computed) answer.
      return true;
    }
    const outcome = controls.applyStructuredEdit(freezeLayoutEdit());
    const operations = freezeOperationsToPersist(outcome);
    if (outcome && operations.length > 0) {
      // Persisted whether or not the PRESSED node was freed: these operations
      // are already in the engine, and whatever they freed has to reach the
      // server or the local scene and the document diverge on the next drain.
      //
      // `outcome.scene` — the POST-freeze scene, not `controls.sceneSnapshot()`
      // (which answers from this render's closure and is still the pre-freeze
      // one until React re-renders). The queue seeds its divergence check from
      // this, so handing it the pre-freeze scene would fake a divergence
      // against the document the server is about to be told about.
      onAppliedOperations?.(operations, outcome.scene);
    }
    // Ruling C-5 applied to the freeze: a press that cannot commit must not
    // preview. Asked of the NODE against the post-freeze scene rather than
    // inferred from the batch being empty — `build_freeze_layout` skips only
    // LOCKED containers and still frees every other Stack, so a non-empty
    // batch does NOT mean this node was freed (pinned against the real engine
    // in `wasmEngine.artifact.test.ts`, two-Stack fixture).
    return pressArmedAfterFreeze(outcome?.scene ?? null, target);
  };

  /** Begin a press: arm (or refuse to arm) the gesture, then let the reducer
   * resolve the selection it implies. */
  const beginPress = (
    event: ReactPointerEvent<HTMLDivElement>,
    point: { x: number; y: number },
    target: PressTarget,
    armed: boolean,
  ) => {
    gestureArmedRef.current = armed;
    if (armed) {
      // Only a press that can actually become a gesture captures the pointer —
      // so a drag that leaves the stage keeps arriving, while a plain select
      // press behaves exactly as it did before this task. Best-effort: capture
      // throws for a pointer the browser has already released.
      try {
        event.currentTarget.setPointerCapture?.(event.pointerId);
      } catch {
        // Ignored deliberately (the source host does the same).
      }
    }
    dispatchGesture({
      kind: "down",
      point,
      target,
      // Not the raw modifiers: an EMPTY press carries none, so a press on
      // nothing clears the selection unconditionally — AD2.5's own behaviour,
      // which the reducer would otherwise preserve-on-additive (multi-select is
      // AD4.E's). Reasoned out at `scenePressModifiers`.
      modifiers: scenePressModifiers(target, modifiersOf(event)),
    });
    if (!armed) {
      // …and then straight back to rest. An unarmed press has no follow-up —
      // moves are ignored and its `up` reduces to nothing — so the machine has
      // no reason to hold `pressed`, and holding it was not free: capture is
      // taken only for an ARMED press, so an unarmed one released off the stage
      // never gets its `pointerup` and would strand `pressed` until the next
      // press anywhere on the canvas. A machine stranded non-idle is exactly
      // what would stop the window Escape listener below being inert — it would
      // swallow the next Escape anywhere in the app. The press keeps its
      // selection; only the leftover state goes.
      gestureRef.current = initialGestureState;
    }
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = panDragRef.current;
    const current = gestureInputsRef.current;
    if (drag) {
      if (drag.pointerId !== event.pointerId || !current.artboard) {
        return;
      }
      const artboardRect = current.artboard.rect;
      const point = stagePoint(event);
      setGestureViewport((live) =>
        sceneDragPanViewport({
          bounds: artboardRect,
          origin: drag.origin,
          point,
          stage: current.stageSize,
          viewport: live ?? current.baseViewport,
        }),
      );
      return;
    }
    // AD4.C: the pan owns the surface first (above); what is left is direct
    // manipulation. An unarmed press never gets here, which is what keeps a
    // locked node still, an empty press out of marquee, and G-H honoured.
    if (!gestureArmedRef.current || gestureRef.current.kind === "idle") {
      return;
    }
    const point = descriptorPoint(event);
    if (!point) {
      return;
    }
    dispatchGesture({ kind: "move", point, modifiers: modifiersOf(event) });
  };

  const endPanDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (panDragRef.current?.pointerId !== event.pointerId) {
      return;
    }
    panDragRef.current = null;
    setPanning(false);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };

  const handlePointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    const panned = panDragRef.current?.pointerId === event.pointerId;
    endPanDrag(event);
    if (panned) {
      return;
    }
    if (gestureRef.current.kind !== "idle") {
      const point = descriptorPoint(event);
      // The reducer commits on `up` and returns to idle.
      if (point) {
        dispatchGesture({ kind: "up", point, modifiers: modifiersOf(event) });
      }
    }
    // UNCONDITIONALLY, whatever that `up` resolved to. The preview is cleared
    // by the `commit` arm, and two reachable paths never reach it while still
    // ending the gesture: no descriptor point at all (a failed reload landing
    // mid-drag), and a committed action whose node or page has left the scene
    // (an agent turn regenerating the document mid-drag), which resolves to
    // `none`. Leaving the preview behind there was unrescuable — the machine
    // is idle by then, so Escape's own guard refuses to fire — so the machine
    // and the preview go back to rest together, always.
    resetGesture();
  };

  const handlePointerCancel = (event: ReactPointerEvent<HTMLDivElement>) => {
    endPanDrag(event);
    resetGesture();
  };

  // Ruling C-2: Escape cancels a live gesture. Registered once and inert
  // otherwise — an Escape with no gesture running reaches whatever else wants
  // it (this canvas has never cleared a selection on Escape, and this task does
  // not add that).
  //
  // The guard is ARMED **and** non-idle, not non-idle alone: this is a global
  // key handler, so its inertness must not rest on a state machine that a
  // missed `pointerup` could leave dirty. Only an armed gesture has anything to
  // cancel, and after `beginPress`/`handlePointerUp` above, armed and non-idle
  // are the same condition — the second half is belt-and-braces on a handler
  // that can `preventDefault` a key the whole app shares.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.key !== "Escape" ||
        !gestureArmedRef.current ||
        gestureRef.current.kind === "idle"
      ) {
        return;
      }
      // The same guard the space-pan listener uses: Escape inside an inspector
      // field is that field's, never the canvas's.
      if (typingTarget(event.target)) {
        return;
      }
      event.preventDefault();
      resetGesture();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // AD2.7: hand the rendered scene up. A passive-ref effect (callback only, no
  // state) so it can never fight the render, and keyed on the scene identity
  // the draw loop is actually using — including the relaid one the C4
  // measurement pass adopts. This owns the load / reload / relaid-scene paths.
  //
  // AD4.R-1 added a SYNCHRONOUS sibling on the accepted-apply path
  // (`controls.applyOperations` above): a write's own scene mirrors up inside
  // the same call stack, so the inspector's live-derived fields re-read the
  // post-write document in the same React batch instead of one passive-effect
  // render later. This effect still fires afterwards for that same scene, and
  // that repeat is an idempotent `setLoaded` — the two are not redundant, they
  // cover different arrivals.
  useEffect(() => {
    onSceneChangeRef.current?.(scene, pageId, documentId);
  }, [documentId, pageId, scene]);

  /**
   * Press-selects, the gesture machine's own semantics (the source editor
   * resolves its press target on pointer-down, not on click).
   *
   * The coordinate chain is `CanvasKitCanvas.tsx:589-617` collapsed to one
   * artboard, and every step matters:
   *
   *   pointer screen offset within the stage
   *     → `screenToWorkspace(point, viewport)`      undo pan + zoom
   *     → minus the artboard's workspace origin     artboard-local descriptor px
   *     → `descriptorToScene(local, unitScale)`     the engine's own units
   *     → `controls.hitTest(x, y)`                  bottom-to-top hit stack
   *     → `representableHit(stack, scene, pageId)`  §5's nearest schema-bearing node
   *
   * The last two conversions are the trap: `hitTest` takes SCENE units, not
   * descriptor px, and the two are identical on a `pt`/`px` page (this ad), so
   * a missing division is invisible here and wrong everywhere else. Both live
   * in `sceneHitPoint`, where they are unit-tested against a non-identity unit.
   */
  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    // Rung B: while a caret session is open the textarea owns the pointer, and
    // this press is the one that closes it — the blur commits. It arms nothing
    // and selects nothing (upstream's own `CanvasKitCanvas.tsx:990-993`), so a
    // press cannot start a drag on a document the commit is about to change.
    if (textEdit) {
      return;
    }
    // AD2.10: a held space or the middle button starts a PAN; a plain primary
    // press still selects. Panning and selecting share the surface, so the
    // discriminator is checked before anything else — and the pan needs no
    // engine, so it works on a disabled-engine canvas too.
    if (
      gestureInputsRef.current.artboard &&
      (spaceHeld || event.button === 1)
    ) {
      panDragRef.current = {
        pointerId: event.pointerId,
        origin: { point: stagePoint(event), pan: viewport.pan },
      };
      setPanning(true);
      event.currentTarget.setPointerCapture?.(event.pointerId);
      event.preventDefault();
      return;
    }
    // Secondary/middle buttons are not a selection gesture.
    if (event.button !== 0) {
      return;
    }
    const element = stageRef.current;
    // No engine → no hit test → NO selection change. A descriptor-space guess
    // would be a selection the engine never agreed to, and the write path that
    // follows in AD2.7 would act on it.
    if (!element || !artboard || !scene || engineStatus.engineDisabled) {
      return;
    }
    const bounds = element.getBoundingClientRect();
    const workspacePoint = screenToWorkspace(
      { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
      viewport,
    );
    const point = sceneDescriptorPoint(workspacePoint, artboard);
    // AD4.C step 1: a HANDLE GRAB on the current selection outranks the hit
    // test — the source host's own order (`CanvasKitCanvas.tsx:587-615`).
    // A corner handle straddles its node's edge, so resolving the hit first
    // would make the bottom-right handle select whatever is behind it instead
    // of starting a resize. It is also why this runs before `sceneHitPoint`'s
    // bounds check: a handle on a node at the page edge sits half off the
    // artboard, and pressing it is a resize, not a press on nothing.
    const handleTarget = scenePressHandleTarget({
      artboard,
      gesturesEnabled: !gestureDisabled,
      pageId,
      point,
      scene,
      selectedNodeId: activeSelectedNodeId,
      zoom: viewport.zoom,
    });
    if (handleTarget) {
      // A drawn handle is only grabbable if the press can actually act: the
      // freeze (when one is needed) must have landed.
      beginPress(event, point, handleTarget, freezeLayoutForPress(handleTarget));
      return;
    }
    const scenePoint = sceneHitPoint(workspacePoint, artboard);
    if (!scenePoint) {
      // Off the artboard entirely: clear, deliberately (not a no-op — the user
      // pressed somewhere with nothing in it). The empty press reduces to
      // exactly that selection, and is never armed, so it cannot become a
      // marquee (§1.9).
      beginPress(event, point, EMPTY_SCENE_PRESS.target, EMPTY_SCENE_PRESS.armed);
      return;
    }
    const result = controls.hitTest(scenePoint.x, scenePoint.y);
    if (!result) {
      return;
    }
    // `HitResult.stack` is bottom-to-top and its last member IS `hit` (the
    // engine's `hit_test` is literally `hit_stack(..).pop()`), so the stack
    // alone is the complete answer.
    const press = scenePressNodeTarget({
      artboard,
      gesturesEnabled: !gestureDisabled,
      nodeId: representableHit(result.stack, scene, pageId),
      pageId,
      scene,
    });
    // `press.armed` was resolved against the PRE-freeze scene, which is right
    // for the ordinary case (the freeze is zero-motion, so the box is the same
    // either side of it) and one case short: a node the freeze could not
    // actually free must not arm after all.
    const freed = freezeLayoutForPress(press.target);
    beginPress(event, point, press.target, press.armed && freed);
  };

  /**
   * Rung B (rich-text plan, 2026-08-24 — this SUPERSEDES §1.9/§7's "no
   * double-click text"): a double-click opens a caret on a text node, and
   * drills the selection out to its top-level container on anything else.
   *
   * The coordinate chain is `handlePointerDown`'s, unchanged and reused whole —
   * the same hit test answers both, so a double-click can never resolve to a
   * node a single click would not have selected. What differs is only what the
   * resolved node MEANS, and that decision is pure
   * (`adapter/scene-text-edit.ts`).
   *
   * Ruling C-9's freeze-on-grab deliberately does NOT fire here: a text session
   * changes content, and the solver re-solving around new content is the
   * solver working. Freezing the whole document's auto-layout because someone
   * fixed a typo would be a far larger edit than the one they asked for.
   */
  const handleDoubleClick = (event: ReactMouseEvent<HTMLDivElement>) => {
    const element = stageRef.current;
    // Same refusal as a press: with no engine there is no hit test, and a
    // descriptor-space guess would open a caret the engine never agreed to.
    if (!element || !artboard || !scene || engineStatus.engineDisabled) {
      return;
    }
    const bounds = element.getBoundingClientRect();
    const workspacePoint = screenToWorkspace(
      { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
      viewport,
    );
    const scenePoint = sceneHitPoint(workspacePoint, artboard);
    const result = scenePoint
      ? controls.hitTest(scenePoint.x, scenePoint.y)
      : null;
    const effect = sceneDoubleClickEffect({
      gestureDisabled,
      nodeId: result ? representableHit(result.stack, scene, pageId) : null,
      scene,
      selectedNodeId: activeSelectedNodeId,
    });
    switch (effect.kind) {
      case "edit":
        // Selected AND opened, in that order: a caret in a node the inspector
        // is not showing would be two surfaces disagreeing about the subject.
        commitSelection(effect.nodeId);
        setEditingNodeId(effect.nodeId);
        break;
      case "select":
        commitSelection(effect.nodeId);
        break;
      case "none":
        break;
    }
  };

  return (
    <div
      className={[
        styles.stage,
        panning ? styles.panning : "",
        !panning && spaceHeld ? styles.pannable : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onDoubleClick={handleDoubleClick}
      onPointerCancel={handlePointerCancel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      ref={stageRef}
    >
      <ArtboardSurface
        artboard={artboard}
        assets={scene?.assets}
        // Test/diagnostic hooks, not chrome: the honest engine + text
        // measurement state and the current selection, readable independently
        // of the approved visuals that now render them (Gates G-A / G-D).
        dataEngine={engineStatus.engineDisabled ? "disabled" : "wasm"}
        dataMeasurement={measurementStatus}
        dataFontDiagnostics={fontDiagnostics.length}
        dataSelectedNode={activeSelectedNodeId ?? "none"}
        viewport={viewport}
      />
      {/* The selection overlay: an absolutely-positioned sibling of the canvas
          (never a canvas draw), so selection never triggers a wasm redraw.
          AD4.C turns G-A's four corner handles on — the one thing Lane C was
          asked to pass, and nothing else about the overlay changes.

          Rung B: an open caret session takes the chrome down entirely (outline
          included — upstream's own `selectionBox && !editingNodeId`). Inside a
          session the subject is a RANGE OF TEXT, not a box, and a resize handle
          straddling the textarea's edge would grab a gesture the session has
          already refused. */}
      <SelectionChrome
        handles={selectionHandles && !textEdit}
        outline={textEdit ? null : selectionOutline}
      />
      {/* Rung B: the caret. CanvasKit cannot host one, so the session is a DOM
          textarea over the node — the design subsystem's own answer, ported. */}
      {textEdit ? (
        <SceneTextEditOverlay
          key={textEdit.nodeId}
          // Rung C: keyed on the NODE, never on its content — a formatting
          // action commits mid-session and the model's content and spans come
          // straight back changed, and a remount there would throw away the
          // live draft, the caret and the selection the next toggle acts on.
          model={textEdit}
          onCancel={cancelTextEdit}
          onCommit={commitTextEdit}
          onStyleCommit={commitTextEditStyle}
          palette={palette}
          stage={stageSize}
        />
      ) : null}
      {/* genad2 Task 5: the zero-page window, said out loud.
       *
       * `open_design_leg@4` births a chat-born ad as a document with `pages:
       * {}`, so the tab opens (F2's auto-open is unchanged — the newborn ad
       * still opens by itself; THIS is what it shows) onto a document that has
       * no artboard yet. Without this the stage painted an unexplained empty
       * workspace: no crash, but nothing to tell the user the agent simply has
       * not authored the page yet.
       *
       * It renders here, inside the stage, for the same reason the G-D banners
       * do: the stage is the one surface both mounts share, so the chats route
       * and the artifact route get it with no plumbing, and the state it reads
       * (`scene`, `pageId`) is already local. It deliberately does NOT suppress
       * the canvas element — the workspace behind it is the honest empty
       * surface, and the engine keeps its mounted surface for the turn that
       * authors the first page.
       *
       * FOUNDER-DESIGN FLAG (open, 2026-08-23): only the WORDS are ratified.
       * This ships as plain centred text on the empty workspace — the stage's
       * existing empty-frame idiom — because the neutral state's visual
       * (typography, illustration, placement, whether an illustration belongs
       * here at all) is an unmade design decision, and the presentation-truth
       * rule forbids inventing one. See `scene-pageless.ts`. */}
      {pagelessNotice ? (
        <p className={styles.pagelessNotice} role="status">
          {pagelessNotice}
        </p>
      ) : null}
      {/* Gate G-D: the two engine-forced states, said out loud. */}
      <SceneEngineBanners
        engineStatus={engineStatus}
        fontDiagnostics={fontDiagnostics}
        measurementStatus={measurementStatus}
      />
    </div>
  );
}

/**
 * Gate G-D (founder, 2026-08-21): the engine-forced failure banners.
 *
 * Both states were live and SILENT before this — a stamp mismatch made the
 * canvas read-only with nothing but a console line and a `data-scene-engine`
 * attribute to say so (the founder hit exactly that when the design API died),
 * and degraded text measurement is worse still, because the ad keeps rendering
 * while its geometry is approximate.
 *
 * The ruling was "as is from the MVP editor, no separate banner", so this is
 * the design subsystem's own `EngineDisabledBanner` / `HeuristicMeasurementBanner`
 * (`EditorChrome.tsx:200-288`) ported whole: same lucide alert glyph, same
 * copy (asserted against that file by `scene-engine-banners.test.ts`), same
 * geometry, and the read-only state gets the SAME treatment as the degraded one
 * rather than a canvas-specific variant.
 *
 * It lives here, inside the canvas stage, rather than in the shell: the stage
 * is the one surface both mounts share, so the artifact route and the chat
 * route get it with no plumbing, it survives the inspector being closed, and
 * the state it reads (`engineStatus`, `measurementStatus`) is already local.
 *
 * The third G-D state — the CAS conflict — is deliberately NOT here: it stays
 * the inspector's existing note line ("Document moved on — reloaded.", D10).
 */
function SceneEngineBanners({
  engineStatus,
  fontDiagnostics,
  measurementStatus,
}: {
  engineStatus: SceneEngineStatus;
  fontDiagnostics: Diagnostic[];
  measurementStatus: string;
}) {
  const banners = sceneEngineBanners(
    engineStatus,
    measurementStatus,
    fontDiagnostics,
  );
  // Nothing wrong → no element at all, so a healthy canvas holds no space and
  // no assistive technology announces an empty alert region.
  if (banners.length === 0) {
    return null;
  }
  return (
    <div className={styles.bannerLayer}>
      {banners.map((banner) => (
        <div
          className={styles.banner}
          data-scene-banner={banner.kind}
          key={banner.kind}
          role="alert"
        >
          <AlertTriangleIcon
            aria-hidden="true"
            className={styles.bannerIcon}
            size={18}
          />
          <div className={styles.bannerBody}>
            <strong className={styles.bannerTitle}>{banner.title}</strong>
            <span className={styles.bannerText}>{banner.body}</span>
            {/* The chip ellipses (upstream's own `white-space: nowrap`), and
                our command string is longer than upstream's, so the DETAIL —
                the two engine hashes, the diagnosis — is what gets cut. The
                title restores it in full on hover without touching the approved
                visual; the console diagnostic still carries it too. */}
            <code
              className={styles.bannerCommand}
              title={
                banner.detail
                  ? `${banner.command} · ${banner.detail}`
                  : banner.command
              }
            >
              <span className={styles.bannerCommandName}>{banner.command}</span>
              {banner.detail ? ` · ${banner.detail}` : null}
            </code>
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Gate G-A's approved selection chrome (Variant B).
 *
 * An SVG with no `viewBox`, so its user units ARE the stage's CSS px and the
 * outline the adapter computed can be stroked verbatim. The stroke width is a
 * screen constant, not a scaled one: the outline is chrome, and the viewport
 * scales content only.
 *
 * Rotation is applied to a `<g>` about the box origin — the same pivot the draw
 * loop rotates a node about — so the outline and (later) its handles turn
 * together with one transform.
 *
 * `handles` is G-A-approved geometry, **enabled by AD4.C** — the canvas passes
 * it exactly when the selection can actually be resized (an editable node, a
 * live engine, and no in-flight agent turn). It keeps its `false` default so a
 * caller that has no drag behaviour behind it still cannot draw a fake
 * affordance.
 */
function SelectionChrome({
  handles = false,
  outline,
}: {
  handles?: boolean;
  outline: SceneSelectionOutline | null;
}) {
  // No selection → no element at all, not an empty overlay.
  if (!outline) {
    return null;
  }
  return (
    <svg
      aria-hidden="true"
      className={styles.selectionChrome}
      data-scene-selection-outline={outline.nodeId}
    >
      <g
        transform={
          outline.rotation
            ? `rotate(${outline.rotation} ${outline.x} ${outline.y})`
            : undefined
        }
      >
        <rect
          fill="none"
          height={outline.height}
          stroke={SELECTION_OUTLINE_COLOR}
          strokeWidth={SELECTION_OUTLINE_WIDTH}
          width={outline.width}
          x={outline.x}
          y={outline.y}
        />
        {handles
          ? selectionHandleRects(outline).map((handle) => (
              <rect
                fill={SELECTION_HANDLE_FILL}
                height={handle.size}
                key={`${handle.x},${handle.y}`}
                rx={SELECTION_HANDLE_CORNER_RADIUS}
                stroke={SELECTION_HANDLE_STROKE}
                strokeWidth={SELECTION_HANDLE_STROKE_WIDTH}
                width={handle.size}
                x={handle.x}
                y={handle.y}
              />
            ))
          : null}
      </g>
    </svg>
  );
}

/**
 * Rung B: the caret surface — the design subsystem's `TextEditOverlay`
 * (`subsystems/clue-design/apps/editor/src/components/canvas/TextEditOverlay.tsx`)
 * ported, presentation and all.
 *
 * CanvasKit cannot host a live caret, so the session is a DOM `<textarea>`
 * positioned over the node and styled to match the painted glyphs. It edits the
 * STORED content (`text_transform` applies to painted text only).
 *
 * Commit on blur or ⌘/Ctrl+Enter, Escape cancels — and the settle flag exists
 * because Escape blurs too, so without it a cancel would commit on the way out.
 * Every key event stops here: an unqualified Enter is a newline, and the
 * canvas's own window listeners (space-pan, AD4.C's Escape) are already inert
 * over a typing target.
 *
 * Two things are NOT ported, because the platform has the real thing: the
 * clamped valign formula is `renderAdapter`'s own `valignOffset` (the single
 * source both editor legs and the engine share), and everything that is not
 * data-driven — the border, the surface, the reset — is a CSS module rule
 * rather than an inline literal.
 *
 * ── RUNG C: THE SESSION IS NOW A PAIR ────────────────────────────────────
 * The session holds the draft AND a working spans vector, maintained across
 * every keystroke so range styling stays attached to the text it was applied
 * to. The transitions are pure (`adapter/scene-text-session.ts`); what is here
 * is the DOM half of them:
 *
 *  • `beforeinput` is read through a NATIVE listener, because it is where the
 *    replacement can still be placed against the string that is about to
 *    change. The prediction it produces is only ever used if the `input` event
 *    that follows proves it right — otherwise the diff remap recovers it, so an
 *    IME or an autofill can never silently misplace styling.
 *  • the selection is tracked on the standard trio (`select`/`keyup`/`mouseup`)
 *    because the toolbar's state, its enablement and every write it makes are
 *    all functions of it.
 *  • the overlay shows the draft as PLAIN text (upstream parity, and the plan's
 *    recorded honesty cost): the styling appears on the canvas the moment a
 *    formatting action commits, which is immediately.
 *
 * Escape still cancels the UNCOMMITTED tail only. Formatting actions have
 * already landed as their own undo frames by then (founder-visible item 5) and
 * stay landed — ⌘Z takes them back one at a time, which is what "its own undo
 * frame" means.
 */
function SceneTextEditOverlay({
  model,
  onCancel,
  onCommit,
  onStyleCommit,
  palette,
  stage,
}: {
  model: SceneTextEditModel;
  onCancel: () => void;
  onCommit: (session: TextEditSession) => void;
  onStyleCommit: (session: TextEditSession) => void;
  palette: ScenePalette | null;
  stage: { width: number; height: number };
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const [session, setSession] = useState<TextEditSession>(() => ({
    content: model.content,
    spans: model.text.spans ?? [],
  }));
  // The mount effect below focuses and SELECTS ALL, so that is where the
  // selection starts — stated here rather than waiting for the first `select`
  // event, so the toolbar is never briefly wrong about it.
  const [selection, setSelection] = useState<TextEditSelection>(() => ({
    start: 0,
    end: model.content.length,
  }));
  // Event handlers bound to the DOM (and the window listener below) must read
  // the CURRENT session and selection, not the ones captured when they were
  // created — the same ref-mirror the canvas's gesture inputs use.
  const sessionRef = useRef(session);
  const selectionRef = useRef(selection);
  useEffect(() => {
    sessionRef.current = session;
    selectionRef.current = selection;
  });
  /** The tracked `beforeinput` prediction awaiting its `input` event. */
  const predictionRef = useRef<TextEditSession | null>(null);
  /** Focus is inside the toolbar: a blur is NOT the end of the session. */
  const interactingRef = useRef(false);
  // A settled session must not settle twice: Escape blurs on its way out, and
  // the outside-pointer listener can race the blur that follows it.
  const settledRef = useRef(false);

  // A7a: match the painted vertical position with a computed top padding. The
  // content height is a LIVE DOM measurement — the only part of the geometry a
  // pure model cannot answer — so it is recomputed as the text grows and
  // shrinks, keeping the caret aligned mid-session.
  //
  // Written STRAIGHT TO THE ELEMENT rather than held in state (upstream holds
  // it in a `useState`): it is a measurement of the DOM feeding a style of the
  // same DOM node, so a render round-trip buys nothing and costs one per
  // keystroke. `paddingTop` is deliberately absent from the `style` prop below,
  // which is what keeps React from overwriting it on the next render.
  const recomputePadding = useCallback(() => {
    const element = ref.current;
    if (!element) {
      return;
    }
    if (model.style.valign === "top") {
      element.style.paddingTop = "0px";
      return;
    }
    // `scrollHeight` floors at `clientHeight` (so content shorter than the box
    // reads back AS the box) and counts whatever padding is already applied —
    // both are zeroed for the read and the height is restored before paint.
    const previousHeight = element.style.height;
    element.style.paddingTop = "0px";
    element.style.height = "0px";
    const contentHeight = element.scrollHeight;
    element.style.height = previousHeight;
    element.style.paddingTop = `${valignOffset(
      model.height,
      contentHeight,
      model.style.valign,
    )}px`;
  }, [model.height, model.style.valign]);

  // MOUNT ONLY: focus the caret and select the node's text, upstream's own
  // opening gesture. Rung C splits this out of the padding effect deliberately
  // — that one re-runs whenever the box or the valign changes, which a
  // formatting commit can do, and re-running `select()` there would silently
  // reset the user's range after every toggle.
  useEffect(() => {
    const element = ref.current;
    if (element) {
      element.focus();
      element.select();
    }
  }, []);

  useEffect(() => {
    recomputePadding();
  }, [recomputePadding]);

  /**
   * The tracked half of rung C's typing path.
   *
   * A NATIVE listener, not React's `onBeforeInput`: only the native event
   * carries `inputType` and `getTargetRanges()`, and this is the one moment the
   * change can still be placed against the string it is changing.
   *
   * `getTargetRanges()` is consulted where it is USABLE — for a `<textarea>` it
   * is empty in every shipping engine (the edited text lives in a shadow tree
   * the ranges cannot address), so the reported selection is the authority
   * here. The pure derivation takes both, so the contentEditable upgrade path
   * the plan records needs no new decision.
   */
  useEffect(() => {
    const element = ref.current;
    if (!element) {
      return;
    }
    const handleBeforeInput = (event: Event) => {
      const input = event as InputEvent;
      const ranges = input.getTargetRanges?.() ?? [];
      const range = ranges[0];
      const addressable =
        range !== undefined &&
        range.startContainer === element.firstChild &&
        range.endContainer === element.firstChild;
      const replacement = textEditReplacement({
        content: sessionRef.current.content,
        data: input.data,
        inputType: input.inputType,
        selection: {
          start: element.selectionStart ?? 0,
          end: element.selectionEnd ?? 0,
        },
        targetRange: addressable
          ? { start: range.startOffset, end: range.endOffset }
          : null,
      });
      predictionRef.current = replacement
        ? textEditSessionAfterReplacement(sessionRef.current, replacement)
        : null;
    };
    element.addEventListener("beforeinput", handleBeforeInput);
    return () => element.removeEventListener("beforeinput", handleBeforeInput);
  }, []);

  /** End the session exactly once. */
  const settle = useCallback(
    (kind: "commit" | "cancel") => {
      if (settledRef.current) {
        return;
      }
      settledRef.current = true;
      if (kind === "commit") {
        onCommit(sessionRef.current);
      } else {
        onCancel();
      }
    },
    [onCancel, onCommit],
  );

  /**
   * The one case a blur cannot cover: focus moved INTO the toolbar (the hex
   * field), so the session was deliberately held open — and then the user
   * pressed somewhere else entirely. Without this the session would have no
   * blur left to close it.
   */
  useEffect(() => {
    const handleOutsidePointer = (event: PointerEvent) => {
      if (!interactingRef.current) {
        return;
      }
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest("[data-scene-text-edit],[data-scene-text-toolbar]")
      ) {
        return;
      }
      settle("commit");
    };
    window.document.addEventListener("pointerdown", handleOutsidePointer, true);
    return () =>
      window.document.removeEventListener(
        "pointerdown",
        handleOutsidePointer,
        true,
      );
  }, [settle]);

  const trackSelection = (element: HTMLTextAreaElement) => {
    setSelection({
      start: element.selectionStart ?? 0,
      end: element.selectionEnd ?? 0,
    });
  };

  /**
   * One formatting action: compute the new vector over the LIVE draft, adopt
   * it, and commit immediately as its own batch (founder-visible item 5). The
   * session stays open and the selection stays exactly where it is, so the next
   * toggle acts on the same range.
   *
   * `sessionRef` is written straight through as well as through state: two
   * actions inside one tick (a chord repeat) must not both compute from the
   * pre-first-action vector.
   */
  const applyStyle = (patch: StylePatch) => {
    const current = sessionRef.current;
    const next: TextEditSession = {
      content: current.content,
      spans: textEditStyledSpans(
        model.text,
        current,
        selectionRef.current,
        patch,
      ),
    };
    sessionRef.current = next;
    setSession(next);
    onStyleCommit(next);
  };

  const applyMark = (channel: SceneTextMarkChannel) => {
    const format = textEditFormatState(
      model.text,
      sessionRef.current,
      selectionRef.current,
    );
    applyStyle(sceneTextMarkPatch(channel, format[channel]));
  };

  const applyFill = (choice: SceneTextFillChoice) => {
    const patch = sceneTextFillPatch(palette, choice);
    // Null is a refused colour (an unresolvable token, an unusable hex) — the
    // §1.6 null contract, which writes nothing rather than guessing one.
    if (patch) {
      applyStyle(patch);
    }
  };

  /** Put the caret back where the toolbar borrowed focus from. */
  const restoreFocus = () => {
    interactingRef.current = false;
    const element = ref.current;
    if (!element) {
      return;
    }
    element.focus();
    element.setSelectionRange(
      selectionRef.current.start,
      selectionRef.current.end,
    );
  };

  const collapsed = selection.start === selection.end;
  const format = textEditFormatState(model.text, session, selection);
  // The toolbar measures itself against this box, so it must not be a fresh
  // object on every keystroke — that would re-run its placement effect (and its
  // `setPosition`) for every character typed.
  const toolbarBox = useMemo(
    () => ({
      height: model.height,
      left: model.left,
      top: model.top,
      width: model.width,
    }),
    [model.height, model.left, model.top, model.width],
  );

  return (
    <>
      <textarea
        aria-label="Edit text"
        className={styles.textEditOverlay}
        data-scene-text-edit={model.nodeId}
        onBlur={() => {
          // Focus inside the toolbar is still inside the session.
          if (!interactingRef.current) {
            settle("commit");
          }
        }}
        onChange={(event) => {
          const prediction = predictionRef.current;
          predictionRef.current = null;
          setSession(
            textEditSessionAfterInput(
              sessionRef.current,
              prediction,
              event.target.value,
            ),
          );
          trackSelection(event.target);
          recomputePadding();
        }}
        onDoubleClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          const chord = sceneTextStyleChord(event);
          if (chord) {
            // Always swallowed, applied only when there is a range to apply it
            // to: ⌘/Ctrl+U is the browser's own view-source in some engines, and
            // a chord that sometimes reaches it would be worse than one that
            // never does.
            event.preventDefault();
            if (!collapsed) {
              applyMark(chord);
            }
          } else if (event.key === "Escape") {
            event.preventDefault();
            settle("cancel");
          } else if (textareaCommitKey(event)) {
            // Otherwise the chord also types the newline it is committing past.
            event.preventDefault();
            settle("commit");
          }
          event.stopPropagation();
        }}
        onKeyUp={(event) => trackSelection(event.currentTarget)}
        onMouseUp={(event) => trackSelection(event.currentTarget)}
        onPointerDown={(event) => event.stopPropagation()}
        onSelect={(event) => trackSelection(event.currentTarget)}
        ref={ref}
        style={{
          color: model.style.color,
          fontFamily: model.style.fontFamily,
          fontSize: model.style.fontSize,
          fontStyle: model.style.fontStyle,
          fontWeight: model.style.fontWeight,
          height: model.height,
          left: model.left,
          letterSpacing: `${model.style.letterSpacing}px`,
          lineHeight: String(model.style.lineHeight),
          textAlign: model.style.textAlign,
          top: model.top,
          transform: model.rotation
            ? `rotate(${model.rotation}deg)`
            : undefined,
          width: model.width,
        }}
        value={session.content}
      />
      {/* Rung C: the range toolbar. A sibling of the caret, not a child of it —
          a `<textarea>` can hold no elements — positioned in the same stage px.
          `inert` is deliberately false: Gate G-H stops a session from OPENING
          while a turn is in flight, and an open one is not force-killed by a
          turn start (the same posture an in-flight gesture takes; D10 CAS is
          the net). A locked node can never have a session at all. */}
      <SceneTextToolbar
        box={toolbarBox}
        collapsed={collapsed}
        format={format}
        inert={false}
        nodeColor={model.style.color}
        nodeId={model.nodeId}
        onFill={applyFill}
        onInteractionEnd={restoreFocus}
        onInteractionStart={() => {
          interactingRef.current = true;
        }}
        onMark={applyMark}
        palette={palette}
        stage={stage}
      />
    </>
  );
}

/**
 * The imperative surface: everything below this line is the ported
 * `CanvasKitStage`, collapsed to one artboard.
 */
function ArtboardSurface({
  artboard,
  assets,
  dataEngine,
  dataFontDiagnostics,
  dataMeasurement,
  dataSelectedNode,
  viewport,
}: {
  artboard: SceneArtboardModel | null;
  assets: Scene["assets"] | undefined;
  dataEngine: string;
  dataFontDiagnostics: number;
  dataMeasurement: string;
  dataSelectedNode: string;
  viewport: WorkspaceViewport;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ckRef = useRef<CanvasKit | null>(null);
  const fontRef = useRef<TypefaceFontProvider | null>(null);
  const imagesRef = useRef<CanvasKitImageCache | null>(null);
  const surfaceRef = useRef<Surface | null>(null);
  const dirtyRef = useRef(false);
  const rafRef = useRef(0);
  // Resize is coalesced into the SAME rAF as the repaint: resetting the canvas
  // bitmap (element.width = …) blanks it, so wipe-and-redraw must happen
  // inside one frame callback or every resize step presents a blank stage.
  const resizePendingRef = useRef(false);
  const remakeSurfaceRef = useRef<(() => void) | null>(null);
  // The draw loop reads the LATEST props through a ref (the source stage
  // assigns it during render; this repo's lint requires the passive-effect
  // form). Declared BEFORE the invalidate effect below so the props it
  // publishes are already current when that effect marks the frame dirty —
  // and the rAF itself only runs after paint, well after both.
  const propsRef = useRef({ artboard, assets, viewport });
  useEffect(() => {
    propsRef.current = { artboard, assets, viewport };
  });

  // One draw pass; scheduled at most once per frame, only while dirty.
  const flush = () => {
    rafRef.current = 0;
    const ck = ckRef.current;
    if (resizePendingRef.current && ck) {
      remakeSurfaceRef.current?.();
    }
    const surface = surfaceRef.current;
    if (!ck || !surface || !dirtyRef.current) {
      return;
    }
    dirtyRef.current = false;
    const current = propsRef.current;
    const canvas = surface.getCanvas();
    canvas.save();
    const dpr = typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
    canvas.scale(dpr, dpr);
    // AD2.10: the workspace — the source stage's own clear, reading the same
    // `--bg-canvas` custom property. This is what makes the surface an infinite
    // canvas rather than a hole in a card.
    canvas.clear(workspaceCanvasColor(ck, canvasRef.current));
    if (current.artboard) {
      canvas.translate(current.viewport.pan.x, current.viewport.pan.y);
      canvas.scale(current.viewport.zoom, current.viewport.zoom);
      drawArtboard(
        ck,
        canvas,
        current.artboard,
        current.viewport,
        fontRef.current,
        imagesRef.current,
      );
    }
    canvas.restore();
    surface.flush();
  };

  const invalidate = () => {
    dirtyRef.current = true;
    if (!rafRef.current && typeof requestAnimationFrame === "function") {
      rafRef.current = requestAnimationFrame(flush);
    }
  };

  // Mount: load CanvasKit once, then bind a surface to this canvas element.
  useEffect(() => {
    let disposed = false;
    const element = canvasRef.current;
    if (!element) {
      return;
    }

    const makeSurface = (ck: CanvasKit) => {
      resizePendingRef.current = false;
      try {
        surfaceRef.current?.delete();
        const dpr = typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
        element.width = Math.max(1, Math.floor(element.clientWidth * dpr));
        element.height = Math.max(1, Math.floor(element.clientHeight * dpr));
        surfaceRef.current =
          ck.MakeWebGLCanvasSurface(element) ?? ck.MakeSWCanvasSurface(element);
      } catch {
        // Surface creation can fail (no GPU/context): leave the canvas blank
        // rather than throwing through the shell.
        surfaceRef.current = null;
      }
    };
    remakeSurfaceRef.current = () => {
      if (ckRef.current) {
        makeSurface(ckRef.current);
      }
    };

    void loadCanvasKit().then((bundle) => {
      if (disposed || !bundle) {
        return;
      }
      ckRef.current = bundle.ck;
      fontRef.current = bundle.fontProvider;
      // Bridges async asset bytes into the synchronous draw loop: a decode
      // landing re-renders the frame with real pixels. Resolution reads
      // through propsRef so it always sees the LATEST scene, and goes to the
      // headerless public passthrough (the cache fetches bare — a
      // workspace-gated URL could only ever 401).
      imagesRef.current = new CanvasKitImageCache(bundle.ck, {
        resolveUrl: (assetId) =>
          sceneAssetPassthroughUrl(propsRef.current.assets, assetId),
        onLoad: invalidate,
      });
      makeSurface(bundle.ck);
      invalidate();
    });

    const observer =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            // Skip no-op notifications (observe() fires once immediately);
            // real size changes wait for the next paint frame so the bitmap
            // wipe and the redraw land together.
            const dpr =
              typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
            const targetWidth = Math.max(
              1,
              Math.floor(element.clientWidth * dpr),
            );
            const targetHeight = Math.max(
              1,
              Math.floor(element.clientHeight * dpr),
            );
            if (
              element.width === targetWidth &&
              element.height === targetHeight
            ) {
              return;
            }
            resizePendingRef.current = true;
            invalidate();
          })
        : null;
    observer?.observe(element);

    // The ResizeObserver only sees CSS-size changes — devicePixelRatio can
    // change with NO size change (window dragged to another display, display
    // scaling, browser zoom). Without this watcher the surface keeps the old
    // density forever and every frame is CSS-stretched. matchMedia is re-armed
    // per value because a resolution query only fires when ITS OWN value stops
    // holding.
    let dprQuery: MediaQueryList | null = null;
    const onDprChange = () => {
      resizePendingRef.current = true;
      invalidate();
      armDprWatch();
    };
    const armDprWatch = () => {
      if (typeof matchMedia !== "function") {
        return;
      }
      dprQuery?.removeEventListener?.("change", onDprChange);
      const dpr = typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
      dprQuery = matchMedia(`(resolution: ${dpr}dppx)`);
      dprQuery.addEventListener?.("change", onDprChange);
    };
    armDprWatch();

    return () => {
      disposed = true;
      observer?.disconnect();
      dprQuery?.removeEventListener?.("change", onDprChange);
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        // Reset the guard: leaving the (now-cancelled) id here would make the
        // next invalidate() skip scheduling, so a re-mount (React StrictMode
        // double-invokes effects in dev) would never redraw.
        rafRef.current = 0;
      }
      surfaceRef.current?.delete();
      surfaceRef.current = null;
      imagesRef.current?.dispose();
      imagesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Descriptor / viewport changes mark dirty; drawing happens in rAF.
  useEffect(invalidate, [artboard, viewport]);

  return (
    <canvas
      className={styles.canvas}
      data-scene-engine={dataEngine}
      data-scene-font-diagnostics={dataFontDiagnostics}
      data-scene-selected-node={dataSelectedNode}
      data-scene-text-measurement={dataMeasurement}
      ref={canvasRef}
    />
  );
}

/**
 * The workspace surface colour, ported verbatim from the source stage
 * (`CanvasKitStage.workspaceCanvasColor`) with one improvement: the custom
 * property is read from the CANVAS, not from `document.documentElement`, so a
 * `--bg-canvas` defined anywhere up this subtree (the stage's own module CSS
 * defines it, since the platform shell does not) is honoured and the painted
 * pixels can never disagree with the CSS backdrop behind them.
 */
function workspaceCanvasColor(
  ck: CanvasKit,
  element: Element | null,
): Float32Array {
  const css =
    element && typeof getComputedStyle === "function"
      ? getComputedStyle(element).getPropertyValue("--bg-canvas").trim()
      : "";
  return (
    parseColor(ck, css || WORKSPACE_CANVAS_FALLBACK) ??
    ck.Color4f(0.961, 0.961, 0.961, 1)
  );
}

/**
 * One artboard on the workspace: shadow, content, edge.
 *
 * The order is the source's `drawArtboard` — shell behind, content clipped to
 * the page box, border stroked on top — and the clip is the load-bearing part:
 * it is what makes the artboard's own edges the ONLY boundary the page has, now
 * that nothing else surrounds it. Overflowing content stops at the page edge;
 * everything outside is workspace.
 *
 * Every Paint (and the MaskFilter) is deleted before returning: these are wasm
 * heap objects, and the draw loop runs on every frame of a pan.
 */
function drawArtboard(
  ck: CanvasKit,
  canvas: ReturnType<Surface["getCanvas"]>,
  artboard: SceneArtboardModel,
  viewport: WorkspaceViewport,
  fontProvider: TypefaceFontProvider | null,
  images: CanvasKitImageCache | null,
) {
  const rect = artboard.rect;
  const chrome = artboardChromeGeometry(rect, viewport.zoom);

  const shadowPaint = new ck.Paint();
  shadowPaint.setAntiAlias(true);
  shadowPaint.setStyle(ck.PaintStyle.Fill);
  shadowPaint.setColor(parseColor(ck, ARTBOARD_SHADOW_COLOR) ?? ck.BLACK);
  const blur = ck.MaskFilter.MakeBlur(
    ck.BlurStyle.Normal,
    chrome.shadowSigma,
    true,
  );
  shadowPaint.setMaskFilter(blur);
  canvas.drawRect(
    ck.LTRBRect(
      chrome.shadow.x,
      chrome.shadow.y,
      chrome.shadow.x + chrome.shadow.width,
      chrome.shadow.y + chrome.shadow.height,
    ),
    shadowPaint,
  );
  blur.delete();
  shadowPaint.delete();

  canvas.save();
  canvas.translate(rect.x, rect.y);
  canvas.clipRect(
    ck.LTRBRect(0, 0, artboard.page.width, artboard.page.height),
    ck.ClipOp.Intersect,
    true,
  );
  drawDescriptorTree(
    ck,
    canvas,
    artboard.page,
    artboard.nodes,
    fontProvider,
    images,
  );
  canvas.restore();

  const borderPaint = new ck.Paint();
  borderPaint.setAntiAlias(true);
  borderPaint.setStyle(ck.PaintStyle.Stroke);
  borderPaint.setStrokeWidth(chrome.borderWidth);
  borderPaint.setColor(parseColor(ck, ARTBOARD_BORDER_COLOR) ?? ck.BLACK);
  canvas.drawRect(
    ck.LTRBRect(rect.x, rect.y, rect.x + rect.width, rect.y + rect.height),
    borderPaint,
  );
  borderPaint.delete();
}
