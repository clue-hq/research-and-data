// The three real kits (garner, conduit, altcarbon: made before measurement), Garner's first measured
// kit (garner.v3: the lane DB's brand_kit_ing_ba0708281cb44f7c847dfb8949110103 version 3, exported
// 2026-10-17) and the minted twins
// (written by subsystems/clue-design/scripts/build_site_kit_brand_fixtures.py from real measured
// values; probe.minted carries every state and motion the real probe measured on its fixture page).
import fs from "node:fs";
import { brandData, type BrandData } from "../../src/brand";

export type KitName = "garner" | "conduit" | "altcarbon" | "garner.v3" | "garner.minted" | "conduit.minted" | "probe.minted";

export function kitBrand(name: KitName): BrandData {
  const kit = JSON.parse(fs.readFileSync(new URL(`./kits/${name}.json`, import.meta.url), "utf-8"));
  return brandData({ slug: name, kit, fonts: [], kitAssets: {}, clones: [] });
}
