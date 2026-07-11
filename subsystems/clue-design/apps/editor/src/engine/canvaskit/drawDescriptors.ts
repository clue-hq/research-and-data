import type { Canvas, CanvasKit, Paint, Paragraph, TypefaceFontProvider } from "canvaskit-wasm";
import type { ImageFitMode } from "../contracts";
import type { RenderNodeDescriptor, RenderPageDescriptor, TextSpanDescriptor } from "../renderAdapter";
import { applyTextTransform, normalizeContentMapped, transformSegments } from "../textTransform";
import type { CanvasKitImageSource } from "./imageCache";

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
 * Text (SkParagraph) is Wave 3 C4; C2 draws every non-text node. Image nodes
 * draw real pixels (Step 2 / E0.1) when a decoded `Image` is available from the
 * `images` source — honoring fit (cover/contain/crop) + focal point + clip +
 * corner radius with the SAME geometry the Skia/SVG exporters use, so the canvas
 * matches export; until the bytes load they fall back to the placeholder box.
 * Skia objects are released immediately (RAII-style) so long editor sessions do
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
  fontProvider: TypefaceFontProvider | null,
  images: CanvasKitImageSource | null = null
): void {
  // Fill the page as a bounded rect (not a full-surface clear, which would
  // erase the stage's backdrop and hide the artboard boundary).
  const bg = parseColor(ck, page.background) ?? ck.WHITE;
  const bgPaint = new ck.Paint();
  bgPaint.setStyle(ck.PaintStyle.Fill);
  bgPaint.setColor(bg);
  canvas.drawRect(ck.LTRBRect(0, 0, page.width, page.height), bgPaint);
  bgPaint.delete();
  for (const node of nodes) {
    drawNode(ck, canvas, node, fontProvider, images);
  }
}

function drawNode(
  ck: CanvasKit,
  canvas: Canvas,
  node: DrawNode,
  fontProvider: TypefaceFontProvider | null,
  images: CanvasKitImageSource | null
): void {
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

  // The effect stack applies to this node's own body only.
  const filter = effectFilter(ck, d);
  if (filter) {
    const layerPaint = new ck.Paint();
    layerPaint.setImageFilter(filter);
    canvas.saveLayer(layerPaint);
    layerPaint.delete();
    filter.delete();
  }

  drawBody(ck, canvas, d, fontProvider, images);

  if (filter) {
    canvas.restore();
  }

  for (const child of node.children) {
    drawNode(ck, canvas, child, fontProvider, images);
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
  fontProvider: TypefaceFontProvider | null,
  images: CanvasKitImageSource | null
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
    drawText(ck, canvas, d, fontProvider);
    return;
  }
  if (d.kind === "image" && d.image) {
    // Real pixels when the bytes are decoded; otherwise fall through to the
    // placeholder box below (the image node draws ONLY the image, matching the
    // Rust renderer's NodeKind::Image arm — no fill/stroke around it).
    if (drawImage(ck, canvas, d, images)) {
      return;
    }
  }
  if (d.contourPath) {
    drawShapedPath(ck, canvas, d, d.contourPath);
  }
}

interface CropWindow {
  x: number;
  y: number;
  width: number;
  height: number;
}

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value));
const clampRange = (value: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, value));

/**
 * Port of lumen-export `focal_crop_geometry`: the explicit cover window for a
 * focal point, sized to the asset's natural aspect ratio and shifted so the
 * focal point sits as near box-center as the image allows. Uses the RECORD's
 * natural ratio (not the decoded pixels) to stay bit-faithful to the exporter.
 * Returns null unless fit is cover/crop with a focal point and a valid ratio.
 */
function focalCropGeometry(
  fit: ImageFitMode | null,
  focal: { x: number; y: number } | null,
  ratio: number | null,
  boxWidth: number,
  boxHeight: number
): CropWindow | null {
  if (!focal || (fit !== "cover" && fit !== "crop")) {
    return null;
  }
  if (boxWidth <= 0 || boxHeight <= 0 || !ratio || !Number.isFinite(ratio) || ratio <= 0) {
    return null;
  }
  const [drawnWidth, drawnHeight] =
    boxWidth / boxHeight < ratio ? [boxHeight * ratio, boxHeight] : [boxWidth, boxWidth / ratio];
  const focalX = clamp01(focal.x);
  const focalY = clamp01(focal.y);
  const offsetX = clampRange(focalX * drawnWidth - boxWidth / 2, 0, Math.max(0, drawnWidth - boxWidth));
  const offsetY = clampRange(focalY * drawnHeight - boxHeight / 2, 0, Math.max(0, drawnHeight - boxHeight));
  return { x: -offsetX, y: -offsetY, width: drawnWidth, height: drawnHeight };
}

