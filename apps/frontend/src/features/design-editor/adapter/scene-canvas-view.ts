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
