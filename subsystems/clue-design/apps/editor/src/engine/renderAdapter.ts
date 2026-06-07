import type {
  Color,
  Fill,
  Node,
  Page,
  Paint,
  Scene,
  SizeSpec,
  Stroke,
  Unit
} from "./contracts";

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
  cornerRadius: number | [number, number, number, number];
  text?: {
    content: string;
    fontFamily: string;
    fontSize: number;
    fontWeight: number;
    align: "left" | "center" | "right" | "justify";
  };
  line?: {
    points: number[];
  };
  vector?: {
    pathData: string;
  };
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

export function nodeDescriptor(scene: Scene, node: Node, page: Page): RenderNodeDescriptor {
  const scale = unitScale(page.size.unit);
  const size = nodeSizeForRender(node, page);
  const stroke = node.strokes[0] ? strokeDescriptor(node.strokes[0]) : null;
  const descriptor: RenderNodeDescriptor = {
    id: node.id,
    kind: node.kind.kind,
    x: node.transform.x * scale,
    y: node.transform.y * scale,
    width: size.width,
    height: size.height,
    rotation: node.transform.rotation,
    opacity: node.opacity,
    fill: paintFromFill(node.fills[0]) ?? defaultFillForNode(node),
    stroke: stroke?.color ?? null,
    strokeWidth: (stroke?.width ?? 0) * scale,
    cornerRadius: [
      node.corner.top_left * scale,
      node.corner.top_right * scale,
      node.corner.bottom_right * scale,
      node.corner.bottom_left * scale
    ]
  };

  if (node.kind.kind === "text") {
    descriptor.text = {
      content: node.kind.content,
      fontFamily: node.kind.font_family,
      fontSize: node.kind.font_size * scale,
      fontWeight: node.kind.font_weight,
      align: node.kind.align
    };
  }

  if (node.kind.kind === "line") {
    descriptor.line = {
      points: [0, 0, node.kind.x2 * scale, node.kind.y2 * scale]
    };
  }

  if (node.kind.kind === "vector") {
    descriptor.vector = {
      pathData: node.kind.path_data
    };
  }

  return descriptor;
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

function normalizeHexForCss(value: string): string {
  const hex = value.trim();
  if (/^#[0-9a-fA-F]{8}$/.test(hex)) {
    const alpha = parseInt(hex.slice(1, 3), 16) / 255;
    const red = parseInt(hex.slice(3, 5), 16);
    const green = parseInt(hex.slice(5, 7), 16);
    const blue = parseInt(hex.slice(7, 9), 16);
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