/**
 * Draw a ready image node's real pixels, mirroring lumen-skia `paint_image`:
 * focal-crop window, else center cover (xMidYMid slice), else contain letterbox
 * (xMidYMid meet), else stretch-to-fill. Cover/crop clip to the box (contour +
 * corner radius); contain fits inside so it needs no clip. Returns false when no
 * decoded bytes are available yet (the caller draws the placeholder).
 */
function drawImage(
  ck: CanvasKit,
  canvas: Canvas,
  d: RenderNodeDescriptor,
  images: CanvasKitImageSource | null
): boolean {
  const info = d.image;
  if (!info || !images || info.assetStatus !== "ready") {
    return false;
  }
  const image = images.get(info.assetId);
  if (!image) {
    return false;
  }
  const boxWidth = d.width;
  const boxHeight = d.height;
  if (boxWidth <= 0 || boxHeight <= 0) {
    return false;
  }

  const src = ck.LTRBRect(0, 0, image.width(), image.height());
  const paint = new ck.Paint();
  paint.setAntiAlias(true);

  const clipToBox = (): void => {
    const path = d.contourPath ? ck.Path.MakeFromSVGString(d.contourPath) : null;
    if (path) {
      canvas.clipPath(path, ck.ClipOp.Intersect, true);
      path.delete();
    } else {
      canvas.clipRect(ck.LTRBRect(0, 0, boxWidth, boxHeight), ck.ClipOp.Intersect, true);
    }
  };

  // Case 1 — explicit focal-crop window.
  const crop = focalCropGeometry(info.fit, info.focalPoint, info.naturalAspectRatio, boxWidth, boxHeight);
  if (crop) {
    canvas.save();
    clipToBox();
    canvas.drawImageRect(image, src, ck.XYWHRect(crop.x, crop.y, crop.width, crop.height), paint);
    canvas.restore();
    paint.delete();
    return true;
  }

  // Intrinsic ratio: prefer the decoded pixels (mirrors `decoded_dimensions`),
  // falling back to the record's natural ratio.
  const decodedRatio = image.height() > 0 ? image.width() / image.height() : null;
  const ratio = decodedRatio && decodedRatio > 0 ? decodedRatio : info.naturalAspectRatio;
  const isCover = info.fit === "cover" || info.fit === "crop";

  if (ratio && ratio > 0 && isCover) {
    // Case 2 — center cover (preserveAspectRatio xMidYMid slice).
    const [drawnWidth, drawnHeight] =
      boxWidth / boxHeight < ratio ? [boxHeight * ratio, boxHeight] : [boxWidth, boxWidth / ratio];
    canvas.save();
    clipToBox();
    canvas.drawImageRect(
      image,
      src,
      ck.XYWHRect((boxWidth - drawnWidth) / 2, (boxHeight - drawnHeight) / 2, drawnWidth, drawnHeight),
      paint
    );
    canvas.restore();
    paint.delete();
    return true;
  }

  if (ratio && ratio > 0) {
    // Case 3 — contain letterbox (xMidYMid meet); fits inside the box, no clip.
    const [drawnWidth, drawnHeight] =
      boxWidth / boxHeight < ratio ? [boxWidth, boxWidth / ratio] : [boxHeight * ratio, boxHeight];
    canvas.drawImageRect(
      image,
      src,
      ck.XYWHRect((boxWidth - drawnWidth) / 2, (boxHeight - drawnHeight) / 2, drawnWidth, drawnHeight),
      paint
    );
    paint.delete();
    return true;
  }

  // Case 4 — no ratio available → stretch to fill the box.
  canvas.drawImageRect(image, src, ck.XYWHRect(0, 0, boxWidth, boxHeight), paint);
  paint.delete();
  return true;
}

