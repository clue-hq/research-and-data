import assert from "node:assert/strict";
import { test } from "node:test";
import { ArtifactWireSchema, toLibraryArtifact } from "./artifact-library";

test("a site row in the artifacts library is a website that remembers it is a site", () => {
  const row = ArtifactWireSchema.parse({
    id: "art-1",
    document_id: "doc-1",
    project_id: "prj-1",
    project_title: "Syracuse ABM",
    kind: "site",
    title: "Syracuse",
    status: "draft",
    current_version: 3,
    created_at: "2026-10-11T09:00:00+00:00",
    updated_at: "2026-10-11T10:00:00+00:00",
    origin_thread_id: "thread-1",
    artifact_type: null,
    width_px: null,
    height_px: null,
    account: null,
    archived_at: null,
    saved: false,
    last_viewed_at: null,
  });
  const artifact = toLibraryArtifact(row, new Date("2026-10-11T12:00:00Z"));
  assert.equal(artifact.kind, "site");
  assert.equal(artifact.type, "website");
  assert.equal(artifact.collateralType, "microsite");
  assert.equal(artifact.documentKind, "site");
});
