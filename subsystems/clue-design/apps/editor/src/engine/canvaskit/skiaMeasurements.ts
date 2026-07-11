import type { CanvasKit, FontWeight, TypefaceFontProvider } from "canvaskit-wasm";
import type { Scene } from "../contracts";
import { resolvedTextFields } from "../renderAdapter";
import { applyTextTransform } from "../textTransform";
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
    // Case transform changes glyph widths, so measure the TRANSFORMED string
    // (the record's `content` key stays the literal, matching the node).
    const measuredContent = applyTextTransform(textTransform, t.content);
    const { width, height } = measureParagraph(ck, fontProvider, {
      content: measuredContent,
      fontFamily: styled.fontFamily,
      fontSize: styled.fontSize,
      fontWeight: styled.fontWeight,
      lineHeight: styled.lineHeight,
      letterSpacing: styled.letterSpacing
    });
    // Paragraph spacing adds `gap` px at each `\n` break (unconstrained hug);
    // mirrors the measurer stacking each paragraph with the extra gap.
    const gap = Number.isFinite(paragraphSpacing) && paragraphSpacing > 0 ? paragraphSpacing : 0;
    const breakCount =
      gap > 0 ? Math.max(0, measuredContent.replace(/\\n/g, "\n").split("\n").length - 1) : 0;
    out.push({
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
      width,
      height: height + breakCount * gap
    });
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
}

/** Unconstrained SkParagraph width/height for a text style. */
export function measureParagraph(
  ck: CanvasKit,
  fontProvider: TypefaceFontProvider,
  input: ParagraphInput
): { width: number; height: number } {
  const style = new ck.ParagraphStyle({
    textStyle: {
      fontFamilies: [input.fontFamily],
      fontSize: input.fontSize,
      // A6a D6.1: the exact numeric weight (no 4-bucket snap), matching the
      // painter and the server so measured widths and painted glyphs agree.
      // CanvasKit accepts a raw number here; the enum type is just the TS shape.
      fontStyle: { weight: input.fontWeight as unknown as FontWeight },
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

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}
