import type {
  CanvasKit,
  FontWeight,
  Paragraph,
  ParagraphBuilder,
  TextAlign,
  TypefaceFontProvider
} from "canvaskit-wasm";
import type { Node, Scene, TextSpan } from "../contracts";
import { resolvedTextFields } from "../renderAdapter";
import { hasItalicFace, resolveFontFamilies } from "./loadCanvasKit";
import {
  applyTextTransform,
  normalizeContentMapped,
  transformSegments
} from "../textTransform";
import type { TextMeasurement, TextMeasurementInput, TextMeasurementLine } from "../wasmEngine";

/** The text arm of the node-kind union — the only shape these passes measure. */
type TextNodeKind = Extract<Node["kind"], { kind: "text" }>;

/**
 * Wave 3 C4 (measure-then-inject): measure every text node with SkParagraph
 * and emit the metrics the engine consumes (`WasmEngine.setMeasurements`).
 * Using the same Inter bytes the server uses makes editor `computed` geometry
 * Skia-faithful, closing the E3 caveat for hug-sized text without a wasm→JS
 * callback during layout.
 *
 * V0 measures unconstrained (no `max_width`), matching the key the engine uses
 * for hug/unconstrained text; constrained (wrapped) text reuses the same
 * payload shape and is refined as the convergence matures. Plan 4 item F adds
 * a SECOND pass (`skiaLineMeasurements`) keyed on the boxes this one solves.
 */
export function skiaMeasurements(ck: CanvasKit, fontProvider: TypefaceFontProvider, scene: Scene): TextMeasurement[] {
  const out: TextMeasurement[] = [];
  for (const node of Object.values(scene.nodes)) {
    if (node.kind.kind !== "text") {
      continue;
    }
    const t = node.kind;
    // Canonical callers pass the Rust presentation: consumed bindings are
    // absent, so shaping and the record key read the exact same text/span
    // fields. The legacy no-context path retains its existing role adapter.
    const styled = resolvedTextFields(t);
    const textTransform = t.text_transform ?? "none";
    const paragraphSpacing = t.paragraph_spacing ?? 0;
    const italic = t.italic ?? false;
    const spans = t.spans ?? [];
    const record = measurementRecord(t, node.id);
    if (spans.length > 0) {
      // A6b: spanned nodes measure ONE segmented paragraph — weight-span
      // overrides change shaping widths, so the styles must be in the measured
      // paragraph (review fix). NO paragraph-gap stacking when spans exist
      // (LUMV0907); the record carries the raw spans so the engine's spans-keyed
      // measure lookup hits instead of falling back to the heuristic.
      const { width, height } = measureSpannedParagraph(ck, fontProvider, styled, spans, t.content, textTransform, italic);
      record.width = width;
      record.height = height;
    } else {
      // Case transform changes glyph widths, so measure the TRANSFORMED string
      // (the record's `content` key stays the literal, matching the node).
      const measuredContent = applyTextTransform(textTransform, t.content);
      const { width, height } = measureParagraph(ck, fontProvider, {
        content: measuredContent,
        fontFamily: styled.fontFamily,
        fontSize: styled.fontSize,
        fontWeight: styled.fontWeight,
        lineHeight: styled.lineHeight,
        letterSpacing: styled.letterSpacing,
        italic
      });
      // Paragraph spacing adds `gap` px at each `\n` break (unconstrained hug);
      // mirrors the measurer stacking each paragraph with the extra gap.
      const gap = Number.isFinite(paragraphSpacing) && paragraphSpacing > 0 ? paragraphSpacing : 0;
      const breakCount =
        gap > 0 ? Math.max(0, measuredContent.replace(/\\n/g, "\n").split("\n").length - 1) : 0;
      record.width = width;
      record.height = height + breakCount * gap;
    }
    out.push(record);
  }
  return out;
}

/**
 * The measurement record for one text node — every field the engine's
 * `measure_key` reads, with a zero extent the caller fills in. Extracted so
 * the unconstrained pass and the Plan 4 line pass emit byte-identical keys:
 * a record whose key fields drift from the node is a lookup MISS, and the
 * engine silently falls back to the heuristic.
 */
