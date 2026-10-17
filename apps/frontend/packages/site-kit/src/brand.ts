// The brand data the sections, the theme, the validator and the catalog need, built from the
// stored kit and clones by the caller (the design API, the agent harness or the editor).
import type { Clone } from "./clone";

/** One font file of the kit, written as an `@font-face` rule by `themeCss` (theme.ts). `themeCss`
 * writes a face only when all four of these hold, and otherwise skips the whole face without a
 * word, so a builder must pass the values in exactly these forms:
 * - `family` keeps at least one character after `cssString` (brand-values.ts) removes quotes,
 *   backslashes, `< > ; { }` and control characters and trims the spaces: a family made only of those
 *   is no family;
 * - `file` is a relative asset path made only of letters, digits and `. _ ~ / -`
 *   (`^[A-Za-z0-9._~/-]+$`): no query string (`?v=2`), no `#`, no spaces, no quotes;
 * - `style` is exactly `normal`, `italic` or `oblique` (not `oblique 10deg`, not `Regular` or `Bold`);
 * - `weight` is `null` (written as 400) or a finite number from 1 to 1000 (not a string like `"700"`). */
export type FontFace = { family: string; weight: number | null; style: string; file: string };
export type BrandAsset = {
  kind: string;
  label: string | null;
  description: string | null;
  mime: string | null;
  file: string;
  logo: unknown;
};
export type BrandData = {
  slug: string;
  kit: Record<string, unknown>;
  fonts: FontFace[];
  assets: Record<string, BrandAsset>;
  clones: Record<string, Clone>;
};

/** Photos and graphics captured with the seller's own sections, offered beside the kit's assets.
 * Clone HTML names its bytes as /asset-store/<sha256> (the fragment sanitizer rewrites them). Each is
 * described by the description stored for its digest, else its alt text, else its section. The alt
 * pattern is lumen_api/site_brand.py's (the optional group holds the gap, so it is tried). */
function cloneImages(clones: Clone[], descriptions: Record<string, string> = {}): Record<string, BrandAsset> {
  const found: Record<string, BrandAsset> = {};
  for (const clone of clones) {
    for (const match of clone.html.matchAll(/<img[^>]*?src="(\/asset-store\/([0-9a-f]{64}))"(?:[^>]*?alt="([^"]*)")?/g)) {
      const file = match[1];
      if (found[file]) continue;
      found[file] = {
        kind: "captured_image",
        label: clone.label,
        description: descriptions[match[2]] || match[3] || `From the seller's section "${clone.label}"`,
        mime: null,
        file,
        logo: null,
      };
    }
  }
  return found;
}

export function brandData(input: {
  slug: string;
  kit: Record<string, unknown>;
  fonts: FontFace[];
  kitAssets: Record<string, BrandAsset>;
  clones: Clone[];
  /** `{digest: text}`: what the capture's describe step said each captured image shows. */
  capturedImageDescriptions?: Record<string, string>;
}): BrandData {
  return {
    slug: input.slug,
    kit: input.kit,
    fonts: input.fonts,
    assets: { ...input.kitAssets, ...cloneImages(input.clones, input.capturedImageDescriptions) },
    clones: Object.fromEntries(input.clones.map((clone) => [clone.id, clone])),
  };
}
