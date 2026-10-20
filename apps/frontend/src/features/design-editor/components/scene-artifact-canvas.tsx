"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type DragEvent as ReactDragEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import type { CanvasKit, Surface, TypefaceFontProvider } from "canvaskit-wasm";
import { AlertTriangleIcon, ChevronDownIcon, XIcon } from "lucide-react";
import { textareaCommitKey } from "@/features/chat-shell/components/inspector-field-draft";
import { sceneEngineBanners } from "../adapter/scene-engine-banners";
import { effectiveScenePageId, scenePagelessNotice } from "../adapter/scene-pageless";
import {
  ARTBOARD_BORDER_COLOR,
  ARTBOARD_SHADOW_COLOR,
  HOVER_OUTLINE_OPACITY,
  HOVER_OUTLINE_WIDTH,
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
  selectionStrokesPaintedOutline,
  type SceneArtboardModel,
  type ScenePreview,
  type SceneSelectionOutline,
} from "../adapter/scene-canvas-view";
import {
  EMPTY_SCENE_PRESS,
  freezeMotionReport,
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
import { sceneHitPoint } from "../adapter/scene-selection";
import {
  deepSelectTarget,
  escapeSelectionEffect,
  sceneHoverTarget,
  selectionPressTarget,
  selectionWalkUp,
} from "../adapter/scene-selection-ladder";
import type { ScenePalette } from "../adapter/scene-palette";
import {
  SCENE_TEXT_EDIT_INTENT,
  SCENE_TEXT_STYLE_INTENT,
  sceneDoubleClickEffect,
  sceneTextEditModel,
  textEditSurfaceHeight,
  type SceneTextEditModel,
} from "../adapter/scene-text-edit";
import {
  textEditFormatState,
  textEditReplacement,
  textEditSessionAfterInput,
  textEditSessionAfterReplacement,
  textEditSessionAfterStyle,
  textEditSessionAfterStyleCommit,
  textEditSessionEnds,
  textEditSessionOperations,
  textEditSessionReseed,
  textEditSessionReseedSelection,
  textEditSessionSeed,
  textEditStyledSpans,
  type TextEditSelection,
  type TextEditSession,
} from "../adapter/scene-text-session";
import type { StylePatch } from "../engine/scene/textSpans";
import { SceneTextToolbar } from "./scene-text-toolbar";
import {
  sceneTextFillPatch,
  sceneTextMarkPatch,
  sceneTextMarkUnavailableReason,
  sceneTextStyleChord,
  type SceneTextFaceAvailability,
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
  boldChangesFace,
  hasItalicFace,
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
  Derivation,
  EngineApplyOutcome,
  EngineStructuredEditOutcome,
  HitResult,
} from "../engine/scene/wasmEngine";
import { descriptorToScene } from "../engine/scene/canvaskitGestures";
import type { Point } from "../engine/scene/workspaceLayout";
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
   * Task 9 (scene live-streaming rung B): apply a STREAMED batch to the live
   * engine and repaint NOTHING.
   *
   * The deliberate half-sibling of `applyOperations` above, and the whole
   * difference is the repaint. The reveal pump runs the engine AHEAD of the
   * picture on purpose — it holds each element back until its draw clock
   * elapses, and then shows the applied scene through `displayScene` below — so
   * a `refresh()` here would materialize the content the instant it was applied
   * and there would be no reveal left to hold.
   *
   * It mirrors nothing up either. The scene it produces is not the document:
   * nothing here is durable until the agent commits a checkpoint, so feeding
   * it to the session would put an uncommitted picture behind the inspector,
   * the layer tree and the edit-target chips.
   *
   * Null when the engine is unavailable, exactly as `applyOperations` is — and
   * the pump reads that null as a refusal, because it is one: nothing was
   * applied, so nothing may be shown.
   */
  applyStreamedOperations(operations: Operation[]): EngineApplyOutcome | null;
  /** Opaque identity for replay bookkeeping; never used to mutate the engine. */
  streamEngineIdentity?(): object | null;
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
  /**
   * Task 4 (scene live-streaming rung A): commit any OPEN caret session right
   * now, exactly as a blur would.
   *
   * The founder default for the agent-run lock: a lock closing over a session
   * with typed changes force-commits it, so the human's paragraph lands instead
   * of being stranded behind a write path that has just gone inert. The draft
   * lives inside the overlay component, so the flush has to be imperative — a
   * prop could only ask the overlay to unmount, which is precisely the silent
   * loss this prevents.
   *
   * A no-op with no session open, and it must be called BEFORE the caller's own
   * lock latch closes: the commit rides the same `onOperations` write path every
   * other edit does (`engageSceneWriteLock` owns that ordering).
   */
  flushTextEdit(): void;
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
  presentationSnapshot?(): Scene | null;
  /**
   * Clipboard Task 8 / R21: the centre of what the user is LOOKING at, in page
   * space — where a ⌘V of an image file lands when no pointer named a spot.
   *
   * The canvas is the only surface that knows it: the viewport is derived here
   * (fit, chosen step, or wherever a pan/zoom gesture left it) and never leaves
   * this component. Null when there is no artboard or the stage has not been
   * measured yet — the caller then falls back to the page's own centre.
   */
  viewportPageCenter(): { x: number; y: number } | null;
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
   * The chats route passes the agent-run lock (task 4,
   * `chat-shell/model/agent-run-lock`), the same source the inspector's
   * `inspectorDisabled` reads. The artifact route deliberately passes nothing —
   * it has no live turn stream to read, and its net stays the D10 CAS
   * reconciliation (see the comment at that call site).
   */
  gestureDisabled?: boolean;
  /**
   * Task 9 (scene live-streaming rung B): draw THIS scene instead of the loaded
   * document, for as long as it is non-null.
   *
   * The same substitution shape AD4.C's gesture `preview` already uses, and
   * kept just as narrow: it supplies the artboard model and its image assets
   * to the draw loop, and touches no state, no selection, no hit test and
   * no write path. Null (the default, and every route but the chat surface)
   * renders the document exactly as before.
   *
   * It is a PICTURE, never a document. The reveal pump that produces it applies
   * streamed operations to the live engine and shows them on an animation
   * clock; nothing it does is durable, and it drops back to null the moment the
   * agent-run lock releases — at which point rung A has already reloaded the
   * canvas from the committed version.
   */
  displayScene?: Scene | null;
  /**
   * Task 4: this press or double-click WOULD have edited the document, and was
   * refused only because `gestureDisabled` holds.
   *
   * The canvas owns no message state, so it reports the refusal instead of
   * inventing somewhere to put it; the shell routes it to the one inline note
   * line every other refusal on this lane already uses. Never fired for a press
   * that changes nothing anyway (a plain selection, a press on empty
   * workspace) — an unasked-for note is noise, not honesty.
   */
  onLockedEdit?: () => void;
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
    presentationScene?: Scene | null,
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
  /**
   * Clipboard Task 8: image files DROPPED on the stage, with the page point the
   * pointer named — the session uploads them and inserts them centred there.
   *
   * Absent (the standalone read path) means a file drop is left entirely to the
   * browser, which is what it does everywhere else in the app today.
   */
  onDropImageFiles?: (
    files: File[],
    pagePoint: { x: number; y: number },
  ) => void;
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

/**
 * Clipboard Task 8 / R21: a workspace-space point in PAGE space (scene units)
 * — the space the paste planner, the payload bounds and `page.size` all speak.
 *
 * It is `sceneHitPoint`'s chain (`scene-selection.ts:42-59`) without its
 * artboard containment test: both callers below name a point that may legally
 * sit off the page (a drop on the workspace beside the artboard, a viewport
 * panned past the page edge), and a node whose box extends past the page is
 * something this engine already models. The `unitScale` divide is NOT optional
 * — descriptor px are scene units only on a `pt`/`px` page, and wrong by 96x on
 * an `in` one, which is the trap `sceneHitPoint`'s own docblock records.
 */
function pagePointOf(workspacePoint: Point, artboard: SceneArtboardModel): Point {
  return descriptorToScene(
    sceneDescriptorPoint(workspacePoint, artboard),
    artboard.page.unitScale,
  );
}

function SceneDocumentCanvas({
  controlsRef,
  displayScene = null,
  documentId,
  gestureDisabled = false,
  onAppliedOperations,
  onDropImageFiles,
  onEngineStatusChange,
  onFitZoom,
  onGestureZoom,
  onHistoryChange,
  onLockedEdit,
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
  // D3a: how much of the stage's TOP the G-D banner band is occupying, in
  // stage px — 0 whenever no banner is up. Measured rather than assumed: a
  // banner wraps to two lines on a narrow stage, and a fixed guess would put
  // the caret toolbar back under it exactly then.
  const [bannerInset, setBannerInset] = useState(0);
  const [ownSelectedNodeId, setOwnSelectedNodeId] = useState<NodeId | null>(
    null,
  );
  // Plan 3 R4: the node an idle pointer is over — what a click would select,
  // resolved through the same ladder the press uses. Null whenever nothing is
  // hovered, a caret is open, a gesture is running, or the pointer has left.
  const [hoverNodeId, setHoverNodeId] = useState<NodeId | null>(null);
  const {
    currentVersion,
    engine,
    engineStatus,
    fontDiagnostics,
    measurementIncomplete,
    loadGeneration,
    pageId: loadedPageId,
    redoDepth,
    refresh,
    scene,
    presentationScene,
    tokenGeneration,
    undoDepth,
  } = useSceneDocument(documentId, reloadToken);

  // The engine's own text-measurement status store — `heuristic` means the
  // Skia pass never ran, which is a real rendering difference the G-D banner
  // names (it was silent until then: the ad renders either way).
  const shapingStatus = useSyncExternalStore(
    subscribeTextMeasurementStatus,
    textMeasurementStatusSnapshot,
    textMeasurementStatusSnapshot,
  );
  const measurementStatus = measurementIncomplete ? "unsettled" : shapingStatus;

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
  /**
   * Task 4: the open session's own "commit now", published by the overlay while
   * it is mounted and read by `controls.flushTextEdit` — the agent-run lock's
   * force-commit seam. Null whenever no session is open, which is exactly what
   * makes the flush a no-op then.
   */
  const textEditSettleRef = useRef<(() => void) | null>(null);

  // The descriptor tree the draw loop walks. `tokenGeneration` is a real dep:
  // descriptors read the renderAdapter's module-level kit maps, which arrive
  // after the first paint. AD4.C adds `preview`: a gesture in flight rebuilds
  // the tree with the dragged node's box substituted, which is how the moving
  // pixels reach the canvas without the scene being touched.
  // Task 9 adds `displayScene`: while the reveal pump is streaming, the tree is
  // built from the scene it is DRAWING rather than the one the document loaded
  // — the same one-derivation substitution `preview` above makes for a dragged
  // node's box, and just as narrow. Null (every route but a locked chat
  // surface) leaves this exactly as it was.
  //
  // Plan 2 item D: the scene being DRAWN (Task 9's `displayScene` while the
  // reveal pump streams, else the loaded scene) and the page derived from it.
  // A pageless load gets its page from the first streamed `add_page`, not
  // from the next checkpoint reload. `loadedPageId` is still what the editing
  // session receives (below): the inspector and layer tree read the LOADED
  // scene, and a page id that scene does not contain would be a lie to them.
  //
  // Both lines stay BELOW every hook call in this component on purpose. Hoisted
  // between `useSceneDocument` and the `useState`/`useRef` block above, the
  // React Compiler stops recognising `setEditingNodeId` as a stable setter and
  // skips optimizing the whole component (`preserve-manual-memoization` errors
  // on `commitTextEdit`/`cancelTextEdit`). Nothing reads either value before
  // here, so the position costs nothing and buys the compiled component back.
  // An invalid/pending derivation has editable authored state but no trusted
  // presentation. Keep its diagnostics visible instead of painting old kit maps.
  const drawnScene = engine && engine.derivation.status !== "ready"
    ? null
    : displayScene ?? presentationScene ?? scene;
  const pageId = effectiveScenePageId(loadedPageId, drawnScene);

  // genad2 Task 5: the loaded-but-pageless line, or null. Pure and derived —
  // never a state that could survive the turn that authors the first page.
  // Plan 2 item D points it at the DRAWN scene and the effective id, so the
  // notice clears on the first streamed `add_page` rather than on the next
  // checkpoint reload — the stage stops claiming there is no page while it is
  // drawing one.
  const pagelessNotice = scenePagelessNotice(drawnScene, pageId);

  // Rung B adds `editingNodeId`: the node under an open caret paints no glyphs,
  // because the DOM overlay is drawing them. The STATE is passed, not the
  // derived model — the model is built FROM this artboard, so feeding it back
  // in would be circular; a stale id matches no node and suppresses nothing.
  const artboard = useMemo(
    () =>
      drawnScene
        ? sceneArtboardModel(drawnScene, pageId, preview, editingNodeId)
        : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tokenGeneration
    [drawnScene, pageId, preview, editingNodeId, tokenGeneration],
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

  // D3a: the stage the caret toolbar is placed against — its size plus the
  // band at its top that is already spoken for. Memoized because the toolbar
  // re-runs its measure-and-place layout effect whenever this identity
  // changes, and a fresh object per render would re-place it every keystroke.
  const stageBounds = useMemo(
    () => ({
      height: stageSize.height,
      topInset: bannerInset,
      width: stageSize.width,
    }),
    [bannerInset, stageSize.height, stageSize.width],
  );
  // Stable, so the banner layer's own measuring effect is not torn down and
  // rebuilt on every parent render.
  const reportBannerInset = useCallback((inset: number) => {
    setBannerInset(inset);
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
          onSceneChangeRef.current?.(outcome.scene, loadedPageId, documentId,
            outcome.derivation?.status === "ready" ? outcome.presentationScene : null);
        }
        return outcome;
      },
      // Task 9: the same engine call, without the repaint and without the
      // mirror-up. See the declaration above for why both are absent.
      applyStreamedOperations: (operations) =>
        engine ? engine.applyOperations(operations) : null,
      streamEngineIdentity: () => engine,
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
          onSceneChangeRef.current?.(outcome.scene, loadedPageId, documentId,
            outcome.derivation?.status === "ready" ? outcome.presentationScene : null);
        }
        return outcome;
      },
      // The same condition `applyOperations` refuses on, asked without
      // applying anything.
      canApply: () => Boolean(engine),
      // Task 4: no session open is a no-op, by construction — the ref is only
      // ever populated by a MOUNTED overlay.
      flushTextEdit: () => textEditSettleRef.current?.(),
      documentVersion: () => currentVersion,
      hitTest: (x, y) =>
        engine && pageId ? engine.hitTest(pageId, x, y) : null,
      refresh,
      sceneSnapshot: () => engine?.scene ?? scene,
      presentationSnapshot: () => engine?.derivation.status === "ready" ? engine.presentationScene : null,
      // R21: the stage's own centre, run through the SAME chain a press takes
      // (`handlePointerDown` below) — screen → workspace → page space. It reads
      // the LIVE `viewport`, so a pasted image lands where the user has panned
      // to, not where the fit put the artboard on open.
      viewportPageCenter: () => {
        if (!artboard || stageSize.width <= 0 || stageSize.height <= 0) {
          return null;
        }
        return pagePointOf(
          screenToWorkspace(
            { x: stageSize.width / 2, y: stageSize.height / 2 },
            viewport,
          ),
          artboard,
        );
      },
    }),
    [
      artboard,
      currentVersion,
      documentId,
      engine,
      loadedPageId,
      pageId,
      refresh,
      scene,
      stageSize,
      viewport,
    ],
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

  // Plan 3 R4: the hover outline — the same derivation as the selection
  // outline over the hover target, so it sits exactly where a click's outline
  // would. Never on the selected node (the hover target is already null there).
  const hoverOutline = useMemo(
    () =>
      artboard && hoverNodeId
        ? sceneSelectionOutline({
            artboard,
            pageId,
            preview: null,
            scene,
            selectedNodeId: hoverNodeId,
            viewport,
          })
        : null,
    [artboard, hoverNodeId, pageId, scene, viewport],
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
   *
   * ── THE ORDER IS THE CONTRACT (F4, review 2026-08-24) ──────────────────
   * The write runs BEFORE the session closes, and its answer decides whether
   * the session closes at all. It used to be the other way round — close, then
   * write, then discard the boolean — so a refused write (a read-only engine,
   * an engine refusal) threw away the typed paragraph while the error slot
   * pointed at nothing left to fix. Returning false here keeps the session and
   * its text alive; the overlay re-arms and the human can retry or Escape.
   *
   * An absent `onOperations` is not a refusal: that canvas has no write path at
   * all (the standalone read path), so the preview simply drops, exactly as it
   * does for a gesture there.
   */
  const commitTextEdit = useCallback(
    (session: TextEditSession): boolean => {
      const node = scene ? getNode(scene, editingNodeId) : null;
      const operations = textEditSessionOperations(node, session);
      const accepted = operations
        ? (onOperations?.(operations, SCENE_TEXT_EDIT_INTENT) ?? true)
        : false;
      const ends = textEditSessionEnds(operations, accepted);
      if (ends) {
        setEditingNodeId(null);
      }
      return ends;
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
   *
   * F4/P3-4: it ANSWERS, like the session commit. A refused formatting write
   * leaves the session holding a vector the document rejected — the toolbar
   * would say "bold" over text that is not, and the next commit would carry the
   * refusal back in — so the overlay reverts its working spans on false.
   */
  const commitTextEditStyle = useCallback(
    (session: TextEditSession): boolean => {
      const node = scene ? getNode(scene, editingNodeId) : null;
      const operations = textEditSessionOperations(node, session);
      if (!operations) {
        // Nothing to write is not a refusal: keep the session as it is.
        return true;
      }
      return onOperations?.(operations, SCENE_TEXT_STYLE_INTENT) ?? true;
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
    const preFreezeScene = controls.sceneSnapshot();
    const outcome = controls.applyStructuredEdit(freezeLayoutEdit());
    if (outcome?.accepted && preFreezeScene) {
      // The zero-motion contract, checked where it actually matters: on the
      // human's real document. A freeze is a pure re-expression of the solve,
      // so if it moved anything the ad just jumped under their finger — an
      // ENGINE defect this canvas cannot repair. It is reported loudly and
      // nothing else changes: ruling C-9 stands and the press goes on to arm
      // (refusing here would trade a visible jump for a dead grab).
      const report = freezeMotionReport(preFreezeScene, outcome.scene);
      if (report.moved.length > 0) {
        console.error(
          "[freeze] a freeze moved nodes; this is an engine defect",
          report.moved,
        );
      }
    }
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
    // Plan 3 R4: a press ends the hover — the selection outline takes over,
    // and nothing recomputes hover again until the pointer is idle.
    setHoverNodeId(null);
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
      // Plan 3 R4: an idle pointer hovers. Same coordinate chain as a press
      // (`handlePointerDown`), same ladder, and only a CHANGE reaches state.
      const element = stageRef.current;
      if (textEdit || !element || !artboard || !scene || engineStatus.engineDisabled) {
        if (hoverNodeId !== null) {
          setHoverNodeId(null);
        }
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
      const target = result
        ? sceneHoverTarget({
            stack: result.stack,
            scene,
            pageId,
            selectedNodeId: activeSelectedNodeId,
          })
        : null;
      if (target !== hoverNodeId) {
        setHoverNodeId(target);
      }
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

  /**
   * R4 (walk up): everything the Escape listener needs, held in a ref because the
   * listener is registered ONCE (`[]`) and must never read a first-render
   * scene. Published from an effect with no deps array — the file's own idiom
   * for a per-render ref (`onSelectRef`, `gestureInputsRef` above) — rather
   * than written during render, which the React Compiler refuses.
   */
  const escapeContextRef = useRef<{
    scene: typeof scene;
    pageId: typeof pageId;
    selectedNodeId: NodeId | null;
    textEditing: boolean;
  }>({
    scene,
    pageId,
    selectedNodeId: activeSelectedNodeId,
    textEditing: Boolean(textEdit),
  });
  useEffect(() => {
    escapeContextRef.current = {
      scene,
      pageId,
      selectedNodeId: activeSelectedNodeId,
      textEditing: Boolean(textEdit),
    };
  });

  // Ruling C-2: Escape cancels a live gesture. Registered once, and — R4 — it
  // also WALKS THE SELECTION UP when no gesture is running and no caret is
  // open, clearing the selection at the root frame. (Before the selection
  // ladder landed, this canvas never touched the selection on Escape.) An
  // Escape that resolves to nothing still reaches whatever else wants it.
  //
  // The gesture guard is ARMED **and** non-idle, not non-idle alone: this is a
  // global key handler, so its inertness must not rest on a state machine that
  // a missed `pointerup` could leave dirty. Only an armed gesture has anything
  // to cancel, and after `beginPress`/`handlePointerUp` above, armed and
  // non-idle are the same condition — the second half is belt-and-braces on a
  // handler that can `preventDefault` a key the whole app shares.
  //
  // `commitSelection` and `resetGesture` are captured from the first render on
  // purpose: both write only stable setters and refs, so a stale closure of
  // either is the same function.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      // The same guard the space-pan listener uses: Escape inside an inspector
      // field is that field's, never the canvas's. It runs FIRST now, because
      // every branch below it acts.
      if (event.key !== "Escape" || typingTarget(event.target)) {
        return;
      }
      const context = escapeContextRef.current;
      const effect = escapeSelectionEffect({
        gestureLive:
          gestureArmedRef.current && gestureRef.current.kind !== "idle",
        textEditing: context.textEditing,
        selectedNodeId: context.selectedNodeId,
        scene: context.scene,
        pageId: context.pageId,
      });
      if (effect.kind === "reset-gesture") {
        event.preventDefault();
        resetGesture();
      } else if (effect.kind === "select") {
        event.preventDefault();
        commitSelection(effect.nodeId);
      }
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
    onSceneChangeRef.current?.(scene, loadedPageId, documentId,
      engine?.derivation.status === "ready" ? presentationScene : null);
  }, [documentId, loadedPageId, scene, engine, presentationScene]);

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
   *     → `selectionPressTarget({ stack, scene, pageId, selectedNodeId })`
   *       selection v2's R1 target — the outermost UNIT on the path (a
   *       button-shaped auto-layout or a group), or else the deepest
   *       schema-bearing node — kept at the current selection when that
   *       selection is itself under the pointer (R6)
   *
   * The last two conversions are the trap: `hitTest` takes SCENE units, not
   * descriptor px, and the two are identical on a `pt`/`px` page (this ad), so
   * a missing division is invisible here and wrong everywhere else. Both live
   * in `sceneHitPoint`, where they are unit-tested against a non-identity unit.
   *
   * The selection model (founder rulings 2026-09-04) in one paragraph. R1 is
   * that click target. R2: a double-click drills one level toward the pointer
   * and opens the caret only once the text itself is the selection. R3:
   * Cmd/Ctrl-click selects the deepest node and cycles one level shallower per
   * repeat. R4: Alt-click and Escape walk up. R5: the hover outline previews
   * what the press would act on. R6: the press drags whatever the click just
   * selected — R1's target, except that a press on the node ALREADY selected
   * keeps it, so a label reached by drilling can be dragged inside its own
   * button instead of re-selecting the button (live proof 2026-09-04). The
   * earlier
   * model's "a second click on the selected node walks up" (and its 4 px
   * same-spot slop) is gone: a double-click IS two clicks at one spot, so the
   * two rules could not coexist — walking up is Alt-click's and Escape's now.
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
      // Plan 3 R4: a pan is not a hover either — the surface moves under the
      // pointer, so the last hover target is no longer what a click would hit.
      setHoverNodeId(null);
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
    // R3: Cmd/Ctrl-click deep-selects (and cycles shallower on repeat);
    // otherwise R1's click target. Either way the press that follows drags
    // what was just selected (R6).
    const hitNodeId = event.metaKey || event.ctrlKey
      ? deepSelectTarget({
          stack: result.stack,
          scene,
          pageId,
          selectedNodeId: activeSelectedNodeId,
        })
      : selectionPressTarget({
          stack: result.stack,
          scene,
          pageId,
          selectedNodeId: activeSelectedNodeId,
        });
    // R4: Alt/Option-click walks up from the click target and starts no press.
    if (event.altKey && hitNodeId !== null) {
      commitSelection(selectionWalkUp(scene, pageId, hitNodeId) ?? hitNodeId);
      return;
    }
    const press = scenePressNodeTarget({
      artboard,
      gesturesEnabled: !gestureDisabled,
      nodeId: hitNodeId,
      pageId,
      scene,
    });
    // Task 4: a press the agent-run lock, and ONLY the lock, refused to arm.
    // Asked by re-running the same pure decision with the gate open, so the
    // answer is the adapter's and not a second copy of its rule here; the extra
    // derivation is paid only while the editor is actually locked, and only for
    // a press that would otherwise have started a drag (a plain selection, a
    // press on nothing, or a node that could never drag says nothing).
    if (gestureDisabled && !press.armed) {
      const wouldArm = scenePressNodeTarget({
        artboard,
        gesturesEnabled: true,
        nodeId: hitNodeId,
        pageId,
        scene,
      }).armed;
      if (wouldArm) {
        onLockedEdit?.();
      }
    }
    // `press.armed` was resolved against the PRE-freeze scene, which is right
    // for the ordinary case (the freeze is zero-motion, so the box is the same
    // either side of it) and one case short: a node the freeze could not
    // actually free must not arm after all.
    const freed = freezeLayoutForPress(press.target);
    beginPress(event, point, press.target, press.armed && freed);
  };

  /**
   * Rung B (rich-text plan, 2026-08-24 — this SUPERSEDES §1.9/§7's "no
   * double-click text"), as re-ruled by selection v2's R2 (2026-09-04): a
   * double-click drills the selection one level DOWN toward the pointer, and
   * opens a caret only once the text node itself is what is selected. (Rung
   * B's original answer — drill OUT to the top-level container — is gone with
   * the rest of the walk-up-on-click model; walking up is Alt-click's and
   * Escape's.) The whole stack under the pointer is handed to the pure rule,
   * because "one level down" is a question about the path, not about a node.
   *
   * The coordinate chain is `handlePointerDown`'s, unchanged and reused whole —
   * the same hit test answers both, so a double-click can never resolve to a
   * node a single click would not have selected. What differs is only what the
   * resolved node MEANS, and that decision is pure
   * (`adapter/scene-text-edit.ts`).
   *
   * F5 (review 2026-08-24) — what C-9 actually does here. This used to claim
   * the freeze-on-grab "does NOT fire" for a double-click. It does: the first
   * pointer-down of that double-click went through `handlePointerDown`, which
   * calls `freezeLayoutForPress` for every press on a freezable node, so by the
   * time this handler runs a layout-managed text node has ALREADY had the
   * document's auto-layout baked to free placement — exactly as a plain
   * selection click on it would (ratified AD4.C-3, ruling C-10; not this lane's
   * to change, and deliberately unchanged). What is true is that THIS handler
   * adds no freeze of its own, and the session's own commit is an ordinary
   * content/spans write that lets the solver re-solve around the new text.
   *
   * Deferring the freeze to a drag threshold — so pure clicks and double-clicks
   * stop freezing — is a live founder question recorded on the plan.
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
      stack: result ? result.stack : [],
      pageId,
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
      case "locked":
        // Task 4: the caret this document would have opened, refused by the
        // agent-run lock. The shell puts the lock's sentence in the note slot;
        // the selection the preceding pointer-down made is left alone.
        onLockedEdit?.();
        break;
      case "none":
        break;
    }
  };

  /**
   * Clipboard Task 8: pictures dragged in from the desktop (or another tab).
   *
   * `dragover` must `preventDefault` for a drop to be delivered at all — that
   * is the DOM's opt-in, not a style choice — and the copy `dropEffect` is what
   * makes the cursor say "this will land here". Both are claimed only when the
   * drag really carries FILES and the stage really has a document to drop into;
   * a text drag, or a canvas with no session wired, keeps the browser's own
   * behaviour.
   */
  const dragCarriesFiles = (transfer: DataTransfer | null): boolean =>
    Array.from(transfer?.types ?? []).includes("Files");

  const handleDragOver = (event: ReactDragEvent<HTMLDivElement>) => {
    if (!onDropImageFiles || !artboard || !dragCarriesFiles(event.dataTransfer)) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  };

  const handleDrop = (event: ReactDragEvent<HTMLDivElement>) => {
    const element = stageRef.current;
    if (!onDropImageFiles || !element || !artboard) {
      return;
    }
    // SYNCHRONOUS, before anything else: a `DataTransfer`'s file list is dead
    // after the event's own turn (the same Firefox lesson the paste snapshot
    // records). A drop carrying no files stays NATIVE — un-prevented — so
    // dragging a link or a text selection onto the stage still does whatever
    // the browser does with it.
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length === 0) {
      return;
    }
    event.preventDefault();
    const bounds = element.getBoundingClientRect();
    onDropImageFiles(
      files,
      pagePointOf(
        screenToWorkspace(
          { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
          viewport,
        ),
        artboard,
      ),
    );
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
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      onPointerCancel={handlePointerCancel}
      onPointerDown={handlePointerDown}
      onPointerLeave={() => setHoverNodeId(null)}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      ref={stageRef}
    >
      <ArtboardSurface
        artboard={artboard}
        assets={drawnScene?.assets}
        assetLoadGeneration={loadGeneration}
        // Test/diagnostic hooks, not chrome: the honest engine + text
        // measurement state and the current selection, readable independently
        // of the approved visuals that now render them (Gates G-A / G-D).
        dataEngine={engineStatus.engineDisabled ? "disabled" : "wasm"}
        dataMeasurement={measurementStatus}
        dataFontDiagnostics={fontDiagnostics.length}
        dataSelectedNode={activeSelectedNodeId ?? "none"}
        viewport={viewport}
      />
      {/* Plan 3 R4: the hover outline — the click target, previewed. Drawn
          UNDER the selection chrome (same absolute overlay, earlier sibling)
          so a selection outline is never overdrawn by a hover one, and taken
          down entirely while a caret or a gesture owns the surface.

          The gesture guard is the STATE pair `preview`/`panning`, not
          `gestureRef.current`: the React Compiler refuses a ref read during
          render, and these say the same thing here — `beginPress` and the pan
          branch both drop the hover target on the way in, and the hover branch
          of `handlePointerMove` never runs while a gesture is armed, so a
          pressed-but-not-yet-dragging gesture already has no hover to draw. */}
      <SelectionChrome
        outline={textEdit || preview || panning ? null : hoverOutline}
        variant="hover"
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
          // Task 4: the session publishes its own "commit now" here, so the
          // agent-run lock can force-commit it on the way in.
          settleRef={textEditSettleRef}
          stage={stageBounds}
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
        derivation={engine?.derivation}
        measurementStatus={measurementStatus}
        onInsetChange={reportBannerInset}
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
 * The diagnostic copy still comes from the MVP editor (asserted by the adapter
 * tests). The platform presentation uses Clue product tokens. Advisory details
 * can be expanded without obscuring the creative by default; critical failures
 * start expanded and retain an assertive announcement.
 *
 * It lives here, inside the canvas stage, rather than in the shell: the stage
 * is the one surface both mounts share, so the artifact route and the chat
 * route get it with no plumbing, it survives the inspector being closed, and
 * the state it reads (`engineStatus`, `measurementStatus`) is already local.
 *
 * The third G-D state — the CAS conflict — is deliberately NOT here: it stays
 * the inspector's existing note line ("Document moved on — reloaded.", D10).
 *
 * D3a: it also REPORTS the band it occupies, so the caret toolbar can place
 * itself clear of it. The band is measured off the mounted layer (bottom edge
 * relative to the stage, which is the layer's offset parent) rather than
 * assumed from a banner count — one banner wraps to two lines on a narrow
 * stage, and that is precisely when a fixed guess would be wrong.
 */
function SceneEngineBanners({
  engineStatus,
  fontDiagnostics,
  derivation,
  measurementStatus,
  onInsetChange,
}: {
  engineStatus: SceneEngineStatus;
  fontDiagnostics: Diagnostic[];
  derivation?: Derivation;
  measurementStatus: string;
  /** The bottom edge of the banner band in stage px, or 0 for no banners. */
  onInsetChange: (inset: number) => void;
}) {
  const layerRef = useRef<HTMLDivElement | null>(null);
  const [dismissedSignature, setDismissedSignature] = useState<string | null>(null);
  const banners = sceneEngineBanners(
    engineStatus,
    measurementStatus,
    fontDiagnostics,
    derivation,
  );
  // Dismiss only this set of diagnostics. New issues must remain discoverable.
  const signature = JSON.stringify(banners);
  const bannerCount = dismissedSignature === signature ? 0 : banners.length;
  const hasError = banners.some((banner) => banner.severity === "error");
  const noticeLabel = hasError
    ? "Canvas needs attention"
    : `${bannerCount} rendering notice${bannerCount === 1 ? "" : "s"}`;
  useEffect(() => {
    const element = layerRef.current;
    if (bannerCount === 0 || !element) {
      onInsetChange(0);
      return;
    }
    const report = () =>
      onInsetChange(element.offsetTop + element.offsetHeight);
    report();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    // A banner reflows with the stage's width, so the band is re-reported
    // rather than measured once at mount.
    const observer = new ResizeObserver(report);
    observer.observe(element);
    return () => {
      observer.disconnect();
      // The band is gone the moment this layer is: leaving a stale inset
      // behind would push the toolbar down past a banner that is not there.
      onInsetChange(0);
    };
  }, [bannerCount, onInsetChange]);
  // Nothing wrong → no element at all, so a healthy canvas holds no space and
  // no assistive technology announces an empty alert region.
  if (bannerCount === 0) {
    return null;
  }
  return (
    <div className={styles.bannerLayer} ref={layerRef}>
      <div
        className={styles.banner}
        data-severity={hasError ? "error" : "warning"}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => event.stopPropagation()}
        onDoubleClick={(event) => event.stopPropagation()}
        onWheel={(event) => event.stopPropagation()}
      >
        <details className={styles.bannerDisclosure} key={signature} open={hasError}>
          <summary className={styles.bannerSummary} aria-label={noticeLabel}>
            <AlertTriangleIcon aria-hidden="true" className={styles.bannerIcon} size={14} />
            <span role={hasError ? "alert" : "status"}>
              {noticeLabel}
            </span>
            <ChevronDownIcon aria-hidden="true" className={styles.bannerChevron} size={14} />
          </summary>
          <div className={styles.bannerList}>
            {banners.map((banner) => (
              <div className={styles.bannerBody} data-scene-banner={banner.kind} key={banner.kind}>
                <strong className={styles.bannerTitle}>{banner.title}</strong>
                <p className={styles.bannerText}>{banner.body}</p>
                <div className={styles.bannerGuidance}>
                  {banner.kind === "engine-disabled" || (measurementStatus === "heuristic" && banner.kind === "heuristic-measurement") ? (
                    <code className={styles.bannerCommand}>{banner.command}</code>
                  ) : (
                    <span className={styles.bannerCommandName}>{banner.command}</span>
                  )}
                  {banner.detail && <p className={styles.bannerText}>{banner.detail}</p>}
                </div>
              </div>
            ))}
          </div>
        </details>
        <button
          type="button"
          className={styles.bannerDismiss}
          aria-label="Dismiss rendering notices"
          title="Dismiss rendering notices"
          onClick={() => setDismissedSignature(signature)}
        >
          <XIcon aria-hidden="true" size={14} />
        </button>
      </div>
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
 *
 * Plan 3 R4 adds the HOVER variant: the same box, the same colour, stroked
 * thinner and translucent, with no handles ever — a preview of what a click
 * would select, not a thing you can grab. It carries its own
 * `data-scene-hover-outline` attribute so the two overlays stay separately
 * readable.
 *
 * Plan 4 item F (ruling R5) adds the dashed FRAME: when the selected text's
 * painted lines do not fill its layout box, the outline carries that box too.
 * It is stroked dashed, it is what the handles ride (a resize changes the box,
 * not the glyphs), and it is the rotation pivot. Never on hover: a hover
 * preview answers "what would a click select", and two boxes there would be
 * noise over a node the user has not chosen yet. Founder ruling 2026-10-18:
 * once selected, such a text shows ONLY the frame — the outline around its
 * letters is the hover preview alone (`selectionStrokesPaintedOutline`).
 */
function SelectionChrome({
  handles = false,
  outline,
  variant = "selection",
}: {
  handles?: boolean;
  outline: SceneSelectionOutline | null;
  variant?: "selection" | "hover";
}) {
  // No selection → no element at all, not an empty overlay.
  if (!outline) {
    return null;
  }
  const hover = variant === "hover";
  // Plan 4 item F: the box the chrome pivots on and hangs its handles from —
  // the dashed layout frame when a text selection has one, the outline itself
  // otherwise. The hover variant never draws a frame, so it never has one.
  const pivot = outline.frame ?? outline;
  return (
    <svg
      aria-hidden="true"
      className={styles.selectionChrome}
      data-scene-hover-outline={hover ? outline.nodeId : undefined}
      data-scene-selection-outline={hover ? undefined : outline.nodeId}
    >
      <g
        transform={
          outline.rotation
            ? `rotate(${outline.rotation} ${pivot.x} ${pivot.y})`
            : undefined
        }
      >
        {selectionStrokesPaintedOutline(outline, variant) ? (
          // 2026-10-18 (amends R5): a selected text with a dashed frame shows
          // only the frame; the outline around its letters is hover-only.
          <rect
            fill="none"
            height={outline.height}
            stroke={SELECTION_OUTLINE_COLOR}
            strokeOpacity={hover ? HOVER_OUTLINE_OPACITY : undefined}
            strokeWidth={hover ? HOVER_OUTLINE_WIDTH : SELECTION_OUTLINE_WIDTH}
            width={outline.width}
            x={outline.x}
            y={outline.y}
          />
        ) : null}
        {outline.frame && !hover ? (
          // Plan 4 item F: the layout box of a text node whose painted lines
          // do not fill it — dashed, so the eye reads "the box you can
          // resize" apart from "the text you selected". Never on hover.
          <rect
            data-scene-selection-frame={outline.nodeId}
            fill="none"
            height={outline.frame.height}
            stroke={SELECTION_OUTLINE_COLOR}
            strokeDasharray="4 3"
            strokeWidth={HOVER_OUTLINE_WIDTH}
            width={outline.frame.width}
            x={outline.frame.x}
            y={outline.frame.y}
          />
        ) : null}
        {handles && !hover
          ? selectionHandleRects(pivot).map((handle) => (
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
 * stay landed. F7/P3-3 correction (review 2026-08-24): ⌘Z does NOT take them
 * back one at a time WHILE THE SESSION IS OPEN — document undo skips typing
 * targets (`scene-arrange.ts::isTypingTarget`, the ⌘Z listener's own rule) and
 * this textarea swallows every key anyway, so inside a session ⌘Z is the
 * browser's native textarea undo over the draft. The landed formatting frames
 * become reachable one at a time once the session closes, which is what "its
 * own undo frame" buys.
 *
 * ── THE SESSION FOLLOWS THE DOCUMENT UNTIL IT IS TOUCHED (F3/G1) ─────────
 * The session state carries TWO dirty flags, one per channel. While a channel
 * is clear the session RE-SEEDS it from the live model on every render, so an
 * untouched caret sitting open across a D10 reload or an agent turn shows what
 * the document now says instead of writing its opening snapshot back over it.
 * The human's first keystroke claims the CONTENT channel; a formatting action
 * claims only the SPANS one, so a Bold-only session still follows the
 * document's text (G1 — with one flag it did not, and its blur reverted the
 * concurrent write). A re-seed that adopts new content also resets the
 * selection to select-all (G2), because the offsets it had were measured in the
 * text that is no longer there.
 */
function SceneTextEditOverlay({
  model,
  onCancel,
  onCommit,
  onStyleCommit,
  palette,
  settleRef,
  stage,
}: {
  model: SceneTextEditModel;
  onCancel: () => void;
  /** Answers whether the session ENDED: false is a refused write, whose typed
   * text must survive (F4). */
  onCommit: (session: TextEditSession) => boolean;
  /** Answers whether the formatting write LANDED (F4/P3-4). */
  onStyleCommit: (session: TextEditSession) => boolean;
  palette: ScenePalette | null;
  /** Task 4: where this session publishes its own commit, so the host's
   * agent-run lock can force it before the write path goes inert. Populated
   * while mounted and cleared on unmount, so a closed session flushes nothing. */
  settleRef: RefObject<(() => void) | null>;
  /** D3a: `topInset` is the occupied band at the stage's top (the G-D banners),
   * which the toolbar places itself clear of. */
  stage: { width: number; height: number; topInset?: number };
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const [session, setSession] = useState<TextEditSession>(() =>
    textEditSessionSeed(model.content, model.text.spans ?? []),
  );
  // The mount effect below focuses and SELECTS ALL, so that is where the
  // selection starts — stated here rather than waiting for the first `select`
  // event, so the toolbar is never briefly wrong about it.
  const [selection, setSelection] = useState<TextEditSelection>(() => ({
    start: 0,
    end: model.content.length,
  }));
  // The content a re-seed last ADOPTED. State rather than a ref because it is
  // what the G2 selection push below is keyed on — it must move exactly when a
  // re-seed rewrites the textarea's value, and never when typing does.
  const [seededContent, setSeededContent] = useState(model.content);
  // F3/G1: an untouched channel follows the document. React's own
  // adjust-state-on-change pattern (the host uses it for the session id), not
  // an effect — an effect would paint one frame of the stale snapshot first,
  // and the reseeded value is what the rest of this render must read.
  const live = textEditSessionReseed(
    session,
    model.content,
    model.text.spans ?? [],
  );
  if (live !== session) {
    setSession(live);
    // G2: the live selection's offsets were measured in the text the re-seed
    // just replaced, so an adopted CONTENT change resets them to the posture a
    // session opens in. A spans-only adoption returns the same object and
    // leaves the human's range alone.
    const reseeded = textEditSessionReseedSelection(session, live, selection);
    if (reseeded !== selection) {
      setSelection(reseeded);
      setSeededContent(live.content);
    }
  }
  // Event handlers bound to the DOM (and the window listener below) must read
  // the CURRENT session and selection, not the ones captured when they were
  // created — the same ref-mirror the canvas's gesture inputs use.
  const sessionRef = useRef(live);
  const selectionRef = useRef(selection);
  useEffect(() => {
    sessionRef.current = live;
    selectionRef.current = selection;
  });
  /** The tracked `beforeinput` prediction awaiting its `input` event. */
  const predictionRef = useRef<TextEditSession | null>(null);
  /** Focus is inside the toolbar: a blur is NOT the end of the session. */
  const interactingRef = useRef(false);
  // A settled session must not settle twice: Escape blurs on its way out, and
  // the outside-pointer listener can race the blur that follows it.
  const settledRef = useRef(false);

  // Founder ruling 2026-10-18: the surface is a live preview of the WHOLE text.
  // A textarea cannot overflow visibly, so it grows to its measured content
  // (`textEditSurfaceHeight`) instead of hiding lines and scrolling to the
  // caret. State, not only a style write, because the toolbar places itself
  // against this height; it changes when the line count does, not per key.
  const [surfaceHeight, setSurfaceHeight] = useState(model.height);

  // A7a: match the painted vertical position with a computed top padding. The
  // content height is a LIVE DOM measurement — the only part of the geometry a
  // pure model cannot answer — so it is recomputed as the text grows and
  // shrinks, keeping the caret aligned mid-session. The same read sizes the
  // surface (2026-10-18, above).
  //
  // Written STRAIGHT TO THE ELEMENT rather than held in state (upstream holds
  // it in a `useState`): it is a measurement of the DOM feeding a style of the
  // same DOM node, so a render round-trip buys nothing and costs one per
  // keystroke. `paddingTop` is deliberately absent from the `style` prop below,
  // which is what keeps React from overwriting it on the next render.
  const recomputeGeometry = useCallback(() => {
    const element = ref.current;
    if (!element) {
      return;
    }
    // `scrollHeight` floors at `clientHeight` (so content shorter than the box
    // reads back AS the box) and counts whatever padding is already applied —
    // both are zeroed for the read, and the height is set before paint. At
    // zero height `offsetHeight - clientHeight` is the border the
    // border-box height must also hold.
    element.style.paddingTop = "0px";
    element.style.height = "0px";
    const contentHeight = element.scrollHeight;
    const chrome = element.offsetHeight - element.clientHeight;
    const height = textEditSurfaceHeight(model.height, contentHeight, chrome);
    element.style.height = `${height}px`;
    element.style.paddingTop = `${valignOffset(
      model.height,
      contentHeight,
      model.style.valign,
    )}px`;
    setSurfaceHeight(height);
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

  // G2: push the re-seeded selection at the DOM, which holds its own and would
  // otherwise keep the offsets it had in the text the re-seed replaced. Keyed
  // on the ADOPTED content, so it fires for a re-seed and never for typing;
  // LAYOUT, so the range is right in the same frame the new value paints. It
  // does not touch focus — a re-seed while the toolbar's hex field has it must
  // not yank the caret back.
  useLayoutEffect(() => {
    const element = ref.current;
    if (element) {
      element.setSelectionRange(0, seededContent.length);
    }
  }, [seededContent]);

  // `live.content` is a dependency because F3's re-seed changes the text with no
  // input event to recompute from: a valigned overlay would otherwise keep the
  // padding of the content it no longer shows.
  // Layout, so the first painted frame already shows every line.
  useLayoutEffect(() => {
    recomputeGeometry();
  }, [live.content, recomputeGeometry]);

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

  /**
   * End the session exactly once — unless the write is REFUSED (F4), in which
   * case the session did not end at all: the latch is re-armed so the next blur
   * or ⌘Enter can try again, and the caret is taken back (the blur that
   * triggered this already moved focus away, and a session nobody can focus is
   * a paragraph nobody can rescue).
   */
  const settle = useCallback(
    (kind: "commit" | "cancel") => {
      if (settledRef.current) {
        return;
      }
      settledRef.current = true;
      if (kind === "cancel") {
        onCancel();
        return;
      }
      if (onCommit(sessionRef.current)) {
        return;
      }
      settledRef.current = false;
      const element = ref.current;
      if (element) {
        element.focus();
        element.setSelectionRange(
          selectionRef.current.start,
          selectionRef.current.end,
        );
      }
    },
    [onCancel, onCommit],
  );

  /**
   * Task 4: publish this session's commit while it is mounted.
   *
   * The host's agent-run lock calls it on the engaging edge, which is the
   * founder default — typed work is committed, never silently dropped — and it
   * is deliberately the SAME `settle("commit")` a blur takes, so the transaction
   * (write first, close only if the write landed, F4) is identical. Cleared on
   * unmount, so a closed session cannot be flushed.
   */
  useEffect(() => {
    settleRef.current = () => settle("commit");
    return () => {
      settleRef.current = null;
    };
  }, [settle, settleRef]);

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

  /**
   * Plan 1 item B: which face-dependent marks this node's family can actually
   * paint, asked of the same registry the canvas shapes through. Neither
   * renderer synthesises a weight or a slant, so a mark with no face is refused
   * with a reason (the button's title, and the chord's silent no-op) instead of
   * writing a style nothing can draw.
   */
  const faces: SceneTextFaceAvailability = {
    bold: boldChangesFace(model.family),
    italic: hasItalicFace(model.family),
  };

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
    // G1: the SPANS channel only. A formatting action says nothing about the
    // text, so it must not claim the draft — claiming it is what let a
    // Bold-only session commit its opening snapshot over a concurrent write.
    const next = textEditSessionAfterStyle(
      current,
      textEditStyledSpans(model.text, current, selectionRef.current, patch),
    );
    sessionRef.current = next;
    setSession(next);
    // F4/P3-4: a refused write puts the pre-action vector straight back, so the
    // toolbar never states styling the document rejected. The error slot is
    // populated by the write path itself.
    const settled = textEditSessionAfterStyleCommit(
      current,
      next,
      onStyleCommit(next),
    );
    if (settled !== next) {
      sessionRef.current = settled;
      setSession(settled);
    }
  };

  const applyMark = (channel: SceneTextMarkChannel) => {
    if (sceneTextMarkUnavailableReason(channel, model.family, faces) !== null) {
      return; // ⌘B/⌘I on a family with no such face: the button is disabled and says why
    }
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
  const format = textEditFormatState(model.text, live, selection);
  // The toolbar measures itself against this box, so it must not be a fresh
  // object on every keystroke — that would re-run its placement effect (and its
  // `setPosition`) for every character typed.
  const toolbarBox = useMemo(
    () => ({
      height: surfaceHeight,
      left: model.left,
      top: model.top,
      width: model.width,
    }),
    [surfaceHeight, model.left, model.top, model.width],
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
          recomputeGeometry();
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
          height: surfaceHeight,
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
        value={live.content}
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
        faces={faces}
        family={model.family}
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
  assetLoadGeneration,
  dataEngine,
  dataFontDiagnostics,
  dataMeasurement,
  dataSelectedNode,
  viewport,
}: {
  artboard: SceneArtboardModel | null;
  assets: Scene["assets"] | undefined;
  assetLoadGeneration: number;
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
      // SVG crispness: the cache re-rasterizes vectors when zoom×dpr outgrows
      // the raster it is serving (a no-op for raster assets and unchanged zoom).
      imagesRef.current?.setViewScale(current.viewport.zoom * dpr);
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
  // A streamed generated asset can 404 before the save publishes its bytes.
  // An authoritative reload is new availability evidence even when its digest
  // URL stays identical. Retrying only then avoids a redraw-driven fetch storm.
  useEffect(() => {
    imagesRef.current?.retryFailed();
  }, [assetLoadGeneration]);
  useEffect(invalidate, [artboard, viewport, assetLoadGeneration]);

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