function measurementRecord(t: TextNodeKind, nodeId: string): TextMeasurement {
  const spans = t.spans ?? [];
  const record: TextMeasurement = {
    node_id: nodeId,
    content: t.content,
    font_family: t.font_family,
    font_size: t.font_size,
    font_weight: t.font_weight,
    line_height: t.line_height ?? 1.2,
    letter_spacing: t.letter_spacing ?? 0,
    wrap: t.wrap ?? "no_wrap",
    max_lines: t.max_lines ?? null,
    direction: t.direction ?? "ltr",
    // A6a: the geometry-affecting typography fields. They also enter the
    // engine's `measure_key`, so the record MUST carry them or the layout
    // lookup misses this override and falls back to the heuristic.
    text_transform: t.text_transform ?? "none",
    truncate: t.truncate ?? false,
    paragraph_spacing: t.paragraph_spacing ?? 0,
    // A7b: block italic is a `measure_key` input (span italic rides in
    // `spans`), so the record MUST carry it or the engine's layout lookup
    // misses and falls back to the heuristic.
    italic: t.italic ?? false,
    width: 0,
    height: 0
  };
  if (spans.length > 0) {
    // A6b review fix: the raw spans are the digest key. A spanless node omits
    // the field entirely, keeping the pre-A6b payload byte-identical.
    record.spans = spans;
  }
  return record;
}

/**
 * Plan 4 item F: painted line boxes per text node the engine has laid out,
 * keyed on the box it SOLVED. Two records per node, same lines and extent:
 *   • `(max_width, max_height)` = `layout_bounds` — the key
 *     `validate_text_nodes` measures with (`TextMeasureInput::with_bounds`),
 *     which is where `computed.text_lines` is placed from;
 *   • `(max_width)` alone — the key taffy's measure closure uses for a
 *     hug-height node (`measure_taffy_node`: `max_width = available width`,
 *     no height), so a wrapped hug box takes CanvasKit's height, not the
 *     heuristic's.
 * Lines are measured LEFT-aligned and paragraph-relative, exactly as
 * `SkiaTextMeasurer` reports them; the engine applies `align`/`valign`. The
 * layout width mirrors the painter: the box width for wrap and for
 * NoWrap+truncate, unbounded for plain NoWrap. Paragraph spacing stacks
 * paragraphs with the gap, as `paintStackedParagraphs` does; `max_lines` cuts
 * the merged list (total across paragraphs, like the Rust measurer).
 * Nodes without `computed` have no box to key on and are skipped.
 */
export function skiaLineMeasurements(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  scene: Scene
): TextMeasurement[] {
  const out: TextMeasurement[] = [];
  for (const node of Object.values(scene.nodes)) {
    if (node.kind.kind !== "text" || !node.computed) {
      continue;
    }
    const bounds = node.computed.layout_bounds;
    if (!(bounds.width > 0) || !(bounds.height > 0)) {
      continue;
    }
    const measured = measureLinesAtWidth(ck, fontProvider, node.kind, bounds.width);
    const base = measurementRecord(node.kind, node.id);
    out.push({
      ...base,
      max_width: bounds.width,
      max_height: bounds.height,
      width: measured.width,
      height: measured.height,
      lines: measured.lines
    });
    out.push({
      ...base,
      max_width: bounds.width,
      width: measured.width,
      height: measured.height,
      lines: measured.lines
    });
  }
  return out;
}

/** Shape the constraints actually requested by Rust, retaining the node's kit
 * tokens even for slot fixtures whose content differs from the saved text. */
export function skiaRequestedMeasurements(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  scene: Scene,
  requests: TextMeasurementInput[]
): TextMeasurement[] {
  return requests.map((input) => {
    const source = input.node_id ? scene.nodes[input.node_id]?.kind : undefined;
    if (input.node_id && source?.kind !== "text") {
      throw new Error(`Text measurement references missing node ${input.node_id}`);
    }
    const text = { ...(source ?? {}), ...input, kind: "text" } as TextNodeKind;
    const measured = measureLinesAtWidth(ck, fontProvider, text, input.max_width ?? Number.MAX_SAFE_INTEGER, input.font_size_override);
    return { ...input, ...measured };
  });
}

