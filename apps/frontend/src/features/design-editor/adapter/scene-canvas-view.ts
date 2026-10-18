import { DESIGN_PUBLIC_BFF_PREFIX } from "../data/design-bff";
import type { DrawNode } from "../engine/scene/canvaskit/drawDescriptors";
import type {
  AssetRecord,
  Node,
  NodeId,
  Page,
  PageId,
  Scene,
} from "../engine/scene/contracts";
import {
  nodeDescriptor,
  pageDescriptor,
  type RenderPageDescriptor,
} from "../engine/scene/renderAdapter";
import { isNodePinned } from "../engine/scene/sceneQueries";
import { deriveSelectionChromeModel } from "../engine/scene/selectionChrome";
import type { Box } from "../engine/scene/transformerMath";
import type { Rect } from "../engine/scene/workspaceLayout";
import {
  clampWorkspacePanToKeepVisible,
  clampWorkspaceZoom,
  fitWorkspaceRectToViewport,
  panWorkspaceViewport,
  workspaceRectToScreen,
  zoomWorkspaceViewportAtPoint,
  type ViewportSize,
  type WorkspaceViewport,
} from "../engine/scene/workspaceViewport";
import type { Point } from "../engine/scene/workspaceLayout";

/**
 * AD2.3: every decision the scene canvas makes that is NOT a WebGL call.
 *
 * The component around this file owns a CanvasKit surface, so its internals
 * cannot be unit-tested (the repo's `node:test` runner has no DOM and no
 * wasm). Everything that could be a function therefore IS one, here, proven
 * against AD2.2's harvested bytes: which asset URL to fetch, what the
 * fit-on-open zoom reads as in the header menu, when text must be re-measured,
 * and the descriptor tree the draw loop walks.
 *
 * The tree builder is the design editor's own `CanvasKitCanvas` artboard memo
 * (`subsystems/clue-design/apps/editor/src/components/canvas/CanvasKitCanvas.tsx:374-458`)
 * collapsed to ONE artboard: the platform mounts a single document inside the
 * dummy's designed artboard hole, so the multi-artboard workspace, its
 * placement grid, and the in-gesture `preview` override (a write-path concern)
 * all fall away. What is preserved verbatim is the part that decides pixels:
 * the parent-computed-origin threading and the pinned-node hoist, which mirror
 * the engine's own `pinned_paint_pass` so canvas and export stack identically.
 */

/** Zoom vocabulary of the ad header's menu (contract §1.10 / AD0.4's
 * `ZOOM_LEVELS`): 10%–150% in 5% steps. Fit-on-open reports the nearest step
 * so the menu can show a value it actually offers. */
export const ZOOM_STEP_PERCENT = 5;
export const MIN_ZOOM_PERCENT = 10;
export const MAX_ZOOM_PERCENT = 150;

/**
 * A fitted zoom factor (`0.4267`) as the nearest menu step (`"45%"`).
 *
 * Clamped into the menu's range, which is also inside the engine's own
 * `[0.1, 2.0]` viewport clamp, so a reported value is always both offerable
 * and applicable. A non-finite or non-positive input reports the minimum
 * rather than throwing — the canvas still renders when the fit math is
 * starved (zero-sized viewport during the first layout pass).
 */
export function snapZoomPercent(zoom: number): string {
  if (!Number.isFinite(zoom) || zoom <= 0) {
    return `${MIN_ZOOM_PERCENT}%`;
  }
  const stepped =
    Math.round((zoom * 100) / ZOOM_STEP_PERCENT) * ZOOM_STEP_PERCENT;
  const clamped = Math.min(
    MAX_ZOOM_PERCENT,
    Math.max(MIN_ZOOM_PERCENT, stepped),
  );
  return `${clamped}%`;
}

/**
 * A menu step (`"45%"`) as the scale the canvas applies, or null for "no
 * choice yet — fit the artboard".
 *
 * Clamped through the engine's own `[0.1, 2.0]` viewport clamp so the value the
 * canvas transforms by is one the engine would accept anywhere else. Every one
 * of the menu's 29 options is already inside that clamp, so the clamp only ever
 * bites on a hand-passed value.
 */
export function chosenZoomScale(zoom: string | null | undefined): number | null {
  if (!zoom) {
    return null;
  }
  const parsed = Number.parseFloat(zoom.replace("%", ""));
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return clampWorkspaceZoom(parsed / 100);
}

/**
 * AD2.10 (founder ruling, 2026-08-20) — **this retires ruling 17.**
 *
 * Ruling 17 set this to 0 because the dummy's `.imageCanvas` card was taken to
 * BE the artboard: fill the card edge to edge and the ad looks right. It looked
 * right at exactly one zoom. Above the fit the ad was drawn larger than the
 * card's ~638px surface and silently clipped with no way to reach the rest;
 * below it, leftover card showed around the ad as meaningless padding; and the
 * card's `aspect-ratio: 1` made any non-square page wrong even at fit.
 *
 * The ruling: the stage is an infinite workspace (Figma's model) and the
 * artboard is a page floating on it, bounded by its own edges alone. So the fit
 * is a fit to the STAGE, and the margin is back — breathing room so the page
 * does not touch the viewport edges, which is what makes it read as a tile on a
 * surface rather than a letterbox. Half the source editor's 128 (its workspace
 * holds a grid of artboards; ours holds one), i.e. 32px per edge.
 */
