import type { CanvasKit, FontWeight, TypefaceFontProvider } from "canvaskit-wasm";
import type { Scene, TextSpan } from "../contracts";
import { resolvedTextFields } from "../renderAdapter";
import { hasItalicFace, resolveFontFamilies } from "./loadCanvasKit";
import { applyTextTransform, normalizeContentMapped, transformSegments } from "../textTransform";
import type { TextMeasurement } from "../wasmEngine";

/**
 * Wave 3 C4 (measure-then-inject): measure every text node with SkParagraph
 * and emit the metrics the engine consumes (`WasmEngine.setMeasurements`).
 * Using the same Inter bytes the server uses makes editor `computed` geometry
 * Skia-faithful, closing the E3 caveat for hug-sized text without a wasm→JS
 * callback during layout.
 *
 * V0 measures unconstrained (no `max_width`), matching the key the engine uses
 * for hug/unconstrained text; constrained (wrapped) text reuses the same
 * payload shape and is refined as the convergence matures.
 */
export function skiaMeasurements(ck: CanvasKit, fontProvider: TypefaceFontProvider, scene: Scene): TextMeasurement[] {
  const out: TextMeasurement[] = [];
  for (const node of Object.values(scene.nodes)) {
    if (node.kind.kind !== "text") {
      continue;
    }
    const t = node.kind;
    const wrap = t.wrap ?? "no_wrap";
    const direction = t.direction ?? "ltr";
    // K1.5: measure with the kit's RESOLVED type-role fields (style_token /
    // *_token over the literals). Agent proposals insert skeleton text
    // (Inter 16) whose real 80pt style arrives only at server preflight —
    // measuring the skeleton fed relayout ~17px lines, and the accept-time
    // freeze baked those collapsed POSITIONS (the LUMV0903/0810 ghost). The
    // measurement RECORD keeps the node's literal fields: that's the key the
    // engine matches on — only the measured extent reflects the resolution.
    const styled = resolvedTextFields(t);
    // A6a: the geometry-affecting typography fields. They also enter the
    // engine's `measure_key`, so the record MUST carry them or the layout
    // lookup misses this override and falls back to the heuristic.
    const textTransform = t.text_transform ?? "none";
    const truncate = t.truncate ?? false;
    const paragraphSpacing = t.paragraph_spacing ?? 0;
    const italic = t.italic ?? false;
    const spans = t.spans ?? [];
    const record: TextMeasurement = {
      content: t.content,
      font_family: t.font_family,
      font_size: t.font_size,
      font_weight: t.font_weight,
      line_height: t.line_height ?? 1.2,
      letter_spacing: t.letter_spacing ?? 0,
      wrap,
      max_lines: t.max_lines ?? null,
      direction,
      text_transform: textTransform,
      truncate,
      paragraph_spacing: paragraphSpacing,
      // A7b: block italic is a `measure_key` input (span italic rides in
      // `spans`), so the record MUST carry it or the engine's layout lookup
      // misses and falls back to the heuristic.
      italic,
      width: 0,
      height: 0
    };
    if (spans.length > 0) {
      // A6b: spanned nodes measure ONE segmented paragraph — weight-span
      // overrides change shaping widths, so the styles must be in the measured
      // paragraph (review fix). NO paragraph-gap stacking when spans exist
      // (LUMV0907); the record carries the raw spans so the engine's spans-keyed
      // measure lookup hits instead of falling back to the heuristic.
      const { width, height } = measureSpannedParagraph(ck, fontProvider, styled, spans, t.content, textTransform, italic);
      record.spans = spans;
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

/** Unconstrained SkParagraph width/height for a text style. */
export function measureParagraph(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  input: ParagraphInput
): { width: number; height: number } {
  // A7b D2 gate: mirror the engine — Italic only when a real face exists,
  // so measured widths reflect the same (upright) shaping the paint uses.
  const italic = (input.italic ?? false) && hasItalicFace(input.fontFamily);
  const style = new ck.ParagraphStyle({
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
  const paragraph = builder.build();
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
 * A6b: unconstrained width/height of a spanned text node measured as ONE
 * segmented paragraph, mirroring lumen-skia `measure_spanned`. Span byte offsets
 * relocate onto the normalized string via the offset map, segments carry their
 * weight AND italic overrides — the two per-run channels that change measured
 * geometry (A7b made italic the second; decoration and fill do not) — and the
 * paragraph is laid out with each segment's style pushed so the shaping-driven
 * width changes are captured. V0 measures unconstrained (no `max_width`),
 * matching the spanless path.
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
  const paragraph = builder.build();
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
