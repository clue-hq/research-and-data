// T1 catalog: the agent's bounded map of what exists (our version of Ploy's page-build plan).
// It must list every clone with its slots and original wording, our sections with their allowed
// choices, and the brand's tokens and assets, all as plain files.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { buildCatalog } from "./build-catalog";
import { loadBrand } from "../lib/brands";

const out = fs.mkdtempSync(path.join(os.tmpdir(), "catalog-"));
const brand = loadBrand("garner");
buildCatalog("garner", out);
const read = (file: string) => fs.readFileSync(path.join(out, file), "utf-8");

test("the index lists every clone and every one of our sections", () => {
  const index = read("catalog/index.md");
  for (const id of Object.keys(brand.clones)) assert.ok(index.includes(id), `index missing ${id}`);
  for (const type of ["StatsBand", "FeatureSplit", "ProofCard", "CtaBand"]) assert.ok(index.includes(type));
});

test("a clone file lists each slot with its kind and original wording", () => {
  const hero = read("catalog/clones/frag_95041c54da629d99.md");
  assert.match(hero, /headline/);
  assert.match(hero, /text/);
  assert.match(hero, /Top Providers/);
  assert.match(hero, /cta_href/);
  assert.match(hero, /garnerhealth\.com\//, "names its source page");
});

test("a clone file lists visible text that has no slot, for text replacements", () => {
  const hero = read("catalog/clones/frag_95041c54da629d99.md");
  assert.match(hero, /Request a demo/, "the baked button label must be offered for replacement");
});

test("sections.md gives each section's fields and the allowed token choices", () => {
  const sections = read("catalog/sections.md");
  assert.match(sections, /StatsBand/);
  assert.match(sections, /surface/);
  for (const choice of ["page", "card", "muted", "brandSubtle", "brand", "inverse"]) {
    assert.ok(sections.includes(choice), `missing surface choice ${choice}`);
  }
  assert.match(sections, /headingRole/);
});

test("brand.md describes the token choices and lists the assets with descriptions", () => {
  const brandMd = read("brand/brand.md");
  assert.match(brandMd, /Stix Two Text/, "names the heading font");
  assert.match(brandMd, /#047464/i, "names the brand surface colour");
  assert.match(brandMd, /button/i);
  const someAsset = Object.values(brand.assets).find((asset) => asset.description);
  assert.ok(someAsset && brandMd.includes(someAsset.file), "lists asset files");
});
