// D7 DIVERGENCE — this is the slice's one deliberately non-verbatim module. The three Konva-only
// exports (konvaFillProps / konvaStrokeProps / konvaShadowProps, upstream lines ~559-624) are
// DELETED per founder ruling D7; an upstream re-sync must re-apply that deletion, not straight-copy.
import type {
  AssetKind,
  AssetStatus,
  Color,
  Effect,
  Fill,
  ImageFitMode,
  Node,
  Page,
  Paint,
  Scene,
  SizeSpec,
  Stroke,
  StrokeCap,
  StrokeJoin,
  Unit,
  VerticalAlign
} from "./contracts";
import { isNodeLayoutManaged } from "./sceneQueries";
import { namesTokenRef } from "./textSpans";
import {
  oklchToHexCss,
  resolveTokenColor,
  type KitTokenMaps,
  type TokenColorMap,
  type TokenTextStyle
} from "./tokenColors";

/**
 * Konva-ready paint description (Effects Contract V0). Gradients carry the
 * full stop list — no first-stop flattening — using the same geometry the
 * SVG exporter emits: linear gradients rotate the unit vector about the
 * box origin, radial gradients fill from the box center.
 */
export type PaintDescriptor =
  | { kind: "solid"; color: string }
  | {
      kind: "linear_gradient";
      start: { x: number; y: number };
      end: { x: number; y: number };
      colorStops: (number | string)[];
    }
  | {
      kind: "radial_gradient";
      center: { x: number; y: number };
      startRadius: number;
      endRadius: number;
      colorStops: (number | string)[];
    };

export interface FillLayerDescriptor {
  id: string;
  paint: PaintDescriptor;
}

export interface StrokeLayerDescriptor {
  id: string;
  paint: PaintDescriptor;
  width: number;
  dash: number[] | null;
  lineCap: StrokeCap;
  lineJoin: StrokeJoin;
}

export interface ShadowDescriptor {
  color: string;
  opacity: number;
  offsetX: number;
  offsetY: number;
  blur: number;
  /** Konva has no shadow spread; non-zero spreads are approximated. */
  spreadApproximated: boolean;
}

/**
 * A4 Effects v1: the full effect stack in declaration order (first entry =
 * topmost of its class), resolved to canvas units and CSS colors — the input
 * to the CanvasKit general effect pipeline (`drawDescriptors.generalEffectFilter`).
 * Colors are CSS; opacity is a 0..1 multiplier the renderer folds into alpha.
 * All lengths are already scaled into canvas units.
 */
export type EffectDescriptor =
  | {
      type: "drop_shadow";
      color: string;
      opacity: number;
      offsetX: number;
      offsetY: number;
      blur: number;
      spread: number;
    }
  | {
      type: "glow";
      color: string;
      opacity: number;
      blur: number;
      spread: number;
    }
  | {
      type: "layer_blur";
      radius: number;
    }
  | {
      type: "inner_shadow";
      color: string;
      opacity: number;
      offsetX: number;
      offsetY: number;
      blur: number;
      spread: number;
    };

export interface RenderPageDescriptor {
  id: string;
  name: string;
  width: number;
  height: number;
  unitScale: number;
  background: string;
}

