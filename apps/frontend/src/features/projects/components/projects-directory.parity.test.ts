import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";

// sha256 of the dummy's projects-directory.module.css at port-of-spain@9fc902a. Recompute with
// `shasum -a 256 <dummy path>` when the founder re-lifts the screen; never edit the CSS here.
const DUMMY_CSS_SHA256 =
  "8882951e79326cb194534766a4de275536468bd39a954aa31375e8a704b9ad33";

test("the lifted directory CSS is byte-identical to the dummy's", () => {
  const bytes = readFileSync(
    new URL("./projects-directory.module.css", import.meta.url),
  );
  assert.equal(createHash("sha256").update(bytes).digest("hex"), DUMMY_CSS_SHA256);
});
