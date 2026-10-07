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
export type BrandData = {
  slug: string;
  kit: Record<string, unknown>;
  fonts: FontFace[];
  assets: Record<string, BrandAsset>;
  clones: Record<string, Clone>;
};

const DIR = path.join(process.cwd(), "data", "brands");

function read<T>(brand: string, file: string): T {
  return JSON.parse(fs.readFileSync(path.join(DIR, brand, file), "utf-8")) as T;
}

export function loadBrand(slug: string): BrandData {
  const clones = read<Clone[]>(slug, "clones.json");
  return {
    slug,
    kit: read(slug, "kit.json"),
    fonts: read(slug, "fonts.json"),
    assets: read(slug, "assets.json"),
    clones: Object.fromEntries(clones.map((clone) => [clone.id, clone])),
  };
}
