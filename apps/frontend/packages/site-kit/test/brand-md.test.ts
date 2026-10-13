// brand.md over the three real kits and their minted twins (Wave 2 A9, T-A9-1).
import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import { brandData } from "../src/brand";
import { buildCatalog, typeRoleBasis } from "../src/catalog";
import { lint, lintOptionsFor } from "../src/check-section";
import { surfaceClass } from "../src/sections";
import { garner } from "./fixtures/garner";
import { kitBrand, type KitName } from "./fixtures/kits";

const md = (name: KitName) => buildCatalog(kitBrand(name), "Seller")["brand/brand.md"];
const row = (text: string, first: string) => text.split("\n").find((line) => line.startsWith(`| ${first} |`)) ?? "";

test("typeRoleBasis reads measured or derived from a token's provenance", () => {
  assert.equal(typeRoleBasis("website:rendered :: h1"), "measured");
  assert.equal(
    typeRoleBasis("derived:type.headline; measured=font_family,font_size,font_weight,line_height @ website:rendered :: h1"),
    "measured: family, size, weight, line height",
  );
  assert.equal(typeRoleBasis("derived:type.eyebrow; measured=none"), "derived");
  assert.equal(typeRoleBasis("default:type-scale"), "derived");
  assert.equal(typeRoleBasis(undefined), "derived");
});

test("Buttons: the standard button and each style with its values and token names", () => {
  const garnerMd = buildCatalog(garner(), "Garner Health")["brand/brand.md"];
  assert.ok(garnerMd.includes('`look`: `kit.Button look="outline.1"` in a section you write, or `"buttonLook": "outline.1"` on'), garnerMd);
  assert.equal(row(garnerMd, "(none)"), "| (none) | the kit's standard button | #047464 (surface.brand) | #FFFFFF (text.inverse) | none | 16px (radius.button) | — | Used when you name no look. |");
  assert.ok(row(garnerMd, "outline.1").startsWith("| outline.1 | outline | none | #0E1110 (text.primary) | 1px (stroke.width.thin) in the label colour | 9999px (radius.full) | high |"), row(garnerMd, "outline.1"));
  assert.ok(row(garnerMd, "solid.2").includes("| not in the kit; drawn: #047464 (surface.brand), the standard button's fill |"));
  assert.ok(garnerMd.includes("This kit was made before button styles were measured"));
  assert.ok(garnerMd.includes("A button whose text or fill would not stand out from its surface changes"));
});

test("Conduit's demo button reads warm dark once measured, and says what is drawn before", () => {
  const demo = row(md("conduit"), "solid.2").split(" | ");
  assert.equal(demo[2], "not in the kit; drawn: #7CE4FC (surface.brand), the standard button's fill");
  assert.equal(demo[3], "the kit's #FFFFFF (text.inverse) does not read on this fill; drawn: #29251E (text.primary)");
  const minted = row(md("conduit.minted"), "solid.28241e");
  assert.ok(minted.startsWith("| solid.28241e | filled | #28241E (surface.band.28241e) | #FFFFFF (text.inverse) |"), minted);
  assert.ok(!minted.includes("#7CE4FC"));
  assert.ok(!md("conduit.minted").includes("This kit was made before button styles were measured"));
  assert.ok(md("altcarbon").includes('kit.Button look="solid.1"'));
});

test("Buttons says a filled button's light version is the page or the inverse colour, whichever stands out", () => {
  const text = md("conduit").replace(/\n/g, " ");
  assert.ok(text.includes("take their light version (the kit's page or inverse colour, whichever stands out more on that surface, with its text colour). Every other button"), text);
});

test("Cards says a text-only or outline card's text takes the surface's text colour where its own would not stand out", () => {
  const text = md("conduit").replace(/\n/g, " ");
  assert.ok(text.includes("it then takes the style's hover and focus looks from the seller's site. A text-only or outline card's text takes the surface's text colour on any surface where its own would not stand out. |"), text);
});

test("Surfaces: one table, our six and every other surface with where it came from", () => {
  const text = md("garner.minted");
  assert.ok(!text.includes("Our sections take only the six choices above"));
  assert.equal(row(text, "page"), "| page | Page | surface.page | `bg-surface-page text-on-surface-page` | #F9FAF8 | #0E1110 (text.primary) | measured |");
  assert.equal(
    row(text, "band-014036"),
    "| band-014036 | Dark band | surface.band.014036 | `bg-surface-band-014036 text-on-surface-band-014036` | #014036 | #FFFFFF (text.inverse), chosen by contrast | measured: a section background on the seller's site (1 band, 733px tall) |",
  );
  assert.ok(row(md("probe.minted"), "band-014036").includes("#FFFFFF (text.inverse), measured on the band"));
});

