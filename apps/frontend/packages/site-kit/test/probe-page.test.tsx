import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { PROBE_PAGE, probePage } from "./fixtures/write-probe-page";

test("the design API's probe page is what site-kit draws today", () => {
  assert.equal(fs.readFileSync(PROBE_PAGE, "utf-8"), probePage(), "run: npx tsx test/fixtures/write-probe-page.tsx");
});
