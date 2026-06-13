import type { Canvas, CanvasKit, FontMgr } from "canvaskit-wasm";
import type { RenderNodeDescriptor, RenderPageDescriptor } from "../renderAdapter";

/**
 * Wave 3 C2: the descriptor→CanvasKit interpreter.
 *
 * Productizes the spike's `drawNode` (which hit 0.003% parity vs the canonical
 * Skia export), with two improvements from C1: it strokes AND fills the
 * descriptor's `contourPath` (the SVG-exporter-faithful outline — uniform
 * corners rounded from (r,0), non-uniform squared, ellipses as ellipses) so
 * fill and stroke both match export, and it chains the FULL `allShadows`
 * stack. Paint order mirrors the exporter: fills bottom-to-top, then strokes.
 * Node rotation (about the top-left origin) and opacity (a group layer over
 * body + children) are honored.
 *
 * Text (SkParagraph) is Wave 3 C4; C2 draws every non-text node. Images draw
 * as their placeholder fill (no asset bytes in the descriptor yet). Skia
 * objects are released immediately (RAII-style) so long editor sessions do
 * not leak the wasm heap.
 */

export interface DrawNode {
  descriptor: RenderNodeDescriptor;
  children: DrawNode[];
}

/** Draw a page background plus its node tree onto an already-transformed
 * canvas (the stage applies devicePixelRatio + zoom/pan before calling). */
export function drawDescriptorTree(
  ck: CanvasKit,
  canvas: Canvas,
  page: RenderPageDescriptor,
  nodes: DrawNode[],
  fontMgr: FontMgr | null
): void {
  const bg = parseColor(ck, page.background);
  canvas.clear(bg ?? ck.WHITE);
  for (const node of nodes) {
    drawNode(ck, canvas, node, fontMgr);
  }
}

function drawNode(ck: CanvasKit, canvas: Canvas, node: DrawNode, fontMgr: FontMgr | null): void {
  const d = node.descriptor;
  canvas.save();
  canvas.translate(d.x, d.y);
  if (d.rotation) {
    canvas.rotate(d.rotation, 0, 0);
  }

  // Group opacity wraps the body AND children (matching the Konva group).
  const opacityLayer = d.opacity < 1;
  if (opacityLayer) {
    const layerPaint = new ck.Paint();
    layerPaint.setAlphaf(d.opacity);
    canvas.saveLayer(layerPaint);
    layerPaint.delete();
  }

  // The shadow stack applies to this node's own body only.
  const filter = shadowFilter(ck, d.allShadows);
  if (filter) {
    const layerPaint = new ck.Paint();
    layerPaint.setImageFilter(filter);
    canvas.saveLayer(layerPaint);
    layerPaint.delete();
    filter.delete();
  }

  drawBody(ck, canvas, d, fontMgr);

  if (filter) {
    canvas.restore();
  }

  for (const child of node.children) {
    drawNode(ck, canvas, child, fontMgr);
  }

  if (opacityLayer) {
    canvas.restore();
  }
  canvas.restore();
}

function drawBody(
  ck: CanvasKit,
  canvas: Canvas,
  d: RenderNodeDescriptor,
  fontMgr: FontMgr | null
): void {
  if (d.kind === "line" && d.line) {
    drawLine(ck, canvas, d);
    return;
  }
  if (d.kind === "vector" && d.vector) {
    drawShapedPath(ck, canvas, d, d.vector.pathData);
    return;
  }
  if (d.kind === "text") {
    drawText(ck, canvas, d, fontMgr);
    return;
  }
  if (d.contourPath) {
    drawShapedPath(ck, canvas, d, d.contourPath);
  }
}

/**
 * Wave 3 C4: SkParagraph text. Using the same Inter bytes the server uses
 * makes line breaks and widths bit-faithful to the export (the heuristic
 * diverged on caps/digits/hyphens). Wraps at the node width when wrap is on;
 * otherwise lays out unbounded. The measurement-provider that feeds these
 * metrics back into the engine's layout (closing the E3 caveat) is the
 * remaining C4 piece. With no font registered, text is skipped.
 */