const KITS: KitName[] = ["garner", "conduit", "altcarbon", "garner.minted", "conduit.minted", "probe.minted"];
const EXAMPLE = fs.readFileSync(new URL("./fixtures/section-example.tsx", import.meta.url), "utf-8");

test("Surfaces: every row's classes are the classes its surface really has, and lint clean, for every kit", () => {
  for (const name of KITS) {
    const brand = kitBrand(name);
    const surfaces = md(name).split("## Surfaces\n")[1].split("\n## ")[0].split("\n");
    const cells = (line: string) => line.split("|").slice(1, -1).map((cell) => cell.trim());
    const header = cells(surfaces.find((line) => line.startsWith("| choice |")) ?? "");
    const column = header.indexOf("classes");
    assert.ok(column > header.indexOf("kit name") && header.indexOf("kit name") >= 0, `${name}: no "classes" column after "kit name": ${header.join(", ")}`);
    const rows = surfaces.filter((line) => line.startsWith("| ") && !line.startsWith("| choice |")).map(cells);
    assert.ok(rows.length >= 6, name);
    for (const row of rows) {
      const classes = row[column].replace(/^`|`$/g, "");
      assert.equal(classes, surfaceClass(row[0]), `${name} ${row[0]}`);
      const section = EXAMPLE.replace("mt-6 font-body text-body text-ink-secondary", `mt-6 ${classes}`);
      assert.deepEqual(lint(section, lintOptionsFor(brand)), [], `${name} ${row[0]}: ${classes}`);
    }
  }
});

test("Surfaces points a section you write at the classes column", () => {
  const text = md("garner.minted").replace(/\n/g, " ");
  assert.ok(text.includes('or `kit.Shell surface="<choice>"` (or the classes in its "classes" column) in a section you write.'), text);
});

test("Buttons says outline, text-only and see-through styles take the surface's text colour", () => {
  const text = md("conduit").replace(/\n/g, " ");
  assert.ok(text.includes("changes: outline, text-only and see-through styles take the surface's text colour on any surface, and on a dark surface"), text);
});

test("Type roles carry their measured colour; Spacing names the kit's classes", () => {
  const text = buildCatalog(garner(), "Garner Health")["brand/brand.md"];
  assert.ok(row(text, "headline").startsWith("| headline | `font-headline text-headline` | Stix Two Text | 87px | 500 | 1 | #0E1110 (text.primary) |"), row(text, "headline"));
  assert.ok(row(text, "eyebrow").includes("| the surface's text colour |"), "text.brand is derived");
  assert.match(text, /## Spacing\nThe seller's spacing, as classes you can use: `py-section` \(space\.section, \d+px at 1440\)/);
});

test("Cards, Links and Motion come from the measured kit, with plain fallbacks", () => {
  const probe = md("probe.minted");
  assert.match(probe, /## Cards\n`kit\.Card` draws a card/);
  assert.match(probe, /Text links look like the seller's own: #0D2B25 \([a-z.0-9-]+\), underlined on hover, #047464 \([a-z.0-9-]+\) on hover\./);
  assert.ok(probe.includes("| `brand-motion-pulse` | opacity 1 → .4, transform scale(1) → scale(1.2); repeats forever, alternating | 1.6s ease-in-out | 1 element: div#pulse.pulse |"), probe);
  assert.match(probe, /\| `brand-motion-reveal-[0-9a-f]{8}` \| fades in from opacity 0 and moves into place from 24px below as it scrolls into view \| ease-out \|/);
  assert.ok(probe.includes("The seller's site also moves in ways a published page cannot, because they need a script: a scripted animation (div#spin.spin). Do not imitate them."));
  assert.ok(probe.includes("Each style's hover, pressed and focus looks, and the motion between them, come from the seller's"));
  const old = md("garner");
  assert.ok(old.includes("The kit recorded no text-link style, so text links are underlined in the surrounding text's"));
  assert.ok(old.includes("The seller's site shows no motion a page can reuse"));
});

test("BrandData has no spike-only measurement", () => {
  const brand = brandData({ slug: "x", kit: {}, fonts: [], kitAssets: {}, clones: [] });
  assert.ok(!("measured" in brand));
});
