import type { BrandTypeface } from "./brand-context";

export const TYPEFACE_SAMPLE = "a quick brown fox jumps over a lazy dog";

/** Quote a CSS font-family or source without allowing another declaration. */
export function cssFontString(value: string): string {
  return `"${value.replace(/[\\"\n\r\f<]/g, (character) => `\\${character.charCodeAt(0).toString(16)} `)}"`;
}

/** Prefer a regular upright face; otherwise display an actual available weight/style. */
export function typefacePreviewSpec(typeface: BrandTypeface) {
  const face = [...(typeface.faces ?? [])].sort((a, b) =>
    Number(a.style !== "normal") - Number(b.style !== "normal")
    || Math.abs(a.weight - 400) - Math.abs(b.weight - 400),
  )[0];
  const registeredFamily = cssFontString(typeface.family === "Satoshi Variable" ? "Satoshi" : typeface.family);
  return {
    family: typeface.previewFamily ?? `clue-preview-${encodeURIComponent(typeface.id)}-${encodeURIComponent(typeface.family)}`,
    registeredFamily: face ? null : registeredFamily,
    // Keep every captured subset of the chosen variant; a family may split its
    // glyphs across several files with the same weight and style.
    sources: face ? [...new Set((typeface.faces ?? [])
      .filter((candidate) => candidate.weight === face.weight && candidate.style === face.style)
      .map((candidate) => `url(${cssFontString(candidate.url)})`))] : [`local(${registeredFamily})`],
    weight: face?.weight ?? 400,
    style: face?.style ?? "normal",
  };
}