function drawText(ck: CanvasKit, canvas: Canvas, d: RenderNodeDescriptor, fontMgr: FontMgr | null): void {
  if (!fontMgr || !d.text) {
    return;
  }
  const color = parseColor(ck, d.fill) ?? ck.BLACK;
  const style = new ck.ParagraphStyle({
    textStyle: {
      color,
      fontFamilies: [d.text.fontFamily],
      fontSize: d.text.fontSize,
      fontStyle: { weight: fontWeight(ck, d.text.fontWeight) },
      heightMultiplier: d.text.lineHeight,
      letterSpacing: d.text.letterSpacing
    },
    textAlign: textAlign(ck, d.text.align),
    maxLines: d.text.maxLines ?? undefined
  });
  const builder = ck.ParagraphBuilder.Make(style, fontMgr);
  builder.addText(d.text.content);
  const paragraph = builder.build();
  // No-wrap text lays out on one line; give it room so it does not wrap.
  paragraph.layout(d.text.wrap === "wrap" ? d.width : Number.MAX_SAFE_INTEGER);
  canvas.drawParagraph(paragraph, 0, 0);
  paragraph.delete();
  builder.delete();
}

function textAlign(ck: CanvasKit, align: "left" | "center" | "right" | "justify") {
  if (align === "center") return ck.TextAlign.Center;
  if (align === "right") return ck.TextAlign.Right;
  if (align === "justify") return ck.TextAlign.Justify;
  return ck.TextAlign.Left;
}

function fontWeight(ck: CanvasKit, weight: number) {
  if (weight >= 700) return ck.FontWeight.Bold;
  if (weight >= 600) return ck.FontWeight.SemiBold;
  if (weight >= 500) return ck.FontWeight.Medium;
  return ck.FontWeight.Normal;
}

/** Fill + stroke a closed shape path (rect/ellipse/image box, or a vector). */
function drawShapedPath(ck: CanvasKit, canvas: Canvas, d: RenderNodeDescriptor, svg: string): void {
  const path = ck.Path.MakeFromSVGString(svg);
  if (!path) {
    return;
  }

  const fills = d.fills.length > 0 ? d.fills.map((layer) => layer.paint) : implicitFill(d);
  for (const fillPaint of fills) {
    const paint = new ck.Paint();
    paint.setAntiAlias(true);
    paint.setStyle(ck.PaintStyle.Fill);
    if (applyPaint(ck, paint, fillPaint)) {
      canvas.drawPath(path, paint);
    }
    paint.delete();
  }

  for (const strokeLayer of d.strokes) {
    const paint = new ck.Paint();
    paint.setAntiAlias(true);
    paint.setStyle(ck.PaintStyle.Stroke);
    paint.setStrokeWidth(strokeLayer.width);
    paint.setStrokeCap(strokeCap(ck, strokeLayer.lineCap));
    paint.setStrokeJoin(strokeJoin(ck, strokeLayer.lineJoin));
    if (strokeLayer.dash) {
      const dash = ck.PathEffect.MakeDash(strokeLayer.dash, 0);
      if (dash) {
        paint.setPathEffect(dash);
        dash.delete();
      }
    }
    if (applyPaint(ck, paint, strokeLayer.paint)) {
      canvas.drawPath(path, paint);
    }
    paint.delete();
  }

  path.delete();
}

function drawLine(ck: CanvasKit, canvas: Canvas, d: RenderNodeDescriptor): void {
  if (!d.line) {
    return;
  }
  const [x1, y1, x2, y2] = d.line.points;
  const paint = new ck.Paint();
  paint.setAntiAlias(true);
  paint.setStyle(ck.PaintStyle.Stroke);
  paint.setStrokeWidth(Math.max(1, d.strokeWidth || 1));
  const color = parseColor(ck, d.stroke ?? d.fill);
  if (color) {
    paint.setColor(color);
    canvas.drawLine(x1, y1, x2, y2, paint);
  }
  paint.delete();
}

/** A descriptor with no fill layers still paints its resolved `fill` unless it
 * is transparent (frames/groups). Mirrors the Konva default-fill behavior. */
function implicitFill(d: RenderNodeDescriptor): RenderNodeDescriptor["fills"][number]["paint"][] {
  if (!d.fill || d.fill === "transparent") {
    return [];
  }
  return [{ kind: "solid", color: d.fill }];
}

