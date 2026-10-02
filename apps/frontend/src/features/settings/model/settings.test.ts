import assert from "node:assert/strict";
import test from "node:test";
import { SettingsRouteSchema } from "./settings";

test("Settings defaults to Profile and preserves the Pages and Data Model routes", () => {
  assert.equal(SettingsRouteSchema.parse([]).section, "profile");
  assert.equal(SettingsRouteSchema.parse(["pages"]).section, "pages");
  assert.equal(SettingsRouteSchema.parse(["data-model"]).entity, undefined);
  for (const entity of ["accounts", "contacts"]) {
    for (const view of ["fields", "display"]) {
      assert.deepEqual(
        SettingsRouteSchema.parse(["data-model", entity, view]),
        {
          section: "data-model",
          entity,
          view,
        },
      );
    }
  }
});

test("Settings rejects unknown routes and nesting outside Data model", () => {
  for (const segments of [
    ["unknown"],
    ["pages", "accounts"],
    ["members", "contacts", "fields"],
    ["data-model", "unknown", "fields"],
    ["data-model", "contacts", "relationships"],
    ["data-model", "accounts", "fields", "extra"],
  ]) {
    assert.equal(SettingsRouteSchema.safeParse(segments).success, false);
  }
});
