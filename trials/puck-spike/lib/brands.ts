// Brand data exported by export/export_brand.py, read on the server and handed to Puck as
// metadata (the editor and the published render both receive it).
import fs from "node:fs";
import path from "node:path";
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

const DIR = path.join(process.cwd(), "data", "brands");

function read<T>(brand: string, file: string): T {
  return JSON.parse(fs.readFileSync(path.join(DIR, brand, file), "utf-8")) as T;
}

/** Photos and graphics captured with the seller's own sections, offered beside the kit's assets. */
function cloneImages(clones: Clone[]): Record<string, BrandAsset> {
  const found: Record<string, BrandAsset> = {};
  for (const clone of clones) {
    for (const match of clone.html.matchAll(/<img[^>]*?src="([^"]+\.(?:png|jpe?g|webp|avif))"[^>]*?(?:alt="([^"]*)")?/g)) {
      const file = match[1];
      if (!file.startsWith("/brands/") || found[file]) continue;
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

export function loadBrand(slug: string): BrandData {
  const clones = read<Clone[]>(slug, "clones.json");
  const kitAssets = read<Record<string, BrandAsset>>(slug, "assets.json");
  return {
    slug,
    kit: read(slug, "kit.json"),
    measured: fs.existsSync(path.join(DIR, slug, "measured.json")) ? read(slug, "measured.json") : null,
    fonts: read(slug, "fonts.json"),
    assets: { ...kitAssets, ...cloneImages(clones) },
    clones: Object.fromEntries(clones.map((clone) => [clone.id, clone])),
  };
}