export interface RenderNodeDescriptor {
  id: string;
  kind: string;
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
  opacity: number;
  fill: string;
  stroke: string | null;
  strokeWidth: number;
  /** Full paint stacks in painting order (fills bottom-to-top, then strokes). */
  fills: FillLayerDescriptor[];
  strokes: StrokeLayerDescriptor[];
  /** First effect entry (topmost shadow); Konva renders one shadow per shape. */
  shadow: ShadowDescriptor | null;
  /** Effects beyond the first are not previewed by Konva (approximation). */
  extraShadowCount: number;
  /**
   * Wave 3 C1: the full drop-shadow stack in paint order (topmost first).
   * `shadow`/`extraShadowCount` stay for the Konva path (one shadow/shape);
   * CanvasKit consumes `allShadows` and chains `MakeDropShadow`. Additive —
   * the Konva renderer ignores it.
   */
  allShadows: ShadowDescriptor[];
  /**
   * A4 Effects v1: the full effect stack (drop shadow, glow, layer blur, inner
   * shadow) in declaration order. `allShadows` stays the drop-shadow-only view
   * the Konva path and the pre-A4 CanvasKit shadow chain consume; the CanvasKit
   * renderer switches to the general pipeline over `effects` when any advanced
   * (glow / layer blur / inner shadow) entry is present.
   */
  effects: EffectDescriptor[];
  cornerRadius: number | [number, number, number, number];
  /**
   * Wave 3 C1: the node's outline as SVG path data in LOCAL space (origin
   * 0,0), following the SVG exporter's `<rect>`/`<ellipse>` contour
   * convention — rounded rects start at `(rx, 0)`, non-uniform corners are
   * squared (export does not support per-corner radii), ellipses start at
   * the rightmost point. CanvasKit strokes this for dashed strokes instead
   * of `drawRRect` (whose contour start differs from SVG's, shifting dash
   * phase). `null` for text/line/vector, which carry their own geometry.
   */
  contourPath: string | null;
  slotKeys: string[];
  text?: {
    content: string;
    fontFamily: string;
    fontSize: number;
    fontWeight: number;
    align: "left" | "center" | "right" | "justify";
    /** A7a: vertical placement within the box; always present ("top" default).
     * Consumed by {@link valignOffset} on both the CanvasKit and DOM legs. */
    valign: "top" | "center" | "bottom";
    lineHeight: number;
    letterSpacing: number;
    maxLines: number | null;
    wrap: "no_wrap" | "wrap";
    direction: "ltr" | "rtl" | "auto";
    /** A6a typography fields (defaults mirror the model). */
    textTransform: "none" | "uppercase" | "lowercase" | "title";
    underline: boolean;
    strikethrough: boolean;
    /** A7b: block italic (always present; false default). Unlike the decoration
     * flags it drives glyph geometry — the CanvasKit legs map it to a
     * `fontStyle.slant`, and the measurer keys on it. */
    italic: boolean;
    truncate: boolean;
    /** Extra vertical gap at each `\n` break, already scaled into canvas units. */
    paragraphSpacing: number;
    /** A6b: rich-text spans, present only when the node carries any. Offsets are
     * the raw model BYTE offsets into `content` (the painter relocates them onto
     * the normalized string); `fill` is already resolved to a CSS color (Solid
     * or Token), `null` = inherit the node fill. */
    spans?: TextSpanDescriptor[];
  };
  line?: {
    points: number[];
  };
  vector?: {
    pathData: string;
    sourceAssetId: string | null;
    assetLabel: string | null;
    assetKind: AssetKind | null;
    assetStatus: AssetStatus | null;
  };
  image?: {
    assetId: string;
    sourceAssetId: string | null;
    alt: string | null;
    assetLabel: string | null;
    assetKind: AssetKind | null;
    assetStatus: AssetStatus | null;
    /** Placement fit; null falls back to the exporter default (contain/meet). */
    fit: ImageFitMode | null;
    /** Normalized 0..1 focal point for cover/crop windows; null = centered. */
    focalPoint: { x: number; y: number } | null;
    /** Asset's natural width/height ratio (for cover/contain/focal math). */
    naturalAspectRatio: number | null;
  };
}

/** A6b: one rich-text span in render form. Offsets are the raw model BYTE
 * offsets into `content`; `fill` is resolved to a CSS color (or `null` to
 * inherit the node fill). Weight/decoration `null` inherit the node. */
export interface TextSpanDescriptor {
  start: number;
  end: number;
  fill: string | null;
  fontWeight: number | null;
  underline: boolean | null;
  strikethrough: boolean | null;
  /** A7b: override italic. `null` inherits the block; `false` de-italicizes the
   * run (OVERRIDE merge, not union) — the painter/measurer resolve
   * `span.italic ?? block.italic`, and `??` treats `null` as inherit. */
  italic: boolean | null;
}

export interface ParentComputedOrigin {
  x: number;
  y: number;
}

export function pageDescriptor(page: Page): RenderPageDescriptor {
  return {
    id: page.id,
    name: page.name,
    width: page.size.width * unitScale(page.size.unit),
    height: page.size.height * unitScale(page.size.unit),
    unitScale: unitScale(page.size.unit),
    background: paintFromFill(page.background[0]) ?? "#ffffff"
  };
}

