import type { BrandTypeface } from "../model/brand-context";
import type { MeasuredIcon, MeasuredSample } from "../model/measured-view";
import { useTypefacePreview } from "../hooks/use-typeface-preview";

/**
 * One measured style in one state, drawn with its own measured values only (Wave 2 A9, Task X6).
 * When the kit carries the style's typeface, the Typography panel's loader loads it first (DR-A9-9).
 */
export function StyleSample({
  sample,
  typeface,
  word,
}: {
  sample: MeasuredSample;
  typeface: BrandTypeface | null;
  word: string;
}) {
  return typeface
    ? <LoadedSample sample={sample} typeface={typeface} word={word} />
    : <DrawnSample fontFamily={null} sample={sample} word={word} />;
}

function LoadedSample({ sample, typeface, word }: { sample: MeasuredSample; typeface: BrandTypeface; word: string }) {
  const font = useTypefacePreview(typeface);
  return <DrawnSample fontFamily={font.status === "ready" ? font.fontFamily : null} sample={sample} word={word} />;
}

function DrawnSample({ fontFamily, sample, word }: { fontFamily: string | null; sample: MeasuredSample; word: string }) {
  const measured = sample.style.fontFamily;
  const style = fontFamily ? { ...sample.style, fontFamily: measured ? `${fontFamily}, ${measured}` : fontFamily } : sample.style;
  const icon = sample.icon ? <SampleIcon icon={sample.icon} /> : null;
  return (
    <span aria-hidden="true" style={style}>
      {sample.icon?.position === "start" ? icon : null}
      <span>{word}</span>
      {sample.icon?.position === "end" ? icon : null}
    </span>
  );
}

function SampleIcon({ icon }: { icon: MeasuredIcon }) {
  if (icon.glyph !== null) return <span style={icon.style}>{icon.glyph}</span>;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- the kit's own icon, drawn as an image so its markup never runs (as brand-context-icon.tsx draws icons)
    <img alt="" height={icon.height ?? undefined} src={icon.src ?? undefined} style={icon.style} width={icon.width ?? undefined} />
  );
}
