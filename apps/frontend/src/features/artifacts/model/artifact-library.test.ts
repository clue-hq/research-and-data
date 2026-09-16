import assert from "node:assert/strict";
import { test } from "node:test";
import { ArtifactWireSchema, libraryKey, toLibraryArtifact } from "./artifact-library";

const row = ArtifactWireSchema.parse({
  id: "doc_1", document_id: "doc_1", project_id: "prj_1", project_title: "Launch",
  kind: "ad", title: "Square ad", status: "draft", current_version: 3,
  created_at: "2026-09-01T09:00:00+00:00", updated_at: "2026-09-02T09:00:00+00:00",
  origin_thread_id: "thr_1", artifact_type: "linkedin_square_ad", width_px: 1080, height_px: 1080,
  account: { id: "acc_1", name: "Acme", domain: "acme.example", account_entity_id: null },
  archived_at: null, saved: true, last_viewed_at: "2026-09-03T09:00:00+00:00",
});

test("an ad row maps to a canvas artifact with real size, channel, account, project and marks", () => {
  const artifact = toLibraryArtifact(row, new Date("2026-09-03T12:00:00Z"));
  assert.equal(artifact.type, "canvas");
  assert.equal(artifact.kind, "ad");
  assert.equal(artifact.collateralType, "linkedin-ad");
  assert.deepEqual(artifact.size, { category: "square", height: 1080, label: "1080 × 1080", width: 1080 });
  assert.equal(artifact.imagePath, "/api/clue/design/documents/doc_1/thumbnail?v=3");
  assert.equal(artifact.projectId, "prj_1");
  assert.equal(artifact.projectTitle, "Launch");
  assert.equal(artifact.accountId, "acc_1");
  assert.equal(artifact.accountName, "Acme");
  assert.equal(artifact.accountLogoPath, "/api/source-favicon?domain=acme.example");
  assert.equal(artifact.account?.accountEntityId, undefined);
  assert.equal(artifact.saved, true);
  assert.equal(artifact.lastViewedAt, "2026-09-03T09:00:00.000Z");
  assert.equal(artifact.updatedAt, "2026-09-02T09:00:00.000Z");
  assert.equal(artifact.archivedAt, undefined);
});

test("a web row is a website artifact; absent account and size stay absent; last-viewed falls back to updated", () => {
  const artifact = toLibraryArtifact(
    ArtifactWireSchema.parse({ ...row, id: "doc_2", document_id: "doc_2", kind: "web", artifact_type: null,
      width_px: null, height_px: null, account: null, saved: false, last_viewed_at: null,
      archived_at: "2026-09-04T09:00:00+00:00" }),
    new Date("2026-09-03T12:00:00Z"),
  );
  assert.equal(artifact.type, "website");
  assert.equal(artifact.collateralType, "microsite");
  assert.equal(artifact.size, undefined);
  assert.equal(artifact.account, undefined);
  assert.equal(artifact.accountLogoPath, undefined);
  assert.equal(artifact.lastViewedAt, "2026-09-02T09:00:00.000Z");
  assert.equal(artifact.archivedAt, "2026-09-04T09:00:00.000Z");
});

test("the library key is project plus artifact id, never the title", () => {
  assert.equal(libraryKey({ projectId: "p", id: "a" }), JSON.stringify(["p", "a"]));
  assert.notEqual(libraryKey({ projectId: "p", id: "a" }), libraryKey({ projectId: "q", id: "a" }));
});