export function nodeDescriptor(
  scene: Scene,
  node: Node,
  page: Page,
  parentComputedOrigin: ParentComputedOrigin | null = null
): RenderNodeDescriptor {
  const scale = unitScale(page.size.unit);
  const size = nodeSizeForRender(node, page);
  const position = nodePositionForRender(node, page, parentComputedOrigin, scene);
  const stroke = node.strokes[0] ? strokeDescriptor(node.strokes[0]) : null;
  const shadows = shadowDescriptors(node.effects ?? [], scale);
  // K1.5: kit-resolved corner radius / opacity when their tokens resolve;
  // otherwise the node's numeric values (the pre-existing behavior).
  const cornerToken = node.corner.token ? resolveTokenNumber(node.corner.token) : null;
  const opacityToken = node.opacity_token ? resolveTokenNumber(node.opacity_token) : null;
  const descriptor: RenderNodeDescriptor = {
    id: node.id,
    kind: node.kind.kind,
    x: position.x,
    y: position.y,
    width: size.width,
    height: size.height,
    rotation: node.transform.rotation,
    opacity: opacityToken ?? node.opacity,
    fill: paintFromFill(node.fills[0]) ?? defaultFillForNode(node),
    stroke: stroke?.color ?? null,
    strokeWidth: (stroke?.width ?? 0) * scale,
    fills: node.fills.map((fill) => fillLayerDescriptor(fill, size.width, size.height)),
    strokes: node.strokes.map((nodeStroke) =>
      strokeLayerDescriptor(nodeStroke, size.width, size.height, scale)
    ),
    shadow: shadows[0] ?? null,
    extraShadowCount: Math.max(0, shadows.length - 1),
    allShadows: shadows,
    effects: effectDescriptors(node.effects ?? [], scale),
    cornerRadius:
      cornerToken !== null
        ? [cornerToken * scale, cornerToken * scale, cornerToken * scale, cornerToken * scale]
        : [
            node.corner.top_left * scale,
            node.corner.top_right * scale,
            node.corner.bottom_right * scale,
            node.corner.bottom_left * scale
          ],
    contourPath: contourPathForNode(node, size.width, size.height, scale),
    slotKeys: slotKeysForNode(scene, node.id)
  };

  if (node.kind.kind === "text") {
    // K1.5: paint what the kit's type roles say, not the skeleton literals —
    // same resolution the measurement pass uses, so pixels match layout.
    const styled = resolvedTextFields(node.kind);
    descriptor.text = {
      content: node.kind.content,
      fontFamily: styled.fontFamily,
      fontSize: styled.fontSize * scale,
      fontWeight: styled.fontWeight,
      align: node.kind.align,
      valign: node.kind.valign ?? "top",
      lineHeight: styled.lineHeight,
      letterSpacing: styled.letterSpacing * scale,
      maxLines: node.kind.max_lines ?? null,
      wrap: node.kind.wrap ?? "no_wrap",
      direction: node.kind.direction ?? "ltr",
      textTransform: node.kind.text_transform ?? "none",
      underline: node.kind.underline ?? false,
      strikethrough: node.kind.strikethrough ?? false,
      italic: node.kind.italic ?? false,
      truncate: node.kind.truncate ?? false,
      paragraphSpacing: (node.kind.paragraph_spacing ?? 0) * scale
    };
    // A6b: resolve span fills to CSS here (Solid/Token → hex, mirroring the
    // engine's fill resolution); offsets stay the raw model byte offsets so the
    // painter can relocate them onto the normalized content.
    if (node.kind.spans && node.kind.spans.length > 0) {
      descriptor.text.spans = node.kind.spans.map((span) => ({
        start: span.start,
        end: span.end,
        fill: span.fill ? paintToCss(span.fill) : null,
        fontWeight: span.font_weight ?? null,
        underline: span.underline ?? null,
        strikethrough: span.strikethrough ?? null,
        italic: span.italic ?? null
      }));
    }
  }

  if (node.kind.kind === "line") {
    descriptor.line = {
      points: [0, 0, node.kind.x2 * scale, node.kind.y2 * scale]
    };
  }

  if (node.kind.kind === "vector") {
    const asset = node.source_asset_id ? scene.assets[node.source_asset_id] : null;
    descriptor.vector = {
      pathData: node.kind.path_data,
      sourceAssetId: node.source_asset_id ?? null,
      assetLabel: asset?.label ?? null,
      assetKind: asset?.kind ?? null,
      assetStatus: asset?.status ?? null
    };
  }

  if (node.kind.kind === "image") {
    const asset = scene.assets[node.kind.asset_id] ?? null;
    const placement = node.asset_placement ?? null;
    const raster = asset?.raster ?? null;
    const ratioCandidate =
      raster?.aspect_ratio ??
      (raster && raster.pixel_height > 0 ? raster.pixel_width / raster.pixel_height : null);
    const naturalAspectRatio =
      typeof ratioCandidate === "number" && Number.isFinite(ratioCandidate) && ratioCandidate > 0
        ? ratioCandidate
        : null;
    descriptor.image = {
      assetId: node.kind.asset_id,
      sourceAssetId: node.source_asset_id ?? null,
      alt: node.kind.alt ?? null,
      assetLabel: asset?.label ?? null,
      assetKind: asset?.kind ?? null,
      assetStatus: asset?.status ?? null,
      fit: placement?.fit ?? null,
      focalPoint: placement?.focal_point
        ? { x: placement.focal_point.x, y: placement.focal_point.y }
        : null,
      naturalAspectRatio
    };
  }

  return descriptor;
}

function slotKeysForNode(scene: Scene, nodeId: string): string[] {
  return Object.values(scene.slots)
    .filter((slot) => slot.bound_nodes.includes(nodeId))
    .map((slot) => slot.key)
    .sort((left, right) => left.localeCompare(right));
}

export function sceneUnitFromCanvas(value: number, page: Page): number {
  return roundForScene(value / unitScale(page.size.unit));
}

