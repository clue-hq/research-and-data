import assert from "node:assert/strict";
import test from "node:test";
import { dragCarriesFiles } from "./file-drag";

test("only a drag that carries files counts", () => {
  assert.equal(dragCarriesFiles(["Files"]), true);
  assert.equal(dragCarriesFiles(["text/plain"]), false);
  assert.equal(dragCarriesFiles(undefined), false);
});