export const ARTBOARD_FIT_MARGIN = 64;

/**
 * The workspace surface behind the artboard.
 *
 * The value is the design subsystem's own `--bg-canvas`
 * (`subsystems/clue-design/apps/editor/src/app/tokens.css`), read at draw time
 * through the same custom-property lookup the source stage uses
 * (`CanvasKitStage.workspaceCanvasColor`) so a host that defines the property
 * wins; this constant is the fallback when nothing does — which is the platform
 * shell today, so it is also the colour actually painted.
 *
 * Light, not dark: the platform shell is light. It has to be clearly separable
 * from a white page, which `--clue-ds-color-bg-page` (#F8F9FB) is not.
 */
export const WORKSPACE_CANVAS_FALLBACK = "#f5f5f5";

/**
 * The artboard's own chrome — the only boundary the page has now that no card
 * surrounds it.
 *
 * Ported in STRUCTURE from the source stage's `drawArtboard` (a shell painted
 * behind the artboard rect, then the content clipped to the page box, then a
 * border stroked on top), with the two colours re-valued for a light workspace:
 * the source's opaque `#151920` slab is legible behind a page on its dark
 * canvas and would read as a hard black frame on ours, so the shell is a blurred
 * black wash — a real drop shadow (founder: the artboard carries a subtle
 * shadow so it reads as a physical tile) — and the border keeps the hairline the
 * retired `.imageCanvas` card drew, `--clue-ds-color-border-subtle`.
 */
export const ARTBOARD_SHADOW_COLOR = "rgba(15, 23, 42, 0.16)";
export const ARTBOARD_SHADOW_BLUR_PX = 16;
export const ARTBOARD_SHADOW_OFFSET_PX = 4;
export const ARTBOARD_BORDER_COLOR = "#E6E9ED";
export const ARTBOARD_BORDER_WIDTH_PX = 1;

/** The artboard's chrome in WORKSPACE units, for the current zoom. */
export interface ArtboardChromeGeometry {
  /** The rect the shadow is painted over (the artboard, nudged down). */
  shadow: Rect;
  /** Blur sigma, in workspace units. */
  shadowSigma: number;
  /** Border stroke width, in workspace units. */
  borderWidth: number;
}

/**
 * The chrome, sized so it is CONSTANT ON SCREEN.
 *
 * The draw loop paints inside the viewport transform, so anything expressed in
 * workspace units is multiplied by the zoom: a 16px blur would be 1.6px at 10%
 * and 32px at 200%. Chrome is not content — the shadow and the hairline must
 * look the same at every zoom — so every screen-px constant is divided by the
 * zoom here. This is the same rule the selection overlay follows by being a
 * screen-space sibling; the artboard cannot be, because it must sit UNDER the
 * page's own pixels.
 */
export function artboardChromeGeometry(
  rect: Rect,
  zoom: number,
): ArtboardChromeGeometry {
  const scale = isPositiveFinite(zoom) ? clampWorkspaceZoom(zoom) : 1;
  const offset = ARTBOARD_SHADOW_OFFSET_PX / scale;
  return {
    shadow: {
      x: rect.x,
      y: rect.y + offset,
      width: rect.width,
      height: rect.height,
    },
    shadowSigma: ARTBOARD_SHADOW_BLUR_PX / scale,
    borderWidth: ARTBOARD_BORDER_WIDTH_PX / scale,
  };
}

/**
 * One wheel notch of zoom — the source stage's own step
 * (`CanvasKitCanvas.tsx:977`: `current.zoom + (deltaY > 0 ? -0.08 : 0.08)`),
 * ported rather than re-tuned.
 */
export const WHEEL_ZOOM_STEP = 0.08;

/**
 * A wheel event's effect on the viewport — the whole decision, in one tested
 * place.
 *
 * Ported from the source canvas's `onWheel` (`CanvasKitCanvas.tsx:968-987`):
 * ⌘/Ctrl + wheel zooms **at the pointer** (so the pixel under the cursor stays
 * under it), a plain wheel — which is what a trackpad's two-finger scroll
 * emits — pans by the inverse of the delta, and the pan is clamped so a slice
 * of the artboard always stays on screen. Panning into an empty void is the one
 * way an infinite canvas can lose a user, and the clamp is the source's answer
 * to it.
 */
