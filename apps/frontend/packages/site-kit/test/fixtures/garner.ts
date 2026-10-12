// The Garner brand and sites as the spike exported them (trials/puck-spike/data/brands/garner and
// data/sites), built with brandData the way the design API, the harness and the editor build theirs.
// clones.json is trimmed to the five clones garner-syracuse uses, each with a stub for its CSS.
import fs from "node:fs";
import { brandData, type BrandData } from "../../src/brand";

const read = (file: string) => JSON.parse(fs.readFileSync(new URL(`./${file}`, import.meta.url), "utf-8"));

export function garner(): BrandData {
  return brandData({
    slug: "garner",
    kit: read("kit.json"),
    fonts: read("fonts.json"),
    kitAssets: read("assets.json"),
    clones: read("clones.json"),
  });
}

/** A stored site ({brand, shell, pages}): "garner-syracuse" or "conduit-atrium". */
export const site = (name: string) => read(`${name}.json`);