export function canvasFromSceneUnit(value: number, page: Page): number {
  return value * unitScale(page.size.unit);
}

export function sizeFromCanvas(width: number, height: number, page: Page): SizeSpec {
  return {
    width: {
      kind: "fixed",
      value: sceneUnitFromCanvas(width, page)
    },
    height: {
      kind: "fixed",
      value: sceneUnitFromCanvas(height, page)
    }
  };
}

/**
 * A7a: the shared clamped valign formula — THE single source both editor legs
 * (CanvasKit `drawDescriptors` fast/stacked/spanned + the Konva DOM leg) derive
 * their vertical offset from, byte-mirroring the engine's `valign_offset`
 * (`crates/lumen-core/src/scene.rs`): `max(box - content, 0) * factor`, factor
 * top=0 / center=0.5 / bottom=1. Slack is clamped at zero so an overflowing box
 * never paints above its top edge (valign degrades to a no-op).
 */
export function valignOffset(boxHeight: number, contentHeight: number, valign: VerticalAlign): number {
  const factor = valign === "center" ? 0.5 : valign === "bottom" ? 1 : 0;
  return Math.max(boxHeight - contentHeight, 0) * factor;
}

export function fixedSize(size: SizeSpec, scale = 1): { width: number; height: number } {
  return {
    width: dimensionToNumber(size.width) * scale,
    height: dimensionToNumber(size.height) * scale
  };
}

export function dimensionToNumber(dimension: SizeSpec["width"]): number {
  if (dimension.kind === "fixed") {
    return dimension.value;
  }
  return 0;
}

export function paintFromFill(fill: Fill | undefined): string | null {
  if (!fill) {
    return null;
  }
  return paintToCss(fill.paint);
}

export function paintToCss(paint: Paint): string {
  switch (paint.kind) {
    case "solid":
      return colorToCss(paint.color);
    case "linear_gradient":
      return paint.stops[0] ? colorToCss(paint.stops[0].color) : "#d8d1c3";
    case "radial_gradient":
      return paint.stops[0] ? colorToCss(paint.stops[0].color) : "#d8d1c3";
    case "token":
      return resolveTokenColor(tokenColorMap, paint.token) ?? tokenFallback(paint.token);
  }
}

export function colorToCss(color: Color): string {
  switch (color.kind) {
    case "hex":
      return normalizeHexForCss(color.value);
    case "oklch":
      // Hex, not an oklch() string: the CanvasKit paint path's parseColor
      // handles hex/rgb only — an oklch string silently erased the paint
      // (the C2 follow-up this closes). Same converter the token map uses,
      // so both paths match the engine's own oklch->hex resolution.
      return oklchToHexCss(color.l, color.c, color.h, color.alpha);
    case "token":
      return resolveTokenColor(tokenColorMap, color.token) ?? tokenFallback(color.token);
  }
}

function strokeDescriptor(stroke: Stroke): { color: string; width: number } {
  return {
    color: paintToCss(stroke.paint),
    width: resolvedStrokeWidth(stroke)
  };
}

/** K1.5: the stroke's kit width when its token resolves, else the literal. */
function resolvedStrokeWidth(stroke: Stroke): number {
  if (stroke.width_token) {
    const resolved = resolveTokenNumber(stroke.width_token);
    if (resolved !== null) {
      return resolved;
    }
  }
  return stroke.width;
}

export function fillLayerDescriptor(fill: Fill, width: number, height: number): FillLayerDescriptor {
  return {
    id: fill.id,
    paint: paintDescriptor(fill.paint, width, height)
  };
}

export function strokeLayerDescriptor(
  stroke: Stroke,
  width: number,
  height: number,
  scale: number
): StrokeLayerDescriptor {
  return {
    id: stroke.id,
    paint: paintDescriptor(stroke.paint, width, height),
    width: resolvedStrokeWidth(stroke) * scale,
    dash: stroke.dash?.length ? stroke.dash.map((value) => value * scale) : null,
    lineCap: stroke.cap ?? "butt",
    lineJoin: stroke.join ?? "miter"
  };
}

/**
 * Real gradient preview: the same stop list the SVG exporter emits, mapped
 * to Konva gradient geometry. Linear gradients rotate the unit vector about
 * the box origin (mirroring SVG's gradientTransform=rotate(angle) on the
 * default 0,0 -> 1,0 objectBoundingBox line); radial gradients fill from
 * the box center out to half the larger dimension.
 */