export function sceneWheelViewport({
  bounds,
  delta,
  point,
  stage,
  viewport,
  zoomGesture,
}: {
  /** The artboard rect — what the pan clamp keeps reachable. */
  bounds: Rect;
  delta: Point;
  /** The pointer, in stage CSS px — the zoom anchor. */
  point: Point;
  stage: ViewportSize;
  viewport: WorkspaceViewport;
  /** ⌘/Ctrl held (or a pinch, which the browser reports as ctrl+wheel). */
  zoomGesture: boolean;
}): WorkspaceViewport {
  if (zoomGesture) {
    if (!Number.isFinite(delta.y) || delta.y === 0) {
      return viewport;
    }
    return zoomWorkspaceViewportAtPoint(
      viewport,
      point,
      viewport.zoom + (delta.y > 0 ? -WHEEL_ZOOM_STEP : WHEEL_ZOOM_STEP),
    );
  }
  return clampWorkspacePanToKeepVisible(
    panWorkspaceViewport(viewport, { x: -delta.x, y: -delta.y }),
    bounds,
    stage,
  );
}

/**
 * A drag-pan's effect on the viewport: the grabbed point follows the pointer.
 *
 * `origin` is the press — the pointer position and the pan at that instant — so
 * the pan is recomputed from the ORIGIN on every move rather than accumulated
 * per event; a dropped or coalesced move can then never leave the content
 * drifting behind the cursor.
 */
export function sceneDragPanViewport({
  bounds,
  origin,
  point,
  stage,
  viewport,
}: {
  bounds: Rect;
  origin: { point: Point; pan: Point };
  point: Point;
  stage: ViewportSize;
  viewport: WorkspaceViewport;
}): WorkspaceViewport {
  return clampWorkspacePanToKeepVisible(
    {
      zoom: viewport.zoom,
      pan: {
        x: origin.pan.x + (point.x - origin.point.x),
        y: origin.pan.y + (point.y - origin.point.y),
      },
    },
    bounds,
    stage,
  );
}

/**
 * The zoom a gesture landed on, as a label for the header's zoom control.
 *
 * NOT `snapZoomPercent`: that one rounds to the menu's 5% steps and clamps into
 * the menu's 10–150% range, which is right for the fit (the menu has to be able
 * to check the item it displays) and wrong for a free gesture — a pinch to 172%
 * is inside the ENGINE's clamp and must not be reported as "150%". So this
 * rounds to a whole percent and clamps only where the engine does. At a
 * percentage the menu happens to offer, the menu's checkmark lights up, which is
 * accurate: that is where the viewport is.
 */
export function formatZoomPercent(zoom: number): string {
  if (!Number.isFinite(zoom) || zoom <= 0) {
    return `${MIN_ZOOM_PERCENT}%`;
  }
  return `${Math.round(clampWorkspaceZoom(zoom) * 100)}%`;
}

/** What the canvas draws with, and what the header menu says it is drawing. */
export interface SceneViewportModel {
  /** The viewport the canvas actually applies. */
  applied: WorkspaceViewport;
  /** The exact contain-fit for this stage and this page box. */
  fit: WorkspaceViewport;
  /** The fit as one of the menu's own 5% steps — a LABEL, not the applied
   * scale. */
  fitLabel: string;
}

/**
 * AD2.8: the fit-vs-chosen decision, in one place.
 *
 * The two are deliberately NOT the same number:
 *
 * - **Fit-on-open (no choice yet).** The canvas applies the EXACT contain-fit
 *   of the artboard to the STAGE, inset by `ARTBOARD_FIT_MARGIN` — an exact
 *   scale (`0.4267…`), not a menu step, so the page lands where the geometry
 *   says and not 2.5% off it. The header menu meanwhile shows `fitLabel` — the
 *   nearest step it actually offers (`"45%"`) — because the ratified menu has 29
 *   items and no "Fit" entry, and inventing one is barred. So on open the label
 *   is an honest APPROXIMATION of the applied scale, and the gap is at most half
 *   a step (2.5%).
 * - **After a choice.** The label and the transform are the same number: the
 *   canvas applies exactly the chosen step and the menu checks exactly that
 *   item. Picking the step the label already showed therefore does move the
 *   canvas slightly (`45%` is not `42.67%`) — that is the model working, not a
 *   bug.
 *
 * A chosen zoom re-centers with `fitWorkspaceRectToViewport`'s own pan math at
 * the chosen scale, so picking a step always brings the artboard back to the
 * middle of the stage.
 *
 * This is the viewport the canvas STARTS from, not the one it is stuck with:
 * AD2.10 gives the stage pan and pointer-anchored wheel-zoom
 * (`sceneWheelViewport` / `sceneDragPanViewport`), and a gesture supersedes this
 * derivation until the next explicit choice. Above the fit the artboard is
 * larger than the viewport and the parts off-screen are reached by panning —
 * they are no longer unreachable, which was the whole defect AD2.10 repairs.
 *
 * A starved stage (zero-sized during the first layout pass) falls back to the
 * fit's own default viewport rather than panning the artboard off-stage.
 */
