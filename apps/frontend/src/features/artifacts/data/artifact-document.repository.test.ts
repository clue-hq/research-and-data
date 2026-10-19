import assert from "node:assert/strict";
import { test } from "node:test";
import { adExportRequestBody } from "./artifact-document.repository";

test("an ad export asks the design API for the saved document at the chosen profile, never persisting", () => {
  const body = adExportRequestBody("PNG", "2x");
  assert.equal(body.format, "png");
  assert.deepEqual(body.page_ids, []);
  assert.equal(body.persist_preflight, false);
  assert.equal((body.profile as { raster: { scale: number } }).raster.scale, 2);
  assert.equal(adExportRequestBody("SVG", "4x").format, "svg");
});