/**
 * Wave 3 C4: SkParagraph text. Using the same Inter bytes the server uses
 * makes line breaks and widths bit-faithful to the export (the heuristic
 * diverged on caps/digits/hyphens). Wraps at the node width when wrap is on;
 * otherwise lays out unbounded. The measurement-provider that feeds these
 * metrics back into the engine's layout (closing the E3 caveat) is the
 * remaining C4 piece. With no font registered, text is skipped.
 */
function drawText(ck: CanvasKit, canvas: Canvas, d: RenderNodeDescriptor, fontProvider: TypefaceFontProvider | null): void {
  if (!fontProvider || !d.text) {
    return;
  }
  const t = d.text;
  const color = parseColor(ck, d.fill) ?? ck.BLACK;

  // A6a D5: the first solid text stroke becomes a stroke-style foreground paint
  // drawn behind the fill glyphs (first-stroke-only, solid-only), mirroring
  // lumen-skia `text_stroke_paint`. Extra/gradient/dash strokes are ignored
  // here just as the engine advises them (LUME0215) and drops them.
  const strokePaint = textStrokePaint(ck, d);

  // A6b D7: spanned text paints ONE segmented paragraph (per-run fill / weight /
  // decoration; the stroke pass keeps per-run weight but the single stroke
  // color). Reached only when spans exist, so the A6a paths below stay
  // byte-identical. Spans are NOT composed with paragraph-gap stacking in v1 —
  // the segmented paragraph hard-breaks on `\n` natively (LUMV0907), mirroring
  // lumen-skia `paint_text_spanned`.
  if (t.spans && t.spans.length > 0) {
    drawSpannedText(ck, canvas, d, fontProvider, color, strokePaint);
    strokePaint?.delete();
    return;
  }

  // A6a D4: split-and-stack only when a positive gap meets an actual break in
  // the normalized content; otherwise the single-paragraph path stays
  // byte-identical to pre-A6a for every existing scene (D1 case transform
  // aside, which is identity for `none`).
  const gap = Number.isFinite(t.paragraphSpacing) && t.paragraphSpacing > 0 ? t.paragraphSpacing : 0;
  const normalizedRaw = normalizeTextContent(t.content);
  if (gap > 0 && normalizedRaw.includes("\n")) {
    // Engine order: normalize → transform → split (lumen-skia render.rs
    // paint_text). `max_lines` is a TOTAL budget across the stacked paragraphs.
    const transformed = applyTextTransform(t.textTransform, normalizedRaw);
    paintStackedParagraphs(ck, canvas, fontProvider, d, transformed, color, strokePaint, gap);
  } else {
    // Fast path: transform the RAW content (identity for `none` → today's
    // bytes) and paint one paragraph honoring the total max_lines cap.
    const transformed = applyTextTransform(t.textTransform, t.content);
    paintTextParagraph(ck, canvas, fontProvider, d, transformed, color, strokePaint, t.maxLines ?? undefined, 0);
  }

  strokePaint?.delete();
}

/** Port of lumen-skia/lumen-core `normalize_content`: literal "\n" and CRLF
 * become real breaks, trailing breaks are trimmed. Used only to decide and
 * drive the paragraph-spacing split so the editor matches the engine there;
 * the single-paragraph fast path keeps drawing the raw content as before. */
function normalizeTextContent(content: string): string {
  return content.replace(/\\n/g, "\n").replace(/\r\n/g, "\n").replace(/\n+$/, "");
}

/**
 * Paint the stacked `\n`-delimited paragraphs at accumulated offsets with
 * `gap` px between them, mirroring lumen-skia `paint_text`: `max_lines` is a
 * TOTAL cap across the stack — each paragraph draws against the remaining line
 * budget, and when the cut lands exactly on a paragraph boundary with more
 * content following, the "…" is carried in the text (SkParagraph's native
 * ellipsis cannot fire there).
 */
