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

test("an ad artifact maps onto a canvas artifact with no collateral type", () => {
  // AD2.1: the feed is kind-aware, so a scene document arrives as `kind: "ad"`.
  // It becomes a `canvas` artifact — the type both editor mounts reconstruct
  // `kind: "ad"` from (`source.type === "website" ? "web" : "ad"`), so the ad
  // reaches the editor with zero mount changes. `collateralType` is left ABSENT
  // rather than guessed: the document says it is an ad, never which channel.
  const artifact = toProjectArtifact(listItem({ id: "doc-ad-1", kind: "ad" }), {
    now: NOW,
  });

  assert.equal(artifact.type, "canvas");
  assert.equal("collateralType" in artifact, false);
  // The honest-empty card holds: no invented thumbnail for an ad either.
  assert.equal(artifact.imagePath, undefined);
  assert.doesNotThrow(() => ProjectArtifactSchema.parse(artifact));
});

test("a web artifact keeps its website mapping alongside ads", () => {
  const web = toProjectArtifact(listItem(), { now: NOW });
  const ad = toProjectArtifact(listItem({ id: "doc-ad-2", kind: "ad" }), { now: NOW });

  assert.deepEqual(
    [web, ad].map((artifact) => [artifact.type, artifact.collateralType]),
    [
      ["website", "microsite"],
      ["canvas", undefined],
    ],
  );
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

// ── G-H (founder ruling 2026-08-20) ────────────────────────────────────────
// A card states only what its document records. The old defaults called every
// design artifact a 1080x1080 "LinkedIn ad"; both facts now come from the
// document, and a document that records neither says nothing.

test("G-H: an ad carries the document's own size and its recorded channel", () => {
  const normalized = normalizeGalleryArtifact(
    toProjectArtifact(
      listItem({
        id: "doc-ad-1",
        documentId: "doc-ad-1",
        kind: "ad",
        title: "Insight Health — LinkedIn square ad",
        artifactType: "linkedin_square_ad",
        widthPx: 1200,
        heightPx: 1200,
      }),
      { now: NOW },
    ),
  );

  assert.equal(normalized.collateralType, "linkedin-ad");
  assert.equal(normalized.collateralTypeLabel, "LinkedIn ad");
  assert.deepEqual(normalized.size, {
    category: "square",
    height: 1200,
    label: "1200 × 1200",
    width: 1200,
  });
});

test("G-H: an ad whose document records no channel claims none", () => {
  const normalized = normalizeGalleryArtifact(
    toProjectArtifact(
      listItem({
        id: "doc-ad-2",
        documentId: "doc-ad-2",
        kind: "ad",
        title: "Untitled design",
        widthPx: 1080,
        heightPx: 1920,
      }),
      { now: NOW },
    ),
  );

  assert.equal(normalized.collateralType, undefined);
  assert.equal(normalized.collateralTypeLabel, "");
  // The size is still the document's own, and its category is derived.
  assert.equal(normalized.size?.label, "1080 × 1920");
  assert.equal(normalized.size?.category, "portrait");
});

test("G-H: an ad whose document records no page states no size", () => {
  const normalized = normalizeGalleryArtifact(
    toProjectArtifact(
      listItem({ id: "doc-ad-3", documentId: "doc-ad-3", kind: "ad", title: "Empty" }),
      { now: NOW },
    ),
  );

  assert.equal(normalized.size, undefined);
  assert.equal(normalized.collateralType, undefined);
});

test("genad2 Task 5 (c): a ZERO-PAGE newborn ad card is honest-empty, not hidden", () => {
  // `open_design_leg@4` births a chat-born ad with `pages: {}`, so the feed row
  // for it carries no `width_px`/`height_px` at all — the backend is already
  // honest (it reports no page rather than a default), and this pins the
  // frontend half of that: the card still appears, with its real id and title,
  // and claims NOTHING it cannot measure. A fabricated 1080x1080 (the pre-G-H
  // default) or a stock thumbnail here would be the gallery inventing a design
  // that does not exist yet.
  const artifact = toProjectArtifact(
    listItem({
      id: "doc-ad-newborn",
      documentId: "doc-ad-newborn",
      kind: "ad",
      title: "LinkedIn ad",
    }),
    { now: NOW },
  );
  const normalized = normalizeGalleryArtifact(artifact);

  assert.equal(normalized.id, "doc-ad-newborn");
  assert.equal(normalized.title, "LinkedIn ad");
  assert.equal(normalized.source.type, "canvas");
  assert.equal(normalized.size, undefined);
  assert.equal(normalized.imagePath, undefined);
});

test("G-H: an unrecognised artifact type is not forced into the vocabulary", () => {
  const artifact = toProjectArtifact(
    listItem({
      id: "doc-ad-4",
      documentId: "doc-ad-4",
      kind: "ad",
      title: "Conference poster",
      artifactType: "a2_conference_poster",
      widthPx: 1191,
      heightPx: 1684,
    }),
  );

  assert.equal(artifact.collateralType, undefined);
});
