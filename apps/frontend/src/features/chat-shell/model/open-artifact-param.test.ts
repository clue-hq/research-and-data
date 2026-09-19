import assert from "node:assert/strict";
import { test } from "node:test";
import { openArtifactFromParam } from "./open-artifact-param";

const feed = [
  { id: "doc_web", title: "Landing", type: "website" as const },
  { id: "doc_ad", title: "Square", type: "canvas" as const },
];

test("resolves a feed artifact by id with the gallery's kind derivation", () => {
  assert.deepEqual(openArtifactFromParam({ openId: "doc_ad", artifacts: feed }), { id: "doc_ad", kind: "ad", title: "Square" });
  assert.deepEqual(openArtifactFromParam({ openId: "doc_web", artifacts: feed }), { id: "doc_web", kind: "web", title: "Landing" });
});

test("ignores an absent, blank or unknown id — never fabricates a tab", () => {
  assert.equal(openArtifactFromParam({ openId: null, artifacts: feed }), null);
  assert.equal(openArtifactFromParam({ openId: "", artifacts: feed }), null);
  assert.equal(openArtifactFromParam({ openId: "doc_missing", artifacts: feed }), null);
});
