// The label ladder reads the viewer's calendar days, so "today"/"yesterday"
// depend on the runtime zone. Node runs each test file in its own process, so
// pinning UTC here makes the boundary cases deterministic without touching the
// mapper's (correct) local-day behaviour.
process.env.TZ = "UTC";

import assert from "node:assert/strict";
import test from "node:test";
import { normalizeGalleryArtifact } from "@/features/gallery/model/project-gallery";
import { ProjectArtifactSchema } from "@/features/projects/model/project-workspace";
import { DesignArtifactListItemSchema } from "../model/artifact";
import { editedLabelFor, toProjectArtifact } from "./gallery";

// Slice 2: the gallery feed's pure mapper — one listed design artifact (the
// backend's leg-derived list item, parsed by the seam) → the gallery's
// `ProjectArtifact`. Every fixture below is the real wire shape the Slice-1
// endpoint serves (`GET /api/v1/projects/{project_id}/design-artifacts`),
// including its Postgres timestamptz offsets.

const NOW = new Date("2026-08-18T12:00:00.000Z");

function listItem(overrides: Record<string, unknown> = {}) {
  return DesignArtifactListItemSchema.parse({
    id: "doc-web-1",
    projectId: "prj-1",
    documentId: "doc-web-1",
    kind: "web",
    title: "Launch landing page",
    status: "draft",
    currentVersionId: "4",
    createdAt: "2026-08-14T09:15:00+00:00",
    updatedAt: "2026-08-18T09:15:00+00:00",
    originThreadId: "thread-9",
    ...overrides,
  });
}

test("a listed design artifact maps onto the gallery's website artifact", () => {
  const artifact = toProjectArtifact(listItem(), { now: NOW });

  assert.equal(artifact.id, "doc-web-1");
  assert.equal(artifact.title, "Launch landing page");
  assert.equal(artifact.type, "website");
  // The gallery's collateral vocabulary has no "website" member; a website
  // artifact is a microsite there (the gallery's own default for the type).
  assert.equal(artifact.collateralType, "microsite");
  assert.equal(artifact.originThreadId, "thread-9");
});

test("real timestamps survive as the schema's UTC instants", () => {
  const artifact = toProjectArtifact(
    listItem({
      createdAt: "2026-08-14T09:15:00.123456+00:00",
      updatedAt: "2026-08-18T09:15:00.500000+05:30",
    }),
    { now: NOW },
  );

  // Postgres timestamptz serializes with an offset; `z.string().datetime()`
  // (the gallery model's own guard) accepts only the Z form, so the mapper
  // normalizes rather than handing the gallery a value it would reject.
  assert.equal(artifact.createdAt, "2026-08-14T09:15:00.123Z");
  assert.equal(artifact.updatedAt, "2026-08-18T03:45:00.500Z");
  assert.doesNotThrow(() => ProjectArtifactSchema.parse(artifact));
});

test("a real document carries no thumbnail and no run", () => {
  const artifact = toProjectArtifact(listItem(), { now: NOW });

  // Ruling 2: real documents have no thumbnails — the mapper invents none.
  assert.equal(artifact.imagePath, undefined);
  // No generation run exists behind a leg-derived document either.
  assert.equal(artifact.originRunId, undefined);
});

test("editedLabel is derived from updated_at in the gallery's label style", () => {
  const label = (updatedAt: string) =>
    toProjectArtifact(listItem({ updatedAt }), { now: NOW }).editedLabel;

  assert.equal(label("2026-08-18T09:15:00+00:00"), "Last edited today");
  assert.equal(label("2026-08-17T23:59:00+00:00"), "Last edited yesterday");
  assert.equal(label("2026-08-16T09:15:00+00:00"), "Last edited 2 days ago");
});

test("the relative ladder spans days, weeks, months and years", () => {
  const at = (isoDay: string) => editedLabelFor(`${isoDay}T12:00:00.000Z`, NOW);

  assert.equal(at("2026-08-18"), "Last edited today");
  assert.equal(at("2026-08-17"), "Last edited yesterday");
  assert.equal(at("2026-08-12"), "Last edited 6 days ago");
  assert.equal(at("2026-08-11"), "Last edited 1 week ago");
  assert.equal(at("2026-08-04"), "Last edited 2 weeks ago");
  assert.equal(at("2026-07-19"), "Last edited 1 month ago");
  assert.equal(at("2026-05-18"), "Last edited 3 months ago");
  assert.equal(at("2025-08-18"), "Last edited 1 year ago");
  assert.equal(at("2024-08-18"), "Last edited 2 years ago");
});

test("a future updated_at still reads as today rather than a negative age", () => {
  assert.equal(
    editedLabelFor("2026-08-18T23:00:00.000Z", NOW),
    "Last edited today",
  );
});

test("an unparseable timestamp is refused, not mapped", () => {
  // The seam schema deliberately admits any non-empty string (normalizing is
  // the mapper's job), so the mapper is the boundary that must refuse. The
  // page's feed loader catches this throw and degrades to an empty feed.
  assert.throws(
    () => toProjectArtifact(listItem({ createdAt: "not-a-date" }), { now: NOW }),
    TypeError,
  );
  assert.throws(
    () => toProjectArtifact(listItem({ updatedAt: "yesterday-ish" }), { now: NOW }),
    TypeError,
  );
});

test("editedLabelFor refuses bad input the same way (never a NaN label)", () => {
  assert.throws(() => editedLabelFor("not-a-date", NOW), TypeError);
});

test("the mapped artifact survives the gallery's normalizer", () => {
  const normalized = normalizeGalleryArtifact(
    toProjectArtifact(listItem(), { now: NOW }),
  );

  assert.equal(normalized.id, "doc-web-1");
  assert.equal(normalized.collateralType, "microsite");
  assert.equal(normalized.collateralTypeLabel, "Microsite");
  // `defaultSize` fills the website size the mapper cannot know.
  assert.deepEqual(normalized.size, {
    category: "responsive",
    height: 900,
    label: "Responsive",
    width: 1440,
  });
  assert.equal(normalized.updatedAt, "2026-08-18T09:15:00.000Z");
  assert.equal(normalized.createdAt, "2026-08-14T09:15:00.000Z");
  assert.equal(normalized.lastViewedAt, "2026-08-18T09:15:00.000Z");
  // The optionals stay absent through normalization — nothing is invented.
  assert.equal(normalized.imagePath, undefined);
  assert.equal(normalized.originRunId, undefined);
});
