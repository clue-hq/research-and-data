import assert from "node:assert/strict";
import { test } from "node:test";
import { DesignArtifactListItemSchema, DesignArtifactListWireSchema } from "../model/artifact";
import { toProjectArtifact } from "./gallery";

const NOW = new Date("2026-10-11T12:00:00Z");

function item(kind: "web" | "ad" | "site") {
  return DesignArtifactListItemSchema.parse({
    id: `art-${kind}`,
    projectId: "prj-1",
    documentId: `doc-${kind}`,
    kind,
    title: `A ${kind} document`,
    currentVersionId: "3",
    status: "draft",
    createdAt: "2026-10-11T09:00:00+00:00",
    updatedAt: "2026-10-11T10:00:00+00:00",
    originThreadId: "thread-1",
  });
}

test("the feed wire accepts a site document (Contract 8)", () => {
  const [parsed] = DesignArtifactListWireSchema.parse({
    data: [
      {
        id: "art-1",
        project_id: "prj-1",
        document_id: "doc-1",
        kind: "site",
        title: "Syracuse",
        status: "draft",
        current_version_id: "3",
        created_at: "2026-10-11T09:00:00+00:00",
        updated_at: "2026-10-11T10:00:00+00:00",
        origin_thread_id: "thread-1",
      },
    ],
  });
  assert.equal(parsed.kind, "site");
});

test("a site card is a website microsite that remembers it is a site", () => {
  const card = toProjectArtifact(item("site"), { now: NOW });
  assert.equal(card.type, "website");
  assert.equal(card.collateralType, "microsite");
  assert.equal(card.documentKind, "site");
});

test("web and ad cards carry their own document kind", () => {
  assert.equal(toProjectArtifact(item("web"), { now: NOW }).documentKind, "web");
  assert.equal(toProjectArtifact(item("ad"), { now: NOW }).documentKind, "ad");
});