/** The slice of `WasmEngine` the injection loop drives: read the solved scene,
 * install a measurement set (which relayouts and replaces the snapshot). */
export interface MeasurementEngine {
  readonly presentationScene?: Scene;
  readonly scene: Scene;
  setMeasurements(measurements: TextMeasurement[]): TextMeasurementInput[] | void;
}

/** Hard cap on line-pass rounds. The loop is monotone over deterministic
 * measurements, so it settles well inside this; the cap is what guarantees a
 * pathological scene cannot spin the effect. */
export const MEASUREMENT_ROUNDS_MAX = 4;

/**
 * Plan 4 item F: measure-then-inject, converged. Pass 1 injects the
 * unconstrained extents; then the line pass is re-run, keyed on the boxes the
 * previous round solved, until a round leaves every text node's solved size
 * unchanged.
 *
 * The loop is not belt-and-braces: the line records CHANGE boxes. The
 * taffy-keyed record hands a wrapped hug-height box CanvasKit's height, so the
 * validate-keyed record emitted in the SAME round still names the height the
 * engine had before it — and for exactly those nodes `validate_text_nodes`'
 * `with_bounds` lookup misses and `text_lines` stays heuristic. Re-running the
 * line pass against the new boxes closes that gap; the effect's outer re-run
 * cannot, because it repeats the same two calls from scratch and lands in the
 * same state. Deterministic input → the loop is monotone and stops;
 * `MEASUREMENT_ROUNDS_MAX` caps it regardless.
 *
 * Returns convergence and any unresolved requests so the editor can warn when
 * its bounded shaping loop cannot establish faithful text geometry.
 */
export function injectSkiaMeasurements(
  engine: MeasurementEngine,
  passes: {
    unconstrained: (scene: Scene) => TextMeasurement[];
    lines: (scene: Scene) => TextMeasurement[];
    requests?: (scene: Scene, requests: TextMeasurementInput[]) => TextMeasurement[];
  }
): { calls: number; converged: boolean; missing: TextMeasurementInput[] } {
  // Both sets ride every line call — `setMeasurements` REPLACES the override
  // set, so dropping the unconstrained records would take hug boxes back to
  // the heuristic.
  const unconstrained = passes.unconstrained((engine.presentationScene ?? engine.scene));
  let missing = engine.setMeasurements(unconstrained) ?? [];
  const requested = new Map<string, TextMeasurement>();
  let calls = 1;
  let previous = textSizeSignature((engine.presentationScene ?? engine.scene));
  for (let round = 0; round < MEASUREMENT_ROUNDS_MAX; round += 1) {
    for (const measurement of passes.requests?.((engine.presentationScene ?? engine.scene), missing) ?? []) {
      // Rust owns the authoritative lookup key. This local map only bounds
      // repeated records; retain every requested constraint during convergence.
      const input: Partial<TextMeasurement> = { ...measurement };
      delete input.width;
      delete input.height;
      delete input.lines;
      requested.set(JSON.stringify(input), measurement);
    }
    missing = engine.setMeasurements([
      ...unconstrained, ...passes.lines((engine.presentationScene ?? engine.scene)), ...requested.values()
    ]) ?? [];
    calls += 1;
    const next = textSizeSignature((engine.presentationScene ?? engine.scene));
    if (next === previous && (!passes.requests || missing.length === 0)) {
      return { calls, converged: true, missing };
    }
    previous = next;
  }
  return { calls, converged: false, missing };
}

/**
 * Every text node's SOLVED box, the only thing the line pass keys on — so two
 * rounds with the same signature would send byte-identical records and the
 * loop is done. Fixed-point formatting matches the measurements' own rounding,
 * so float noise below a thousandth cannot keep the loop alive. Local rather
 * than the adapter's `textMeasurementSignature`: the engine layer never
 * imports the adapter layer.
 */