export function sceneViewportModel({
  rect,
  stage,
  zoom,
}: {
  /** The artboard's rect in workspace space. */
  rect: Rect;
  /** The artboard card's measured size. */
  stage: ViewportSize;
  /** The header menu's chosen step, or null/absent for fit. */
  zoom: string | null | undefined;
}): SceneViewportModel {
  const fit = fitWorkspaceRectToViewport({
    viewport: stage,
    rect,
    margin: ARTBOARD_FIT_MARGIN,
  });
  const fitLabel = snapZoomPercent(fit.zoom);
  const chosen = chosenZoomScale(zoom);
  if (
    chosen === null ||
    !isPositiveFinite(stage.width) ||
    !isPositiveFinite(stage.height)
  ) {
    return { applied: fit, fit, fitLabel };
  }
  return {
    applied: {
      zoom: chosen,
      pan: {
        x: stage.width / 2 - (rect.x + rect.width / 2) * chosen,
        y: stage.height / 2 - (rect.y + rect.height / 2) * chosen,
      },
    },
    fit,
    fitLabel,
  };
}

function isPositiveFinite(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}

const SHA256_HEX = /^[0-9a-f]{64}$/;

/**
 * The bytes URL for one of the scene's own asset records, through the
 * headerless public passthrough (AD1.7 / ruling D8).
 *
 * Built by string concatenation, deliberately: `DESIGN_PUBLIC_BFF_PREFIX` is a
 * PATH prefix, and the engine's `assetStoreBytesUrl` resolves through
 * `new URL(path, base)`, which silently drops a base's path (there is a note
 * to that effect at its definition). Passing the prefix there would produce
 * `/asset-store/{digest}` — a 404 on this origin — so this resolver never
 * touches it.
 *
 * Resolution reads `media.digest` (the same source of truth server exports
 * resolve from), never `media.thumbnail`, which `GET /documents/{id}` serves
 * without a digest. An unusable or missing digest resolves to null, which the
 * image cache models as a skipped load — an honestly blank image, never a
 * fetch that can only fail.
 */
export function sceneAssetPassthroughUrl(
  assets: Record<string, AssetRecord> | undefined,
  assetId: string,
): string | null {
  return digestPassthroughUrl(assets?.[assetId]?.media?.digest);
}

/**
 * AD4.A step 3: the same passthrough for a record the scene does NOT carry —
 * the AI suite's staged candidate, which is a real, registered asset but is not
 * in `scene.assets` until an Accept upserts it.
 *
 * It prefers the THUMBNAIL digest where the one above cannot: the engine's own
 * `publicAssetThumbnailUrl` states that policy ("the API stamps it at the DTO
 * boundary"), and this record comes straight off `POST /assets/generate`, which
 * is exactly that boundary. `GET /documents/{id}` serves no thumbnail digest,
 * which is why the scene-map resolver above never looks. Same fallback either
 * way: no usable digest ⇒ null ⇒ an honestly blank tile, never a fetch that can
 * only fail.
 */
export function assetRecordPassthroughUrl(
  record: AssetRecord | null | undefined,
): string | null {
  return (
    digestPassthroughUrl(record?.media?.thumbnail?.digest) ??
    digestPassthroughUrl(record?.media?.digest)
  );
}

function digestPassthroughUrl(
  digest: { algorithm?: string; value?: string } | null | undefined,
): string | null {
  if (
    !digest ||
    digest.algorithm !== "sha256" ||
    typeof digest.value !== "string" ||
    !SHA256_HEX.test(digest.value)
  ) {
    return null;
  }
  return `${DESIGN_PUBLIC_BFF_PREFIX}/asset-store/${digest.value}`;
}

/**
 * A digest of every text node's measurement inputs — the C4 measure-then-
 * inject pass keys on THIS, never on the whole scene.
 *
 * Ported field-for-field from `CanvasKitCanvas.tsx:313-350`, and the exactness
 * is load-bearing: `setMeasurements` relayouts and hands back a new scene, so
 * a signature that moved with any scene change would make measure → relayout →
 * refresh → measure an infinite loop. `generation` is the kit token maps'
 * generation (kit values land after the first paint and are measurement
 * inputs), so measurements re-run when the brand kit arrives.
 *
 * Plan 4 item F adds each text node's SOLVED size to its part: the line pass
 * (`skiaLineMeasurements`) is keyed on the box the engine solved, so that box
 * is a measurement input now — a resized box whose signature did not move
 * would keep serving stale lines (the key misses → heuristic lines). This does
 * NOT reopen the loop: the injection is deterministic, so once the boxes stop
 * moving the signature stops moving and the effect reaches a fixed point.
 * Fixed-point (`toFixed(3)`) formatting matches the measurements' own rounding,
 * so float noise below a thousandth cannot keep the effect alive.
 */
