// The three real kits (garner, conduit, altcarbon: made before measurement) and their minted twins
// (written by subsystems/clue-design/scripts/build_site_kit_brand_fixtures.py from real measured
// values; probe.minted carries every state and motion the real probe measured on its fixture page).
import fs from "node:fs";
import { brandData, type BrandData } from "../../src/brand";

export type KitName = "garner" | "conduit" | "altcarbon" | "garner.minted" | "conduit.minted" | "probe.minted";

export function kitBrand(name: KitName): BrandData {
  const kit = JSON.parse(fs.readFileSync(new URL(`./kits/${name}.json`, import.meta.url), "utf-8"));
  return brandData({ slug: name, kit, fonts: [], kitAssets: {}, clones: [] });
}