function textSizeSignature(scene: Scene): string {
  const parts: string[] = [];
  for (const node of Object.values(scene.nodes)) {
    if (node.kind.kind !== "text") {
      continue;
    }
    const box = node.computed?.layout_bounds;
    parts.push(
      box ? `${node.id}|${box.width.toFixed(3)}x${box.height.toFixed(3)}` : `${node.id}|_`
    );
  }
  return parts.sort().join("\n");
}

/** The measured extent and painted line boxes of one text node at one width. */
interface MeasuredLines {
  width: number;
  height: number;
  lines: TextMeasurementLine[];
}

/**
 * Lay one text node out at `boxWidth` and report the line boxes the canvas
 * paints, paragraph-relative and left-aligned. The layout width mirrors
 * `paintTextParagraph`: the box width when the text wraps and when NoWrap
 * truncates (SkParagraph needs the bound to cut), unbounded for plain NoWrap.
 * Stacking mirrors `paintStackedParagraphs` / lumen-skia `measure_stacked` —
 * normalize, transform, split on `\n`, and advance the cursor by each
 * paragraph's height with the gap BETWEEN consecutive paragraphs.
 */
function measureLinesAtWidth(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  t: TextNodeKind,
  boxWidth: number,
  fontSizeOverride?: number | null
): MeasuredLines {
  const styled = resolvedTextFields(t);
  if (fontSizeOverride != null) styled.fontSize = fontSizeOverride;
  const textTransform = t.text_transform ?? "none";
  const truncate = t.truncate ?? false;
  const wrap = t.wrap ?? "no_wrap";
  const italic = t.italic ?? false;
  const spans = t.spans ?? [];
  const paragraphSpacing = t.paragraph_spacing ?? 0;
  const maxLines = t.max_lines ?? null;
  const layoutWidth = wrap === "wrap" || truncate ? Math.max(0, boxWidth) : Number.MAX_SAFE_INTEGER;

  const lines: TextMeasurementLine[] = [];
  // The painted stack's total height: each paragraph's laid-out height plus a
  // gap between consecutive paragraphs (never a trailing one).
  let stackHeight = 0;
  if (spans.length > 0) {
    // A6b: a spanned node is ONE segmented paragraph that hard-breaks on `\n`
    // natively — paragraph stacking is not composed with spans (LUMV0907).
    const { paragraph, builder } = buildSpannedParagraph(
      ck,
      fontProvider,
      styled,
      spans,
      t.content,
      textTransform,
      italic
    );
    paragraph.layout(layoutWidth);
    collectLineBoxes(paragraph, 0, lines);
    stackHeight = paragraph.getHeight();
    paragraph.delete();
    builder.delete();
  } else {
    const gap = Number.isFinite(paragraphSpacing) && paragraphSpacing > 0 ? paragraphSpacing : 0;
    const normalized = normalizeContentMapped(t.content).normalized;
    // Engine order: normalize → transform → split. The single-paragraph fast
    // path transforms the RAW content, exactly as the painter does.
    const paragraphs =
      gap > 0 && normalized.includes("\n")
        ? applyTextTransform(textTransform, normalized).split("\n")
        : [applyTextTransform(textTransform, t.content)];
    for (let index = 0; index < paragraphs.length; index += 1) {
      if (index > 0) {
        stackHeight += gap;
      }
      const { paragraph, builder } = buildPlainParagraph(ck, fontProvider, {
        content: paragraphs[index],
        fontFamily: styled.fontFamily,
        fontSize: styled.fontSize,
        fontWeight: styled.fontWeight,
        lineHeight: styled.lineHeight,
        letterSpacing: styled.letterSpacing,
        italic
      });
      paragraph.layout(layoutWidth);
      collectLineBoxes(paragraph, stackHeight, lines);
      stackHeight += paragraph.getHeight();
      paragraph.delete();
      builder.delete();
    }
  }

  // `max_lines` is a TOTAL cap across the stack, applied to the merged list
  // (lumen-skia `measure_stacked`). When it actually cuts, the extent is the
  // last VISIBLE line's bottom — the per-line offsets already fold the gaps in.
  const cut = maxLines !== null && lines.length > maxLines;
  if (cut) {
    lines.length = maxLines;
  }
  const last = lines[lines.length - 1];
  const height = cut && last ? last.y + last.height : stackHeight;
  const width = lines.reduce((widest, line) => Math.max(widest, line.width), 0);
  return {
    width: round(width),
    height: round(height),
    lines: lines.map((line) => ({
      x: round(line.x),
      y: round(line.y),
      width: round(line.width),
      height: round(line.height),
      baseline: round(line.baseline)
    }))
  };
}