export function textMeasurementSignature(
  scene: Scene,
  generation: number,
): string {
  const parts: string[] = [];
  for (const node of Object.values(scene.nodes)) {
    if (node.kind.kind !== "text") {
      continue;
    }
    const t = node.kind;
    parts.push(
      [
        node.id,
        t.content,
        t.font_family,
        t.font_size,
        t.font_weight,
        t.line_height ?? 1.2,
        t.letter_spacing ?? 0,
        t.wrap ?? "no_wrap",
        t.max_lines ?? "_",
        t.direction ?? "ltr",
        t.text_transform ?? "none",
        t.truncate ?? false,
        t.paragraph_spacing ?? 0,
        t.spans && t.spans.length > 0 ? JSON.stringify(t.spans) : "_",
        t.style_token ?? "_",
        t.font_size_token ?? "_",
        t.line_height_token ?? "_",
        t.letter_spacing_token ?? "_",
        node.computed
          ? `${node.computed.layout_bounds.width.toFixed(3)}x${node.computed.layout_bounds.height.toFixed(3)}`
          : "_",
      ].join("|"),
    );
  }
  return `${generation}\n${parts.sort().join("\n")}`;
}

/** One artboard's draw model: what the surface clears, clips and walks. */
export interface SceneArtboardModel {
  page: RenderPageDescriptor;
  nodes: DrawNode[];
  /** The artboard's rect in workspace space. A single artboard sits at the
   * workspace origin, so this is the page box — the rect fit-on-open fits. */
  rect: Rect;
}

/**
 * AD4.C: one node's live gesture geometry — a DESCRIPTOR-space box (the space
 * the gesture machine and the operation builders speak), for the duration of a
 * drag or a resize.
 *
 * It is a render-time override and nothing else. The engine's scene owns the
 * document's values (AD4.R), so a gesture in flight writes nowhere: the
 * descriptor tree below is rebuilt with this box substituted, the overlay
 * outlines the same box, and dropping it repaints the document's own truth.
 */
export interface ScenePreview {
  nodeId: NodeId;
  box: Box;
  /** Degrees. Unchanged by v1's two gestures (§1.9: no rotate handle), so it
   * is the node's own rotation — carried so the override is complete. */
  rotation: number;
}

/**
 * Build the descriptor tree for one page of a scene.
 *
 * Returns null when the page is not in the scene (a document whose pages
 * changed under a stale page id renders nothing rather than throwing).
 *
 * AD4.C restores the one thing this builder dropped when it was lifted from
 * the source canvas: the in-gesture `preview` override
 * (`CanvasKitCanvas.tsx:373-388`), which was "a write-path concern" until the
 * write path existed. It is applied HERE, at descriptor-build time, for the
 * same reason it is upstream — the draw loop then needs no gesture awareness at
 * all, and the previewed node is drawn by exactly the code that draws every
 * other node.
 *
 * Rung B (rich-text plan, 2026-08-24) rides the SAME mechanism for the one
 * other render-time override the canvas needs: `editingNodeId` drops that
 * node's text payload, so a node under an open caret session paints its fills,
 * strokes and box as always and its glyphs not at all — the DOM overlay is the
 * only copy of the string on screen, and the draw loop needs no session
 * awareness either. A stale id (the node left the scene mid-session) matches
 * nothing and suppresses nothing.
 */
export function sceneArtboardModel(
  scene: Scene,
  pageId: PageId | null,
  preview: ScenePreview | null = null,
  editingNodeId: NodeId | null = null,
): SceneArtboardModel | null {
  const page = pageId ? scene.pages[pageId] : null;
  if (!page) {
    return null;
  }
  const descriptor = pageDescriptor(page);
  const inFlow = page.children
    .filter((nodeId) => !isNodePinned(scene, nodeId))
    .map((nodeId) =>
      buildDrawNode(scene, page, nodeId, null, preview, editingNodeId),
    )
    .filter((node): node is DrawNode => node !== null);
  return {
    page: descriptor,
    // Pinned nodes are skipped inline and hoisted here, painted last (above
    // in-flow content) from their page-space computed box — the engine's own
    // `pinned_paint_pass` order.
    nodes: [...inFlow, ...pinnedDrawNodes(scene, page, preview, editingNodeId)],
    rect: { x: 0, y: 0, width: descriptor.width, height: descriptor.height },
  };
}

