import assert from "node:assert/strict";
import { test } from "node:test";
import { buildComposerCatalog } from "./composer-context-catalog";
import { ProjectArtifactSchema } from "./project-workspace";

test("a site lists in the composer exactly like a website: a Microsite design document", () => {
  const catalog = buildComposerCatalog({
    artifacts: [
      ProjectArtifactSchema.parse({
        collateralType: "microsite",
        documentId: "doc-1",
        documentKind: "site",
        editedLabel: "Last edited today",
        id: "art-1",
        originThreadId: "thread-1",
        title: "Syracuse",
        type: "website",
        version: 3,
      }),
    ],
    documents: [],
    entities: [],
  });
  assert.deepEqual(
    catalog.map((entity) => [entity.category, entity.secondaryLabel, entity.type, entity.id]),
    [["microsites", "Microsite", "design_document", "doc-1"]],
  );
});
