import type { InspectorIconName } from "@/features/chat-shell/components/inspector-primitives";
import type { Node, NodeId, PageId, Scene } from "../engine/scene/contracts";
import { nodeDisplayName } from "../engine/scene/sceneQueries";
import { oklchToHexCss } from "../engine/scene/tokenColors";
import { rootFrameId, sceneSelectionFor } from "./scene-hydrate";

/**
 * AD2.6: the ad Layers panel's rows, built from the REAL scene tree — mapping
 * contract §1.7 ("real recursive tree, any depth · kind glyphs incl. fill-swatch
 * squares for Rect/Ellipse · additive multi-select · auto-scroll to primary ·
 * no up/down reorder buttons · container rows keep the dummy's collapse/expand
 * chevrons"). It replaces the dummy's hardcoded eight-row fixture tree; the row
 * MARKUP is untouched.
 *
 * The tree starts at the PAGE's children, so the artboard frame is itself a
 * depth-0 row whose children sit at depth 1 — the design editor's own
 * `LayerPanel` (`subsystems/clue-design/apps/editor/src/components/LayerPanel.tsx`)
 * maps `page.children` at depth 0 exactly this way, and clicking that row is
 * meaningful here because `sceneSelectionFor` routes the root frame to the
 * CANVAS schema. Nothing is elided, which is what "any depth" asks for.
 *
 * Three rules keep this file honest:
 *   • `selectable` is NOT a second kind list. It asks AD2.4's oracle
 *     (`sceneSelectionFor`) whether the node has a schema at all, so §5's
 *     unrepresented kinds (line / vector / instance) come out false for free and
 *     a future schema addition needs no edit here. A row that is not selectable
 *     is a dead click (§5), not a hidden row — the layer still exists and the
 *     panel says so.
 *   • `expanded` is an INPUT, not state. The caller owns the expansion set (the
 *     dummy's `useInspectorLayerTree` in the component tree above); this
 *     function only filters by it, so the panel can never disagree with the
 *     chevron the dummy already draws.
 *   • `fillSwatch` is the §1.7 fill chip and exists for Rect/Ellipse only, from
 *     a SOLID fill only. A token or gradient fill has no single hex to show —
 *     resolving a token needs the brand kit, which the scene carries only as a
 *     `{id, version}` ref — so the chip is absent rather than invented.
 */

/**
 * The subset of `InspectorLayerRow`'s icon vocabulary the scene kinds map onto.
 * Assignable to the row's own `icon` prop by construction.
 */
export type SceneLayerIcon = Extract<
  InspectorIconName,
  | "div"
  | "ellipse"
  | "image"
  | "layout-template"
  | "rectangle"
  | "square-dashed"
  | "type"
>;

export interface SceneLayerRow {
  nodeId: string;
  /** Distance from the page: the artboard frame is 0, its children 1, … (§1.7
   * puts no cap on this — the website lane's depth-1 cap is ruling 41, and it
   * governs the WEB panel only). */
  depth: number;
  /** The editor-naming ruling: the node's own name (never a `Text34` artifact).
   * A nameless node falls back to the engine's own `nodeDisplayName`
   * (`"<kind> <id>"`) — the same string AD2.4 puts in the inspector header, so
   * the row and the header can never disagree about what a node is called. */
  label: string;
  icon: SceneLayerIcon;
  /** §1.7's Rect/Ellipse fill chip; absent for every other kind and for
   * token/gradient fills. */
  fillSwatch?: string;
  expandable: boolean;
  expanded: boolean;
  /** False for §5's unrepresented kinds — the row renders, the click is dead. */
  selectable: boolean;
}

/**
 * kind → glyph, in the dummy's own vocabulary (`InspectorLayerRow`'s union).
 *
 * The AD0.1 delta authored the two container glyphs this table needs
 * (`layout-template` for auto-layout, `square-dashed` for group); `type`,
 * `image`, `rectangle` and `ellipse` shipped with the dummy. The dummy set
 * carries NO frame / line / vector / instance glyph, and a new icon file is
 * founder-gated chrome, so those four fall back to `div` — the generic block
 * glyph the website lane already uses for "a container, or a kind with no
 * glyph of its own" (`adapter/layers.ts`). Recorded as a substitution, not a
 * claim that a line looks like a div.
 */
const KIND_ICONS: Record<string, SceneLayerIcon> = {
  auto_layout: "layout-template",
  ellipse: "ellipse",
  group: "square-dashed",
  image: "image",
  rect: "rectangle",
  text: "type",
};

const FALLBACK_ICON: SceneLayerIcon = "div";

function iconFor(node: Node): SceneLayerIcon {
  return KIND_ICONS[node.kind.kind] ?? FALLBACK_ICON;
}

/**
 * §1.7's fill chip: the first SOLID fill of a Rect/Ellipse as a hex string.
 *
 * The two convertible color kinds mirror `scene-hydrate`'s `colorText` (hex
 * verbatim, upper-cased the way `ColorControl` commits it; oklch through the
 * engine's own converter). A token COLOR is deliberately not handled here even
 * though `colorText` returns its `$name` — a chip needs a paintable value and
 * the name is not one.
 */
function fillSwatchFor(node: Node): string | undefined {
  if (node.kind.kind !== "rect" && node.kind.kind !== "ellipse") {
    return undefined;
  }
  const paint = node.fills[0]?.paint;
  if (!paint || paint.kind !== "solid") {
    return undefined;
  }
  const { color } = paint;
  switch (color.kind) {
    case "hex":
      return color.value.toUpperCase();
    case "oklch":
      return oklchToHexCss(color.l, color.c, color.h, color.alpha);
    case "token":
      return undefined;
  }
}

/**
 * The panel's rows, top to bottom, for one page.
 *
 * `expanded` holds the node ids whose children are revealed; a container not in
 * it contributes its own row and nothing below it. An unknown page has no tree,
 * so the panel is empty rather than guessing at another page's nodes.
 *
 * A child id missing from `scene.nodes` is skipped rather than throwing (the
 * rendered snapshot can lag the engine's own scene by a frame, and a stale id
 * must not take the shell down), and a node already on the current path is
 * skipped too — a cyclic scene is malformed, but a malformed scene must not
 * hang the panel in an infinite walk.
 */
export function sceneLayerRows(
  scene: Scene,
  pageId: PageId,
  expanded: ReadonlySet<string>,
): SceneLayerRow[] {
  const page = scene.pages[pageId];
  if (!page) {
    return [];
  }
  const root = rootFrameId(scene, pageId);
  const rows: SceneLayerRow[] = [];

  const walk = (nodeIds: NodeId[], depth: number, seen: ReadonlySet<NodeId>) => {
    for (const nodeId of nodeIds) {
      const node = scene.nodes[nodeId];
      if (!node || seen.has(nodeId)) {
        continue;
      }
      const children = node.children.filter((childId) => scene.nodes[childId]);
      const expandable = children.length > 0;
      const isExpanded = expandable && expanded.has(nodeId);
      const swatch = fillSwatchFor(node);
      rows.push({
        depth,
        expandable,
        expanded: isExpanded,
        icon: iconFor(node),
        label: nodeDisplayName(node),
        nodeId,
        selectable: sceneSelectionFor(node, root) !== null,
        ...(swatch === undefined ? {} : { fillSwatch: swatch }),
      });
      if (isExpanded) {
        walk(children, depth + 1, new Set(seen).add(nodeId));
      }
    }
  };

  walk(page.children, 0, new Set());
  return rows;
}