function applyPaint(
  ck: CanvasKit,
  paint: import("canvaskit-wasm").Paint,
  desc: RenderNodeDescriptor["fills"][number]["paint"]
): boolean {
  if (desc.kind === "solid") {
    const color = parseColor(ck, desc.color);
    if (!color) {
      return false;
    }
    paint.setColor(color);
    return true;
  }
  const shader = gradientShader(ck, desc);
  if (!shader) {
    return false;
  }
  paint.setShader(shader);
  shader.delete();
  return true;
}

function gradientShader(
  ck: CanvasKit,
  desc: Extract<RenderNodeDescriptor["fills"][number]["paint"], { kind: "linear_gradient" | "radial_gradient" }>
) {
  const positions: number[] = [];
  const colors: Float32Array[] = [];
  for (let i = 0; i < desc.colorStops.length; i += 2) {
    const pos = desc.colorStops[i];
    const css = desc.colorStops[i + 1];
    if (typeof pos === "number" && typeof css === "string") {
      const color = parseColor(ck, css);
      if (color) {
        positions.push(pos);
        colors.push(color);
      }
    }
  }
  if (colors.length === 0) {
    return null;
  }
  if (desc.kind === "linear_gradient") {
    return ck.Shader.MakeLinearGradient(
      [desc.start.x, desc.start.y],
      [desc.end.x, desc.end.y],
      colors,
      positions,
      ck.TileMode.Clamp
    );
  }
  return ck.Shader.MakeRadialGradient(
    [desc.center.x, desc.center.y],
    desc.endRadius,
    colors,
    positions,
    ck.TileMode.Clamp
  );
}

/** Chained drop shadows — first entry topmost — mirroring chained feDropShadow;
 * Skia sigma = SVG stdDeviation = blur/2. Caller deletes the returned filter. */
function shadowFilter(ck: CanvasKit, shadows: RenderNodeDescriptor["allShadows"]) {
  let filter: import("canvaskit-wasm").ImageFilter | null = null;
  for (const shadow of shadows) {
    const sigma = shadow.blur / 2;
    const color = parseColor(ck, shadow.color, shadow.opacity);
    if (!color) {
      continue;
    }
    filter = ck.ImageFilter.MakeDropShadow(shadow.offsetX, shadow.offsetY, sigma, sigma, color, filter);
  }
  return filter;
}

function strokeCap(ck: CanvasKit, cap: string) {
  if (cap === "round") return ck.StrokeCap.Round;
  if (cap === "square") return ck.StrokeCap.Square;
  return ck.StrokeCap.Butt;
}

function strokeJoin(ck: CanvasKit, join: string) {
  if (join === "round") return ck.StrokeJoin.Round;
  if (join === "bevel") return ck.StrokeJoin.Bevel;
  return ck.StrokeJoin.Miter;
}

/** Parse a CSS color (the only forms the render adapter emits: #rgb, #rrggbb,
 * #rrggbbaa, rgba(...)) to a CanvasKit Color4f, multiplying by `opacity`.
 * Returns null for `transparent` / unparseable input (the caller skips it). */
export function parseColor(ck: CanvasKit, css: string, opacity = 1): Float32Array | null {
  if (!css || css === "transparent" || css === "none") {
    return null;
  }
  if (css.startsWith("#")) {
    const hex = css.slice(1);
    const full = hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex;
    if (full.length !== 6 && full.length !== 8) {
      return null;
    }
    const r = parseInt(full.slice(0, 2), 16);
    const g = parseInt(full.slice(2, 4), 16);
    const b = parseInt(full.slice(4, 6), 16);
    const a = full.length === 8 ? parseInt(full.slice(6, 8), 16) / 255 : 1;
    return ck.Color4f(r / 255, g / 255, b / 255, a * opacity);
  }
  const rgba = css.match(/rgba?\(([^)]+)\)/);
  if (rgba) {
    const parts = rgba[1].split(",").map((part) => part.trim());
    const r = Number(parts[0]);
    const g = Number(parts[1]);
    const b = Number(parts[2]);
    const a = parts[3] !== undefined ? Number(parts[3]) : 1;
    if ([r, g, b, a].some((n) => Number.isNaN(n))) {
      return null;
    }
    return ck.Color4f(r / 255, g / 255, b / 255, a * opacity);
  }
  // oklch(...) and token fallbacks are not parsed here; the adapter already
  // resolves tokens to hex, and oklch is a documented C2 follow-up.
  return null;
}