function paintStackedParagraphs(
  ck: CanvasKit,
  canvas: Canvas,
  fontProvider: TypefaceFontProvider,
  d: RenderNodeDescriptor,
  content: string,
  color: Float32Array,
  strokePaint: Paint | null,
  gap: number
): void {
  const t = d.text!;
  const paragraphs = content.split("\n");
  const last = paragraphs.length - 1;
  let cursorY = 0;
  // null = unbounded (no max_lines).
  let remaining: number | null = t.maxLines ?? null;
  for (let index = 0; index < paragraphs.length; index += 1) {
    if (remaining === 0) {
      break;
    }
    let paraText = paragraphs[index];
    let paraMax: number | undefined;
    if (remaining !== null) {
      const natural = paragraphLineCount(ck, fontProvider, d, paraText);
      if (natural < remaining || (natural === remaining && index === last)) {
        paraMax = undefined;
      } else {
        if (natural === remaining && t.truncate) {
          paraText = `${paraText.replace(/\s+$/u, "")}…`;
        }
        paraMax = Math.min(remaining, 65535);
      }
    }
    const { height, lineCount } = paintTextParagraph(
      ck,
      canvas,
      fontProvider,
      d,
      paraText,
      color,
      strokePaint,
      paraMax,
      cursorY
    );
    if (remaining !== null) {
      remaining = Math.max(0, remaining - lineCount);
    }
    cursorY += height;
    if (index !== last) {
      cursorY += gap;
    }
  }
}

/**
 * Paint one paragraph's glyphs (stroke pass behind, then fill) at a vertical
 * offset, mirroring lumen-skia `paint_text_paragraph`: Wrap lays out at the box
 * width (x=0); NoWrap+truncate lays out at the box width so SkParagraph's "…"
 * fires, placed per alignment against the longest line; plain NoWrap lays out
 * unbounded, snaps to the natural width, then places per alignment. Returns the
 * laid-out height and line count so the stacking loop can advance + budget.
 */
function paintTextParagraph(
  ck: CanvasKit,
  canvas: Canvas,
  fontProvider: TypefaceFontProvider,
  d: RenderNodeDescriptor,
  content: string,
  color: Float32Array,
  strokePaint: Paint | null,
  maxLines: number | undefined,
  yOffset: number
): { height: number; lineCount: number } {
  const t = d.text!;
  const fill = buildTextParagraph(ck, fontProvider, t, content, maxLines, { color });

  let layoutWidth: number;
  let x: number;
  if (t.wrap === "wrap") {
    layoutWidth = Math.max(0, d.width);
    x = 0;
  } else if (t.truncate) {
    const bound = Math.max(0, d.width);
    fill.layout(bound);
    const longest = fill.getLongestLine();
    x = t.align === "center" ? (d.width - longest) / 2 : t.align === "right" ? d.width - longest : 0;
    layoutWidth = bound;
  } else {
    fill.layout(Number.MAX_SAFE_INTEGER);
    const natural = Math.ceil(fill.getLongestLine()) + 2;
    x = t.align === "center" ? (d.width - natural) / 2 : t.align === "right" ? d.width - natural : 0;
    layoutWidth = natural;
  }
  fill.layout(layoutWidth);

  if (strokePaint) {
    const stroke = buildTextParagraph(ck, fontProvider, t, content, maxLines, { paint: strokePaint });
    stroke.layout(layoutWidth);
    canvas.drawParagraph(stroke, x, yOffset);
    stroke.delete();
  }
  canvas.drawParagraph(fill, x, yOffset);
  const height = fill.getHeight();
  const lineCount = fill.getLineMetrics().length;
  fill.delete();
  return { height, lineCount };
}

/** The natural (uncapped) line count of one paragraph at the same layout width
 * the paint pass uses, so the stacking loop can budget the total `max_lines`
 * cap exactly like the engine's `paragraph_line_count`. */
function paragraphLineCount(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  d: RenderNodeDescriptor,
  para: string
): number {
  const t = d.text!;
  const paragraph = buildTextParagraph(ck, fontProvider, t, para, undefined, { color: ck.BLACK });
  paragraph.layout(t.wrap === "wrap" ? Math.max(0, d.width) : Number.MAX_SAFE_INTEGER);
  const count = paragraph.getLineMetrics().length;
  paragraph.delete();
  return count;
}

/**
 * Build a laid-out-ready paragraph for one text run. `foreground` is either a
 * solid fill color (the fill pass) or a stroke-style Paint (the D5 stroke pass,
 * pushed via `pushPaintStyle` since CanvasKit `TextStyle` carries no Paint
 * foreground in object form). Decoration (D2) is set on both passes so the
 * outline traces the underline/strike too, matching the engine's shared
 * `build_paragraph`. Weight is the EXACT numeric value (D6.1) — no bucketing.
 */
