import type { BrandTypeface } from "./brand-context";

/** Quote CSS strings, including the HTML style end-tag boundary. */
function cssString(value: string): string {
  return `"${value.replace(/[\\"\n\r\f<]/g, (character) => `\\${character.charCodeAt(0).toString(16)} `)}"`;
}

export function typefacePreviewFamily(typeface: BrandTypeface): string {
  return cssString(typeface.previewFamily ?? (typeface.family === "Satoshi Variable" ? "Satoshi" : typeface.family));
}

/** Use the kit's actual face descriptors, with stored bytes served through the BFF. */
export function typefacePreviewCss(typefaces: readonly BrandTypeface[]): string {
  return typefaces.flatMap((typeface) => (typeface.faces ?? []).map((face) => `
@font-face {
  font-family: ${typefacePreviewFamily(typeface)};
  src: url(${cssString(face.url)});
  font-weight: ${face.weight};
  font-style: ${face.style};
  font-display: swap;
}`)).join("\n");
}