export function paintDescriptor(paint: Paint, width: number, height: number): PaintDescriptor {
  switch (paint.kind) {
    case "solid":
      return { kind: "solid", color: colorToCss(paint.color) };
    case "linear_gradient": {
      const radians = (paint.angle * Math.PI) / 180;
      return {
        kind: "linear_gradient",
        start: { x: 0, y: 0 },
        end: {
          x: roundForScene(Math.cos(radians) * width),
          y: roundForScene(Math.sin(radians) * height)
        },
        colorStops: paint.stops.flatMap((stop) => [stop.position, colorToCss(stop.color)])
      };
    }
    case "radial_gradient":
      return {
        kind: "radial_gradient",
        center: { x: width / 2, y: height / 2 },
        startRadius: 0,
        endRadius: Math.max(width, height) / 2,
        colorStops: paint.stops.flatMap((stop) => [stop.position, colorToCss(stop.color)])
      };
    case "token":
      return {
        kind: "solid",
        color: resolveTokenColor(tokenColorMap, paint.token) ?? tokenFallback(paint.token)
      };
  }
}

/**
 * Drop-shadow-only view of the effect stack (the Konva path renders one shadow
 * per shape; the pre-A4 CanvasKit shadow chain consumes the whole list). Glow,
 * layer blur, and inner shadow are NOT drop shadows and are filtered out here —
 * they ride `effectDescriptors` and the CanvasKit general pipeline instead.
 */
function shadowDescriptors(effects: Effect[], scale: number): ShadowDescriptor[] {
  const shadows: ShadowDescriptor[] = [];
  for (const effect of effects) {
    if (effect.kind.kind !== "drop_shadow") {
      continue;
    }
    shadows.push({
      color: colorToCss(effect.kind.color),
      opacity: effect.kind.opacity,
      offsetX: effect.kind.x * scale,
      offsetY: effect.kind.y * scale,
      blur: effect.kind.blur * scale,
      spreadApproximated: effect.kind.spread !== 0
    });
  }
  return shadows;
}

/**
 * A4: the full effect stack resolved into `EffectDescriptor`s in declaration
 * order — colors to CSS, geometry into canvas units. Mirrors the engine's
 * `EffectKind` variants one-to-one so the CanvasKit general pipeline can honor
 * the D1 stacking contract.
 */
function effectDescriptors(effects: Effect[], scale: number): EffectDescriptor[] {
  return effects.map((effect): EffectDescriptor => {
    const kind = effect.kind;
    switch (kind.kind) {
      case "drop_shadow":
        return {
          type: "drop_shadow",
          color: colorToCss(kind.color),
          opacity: kind.opacity,
          offsetX: kind.x * scale,
          offsetY: kind.y * scale,
          blur: kind.blur * scale,
          spread: kind.spread * scale
        };
      case "glow":
        return {
          type: "glow",
          color: colorToCss(kind.color),
          opacity: kind.opacity,
          blur: kind.blur * scale,
          spread: kind.spread * scale
        };
      case "layer_blur":
        return {
          type: "layer_blur",
          radius: kind.radius * scale
        };
      case "inner_shadow":
        return {
          type: "inner_shadow",
          color: colorToCss(kind.color),
          opacity: kind.opacity,
          offsetX: kind.x * scale,
          offsetY: kind.y * scale,
          blur: kind.blur * scale,
          spread: kind.spread * scale
        };
    }
  });
}

function defaultFillForNode(node: Node): string {
  if (node.kind.kind === "text" || node.kind.kind === "line") {
    return "#27231d";
  }
  if (node.kind.kind === "image") {
    return "#ddd7cc";
  }
  if (node.kind.kind === "frame" || node.kind.kind === "group" || node.kind.kind === "auto_layout") {
    return "transparent";
  }
  return "#f5f1e9";
}

export function nodeSizeForRender(node: Node, page: Page): { width: number; height: number } {
  const scale = unitScale(page.size.unit);
  if (node.computed) {
    return {
      width: node.computed.layout_bounds.width * scale,
      height: node.computed.layout_bounds.height * scale
    };
  }
  return fixedSize(node.size, scale);
}

export function nodePositionForRender(
  node: Node,
  page: Page,
  parentComputedOrigin: ParentComputedOrigin | null = null,
  scene: Scene | null = null
): { x: number; y: number } {
  const scale = unitScale(page.size.unit);
  if (node.computed) {
    const offsetX = parentComputedOrigin?.x ?? 0;
    const offsetY = parentComputedOrigin?.y ?? 0;
    return {
      x: (node.computed.layout_bounds.x - offsetX) * scale,
      y: (node.computed.layout_bounds.y - offsetY) * scale
    };
  }
  // Fallback for a node that has never been laid out. With the engine
  // relaying out on load, `computed` is effectively always present, so this
  // is a guard, not the normal path. For a layout-managed node (an
  // auto-layout child) `transform` is NOT its real position — flow owns it —
  // so falling back to `transform` would jump it to a meaningless spot.
  // Render it at its container origin (0,0 relative to the parent group)
  // instead: a stable, in-bounds default until layout runs. For all other
  // nodes the (parent-relative) transform is the correct authored position.
  if (scene && isNodeLayoutManaged(scene, node.id)) {
    return { x: 0, y: 0 };
  }
  return {
    x: node.transform.x * scale,
    y: node.transform.y * scale
  };
}

