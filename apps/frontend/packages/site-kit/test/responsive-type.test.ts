// Responsive brand type, Task 4: site-kit draws the kit's measured type steps (spec
// docs/superpowers/specs/2026-10-18-responsive-brand-type-design.md §3.3).
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";
import { typeSteps } from "../src/brand-values";
import { buildCatalog } from "../src/catalog";
import { themeCss } from "../src/theme";
import { garner } from "./fixtures/garner";

const twelve = ["display", "headline", "title", "subtitle", "body", "body.small", "caption", "eyebrow", "label", "cta", "stat", "legal"];

function measured(roles: Record<string, object[]> = {}) {
  const brand = garner();
  const all = Object.fromEntries(twelve.map((role) => [`type.${role}`, []]));
  brand.kit = {
    ...brand.kit,
    responsive_type: {
      version: 1, measured_from: 1440, widths: [991, 767], source: { url: "https://garnerhealth.com/", measured_at: "2026-10-18" },
      roles: { ...all, "type.headline": [{ max_width: 991, font_size: 62 }, { max_width: 767, font_size: 44 }], "type.body": [{ max_width: 767, font_size: 15 }], ...roles },
    },
  };
  return brand;
}

test("a measured kit writes desktop sizes and one rule per width", () => {
  const css = themeCss(measured());
  assert.match(css, /--brand-text-headline:87px[;}]/);
  assert.match(css, /@media \(max-width:991px\)\{\.brand-root\{--brand-text-headline:62px\}\}/);
  assert.match(css, /@media \(max-width:767px\)\{\.brand-root\{--brand-text-headline:44px;--brand-text-body:15px\}\}/);
  assert.ok(css.indexOf("@media (max-width:991px)") < css.indexOf("@media (max-width:767px)"), "narrower rules come later");
});

test("a measured role with no steps is a fixed size", () => {
  assert.match(themeCss(measured()), /--brand-text-caption:12px[;}]/);
});

test("a role missing from the section draws as today", () => {
  const brand = measured();
  delete (brand.kit.responsive_type as { roles: Record<string, unknown> }).roles["type.stat"];
  assert.match(themeCss(brand), /--brand-text-stat:clamp\(/);
});

test("a kit without the section draws exactly as today", () => {
  assert.equal(createHash("sha256").update(themeCss(garner())).digest("hex"), "c1f03b053951403c5c3ebbe66ecda130729e1a1e0ddab7d62bace864993d1ebe");
  assert.equal(typeSteps(garner()), null);
});

test("a malformed section is ignored, never half-drawn", () => {
  const brand = garner();
  brand.kit = { ...brand.kit, responsive_type: { roles: { "type.headline": [{ max_width: "991px", font_size: 62 }] } } };
  assert.equal(typeSteps(brand), null);
});

test("brand.md says how type changes with the window", () => {
  const md = buildCatalog(measured(), "Garner Health")["brand/brand.md"];
  assert.match(md, /headline 87px; 62px at 991px and narrower; 44px at 767px and narrower/);
  const still = measured({ "type.headline": [], "type.body": [] });
  assert.match(buildCatalog(still, "Garner Health")["brand/brand.md"], /Type sizes do not change with the window on this site\./);
  assert.doesNotMatch(buildCatalog(garner(), "Garner Health")["brand/brand.md"], /change with the window/);
});