/** Append one laid-out paragraph's line boxes, offset by the stack cursor. */
function collectLineBoxes(paragraph: Paragraph, top: number, out: TextMeasurementLine[]): void {
  for (const metrics of paragraph.getLineMetrics()) {
    out.push({
      x: metrics.left,
      y: top + metrics.baseline - metrics.ascent,
      width: metrics.width,
      height: metrics.height,
      baseline: top + metrics.baseline
    });
  }
}

interface ParagraphInput {
  content: string;
  fontFamily: string;
  fontSize: number;
  fontWeight: number;
  lineHeight: number;
  letterSpacing: number;
  /** A7b: block italic — a shaping input (changes advances), so it enters the
   * measured paragraph's `fontStyle.slant`. Optional (default upright) so the
   * pre-A7b call sites need no change. */
  italic?: boolean;
}

/**
 * Build (not lay out) one plain SkParagraph for a text style. Shared by the
 * unconstrained extent pass and the Plan 4 line pass so both shape through
 * exactly the same style mapping. Alignment defaults to LEFT, mirroring
 * `SkiaTextMeasurer`: alignment moves lines inside the box but never changes
 * break positions, and the engine places the lines by `align`/`valign` itself.
 * The caller lays the paragraph out and deletes BOTH handles.
 */
function buildPlainParagraph(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  input: ParagraphInput,
  align?: TextAlign
): { paragraph: Paragraph; builder: ParagraphBuilder } {
  // A7b D2 gate: mirror the engine — Italic only when a real face exists,
  // so measured widths reflect the same (upright) shaping the paint uses.
  const italic = (input.italic ?? false) && hasItalicFace(input.fontFamily);
  const style = new ck.ParagraphStyle({
    textAlign: align ?? ck.TextAlign.Left,
    textStyle: {
      // Alias-first chain: face selection is the editor's (CanvasKit's
      // provider ignores fontStyle), so measurement resolves the SAME face
      // the painter and the server do.
      fontFamilies: resolveFontFamilies(input.fontFamily, input.fontWeight, italic),
      fontSize: input.fontSize,
      // A6a D6.1: the exact numeric weight (no 4-bucket snap), matching the
      // painter and the server so measured widths and painted glyphs agree.
      // CanvasKit accepts a raw number here; the enum type is just the TS shape.
      fontStyle: {
        weight: input.fontWeight as unknown as FontWeight,
        slant: italic ? ck.FontSlant.Italic : ck.FontSlant.Upright
      },
      heightMultiplier: input.lineHeight,
      letterSpacing: input.letterSpacing
    }
  });
  const builder = ck.ParagraphBuilder.MakeFromFontProvider(style, fontProvider);
  builder.addText(input.content);
  return { paragraph: builder.build(), builder };
}

/** Unconstrained SkParagraph width/height for a text style. */
export function measureParagraph(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  input: ParagraphInput
): { width: number; height: number } {
  const { paragraph, builder } = buildPlainParagraph(ck, fontProvider, input);
  paragraph.layout(Number.MAX_SAFE_INTEGER);
  const width = paragraph.getMaxIntrinsicWidth();
  const height = paragraph.getHeight();
  paragraph.delete();
  builder.delete();
  return { width: round(width), height: round(height) };
}