function buildTextParagraph(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  t: NonNullable<RenderNodeDescriptor["text"]>,
  content: string,
  maxLines: number | undefined,
  foreground: { color: Float32Array } | { paint: Paint }
): Paragraph {
  const decoration =
    (t.underline ? ck.UnderlineDecoration : 0) | (t.strikethrough ? ck.LineThroughDecoration : 0);
  const isFill = "color" in foreground;
  const textStyle: Record<string, unknown> = {
    fontFamilies: [t.fontFamily],
    fontSize: t.fontSize,
    fontStyle: { weight: t.fontWeight },
    heightMultiplier: t.lineHeight,
    letterSpacing: t.letterSpacing
  };
  if (decoration) {
    textStyle.decoration = decoration;
  }
  if (isFill) {
    textStyle.color = foreground.color;
    if (decoration) {
      textStyle.decorationColor = foreground.color;
    }
  }
  const style = new ck.ParagraphStyle({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    textStyle: textStyle as any,
    textAlign: textAlign(ck, t.align),
    maxLines: maxLines ?? undefined,
    // A6a D3: opt-in native "…" — fires on the max_lines cut, or on a bounded
    // NoWrap line that overflows its box (laid out at the box width above).
    ellipsis: t.truncate ? "…" : undefined
  });
  const builder = ck.ParagraphBuilder.MakeFromFontProvider(style, fontProvider);
  if (!isFill) {
    // Paint the glyphs with the stroke paint; a transparent background paint
    // keeps `pushPaintStyle`'s bg from drawing a filled box behind the text.
    const bg = new ck.Paint();
    bg.setColor(ck.Color4f(0, 0, 0, 0));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    builder.pushPaintStyle(new ck.TextStyle(textStyle as any), foreground.paint, bg);
    bg.delete();
  }
  builder.addText(content);
  const paragraph = builder.build();
  builder.delete();
  return paragraph;
}

/** A6b: one resolved styled run for the segmented paragraph — weight/decoration
 * (node ∪ span) and the fill-pass color (span fill, else the node fill). */
interface SpannedSegment {
  text: string;
  weight: number;
  underline: boolean;
  strikethrough: boolean;
  color: Float32Array;
}

/**
 * A6b D7: paint spanned text as ONE segmented paragraph, mirroring lumen-skia
 * `paint_text_spanned`. Normalize with the offset map, relocate span byte
 * offsets onto the normalized string, transform segments (stateful case), then
 * build the fill paragraph (per-run color/weight/decoration ∪ node with
 * decorationColor) and — when a text stroke exists — a stroke paragraph that
 * keeps per-run WEIGHT but paints every run in the single stroke color. Layout
 * arms (Wrap / NoWrap / NoWrap+truncate) match the A6a non-span path; there is
 * NO paragraph-gap stacking (LUMV0907) and the block sits at y=0.
 */
function drawSpannedText(
  ck: CanvasKit,
  canvas: Canvas,
  d: RenderNodeDescriptor,
  fontProvider: TypefaceFontProvider,
  baseColor: Float32Array,
  strokePaint: Paint | null
): void {
  const t = d.text!;
  const spans = t.spans as TextSpanDescriptor[];
  const { normalized, map } = normalizeContentMapped(t.content);
  // map's last entry is the normalized byte length — the out-of-range fallback,
  // mirroring Rust's `map.get(span.start).unwrap_or(normalized.len())`.
  const normLen = map[map.length - 1];
  const boundaries: Array<[number, number]> = spans.map((span) => {
    const start = map[span.start] ?? normLen;
    const end = map[span.end] ?? normLen;
    return [Math.min(start, end), Math.max(start, end)];
  });
  const core = transformSegments(normalized, boundaries, t.textTransform);
  const segments: SpannedSegment[] = core.map((seg) => {
    const span = seg.span !== null ? spans[seg.span] : undefined;
    const weight = span?.fontWeight ?? t.fontWeight;
    // Decoration is the union of node and span (span true adds; span never
    // subtracts the node flag), mirroring the engine.
    const underline = t.underline || (span?.underline ?? false);
    const strikethrough = t.strikethrough || (span?.strikethrough ?? false);
    const color = span?.fill ? parseColor(ck, span.fill) ?? baseColor : baseColor;
    return { text: seg.text, weight, underline, strikethrough, color };
  });

  const maxLines = t.maxLines ?? undefined;
  const fill = buildSpannedParagraph(ck, fontProvider, t, segments, maxLines, null);

  let layoutWidth: number;
  let x: number;
  if (t.wrap === "wrap") {
    layoutWidth = Math.max(0, d.width);
    x = 0;
  } else if (t.truncate) {
    const bound = Math.max(0, d.width);
    fill.layout(bound);
    const longest = fill.getLongestLine();
    x = t.align === "center" ? (d.width - longest) / 2 : t.align === "right" ? d.width - longest : 0;
    layoutWidth = bound;
  } else {
    fill.layout(Number.MAX_SAFE_INTEGER);
    const natural = Math.ceil(fill.getLongestLine()) + 2;
    x = t.align === "center" ? (d.width - natural) / 2 : t.align === "right" ? d.width - natural : 0;
    layoutWidth = natural;
  }
  fill.layout(layoutWidth);

  if (strokePaint) {
    const stroke = buildSpannedParagraph(ck, fontProvider, t, segments, maxLines, strokePaint);
    stroke.layout(layoutWidth);
    canvas.drawParagraph(stroke, x, 0);
    stroke.delete();
  }
  canvas.drawParagraph(fill, x, 0);
  fill.delete();
}