/**
 * SVG-equivalent outline for a node's box, in LOCAL space (origin 0,0), used
 * by the CanvasKit renderer to stroke dashed strokes with the same contour
 * start the SVG export uses. Mirrors the exporter: uniform corner radius →
 * rounded rect starting at `(r, 0)`; non-uniform or zero → plain rect (export
 * squares per-corner radii); ellipse → ellipse path from the rightmost point.
 * `null` for kinds that carry their own geometry (text/line/vector).
 */
export function contourPathForNode(
  node: Node,
  width: number,
  height: number,
  scale: number
): string | null {
  switch (node.kind.kind) {
    case "ellipse":
      return ellipseContourPath(width, height);
    case "rect":
    case "frame":
    case "group":
    case "auto_layout":
    case "image":
      return rectBodyContourPath(node, width, height, scale);
    default:
      return null;
  }
}

/**
 * Rect-body outline honoring per-corner radii (A4 / D3). A resolved radius
 * token or four equal corners take the uniform arc path; mixed corners take a
 * per-corner arc `<path>` (CSS overlap-clamped), mirroring the SVG exporter's
 * `rounded_rect_path` — so the canvas matches export AND a zero-radius corner
 * stays square. Shared by body geometry and the image clip (both read
 * `contourPath`).
 */
function rectBodyContourPath(node: Node, width: number, height: number, scale: number): string {
  // K1.5: a resolved radius token IS uniform by definition.
  if (node.corner.token) {
    const resolved = resolveTokenNumber(node.corner.token);
    if (resolved !== null) {
      return rectContourPath(width, height, resolved * scale);
    }
  }
  const { top_left, top_right, bottom_right, bottom_left } = node.corner;
  if (top_left === top_right && top_left === bottom_right && top_left === bottom_left) {
    return rectContourPath(width, height, top_left * scale);
  }
  const clamped = clampedCorners(
    [top_left * scale, top_right * scale, bottom_right * scale, bottom_left * scale],
    width,
    height
  );
  return perCornerContourPath(width, height, clamped);
}

/**
 * CSS overlap-algorithm clamp (mirrors the SVG exporter's `clamped_corners`):
 * scale every radius down by the single factor that keeps each pair of adjacent
 * radii within their shared side length. Returns `[tl, tr, br, bl]`.
 */
function clampedCorners(
  radii: [number, number, number, number],
  width: number,
  height: number
): [number, number, number, number] {
  const [tl, tr, br, bl] = radii.map((r) => Math.max(0, r)) as [number, number, number, number];
  const ratios: [number, number][] = [
    [width, tl + tr], // top
    [height, tr + br], // right
    [width, br + bl], // bottom
    [height, tl + bl] // left
  ];
  let factor = 1;
  for (const [side, sum] of ratios) {
    if (sum > 0) {
      factor = Math.min(factor, side / sum);
    }
  }
  if (factor < 1) {
    return [tl * factor, tr * factor, br * factor, bl * factor];
  }
  return [tl, tr, br, bl];
}

/**
 * Per-corner rounded-rect `<path>` `d`, clockwise from the top-left corner,
 * byte-mirroring the SVG exporter's `rounded_rect_path`. A zero-radius corner
 * degenerates to a lineto per SVG arc semantics.
 */
function perCornerContourPath(
  width: number,
  height: number,
  radii: [number, number, number, number]
): string {
  const [tl, tr, br, bl] = radii;
  const n = (value: number) => roundForScene(value);
  return (
    `M${n(tl)} 0` +
    `H${n(width - tr)}` +
    `A${n(tr)} ${n(tr)} 0 0 1 ${n(width)} ${n(tr)}` +
    `V${n(height - br)}` +
    `A${n(br)} ${n(br)} 0 0 1 ${n(width - br)} ${n(height)}` +
    `H${n(bl)}` +
    `A${n(bl)} ${n(bl)} 0 0 1 0 ${n(height - bl)}` +
    `V${n(tl)}` +
    `A${n(tl)} ${n(tl)} 0 0 1 ${n(tl)} 0Z`
  );
}

function rectContourPath(width: number, height: number, radius: number): string {
  const n = (value: number) => roundForScene(value);
  const r = Math.min(radius, width / 2, height / 2);
  if (r <= 0) {
    return `M0 0H${n(width)}V${n(height)}H0Z`;
  }
  return (
    `M${n(r)} 0` +
    `H${n(width - r)}` +
    `A${n(r)} ${n(r)} 0 0 1 ${n(width)} ${n(r)}` +
    `V${n(height - r)}` +
    `A${n(r)} ${n(r)} 0 0 1 ${n(width - r)} ${n(height)}` +
    `H${n(r)}` +
    `A${n(r)} ${n(r)} 0 0 1 0 ${n(height - r)}` +
    `V${n(r)}` +
    `A${n(r)} ${n(r)} 0 0 1 ${n(r)} 0Z`
  );
}

