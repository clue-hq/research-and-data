import { DESIGN_PUBLIC_BFF_PREFIX } from "../data/design-bff";
import type { DrawNode } from "../engine/scene/canvaskit/drawDescriptors";
import type {
  AssetRecord,
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
import type { Rect } from "../engine/scene/workspaceLayout";
import {
  clampWorkspaceZoom,
  fitWorkspaceRectToViewport,
  type ViewportSize,
  type WorkspaceViewport,
} from "../engine/scene/workspaceViewport";

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
 * margin 0: the dummy's `.imageCanvas` card IS the artboard (its hairline
 * border is the artboard edge), so the page fills it edge-to-edge (AD2.3
 * review / ruling 17). The upstream default (128) exists for the standalone
 * editor's infinite workspace, where the artboard floats in a dark shell —
 * porting it here leaves a white ring inside the designed card. Contain-fit
 * still letterboxes a non-square page in the square card.
 */
export const ARTBOARD_FIT_MARGIN = 0;

/** What the canvas draws with, and what the header menu says it is drawing. */
export interface SceneViewportModel {
  /** The viewport the canvas actually applies. */
  applied: WorkspaceViewport;
  /** The exact contain-fit for this card and this page box. */
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
 *   (`0.4267…`), because that is what makes the ad fill the designed artboard
 *   card edge-to-edge (ruling 17). The header menu meanwhile shows
 *   `fitLabel` — the nearest step it actually offers (`"45%"`) — because the
 *   ratified menu has 29 items and no "Fit" entry, and inventing one is barred.
 *   So on open the label is an honest APPROXIMATION of the applied scale, and
 *   the gap is at most half a step (2.5%).
 * - **After a choice.** The label and the transform are the same number: the
 *   canvas applies exactly the chosen step and the menu checks exactly that
 *   item. Picking the step the label already showed therefore does move the
 *   canvas slightly (`45%` is not `42.67%`) — that is the model working, not a
 *   bug.
 *
 * A chosen zoom re-centers with `fitWorkspaceRectToViewport`'s own pan math at
 * the chosen scale, so the artboard stays centered in the card at every zoom.
 * There is no pointer-anchored zoom (`zoomWorkspaceViewportAtPoint`) and no
 * panning: the dummy has no designed affordance for either, so above the fit
 * the page is simply clipped by the card, centered.
 *
 * A starved stage (zero-sized during the first layout pass) falls back to the
 * fit's own default viewport rather than panning the artboard off-card.
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
  const digest = assets?.[assetId]?.media?.digest;
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
 * Build the descriptor tree for one page of a scene.
 *
 * Returns null when the page is not in the scene (a document whose pages
 * changed under a stale page id renders nothing rather than throwing).
 */
export function sceneArtboardModel(
  scene: Scene,
  pageId: PageId | null,
): SceneArtboardModel | null {
  const page = pageId ? scene.pages[pageId] : null;
  if (!page) {
    return null;
  }
  const descriptor = pageDescriptor(page);
  const inFlow = page.children
    .filter((nodeId) => !isNodePinned(scene, nodeId))
    .map((nodeId) => buildDrawNode(scene, page, nodeId, null))
    .filter((node): node is DrawNode => node !== null);
  return {
    page: descriptor,
    // Pinned nodes are skipped inline and hoisted here, painted last (above
    // in-flow content) from their page-space computed box — the engine's own
    // `pinned_paint_pass` order.
    nodes: [...inFlow, ...pinnedDrawNodes(scene, page)],
    rect: { x: 0, y: 0, width: descriptor.width, height: descriptor.height },
  };
}

function buildDrawNode(
  scene: Scene,
  page: Page,
  nodeId: NodeId,
  parentComputedOrigin: { x: number; y: number } | null,
): DrawNode | null {
  const node = scene.nodes[nodeId];
  if (!node) {
    return null;
  }
  const descriptor = nodeDescriptor(scene, node, page, parentComputedOrigin);
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
      .map((childId) => buildDrawNode(scene, page, childId, childOrigin))
      .filter((child): child is DrawNode => child !== null),
  };
}

function pinnedDrawNodes(scene: Scene, page: Page): DrawNode[] {
  const out: DrawNode[] = [];
  const walk = (nodeId: NodeId) => {
    const node = scene.nodes[nodeId];
    if (!node) {
      return;
    }
    if (isNodePinned(scene, nodeId)) {
      const built = buildDrawNode(scene, page, nodeId, null);
      if (built) {
        out.push(built);
      }
    }
    node.children.forEach(walk);
  };
  page.children.forEach(walk);
  return out;
}
