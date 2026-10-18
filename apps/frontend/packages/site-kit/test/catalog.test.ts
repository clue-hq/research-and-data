// T1 catalog: the agent's bounded map of what exists (our version of Ploy's page-build plan).
// It must list every clone with its slots and original wording, our sections with their allowed
// choices, and the brand's tokens and assets, all as plain files.
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildCatalog } from "../src/catalog";
import { garner } from "./fixtures/garner";

const brand = garner();
const files = buildCatalog(brand, "Garner Health");
const read = (file: string) => {
  assert.ok(file in files, `the catalog has no ${file}`);
  return files[file];
};

test("the catalog is the index, one card per clone, sections.md and brand.md", () => {
  const expected = [
    "catalog/index.md",
    ...Object.keys(brand.clones).map((id) => `catalog/clones/${id}.md`),
    "catalog/sections.md",
    "brand/brand.md",
  ];
  assert.deepEqual(Object.keys(files).sort(), expected.sort());
});

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
  assert.match(sections, /buttonLook/);
  assert.ok(sections.includes("a button style from brand/brand.md (Buttons): outline.1"));
});

test("brand.md describes the token choices and lists the assets with descriptions", () => {
  const brandMd = read("brand/brand.md");
  assert.match(brandMd, /Stix Two Text/, "names the heading font");
  assert.match(brandMd, /#047464/i, "names the brand surface colour");
  assert.match(brandMd, /button/i);
  const someAsset = Object.values(brand.assets).find((asset) => asset.description);
  assert.ok(someAsset && brandMd.includes(someAsset.file), "lists asset files");
});

test("a degraded clone says so in the index and on its card", () => {
  const degradedBrand = garner();
  const first = Object.values(degradedBrand.clones)[0];
  degradedBrand.clones[first.id] = { ...first, degraded_note: "the band lost its images when it was captured." };
  const degradedFiles = buildCatalog(degradedBrand, "Garner Health");
  const line = degradedFiles["catalog/index.md"].split("\n").find((l) => l.includes(`\`${first.id}\``)) ?? "";
  assert.ok(line.endsWith(" · degraded"), line);
  assert.match(degradedFiles[`catalog/clones/${first.id}.md`], /\n\nDegraded: the band lost its images when it was captured\.\n/);
  const healthy = files["catalog/index.md"].split("\n").find((l) => l.includes(`\`${first.id}\``)) ?? "";
  assert.ok(!healthy.includes("degraded"), healthy);
});

test("a section the page already uses but the catalog no longer offers is kept out of the catalog", () => {
  // Founder ruling Q5 (2026-10-12): the brand data carries every section the page itself uses,
  // whatever its status, so the page still draws, saves and publishes; the catalog (what the agent
  // may newly place) stays current-only.
  const pinnedBrand = garner();
  const first = Object.values(pinnedBrand.clones)[0];
  pinnedBrand.clones[first.id] = { ...first, in_catalog: false };
  const pinnedFiles = buildCatalog(pinnedBrand, "Garner Health");
  assert.ok(!pinnedFiles["catalog/index.md"].includes(`\`${first.id}\``));
  assert.equal(pinnedFiles[`catalog/clones/${first.id}.md`], undefined);
});

test("brand.md lists the font library's families with their weights, after the brand's own fonts", () => {
  const brand = { ...garner(), libraryFonts: [{ family: "Lora", category: "serif", faces: [{ weight: 400, style: "normal", file: "/asset-store/aa" }, { weight: 700, style: "normal", file: "/asset-store/bb" }] }] };
  const md = buildCatalog(brand, "Garner Health")["brand/brand.md"];
  assert.ok(md.includes("## Other fonts"), md);
  assert.ok(md.includes("- Lora (serif): 400, 700"));
  assert.ok(!buildCatalog(garner(), "Garner Health")["brand/brand.md"].includes("## Other fonts"), "no library, no section");
});

// Plan 6 (ruling R13): a kit's header and footer templates are listed first, for shell.json, and
// not among the seller's page sections.
test("templates are listed first and not among page sections", () => {
  const brand = garner();
  const template = { ...Object.values(brand.clones)[0], id: "frag_00000000000000ad", role: "site_header", label: "Header template — garnerhealth.com", section_index: null };
  brand.clones = { ...brand.clones, [template.id]: template };
  const index = buildCatalog(brand, "Garner Health")["catalog/index.md"];
  const templates = index.indexOf("## Header and footer templates (use them in shell.json)");
  const sections = index.indexOf("## The seller's own sections (clones), by source page");
  assert.ok(templates >= 0 && templates < sections, index.slice(0, 600));
  assert.match(index.slice(templates, sections), /`frag_00000000000000ad` · site_header · Header template — garnerhealth\.com/);
  assert.doesNotMatch(index.slice(sections), /frag_00000000000000ad/);
  assert.ok(buildCatalog(brand, "Garner Health")["catalog/clones/frag_00000000000000ad.md"], "the template has its card");
});