function ellipseContourPath(width: number, height: number): string {
  const n = (value: number) => roundForScene(value);
  const rx = width / 2;
  const ry = height / 2;
  return (
    `M${n(width)} ${n(ry)}` +
    `A${n(rx)} ${n(ry)} 0 0 1 0 ${n(ry)}` +
    `A${n(rx)} ${n(ry)} 0 0 1 ${n(width)} ${n(ry)}Z`
  );
}

function normalizeHexForCss(value: string): string {
  const hex = value.trim();
  if (/^#[0-9a-fA-F]{8}$/.test(hex)) {
    const red = parseInt(hex.slice(1, 3), 16);
    const green = parseInt(hex.slice(3, 5), 16);
    const blue = parseInt(hex.slice(5, 7), 16);
    const alpha = parseInt(hex.slice(7, 9), 16) / 255;
    return `rgba(${red}, ${green}, ${blue}, ${Number(alpha.toFixed(3))})`;
  }
  return hex;
}

/**
 * Real token color values for the current document's effective brand kit
 * (attached kit, or the platform default when none is attached), set from
 * exactly one place: an `EditorApp` effect keyed on
 * `[scene.meta.brand_kit, availableBrandKits]` (see `EditorApp.tsx`). A
 * module-level registry — rather than threading a map through every
 * `nodeDescriptor`/`pageDescriptor` caller — because those descriptors are
 * built from ~10 call sites across the Konva (`CanvasSurface`, `SceneNode`)
 * and CanvasKit (`CanvasKitCanvas`) render paths plus `EditorChrome`,
 * `exportParity`, and `workspaceLayout`; none of them share a context/props
 * chain today, so plumbing a map through all of them would touch every one
 * of those signatures for a value that's document-scoped, not
 * render-call-scoped. Both canvas backends and the compare-pane/preview
 * instances read the same module-level map, so they resolve identically.
 *
 * Unset (tests, SSR, a document with no available kits yet) leaves the map
 * empty, which makes every token lookup miss and fall through to
 * `tokenFallback` below — the pre-existing heuristic behavior, preserved as
 * the safe default.
 */
let tokenColorMap: TokenColorMap = {};
// K1.5: typography roles + number tokens from the same kit fetch, so the
// client measure/render path speaks the kit's type before server preflight
// resolves it into literals (the LUMV0903/0810 ghost-killer).
let tokenTextStyles: Record<string, TokenTextStyle> = {};
let tokenNumbers: Record<string, number> = {};

/**
 * K0.5 reactivity: the map is set by an async fetch that usually resolves
 * AFTER the canvas first paints, and a module-level assignment re-renders
 * nothing — the live K0 proof showed a freshly loaded document staying on
 * heuristic colors forever because no scene change ever followed the fetch.
 * `setTokenColorMap` therefore bumps a generation and notifies subscribers;
 * canvas components read the generation via `useSyncExternalStore` and key
 * their descriptor memos on it, so kit values repaint the moment they land.
 */
let tokenColorsGeneration = 0;
const tokenColorListeners = new Set<() => void>();

/** Sets the token color map consulted by the token paint cases in
 * `paintToCss`/`colorToCss`/`paintDescriptor`, and notifies subscribers.
 * Colors-only legacy/test entry point — it RESETS the typography/number
 * maps so test isolation stays one call. Product code uses
 * `setKitTokenMaps`. */
export function setTokenColorMap(map: TokenColorMap): void {
  setKitTokenMaps({ colors: map, typography: {}, numbers: {} });
}

/** K1.5: install all three kit maps (colors, typography roles, numbers) and
 * notify subscribers — one generation covers paint, type, and radii. */
export function setKitTokenMaps(maps: KitTokenMaps): void {
  tokenColorMap = maps.colors;
  tokenTextStyles = maps.typography;
  tokenNumbers = maps.numbers;
  tokenColorsGeneration += 1;
  for (const listener of tokenColorListeners) {
    listener();
  }
}

/** K3: kit font faces landed in the CanvasKit provider AFTER first paint —
 * same generation bump as a token-map install, so text measurement and
 * descriptor memos rebuild against the newly registered faces. */
export function notifyKitFontsChanged(): void {
  tokenColorsGeneration += 1;
  for (const listener of tokenColorListeners) {
    listener();
  }
}

/** Subscribe to token-map replacements (useSyncExternalStore contract). */
export function subscribeTokenColors(listener: () => void): () => void {
  tokenColorListeners.add(listener);
  return () => {
    tokenColorListeners.delete(listener);
  };
}

/** Monotonic generation of the current token map (useSyncExternalStore
 * snapshot; also the memo key that invalidates descriptor trees). */