function buildDrawNode(
  scene: Scene,
  page: Page,
  nodeId: NodeId,
  parentComputedOrigin: { x: number; y: number } | null,
  preview: ScenePreview | null,
  editingNodeId: NodeId | null,
): DrawNode | null {
  const node = scene.nodes[nodeId];
  if (!node) {
    return null;
  }
  const descriptor = nodeDescriptor(scene, node, page, parentComputedOrigin);
  if (editingNodeId === nodeId) {
    // `drawDescriptors` skips the whole text leg on a missing payload, so
    // dropping it is the complete suppression — no empty-string special case
    // reaches the painter, and every other descriptor field stays honest.
    descriptor.text = undefined;
  }
  if (preview && preview.nodeId === nodeId) {
    // The preview box is page-ABSOLUTE descriptor px; a descriptor's x/y are
    // PARENT-relative (`nodeDescriptor` subtracts the parent's computed
    // origin), so the same offset comes back off here — in descriptor px,
    // which is why it is scaled. Upstream's own arithmetic.
    const scale = pageDescriptor(page).unitScale;
    descriptor.x = preview.box.x - (parentComputedOrigin?.x ?? 0) * scale;
    descriptor.y = preview.box.y - (parentComputedOrigin?.y ?? 0) * scale;
    descriptor.width = preview.box.width;
    descriptor.height = preview.box.height;
    descriptor.rotation = preview.rotation;
  }
  const childOrigin = node.computed
    ? {
        x: node.computed.layout_bounds.x,
        y: node.computed.layout_bounds.y,
      }
    : null;
  return {
    descriptor,
    children: node.children
      .filter((childId) => !isNodePinned(scene, childId))
      .map((childId) =>
        buildDrawNode(scene, page, childId, childOrigin, preview, editingNodeId),
      )
      .filter((child): child is DrawNode => child !== null),
  };
}

function pinnedDrawNodes(
  scene: Scene,
  page: Page,
  preview: ScenePreview | null,
  editingNodeId: NodeId | null,
): DrawNode[] {
  const out: DrawNode[] = [];
  const walk = (nodeId: NodeId) => {
    const node = scene.nodes[nodeId];
    if (!node) {
      return;
    }
    if (isNodePinned(scene, nodeId)) {
      const built = buildDrawNode(scene, page, nodeId, null, preview, editingNodeId);
      if (built) {
        out.push(built);
      }
    }
    node.children.forEach(walk);
  };
  page.children.forEach(walk);
  return out;
}

/* -------------------------------------------------------------------------
 * Gate G-A — the selection outline (founder ruling, 2026-08-20: Variant B)
 * ---------------------------------------------------------------------- */

/**
 * The approved selection stroke: a 1.5px indigo outline around the selected
 * node's box (Variant B, `/tmp/ga-variant-B.png`).
 *
 * Screen-space constants, deliberately: the overlay is an SVG sibling of the
 * canvas whose user units ARE stage CSS px, so the stroke stays 1.5px at every
 * zoom — the outline is chrome, not content, and content is the only thing the
 * viewport scales.
 */
export const SELECTION_OUTLINE_COLOR = "#4F46E5";
export const SELECTION_OUTLINE_WIDTH = 1.5;
/** Plan 3 R4: the hover outline — the selection colour, 1px, translucent, no handles. */
export const HOVER_OUTLINE_WIDTH = 1;
export const HOVER_OUTLINE_OPACITY = 0.55;

/**
 * The four corner handles of the same G-A ruling — **approved, and LIVE since
 * AD4.C.**
 *
 * Handles are a promise of drag-and-resize, so they waited for that behaviour
 * (the editor was read-only until AD3 armed the write path, and a handle a user
 * can grab that does nothing is a fake affordance). AD4.C shipped it: the
 * canvas passes `handles` to the overlay whenever the selection can actually be
 * resized — an editable node, a live engine, and no in-flight agent turn.
 */
export const SELECTION_HANDLE_SIZE = 8;
export const SELECTION_HANDLE_CORNER_RADIUS = 1;
export const SELECTION_HANDLE_FILL = "#FFFFFF";
export const SELECTION_HANDLE_STROKE = SELECTION_OUTLINE_COLOR;
export const SELECTION_HANDLE_STROKE_WIDTH = 1.5;

/** The selected node's box in STAGE CSS px — what the overlay strokes. */
export interface SceneSelectionOutline {
  nodeId: NodeId;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Degrees, about the box origin (`x`,`y`) — the same pivot the draw loop
   * rotates a node about (`drawDescriptors`: translate to the origin, then
   * `rotate(rotation, 0, 0)`). */
  rotation: number;
  /** Plan 4 item F: for a text node whose layout box differs from its painted
   * lines, the layout box — drawn dashed, and where the resize handles sit
   * (a resize changes the BOX). Null for every other selection, for a hug box,
   * and during a gesture preview (the preview IS the box). Screen px, like
   * the outline itself; rotation pivots on its origin when present. */
  frame: { x: number; y: number; width: number; height: number } | null;
}

/** Founder ruling 2026-10-18 (amends R5): whether the overlay strokes the
 * outline around a text's letters. A SELECTED text that has a dashed frame
 * shows only that frame — the box its handles resize — because two boxes on
 * one selection read as two things to resize. The letters' outline stays as
 * the hover preview, and every selection without a frame strokes its outline
 * as before (there the outline IS the box). */
export function selectionStrokesPaintedOutline(
  outline: SceneSelectionOutline,
  variant: "selection" | "hover",
): boolean {
  return variant === "hover" || outline.frame === null;
}

/** Plan 4 item F: the layout box may differ from the painted box by taffy's
 * whole-pixel rounding (a hug box sits up to half a pixel under the measured
 * height — `layout.rs` ROUNDING_TOLERANCE); only a larger difference is a
 * fixed size worth a frame. Scene units. */
