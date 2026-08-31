import assert from "node:assert/strict";
import test from "node:test";
import {
  ARTIFACT_ADVANCED_TABS,
  ARTIFACT_PUBLISH_STATUSES,
  ARTIFACT_SHARE_EXPORT_FORMATS,
  ARTIFACT_SHARE_VIEWS,
  slugifyArtifactTitle,
} from "./artifact-sharing";

test("artifact sharing exposes the production shell states", () => {
  assert.deepEqual(ARTIFACT_SHARE_EXPORT_FORMATS, ["ZIP", "PDF"]);
  assert.deepEqual(ARTIFACT_PUBLISH_STATUSES, [
    "draft",
    "publishing",
    "published",
  ]);
  assert.deepEqual(ARTIFACT_SHARE_VIEWS, ["main", "advanced"]);
  assert.deepEqual(ARTIFACT_ADVANCED_TABS, ["page", "html"]);
});

test("artifact titles become stable publishing slugs", () => {
  assert.equal(slugifyArtifactTitle(" Landing page — OpenAI "), "landing-page-openai");
  assert.equal(slugifyArtifactTitle(""), "untitled-artifact");
});