export function tokenColorsGenerationSnapshot(): number {
  return tokenColorsGeneration;
}

/** Whether a token paint will resolve to a real kit value on the canvas —
 * i.e. the render is NOT on the string-heuristic fallback for this token.
 * `renderDiagnostics` consults this so EDITOR_RENDER_TOKEN_FALLBACK is only
 * reported when the fallback is actually in use. */
export function tokenPaintResolves(token: string): boolean {
  return resolveTokenColor(tokenColorMap, token) !== null;
}

function stripTokenPrefix(token: string): string {
  return token.startsWith("$") ? token.slice(1) : token;
}

/** K1.5: whether a `style($type.role)` resolves from the kit's typography. */
export function tokenTextStyleResolves(token: string): boolean {
  return tokenTextStyles[stripTokenPrefix(token)] !== undefined;
}

/** K1.5: a number token's kit value (radius/stroke-width/opacity/size-step),
 * or null when the map misses. */
export function resolveTokenNumber(token: string): number | null {
  return tokenNumbers[stripTokenPrefix(token)] ?? null;
}

/** A manual typography edit must not bake unresolved skeleton values. Always
 * use the selected document's maps here, never the active canvas's globals. */
export function textTypographyResolves(
  text: Parameters<typeof resolvedTextFields>[0],
  maps?: Pick<KitTokenMaps, "typography" | "numbers"> | null,
): boolean {
  let family = text.font_family;
  if (text.style_token) {
    const role = stripTokenPrefix(text.style_token);
    if (!maps || !Object.hasOwn(maps.typography, role)) return false;
    family = maps.typography[role].fontFamily ?? family;
  }
  if (namesTokenRef(family)) return false;
  return [text.font_size_token, text.line_height_token, text.letter_spacing_token]
    .every((token) => !token || (maps != null && Object.hasOwn(maps.numbers, stripTokenPrefix(token))
      && Number.isFinite(maps.numbers[stripTokenPrefix(token)])));
}

/**
 * K1.5: a text node's EFFECTIVE fields — the kit style_token's values (with
 * a size-token override) over the node's literals, mirroring the
 * engine's resolve_text_style precedence. When a token is present but not
 * yet resolvable client-side, the literal is kept — the pre-existing
 * skeleton behavior, and honest about what the canvas will show.
 */
export function resolvedTextFields(text: {
  font_family: string;
  font_size: number;
  font_weight: number;
  line_height?: number | null;
  letter_spacing?: number | null;
  style_token?: string | null;
  font_size_token?: string | null;
  line_height_token?: string | null;
  letter_spacing_token?: string | null;
}, maps: Pick<KitTokenMaps, "typography" | "numbers"> = {
  typography: tokenTextStyles, numbers: tokenNumbers,
}): {
  fontFamily: string;
  fontSize: number;
  fontWeight: number;
  lineHeight: number;
  letterSpacing: number;
} {
  const style = text.style_token ? maps.typography[stripTokenPrefix(text.style_token)] : undefined;
  const number = (token: string) => maps.numbers[stripTokenPrefix(token)] ?? null;
  const sizeOverride = text.font_size_token ? number(text.font_size_token) : null;
  const lineHeightOverride = text.line_height_token
    ? number(text.line_height_token)
    : null;
  const letterSpacingOverride = text.letter_spacing_token
    ? number(text.letter_spacing_token)
    : null;
  return {
    fontFamily: style?.fontFamily ?? text.font_family,
    fontSize: sizeOverride ?? style?.fontSize ?? text.font_size,
    fontWeight: style?.fontWeight ?? text.font_weight,
    // Core resolves leading/tracking first, then the role, then the size token.
    lineHeight: style?.lineHeight ?? lineHeightOverride ?? text.line_height ?? 1.2,
    letterSpacing: style?.letterSpacing ?? letterSpacingOverride ?? text.letter_spacing ?? 0
  };
}

/** The CSS color a token swatch should show — EXACTLY what the canvas will
 * paint for that token: the kit-resolved value when the map has it, else the
 * same heuristic fallback the paint path uses. One resolution path for chips,
 * previews, and canvas. */
export function tokenSwatchCss(token: string): string {
  return resolveTokenColor(tokenColorMap, token) ?? tokenFallback(token);
}

function tokenFallback(token: string): string {
  if (token.includes("text")) {
    return "#27231d";
  }
  if (token.includes("surface")) {
    return "#f8f4ec";
  }
  if (token.includes("accent") || token.includes("primary")) {
    return "#256c70";
  }
  return "#b7aa96";
}

function unitScale(unit: Unit): number {
  switch (unit) {
    case "pt":
    case "px":
      return 1;
    case "mm":
      return 96 / 25.4;
    case "in":
      return 96;
  }
}

function roundForScene(value: number): number {
  return Math.round(value * 1000) / 1000;
}
