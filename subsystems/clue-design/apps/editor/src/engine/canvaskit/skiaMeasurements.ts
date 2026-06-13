import type { CanvasKit, FontMgr } from "canvaskit-wasm";
import type { Scene } from "../contracts";
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
export function skiaMeasurements(ck: CanvasKit, fontMgr: FontMgr, scene: Scene): TextMeasurement[] {
  const out: TextMeasurement[] = [];
  for (const node of Object.values(scene.nodes)) {
    if (node.kind.kind !== "text") {
      continue;
    }
    const t = node.kind;
    const lineHeight = t.line_height ?? 1.2;
    const letterSpacing = t.letter_spacing ?? 0;
    const wrap = t.wrap ?? "no_wrap";
    const direction = t.direction ?? "ltr";
    const { width, height } = measureParagraph(ck, fontMgr, {
      content: t.content,
      fontFamily: t.font_family,
      fontSize: t.font_size,
      fontWeight: t.font_weight,
      lineHeight,
      letterSpacing
    });
    out.push({
      content: t.content,
      font_family: t.font_family,
      font_size: t.font_size,
      font_weight: t.font_weight,
      line_height: lineHeight,
      letter_spacing: letterSpacing,
      wrap,
      max_lines: t.max_lines ?? null,
      direction,
      width,
      height
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
  fontMgr: FontMgr,
  input: ParagraphInput
): { width: number; height: number } {
  const style = new ck.ParagraphStyle({
    textStyle: {
      fontFamilies: [input.fontFamily],
      fontSize: input.fontSize,
      fontStyle: { weight: fontWeight(ck, input.fontWeight) },
      heightMultiplier: input.lineHeight,
      letterSpacing: input.letterSpacing
    }
  });
  const builder = ck.ParagraphBuilder.Make(style, fontMgr);
  builder.addText(input.content);
  const paragraph = builder.build();
  paragraph.layout(Number.MAX_SAFE_INTEGER);
  const width = paragraph.getMaxIntrinsicWidth();
  const height = paragraph.getHeight();
  paragraph.delete();
  builder.delete();
  return { width: round(width), height: round(height) };
}

function fontWeight(ck: CanvasKit, weight: number) {
  if (weight >= 700) return ck.FontWeight.Bold;
  if (weight >= 600) return ck.FontWeight.SemiBold;
  if (weight >= 500) return ck.FontWeight.Medium;
  return ck.FontWeight.Normal;
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}
