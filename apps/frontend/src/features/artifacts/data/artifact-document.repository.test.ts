import assert from "node:assert/strict";
import { test } from "node:test";
import { adExportRequestBody, webExportFilename } from "./artifact-document.repository";

test("an ad export asks the design API for the saved document at the chosen profile, never persisting", () => {
  const body = adExportRequestBody("PNG", "2x");
  assert.equal(body.format, "png");
  assert.deepEqual(body.page_ids, []);
  assert.equal(body.persist_preflight, false);
  assert.equal((body.profile as { raster: { scale: number } }).raster.scale, 2);
  assert.equal(adExportRequestBody("SVG", "4x").format, "svg");
});

test("a web export takes its filename from the design API's own content-disposition, quoted", () => {
  assert.equal(
    webExportFilename("Spring launch", 'attachment; filename="spring-launch-1a2b3c4d.zip"'),
    "spring-launch-1a2b3c4d.zip",
  );
});

test("a web export takes an unquoted content-disposition filename too", () => {
  assert.equal(
    webExportFilename("Spring launch", "attachment; filename=spring-launch-1a2b3c4d.zip"),
    "spring-launch-1a2b3c4d.zip",
  );
});

test("a web export with no content-disposition falls back to the sanitized title", () => {
  assert.equal(webExportFilename('Spring: launch/2026 "big"', null), "Spring launch 2026 big.zip");
});

test("a web export whose title is blank falls back to website.zip", () => {
  assert.equal(webExportFilename("   ", null), "website.zip");
});
