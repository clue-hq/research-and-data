import assert from "node:assert/strict";
import test from "node:test";
import { galleryFixtureArtifacts } from "./project-gallery.test.fixture";
import {
  DEFAULT_GALLERY_FILTERS,
  filterGalleryArtifacts,
  groupGalleryArtifacts,
  normalizeGalleryArtifact,
  sortGalleryArtifacts,
} from "./project-gallery";

const artifacts = galleryFixtureArtifacts.map(normalizeGalleryArtifact);

test("gallery artifacts retain project provenance and backend filter facets", () => {
  assert.ok(artifacts.length >= 7);
  assert.ok(artifacts.every((artifact) => artifact.originRunId));
  assert.ok(artifacts.every((artifact) => artifact.originThreadId));
  assert.ok(artifacts.every((artifact) => artifact.account.id));
  assert.ok(artifacts.every((artifact) => artifact.collateralType));
  assert.ok(artifacts.every((artifact) => artifact.size.label));
  assert.ok(artifacts.every((artifact) => artifact.updatedAt));
});

test("gallery filtering combines account, collateral, date, size, and search", () => {
  const results = filterGalleryArtifacts({
    artifacts,
    filters: {
      ...DEFAULT_GALLERY_FILTERS,
      accountIds: ["openai"],
      collateralTypes: ["report"],
      dateRange: "last-7-days",
      sizeCategories: ["landscape"],
    },
    now: new Date("2026-08-16T23:59:59.000Z"),
    query: "insight",
  });

  assert.deepEqual(results.map((artifact) => artifact.id), ["account-insight-report"]);
});

test("gallery supports stable ascending dates and project groupings", () => {
  const sorted = sortGalleryArtifacts(artifacts, "edited-asc");
  assert.equal(sorted[0].id, "product-launch-brief");
  assert.equal(sorted.at(-1)?.id, "target-accounts");

  const accountGroups = groupGalleryArtifacts(artifacts, "account");
  assert.deepEqual(
    accountGroups.map((group) => group.label),
    ["OpenAI", "Anthropic", "Cursor"],
  );

  const typeGroups = groupGalleryArtifacts(artifacts, "type");
  assert.ok(typeGroups.some((group) => group.label === "Websites"));
  assert.ok(typeGroups.some((group) => group.label === "Ads"));
});
