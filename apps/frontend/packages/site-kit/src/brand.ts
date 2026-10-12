// The brand data the sections, the theme, the validator and the catalog need, built from the
// stored kit and clones by the caller (the design API, the agent harness or the editor).
import type { Clone } from "./clone";

export type FontFace = { family: string; weight: number | null; style: string; file: string };
export type BrandAsset = {
  kind: string;
  label: string | null;
  description: string | null;
  mime: string | null;
  file: string;
  logo: unknown;
};
export type MeasuredButton = {
  background: string; color: string; borderRadius: string; paddingY: string; paddingX: string;
  height: string; fontFamily: string; fontSize: string; fontWeight: string; letterSpacing: string;
};
export type BrandData = {
  slug: string;
  measured: { primary_button: MeasuredButton | null; heading_on_light?: { color: string } | null } | null;
  kit: Record<string, unknown>;
  fonts: FontFace[];
  assets: Record<string, BrandAsset>;
  clones: Record<string, Clone>;
};

/** Photos and graphics captured with the seller's own sections, offered beside the kit's assets.
 * Clone HTML names its bytes as /asset-store/<sha256> (the fragment sanitizer rewrites them). */
function cloneImages(clones: Clone[]): Record<string, BrandAsset> {
  const found: Record<string, BrandAsset> = {};
  for (const clone of clones) {
    for (const match of clone.html.matchAll(/<img[^>]*?src="(\/asset-store\/[0-9a-f]{64})"[^>]*?(?:alt="([^"]*)")?/g)) {
      const file = match[1];
      if (found[file]) continue;
      found[file] = {
        kind: "captured_image",
        label: clone.label,
        description: match[2] || `From the seller's section "${clone.label}"`,
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
  measured: BrandData["measured"];
}): BrandData {
  return {
    slug: input.slug,
    kit: input.kit,
    measured: input.measured,
    fonts: input.fonts,
    assets: { ...input.kitAssets, ...cloneImages(input.clones) },
    clones: Object.fromEntries(input.clones.map((clone) => [clone.id, clone])),
  };
}
