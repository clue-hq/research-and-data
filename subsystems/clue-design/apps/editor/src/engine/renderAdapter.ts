import type {
  AssetKind,
  AssetStatus,
  Color,
  Effect,
  Fill,
  Node,
  Page,
  Paint,
  Scene,
  SizeSpec,
  Stroke,
  StrokeCap,
  StrokeJoin,
  Unit
} from "./contracts";

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
  cornerRadius: number | [number, number, number, number];
  slotKeys: string[];
  text?: {
    content: string;
    fontFamily: string;
    fontSize: number;
    fontWeight: number;
    align: "left" | "center" | "right" | "justify";
    lineHeight: number;
    letterSpacing: number;
    maxLines: number | null;
    wrap: "no_wrap" | "wrap";
    direction: "ltr" | "rtl" | "auto";
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
  };
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
  const position = nodePositionForRender(node, page, parentComputedOrigin);
  const stroke = node.strokes[0] ? strokeDescriptor(node.strokes[0]) : null;
  const shadows = shadowDescriptors(node.effects ?? [], scale);
  const descriptor: RenderNodeDescriptor = {
    id: node.id,
    kind: node.kind.kind,
    x: position.x,
    y: position.y,
    width: size.width,
    height: size.height,
    rotation: node.transform.rotation,
    opacity: node.opacity,
    fill: paintFromFill(node.fills[0]) ?? defaultFillForNode(node),
    stroke: stroke?.color ?? null,
    strokeWidth: (stroke?.width ?? 0) * scale,
    fills: node.fills.map((fill) => fillLayerDescriptor(fill, size.width, size.height)),
    strokes: node.strokes.map((nodeStroke) =>
      strokeLayerDescriptor(nodeStroke, size.width, size.height, scale)
    ),
    shadow: shadows[0] ?? null,
    extraShadowCount: Math.max(0, shadows.length - 1),
    cornerRadius: [
      node.corner.top_left * scale,
      node.corner.top_right * scale,
      node.corner.bottom_right * scale,
      node.corner.bottom_left * scale
    ],
    slotKeys: slotKeysForNode(scene, node.id)
  };

  if (node.kind.kind === "text") {
    descriptor.text = {
      content: node.kind.content,
      fontFamily: node.kind.font_family,
      fontSize: node.kind.font_size * scale,
      fontWeight: node.kind.font_weight,
      align: node.kind.align,
      lineHeight: node.kind.line_height ?? 1.2,
      letterSpacing: (node.kind.letter_spacing ?? 0) * scale,
      maxLines: node.kind.max_lines ?? null,
      wrap: node.kind.wrap ?? "no_wrap",
      direction: node.kind.direction ?? "ltr"
    };
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
    descriptor.image = {
      assetId: node.kind.asset_id,
      sourceAssetId: node.source_asset_id ?? null,
      alt: node.kind.alt ?? null,
      assetLabel: asset?.label ?? null,
      assetKind: asset?.kind ?? null,
      assetStatus: asset?.status ?? null
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
      return tokenFallback(paint.token);
  }
}

export function colorToCss(color: Color): string {
  switch (color.kind) {
    case "hex":
      return normalizeHexForCss(color.value);
    case "oklch":
      return `oklch(${color.l} ${color.c} ${color.h} / ${color.alpha})`;
    case "token":
      return tokenFallback(color.token);
  }
}

function strokeDescriptor(stroke: Stroke): { color: string; width: number } {
  return {
    color: paintToCss(stroke.paint),
    width: stroke.width
  };
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
    width: stroke.width * scale,
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
      return { kind: "solid", color: tokenFallback(paint.token) };
  }
}

/** Konva fill props for a paint layer (solid, linear, or radial gradient). */
export function konvaFillProps(paint: PaintDescriptor): Record<string, unknown> {
  switch (paint.kind) {
    case "solid":
      return { fill: paint.color };
    case "linear_gradient":
      return {
        fillLinearGradientStartPoint: paint.start,
        fillLinearGradientEndPoint: paint.end,
        fillLinearGradientColorStops: paint.colorStops
      };
    case "radial_gradient":
      return {
        fillRadialGradientStartPoint: paint.center,
        fillRadialGradientEndPoint: paint.center,
        fillRadialGradientStartRadius: paint.startRadius,
        fillRadialGradientEndRadius: paint.endRadius,
        fillRadialGradientColorStops: paint.colorStops
      };
  }
}

/**
 * Konva stroke props for a stroke layer. Konva has no radial stroke
 * gradient; it falls back to the first stop color.
 */
export function konvaStrokeProps(layer: StrokeLayerDescriptor): Record<string, unknown> {
  const base: Record<string, unknown> = {
    strokeWidth: layer.width,
    lineCap: layer.lineCap,
    lineJoin: layer.lineJoin,
    ...(layer.dash ? { dash: layer.dash } : {})
  };
  switch (layer.paint.kind) {
    case "solid":
      return { ...base, stroke: layer.paint.color };
    case "linear_gradient":
      return {
        ...base,
        strokeLinearGradientStartPoint: layer.paint.start,
        strokeLinearGradientEndPoint: layer.paint.end,
        strokeLinearGradientColorStops: layer.paint.colorStops
      };
    case "radial_gradient":
      return {
        ...base,
        stroke: typeof layer.paint.colorStops[1] === "string" ? layer.paint.colorStops[1] : "#000000"
      };
  }
}

/** Konva shadow props for the node's topmost shadow. */
export function konvaShadowProps(shadow: ShadowDescriptor | null): Record<string, unknown> {
  if (!shadow) {
    return {};
  }
  return {
    shadowEnabled: true,
    shadowColor: shadow.color,
    shadowOpacity: shadow.opacity,
    shadowOffsetX: shadow.offsetX,
    shadowOffsetY: shadow.offsetY,
    shadowBlur: shadow.blur
  };
}

function shadowDescriptors(effects: Effect[], scale: number): ShadowDescriptor[] {
  return effects.map((effect) => ({
    color: colorToCss(effect.kind.color),
    opacity: effect.kind.opacity,
    offsetX: effect.kind.x * scale,
    offsetY: effect.kind.y * scale,
    blur: effect.kind.blur * scale,
    spreadApproximated: effect.kind.spread !== 0
  }));
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
  parentComputedOrigin: ParentComputedOrigin | null = null
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
  return {
    x: node.transform.x * scale,
    y: node.transform.y * scale
  };
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