/**
 * Build the segmented paragraph, mirroring lumen-skia `build_paragraph`'s
 * `Some(segments)` branch: one base ParagraphStyle (align / maxLines / ellipsis)
 * then a per-segment `pushStyle`/`pop` (or `pushPaintStyle` for the stroke pass)
 * so weight overrides change shaping inside the measured/painted paragraph.
 */
function buildSpannedParagraph(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  t: NonNullable<RenderNodeDescriptor["text"]>,
  segments: SpannedSegment[],
  maxLines: number | undefined,
  strokePaint: Paint | null
): Paragraph {
  const baseTextStyle: Record<string, unknown> = {
    fontFamilies: [t.fontFamily],
    fontSize: t.fontSize,
    fontStyle: { weight: t.fontWeight },
    heightMultiplier: t.lineHeight,
    letterSpacing: t.letterSpacing
  };
  const style = new ck.ParagraphStyle({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    textStyle: baseTextStyle as any,
    textAlign: textAlign(ck, t.align),
    maxLines: maxLines ?? undefined,
    ellipsis: t.truncate ? "…" : undefined
  });
  const builder = ck.ParagraphBuilder.MakeFromFontProvider(style, fontProvider);
  // A transparent background keeps `pushPaintStyle`'s bg from drawing a box.
  const bg = strokePaint ? new ck.Paint() : null;
  bg?.setColor(ck.Color4f(0, 0, 0, 0));
  for (const seg of segments) {
    const decoration =
      (seg.underline ? ck.UnderlineDecoration : 0) | (seg.strikethrough ? ck.LineThroughDecoration : 0);
    const segStyle: Record<string, unknown> = {
      fontFamilies: [t.fontFamily],
      fontSize: t.fontSize,
      fontStyle: { weight: seg.weight },
      heightMultiplier: t.lineHeight,
      letterSpacing: t.letterSpacing
    };
    if (decoration) {
      segStyle.decoration = decoration;
    }
    if (strokePaint) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      builder.pushPaintStyle(new ck.TextStyle(segStyle as any), strokePaint, bg!);
    } else {
      segStyle.color = seg.color;
      if (decoration) {
        segStyle.decorationColor = seg.color;
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      builder.pushStyle(new ck.TextStyle(segStyle as any));
    }
    builder.addText(seg.text);
    builder.pop();
  }
  bg?.delete();
  const paragraph = builder.build();
  builder.delete();
  return paragraph;
}

/**
 * A6a D5: the first solid text stroke as a stroke-style Paint (first-stroke-only,
 * solid-only). A gradient stroke takes its first stop's color; dash/caps/joins
 * are ignored — the same reduction the engine's `text_stroke_paint` applies
 * before advising LUME0215. Caller deletes the returned paint.
 */
