// The Brand page's entry point (Wave 2 A9, Task X6): the same reading as a site, and server-safe.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import * as view from "../src/brand-view";
import { kitBrand } from "./fixtures/kits";

test("the Brand page's entry point reads a measured kit the way a site does", () => {
  const brand = kitBrand("probe.minted");
  const solid = view.measuredComponents(brand)!.styles!.find((style) => style.variant === "solid.047464")!;
  assert.equal(view.partsFromSlots(brand, solid.rest).parts.fill, "#047464");
  assert.ok(view.surfaceLabels(brand).get("surface.band.014036")?.startsWith("Dark band"));
  assert.ok(view.motionEntries(brand).some((entry) => entry.className === "brand-motion-pulse"));
});

test("the entry point and every module it reads stay free of React and Puck", () => {
  for (const file of ["brand-view.ts", "brand.ts", "brand-values.ts", "looks.ts", "surfaces.ts", "schemas.ts"]) {
    const source = fs.readFileSync(new URL(`../src/${file}`, import.meta.url), "utf-8");
    assert.doesNotMatch(source, /from "(react|react-dom|@puckeditor\/core)[^"]*"|from "\.\/[^"]+\.tsx"/, file);
  }
});