const TEXT_FRAME_TOLERANCE = 0.5;

/**
 * The union of a text node's PAINTED line boxes (page space, unrotated — the
 * frame `layout_bounds` is in), or null when the node is not text or carries
 * no positive-area line (a stored scene, an engine that predates the lines, an
 * empty string).
 *
 * This is what a text selection outlines: the glyphs, not the box the author
 * typed. A fixed box the copy does not fill outlined empty space, and a glyph
 * painted past a box the copy outgrew was outlined nowhere near where it sits.
 */
export function sceneTextPaintedBox(node: Node): Box | null {
  if (node.kind.kind !== "text") {
    return null;
  }
  let left = Number.POSITIVE_INFINITY;
  let top = Number.POSITIVE_INFINITY;
  let right = Number.NEGATIVE_INFINITY;
  let bottom = Number.NEGATIVE_INFINITY;
  for (const line of node.computed?.text_lines ?? []) {
    if (!(line.width > 0) || !(line.height > 0)) {
      continue;
    }
    left = Math.min(left, line.x);
    top = Math.min(top, line.y);
    right = Math.max(right, line.x + line.width);
    bottom = Math.max(bottom, line.y + line.height);
  }
  if (!Number.isFinite(left) || !Number.isFinite(top)) {
    return null;
  }
  return { x: left, y: top, width: right - left, height: bottom - top };
}

/** Plan 4 item F: does the layout box stand apart from the painted glyphs by
 * more than the rounding contract — i.e. is there a box worth drawing dashed
 * alongside the text? Both boxes are page-space scene units. */
export function sceneTextFrameDiffers(layout: Box, painted: Box): boolean {
  return (
    Math.abs(layout.x - painted.x) > TEXT_FRAME_TOLERANCE ||
    Math.abs(layout.y - painted.y) > TEXT_FRAME_TOLERANCE ||
    Math.abs(layout.x + layout.width - (painted.x + painted.width)) >
      TEXT_FRAME_TOLERANCE ||
    Math.abs(layout.y + layout.height - (painted.y + painted.height)) >
      TEXT_FRAME_TOLERANCE
  );
}

/**
 * A selected node's box, in the stage's own CSS px.
 *
 * This is the exact inverse of AD2.5's input chain (`sceneHitPoint`), run
 * backwards, and every step has a mirror there:
 *
 *   engine box (`computed.layout_bounds`, absolute page space, SCENE units)
 *     → × `page.unitScale`                    scene units → descriptor px
 *     → + the artboard's workspace origin      descriptor px → workspace
 *     → `workspaceRectToScreen(rect, viewport)` undo pan + zoom
 *
 * The `unitScale` multiply is the same trap `sceneHitPoint`'s divide is:
 * invisible on a `pt`/`px` page (unitScale 1, which the seeded ad is) and wrong
 * by 96x on an `in` page. It is unit-tested against a non-identity unit.
 *
 * Derived per render from the SAME `WorkspaceViewport` the draw loop transforms
 * by, never stored — so zoom changes and stage resizes cannot leave a stale box
 * behind.
 */
export function selectionOutlineForBox({
  artboard,
  box,
  nodeId,
  rotation,
  viewport,
}: {
  artboard: SceneArtboardModel;
  /** Absolute page-space box in the engine's own units. */
  box: Box;
  nodeId: NodeId;
  rotation: number;
  viewport: WorkspaceViewport;
}): SceneSelectionOutline | null {
  const scale = artboard.page.unitScale;
  if (
    !Number.isFinite(box.x) ||
    !Number.isFinite(box.y) ||
    !Number.isFinite(box.width) ||
    !Number.isFinite(box.height) ||
    !isPositiveFinite(scale)
  ) {
    return null;
  }
  const screen = workspaceRectToScreen(
    {
      x: artboard.rect.x + box.x * scale,
      y: artboard.rect.y + box.y * scale,
      width: box.width * scale,
      height: box.height * scale,
    },
    viewport,
  );
  return {
    nodeId,
    x: screen.x,
    y: screen.y,
    width: screen.width,
    height: screen.height,
    rotation: Number.isFinite(rotation) ? rotation : 0,
    // Plan 4 item F: one box in, one box out. The dashed layout frame is a
    // TEXT selection's second box, so it is `sceneSelectionOutline`'s to add.
    frame: null,
  };
}