function textStrokePaint(ck: CanvasKit, d: RenderNodeDescriptor): Paint | null {
  const stroke = d.strokes[0];
  if (!stroke) {
    return null;
  }
  let color: Float32Array | null;
  if (stroke.paint.kind === "solid") {
    color = parseColor(ck, stroke.paint.color);
  } else {
    // First gradient stop is `[pos, css, ...]`; paint it solid.
    const css = stroke.paint.colorStops[1];
    color = typeof css === "string" ? parseColor(ck, css) : null;
  }
  if (!color) {
    return null;
  }
  const paint = new ck.Paint();
  paint.setAntiAlias(true);
  paint.setStyle(ck.PaintStyle.Stroke);
  paint.setStrokeWidth(stroke.width);
  paint.setColor(color);
  return paint;
}

function textAlign(ck: CanvasKit, align: "left" | "center" | "right" | "justify") {
  if (align === "center") return ck.TextAlign.Center;
  if (align === "right") return ck.TextAlign.Right;
  if (align === "justify") return ck.TextAlign.Justify;
  return ck.TextAlign.Left;
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

type ImageFilter = import("canvaskit-wasm").ImageFilter;

/**
 * Build the node's effect stack as one image filter, mirroring the engine's
 * `effect_image_filter` branch: a pure drop-shadow stack keeps the exact
 * pre-A4 chain (`shadowFilter`); a stack carrying any glow / layer blur /
 * inner shadow uses the A4 general pipeline honoring the D1 stacking contract.
 * Caller deletes the returned filter (the intermediate nodes are held by it).
 */
function effectFilter(ck: CanvasKit, d: RenderNodeDescriptor): ImageFilter | null {
  if (d.effects.length === 0) {
    return null;
  }
  // Spread needs the general pipeline too: the pre-A4 MakeDropShadow chain has
  // no spread parameter, but MakeDilate/MakeErode give it faithfully there.
  const needsGeneral = d.effects.some(
    (effect) => effect.type !== "drop_shadow" || effect.spread !== 0
  );
  if (!needsGeneral) {
    return shadowFilter(ck, d.allShadows);
  }
  return generalEffectFilter(ck, d.effects);
}

/** Chained drop shadows — first entry topmost — mirroring chained feDropShadow;
 * Skia sigma = SVG stdDeviation = blur/2. Caller deletes the returned filter. */
function shadowFilter(ck: CanvasKit, shadows: RenderNodeDescriptor["allShadows"]) {
  let filter: ImageFilter | null = null;
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

/**
 * A4 general effect pipeline, mirroring lumen-skia `general_effect_filter`
 * (D1 stacking contract, matched to the SVG exporter):
 *   source → layer blurs applied to the source → outer shadows/glows beneath
 *   the blurred base → inner shadows over it, clipped to its alpha.
 * CanvasKit has no `MakeMerge`, so the merge is folded with SrcOver blends
 * (equivalent to Skia's union merge). Applied to a saveLayer over the body, so
 * the "dynamic source" the null-input filters read is the node's own body.
 */
function generalEffectFilter(ck: CanvasKit, effects: RenderNodeDescriptor["effects"]): ImageFilter | null {
  // 1. Blurred base (null = the source graphic when there are no layer blurs).
  let base: ImageFilter | null = null;
  for (const effect of effects) {
    if (effect.type === "layer_blur") {
      const sigma = effect.radius / 2;
      base = ck.ImageFilter.MakeBlur(sigma, sigma, ck.TileMode.Decal, base);
    }
  }

  // 2. Outer shadows/glows (declaration order; first = topmost of its class).
  // 3. Inner shadows (declaration order; first = topmost of its class).
  const outers: ImageFilter[] = [];
  const inners: ImageFilter[] = [];
  for (const effect of effects) {
    if (effect.type === "drop_shadow") {
      const f = outerEffectFilter(
        ck,
        effect.color,
        effect.opacity,
        effect.offsetX,
        effect.offsetY,
        effect.blur,
        effect.spread,
        base
      );
      if (f) {
        outers.push(f);
      }
    } else if (effect.type === "glow") {
      const f = outerEffectFilter(ck, effect.color, effect.opacity, 0, 0, effect.blur, effect.spread, base);
      if (f) {
        outers.push(f);
      }
    } else if (effect.type === "inner_shadow") {
      const f = innerShadowFilter(
        ck,
        effect.color,
        effect.opacity,
        effect.offsetX,
        effect.offsetY,
        effect.blur,
        effect.spread,
        base
      );
      if (f) {
        inners.push(f);
      }
    }
    // layer_blur folded into `base` above.
  }

  if (outers.length === 0 && inners.length === 0) {
    // Layer-blur only.
    return base;
  }

  // 4. Merge bottom-up: outers reversed (first outer topmost), the blurred
  //    base, inner shadows reversed (first inner topmost).
  const mergeList: (ImageFilter | null)[] = [];
  for (let i = outers.length - 1; i >= 0; i -= 1) {
    mergeList.push(outers[i]);
  }
  mergeList.push(base);
  for (let i = inners.length - 1; i >= 0; i -= 1) {
    mergeList.push(inners[i]);
  }
  return mergeFilters(ck, mergeList);
}

/**
 * One outer shadow/glow: `MakeDropShadowOnly` (shadow only, not the source)
 * derived from the blurred base, sigma = blur/2, opacity folded into the color
 * alpha. Spread is FAITHFUL — dilate/erode the base alpha first, byte-mirroring
 * lumen-skia's `outer_effect_filter` (gate-R upgrade: the D7 "no dilate in
 * CanvasKit" premise was wrong; MakeDilate/MakeErode exist in this build).
 */
function outerEffectFilter(
  ck: CanvasKit,
  css: string,
  opacity: number,
  offsetX: number,
  offsetY: number,
  blur: number,
  spread: number,
  base: ImageFilter | null
): ImageFilter | null {
  const color = parseColor(ck, css, opacity);
  if (!color) {
    return null;
  }
  const spreadInput =
    spread > 0
      ? ck.ImageFilter.MakeDilate(spread, spread, base)
      : spread < 0
        ? ck.ImageFilter.MakeErode(-spread, -spread, base)
        : base;
  const sigma = blur / 2;
  return ck.ImageFilter.MakeDropShadowOnly(offsetX, offsetY, sigma, sigma, color, spreadInput);
}

/**
 * One inner shadow via the standard alpha-invert composite, byte-mirroring
 * lumen-skia `inner_shadow_filter`: erode the (blurred) base inward by spread,
 * offset + blur it, take `base SrcOut offset_blur` (inside the base alpha but
 * outside the shifted blurred alpha), then recolor that ring to the shadow
 * color with a SrcIn color filter. Faithful — spread IS honored here (unlike
 * outer spread), so no approximation diagnostic applies to inner shadows.
 */
function innerShadowFilter(
  ck: CanvasKit,
  css: string,
  opacity: number,
  offsetX: number,
  offsetY: number,
  blur: number,
  spread: number,
  base: ImageFilter | null
): ImageFilter | null {
  const color = parseColor(ck, css, opacity);
  if (!color) {
    return null;
  }
  // Shape eroded inward by spread.
  const shape = spread > 0 ? ck.ImageFilter.MakeErode(spread, spread, base) : base;
  // Offset then blur the (eroded) shape.
  const offset = ck.ImageFilter.MakeOffset(offsetX, offsetY, shape);
  const sigma = blur / 2;
  const offsetBlur = ck.ImageFilter.MakeBlur(sigma, sigma, ck.TileMode.Decal, offset);
  // ring = base SrcOut offset_blur. MakeBlend(mode, background, foreground)
  // computes foreground <mode> background, so foreground = base, background =
  // offset_blur — the same argument order as the Skia recipe.
  const ring = ck.ImageFilter.MakeBlend(ck.BlendMode.SrcOut, offsetBlur, base);
  // Recolor the ring to the shadow color (SrcIn keeps the ring's alpha).
  const colorFilter = ck.ColorFilter.MakeBlend(color, ck.BlendMode.SrcIn);
  const recolored = ck.ImageFilter.MakeColorFilter(colorFilter, ring);
  colorFilter.delete();
  return recolored;
}

/**
 * Fold a bottom-to-top filter list into one via SrcOver blends — CanvasKit's
 * stand-in for Skia's `merge` (which unions its inputs in order). A null entry
 * is the dynamic source image (the node body); at most one entry (the unblurred
 * base) is null.
 */
function mergeFilters(ck: CanvasKit, list: (ImageFilter | null)[]): ImageFilter | null {
  let acc = list[0] ?? null;
  for (let i = 1; i < list.length; i += 1) {
    acc = ck.ImageFilter.MakeBlend(ck.BlendMode.SrcOver, acc, list[i]);
  }
  return acc;
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