interface StyledTextFields {
  fontFamily: string;
  fontSize: number;
  fontWeight: number;
  lineHeight: number;
  letterSpacing: number;
}

/**
 * Build (not lay out) the ONE segmented paragraph a spanned text node shapes
 * as, mirroring lumen-skia `measure_spanned`. Span byte offsets relocate onto
 * the normalized string via the offset map, segments carry their weight AND
 * italic overrides — the two per-run channels that change measured geometry
 * (A7b made italic the second; decoration and fill do not) — so the
 * shaping-driven width changes are captured. Alignment defaults to LEFT for
 * the same reason as the plain builder. The caller lays out and deletes both.
 */
function buildSpannedParagraph(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  styled: StyledTextFields,
  spans: TextSpan[],
  content: string,
  textTransform: "none" | "uppercase" | "lowercase" | "title",
  blockItalic: boolean,
  align?: TextAlign
): { paragraph: Paragraph; builder: ParagraphBuilder } {
  const familyHasItalic = hasItalicFace(styled.fontFamily);
  const { normalized, map } = normalizeContentMapped(content);
  const normLen = map[map.length - 1];
  const boundaries: Array<[number, number]> = spans.map((span) => {
    const start = map[span.start] ?? normLen;
    const end = map[span.end] ?? normLen;
    return [Math.min(start, end), Math.max(start, end)];
  });
  const core = transformSegments(normalized, boundaries, textTransform);

  // A7b D2 gate: one family-level answer shared with every segment below.
  const baseItalic = blockItalic && familyHasItalic;
  const style = new ck.ParagraphStyle({
    textAlign: align ?? ck.TextAlign.Left,
    textStyle: {
      fontFamilies: resolveFontFamilies(styled.fontFamily, styled.fontWeight, baseItalic),
      fontSize: styled.fontSize,
      fontStyle: {
        weight: styled.fontWeight as unknown as FontWeight,
        slant: baseItalic ? ck.FontSlant.Italic : ck.FontSlant.Upright
      },
      heightMultiplier: styled.lineHeight,
      letterSpacing: styled.letterSpacing
    }
  });
  const builder = ck.ParagraphBuilder.MakeFromFontProvider(style, fontProvider);
  for (const seg of core) {
    const span = seg.span !== null ? spans[seg.span] : undefined;
    const weight = span?.font_weight ?? styled.fontWeight;
    // A7b: italic is OVERRIDE (`span.italic ?? block`) — must byte-mirror the
    // engine's spanned measurer and the CanvasKit painter so measured widths
    // and painted glyphs agree for a de-italicized run.
    const italic = (span?.italic ?? blockItalic) && familyHasItalic;
    builder.pushStyle(
      new ck.TextStyle({
        fontFamilies: resolveFontFamilies(styled.fontFamily, weight, italic),
        fontSize: styled.fontSize,
        fontStyle: {
          weight: weight as unknown as FontWeight,
          slant: italic ? ck.FontSlant.Italic : ck.FontSlant.Upright
        },
        heightMultiplier: styled.lineHeight,
        letterSpacing: styled.letterSpacing
      })
    );
    builder.addText(seg.text);
    builder.pop();
  }
  return { paragraph: builder.build(), builder };
}

/**
 * A6b: unconstrained width/height of a spanned text node measured as ONE
 * segmented paragraph. V0 measures unconstrained (no `max_width`), matching
 * the spanless path.
 */
function measureSpannedParagraph(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  styled: StyledTextFields,
  spans: TextSpan[],
  content: string,
  textTransform: "none" | "uppercase" | "lowercase" | "title",
  blockItalic: boolean
): { width: number; height: number } {
  const { paragraph, builder } = buildSpannedParagraph(
    ck,
    fontProvider,
    styled,
    spans,
    content,
    textTransform,
    blockItalic
  );
  paragraph.layout(Number.MAX_SAFE_INTEGER);
  const width = paragraph.getMaxIntrinsicWidth();
  const height = paragraph.getHeight();
  paragraph.delete();
  builder.delete();
  return { width: round(width), height: round(height) };
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}