/**
 * The outline for the current selection, or null when there is nothing to
 * outline.
 *
 * The box is not re-derived here: `deriveSelectionChromeModel` is the engine's
 * own selection-chrome oracle (the standalone editor's canvas reads the same
 * model), so the platform overlay and the design subsystem can never disagree
 * about what "the selected node's box" means.
 *
 * Null — no overlay element at all — in every honest empty case: no selection,
 * a selected id the scene no longer carries, and a node with **no computed
 * geometry** (`selectionBoxForNode` returns null). That last one matters: the
 * stored scene carries `computed: null` on every node, and only the engine's
 * relayout fills it in. With the engine live (the only state in which a canvas
 * click can select anything at all — AD2.5) the geometry is there; without it
 * there is no outline rather than a box guessed from `transform`, which for an
 * auto-laid-out child would be drawn somewhere the node is not.
 *
 * Plan 4 item F (ruling R5): for a TEXT node the engine has placed lines for,
 * the stroked box is the union of those painted lines and the layout box rides
 * along as `frame` when the two differ. The chrome model's box is untouched —
 * gesture geometry stays the layout box, because that is what a drag or a
 * resize changes.
 */
export function sceneSelectionOutline({
  artboard,
  pageId,
  preview,
  scene,
  selectedNodeId,
  viewport,
}: {
  artboard: SceneArtboardModel | null;
  pageId: PageId | null;
  /** AD4.C: a gesture in flight on THIS node — the outline (and its handles)
   * follow the live box, so the chrome and the previewed pixels move together
   * as one thing. Upstream's own `selectionBox` memo
   * (`CanvasKitCanvas.tsx:462-464`). A preview for another node is ignored. */
  preview?: ScenePreview | null;
  scene: Scene | null;
  selectedNodeId: NodeId | null;
  viewport: WorkspaceViewport;
}): SceneSelectionOutline | null {
  if (!scene || !artboard || !selectedNodeId) {
    return null;
  }
  if (preview && preview.nodeId === selectedNodeId) {
    // The preview box is descriptor px and `selectionOutlineForBox` takes
    // scene units (it applies the `unitScale` multiply itself), so the one
    // conversion happens here rather than the box being carried in two spaces.
    const scale = artboard.page.unitScale;
    return selectionOutlineForBox({
      artboard,
      box: sceneBoxFromDescriptor(preview.box, scale),
      nodeId: preview.nodeId,
      rotation: preview.rotation,
      viewport,
    });
  }
  const { selectionBox } = deriveSelectionChromeModel(scene, {
    activePageId: pageId,
    selectedNodeId,
  });
  if (!selectionBox) {
    return null;
  }
  // Plan 4 item F (ruling R5): a text node is outlined by the glyphs it paints.
  // `selectionBox.box` stays the layout box everywhere else — it is the gesture
  // box, and a resize changes the BOX — so the painted union is only ever the
  // stroke, with the layout box returned alongside it as the dashed frame.
  const node = scene.nodes[selectedNodeId];
  const painted = node ? sceneTextPaintedBox(node) : null;
  if (!painted) {
    return selectionOutlineForBox({
      artboard,
      box: selectionBox.box,
      nodeId: selectionBox.nodeId,
      rotation: selectionBox.rotation,
      viewport,
    });
  }
  const outline = selectionOutlineForBox({
    artboard,
    box: painted,
    nodeId: selectionBox.nodeId,
    rotation: selectionBox.rotation,
    viewport,
  });
  if (!outline) {
    return null;
  }
  const frame = sceneTextFrameDiffers(selectionBox.box, painted)
    ? selectionOutlineForBox({
        artboard,
        box: selectionBox.box,
        nodeId: selectionBox.nodeId,
        rotation: selectionBox.rotation,
        viewport,
      })
    : null;
  return {
    ...outline,
    frame: frame
      ? { x: frame.x, y: frame.y, width: frame.width, height: frame.height }
      : null,
  };
}

/** A descriptor-px box back in the scene units `selectionOutlineForBox` takes
 * — the inverse of its own `unitScale` multiply, for a gesture's live box. */
function sceneBoxFromDescriptor(box: Box, unitScale: number): Box {
  const scale = isPositiveFinite(unitScale) ? unitScale : 1;
  return {
    x: box.x / scale,
    y: box.y / scale,
    width: box.width / scale,
    height: box.height / scale,
  };
}

/**
 * The four corner handles for an outline, centred on its corners, in the
 * outline's own PRE-rotation frame — the overlay rotates the outline and its
 * handles together as one group, so a rotated selection's handles ride its
 * corners without any second rotation here.
 *
 * G-A-approved geometry, **rendered since AD4.C** (see the handle constants
 * above).
 *
 * Plan 4 item F: any box, not only the outline itself — a text selection whose
 * stroke is its painted lines hands its dashed `frame` here instead, since the
 * box is what a resize changes.
 */
export function selectionHandleRects(outline: {
  x: number;
  y: number;
  width: number;
  height: number;
}): Array<{ x: number; y: number; size: number }> {
  const half = SELECTION_HANDLE_SIZE / 2;
  const right = outline.x + outline.width;
  const bottom = outline.y + outline.height;
  return [
    { x: outline.x, y: outline.y },
    { x: right, y: outline.y },
    { x: outline.x, y: bottom },
    { x: right, y: bottom },
  ].map((corner) => ({
    x: corner.x - half,
    y: corner.y - half,
    size: SELECTION_HANDLE_SIZE,
  }));
}
