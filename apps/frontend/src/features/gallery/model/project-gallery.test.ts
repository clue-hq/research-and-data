import assert from "node:assert/strict";
import test from "node:test";
import { galleryFixtureArtifacts } from "./project-gallery.test.fixture";
import {
  countActiveGalleryFilters,
  DEFAULT_GALLERY_FILTERS,
  filterGalleryArtifacts,
  groupGalleryArtifacts,
  normalizeGalleryArtifact,
  sortGalleryArtifacts,
  type GalleryArtifact,
} from "./project-gallery";

const artifacts = galleryFixtureArtifacts.map(normalizeGalleryArtifact);

test("gallery artifacts retain project provenance and backend filter facets", () => {
  assert.ok(artifacts.length >= 7);
  assert.ok(artifacts.every((artifact) => artifact.originRunId));
  assert.ok(artifacts.every((artifact) => artifact.originThreadId));
  assert.ok(artifacts.every((artifact) => artifact.account?.id));
  assert.ok(artifacts.every((artifact) => artifact.collateralType));
  assert.ok(artifacts.every((artifact) => artifact.size?.label));
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

// A real, leg-derived artifact carries no account data. The gallery must show
// honest absence — never the fixture "OpenAI" fallback painted onto a real
// document (ruling 2's no-invented-imagery, extended to account attribution).
const unattributed = normalizeGalleryArtifact({
  collateralType: "microsite",
  createdAt: "2026-08-18T09:00:00.000Z",
  editedLabel: "Last edited today",
  id: "doc_real_web",
  originThreadId: "thr_real",
  title: "Insight Health homepage",
  type: "website",
  updatedAt: "2026-08-18T09:00:00.000Z",
});

test("an artifact without account hints normalizes to no account at all", () => {
  assert.equal(unattributed.account, undefined);
  assert.equal(unattributed.imagePath, undefined);
  assert.equal(unattributed.originRunId, undefined);
});

test("an active account filter excludes unattributed artifacts", () => {
  const results = filterGalleryArtifacts({
    artifacts: [...artifacts, unattributed],
    filters: { ...DEFAULT_GALLERY_FILTERS, accountIds: ["openai"] },
    query: "",
  });
  assert.ok(results.length > 0);
  assert.ok(results.every((artifact) => artifact.account?.id === "openai"));
});

test("unattributed artifacts share one unlabeled account group", () => {
  const groups = groupGalleryArtifacts([...artifacts, unattributed], "account");
  const group = groups.find((candidate) => candidate.id === "unattributed");
  assert.ok(group);
  assert.equal(group.label, "");
  assert.equal(group.account, undefined);
  assert.deepEqual(group.artifacts.map((artifact) => artifact.id), ["doc_real_web"]);
});

test("search tolerates a missing account name", () => {
  const results = filterGalleryArtifacts({
    artifacts: [unattributed],
    filters: DEFAULT_GALLERY_FILTERS,
    query: "insight health",
  });
  assert.deepEqual(results.map((artifact) => artifact.id), ["doc_real_web"]);
});

const withProject = (artifact: GalleryArtifact, id: string, title: string): GalleryArtifact => ({
  ...artifact, project: { id, title },
});

test("library: project filter, project group and the three extra sorts", () => {
  const [first, second, third] = artifacts;
  const rows = [withProject(first, "p1", "Beta"), withProject(second, "p2", "Alpha"), withProject(third, "p1", "Beta")];
  const filtered = filterGalleryArtifacts({
    artifacts: rows, query: "", filters: { ...DEFAULT_GALLERY_FILTERS, projectIds: ["p2"] },
  });
  assert.deepEqual(filtered.map((row) => row.project?.id), ["p2"]);
  assert.equal(countActiveGalleryFilters({ ...DEFAULT_GALLERY_FILTERS, projectIds: ["p2"] }), 1);
  const groups = groupGalleryArtifacts(rows, "project");
  assert.deepEqual(groups.map((group) => [group.id, group.label, group.artifacts.length]), [["p1", "Beta", 2], ["p2", "Alpha", 1]]);
  assert.deepEqual(sortGalleryArtifacts(rows, "project-asc").map((row) => row.project?.title), ["Alpha", "Beta", "Beta"]);
  const byType = sortGalleryArtifacts(rows, "type-asc");
  assert.ok(byType.every((row, index) => index === 0 || byType[index - 1].collateralTypeLabel.localeCompare(row.collateralTypeLabel) <= 0));
  const byAccount = sortGalleryArtifacts(rows, "account-asc");
  assert.ok(byAccount.every((row, index) => index === 0 || (byAccount[index - 1].account?.name ?? "").localeCompare(row.account?.name ?? "") <= 0));
});

test("library: a project title is searchable", () => {
  const rows = [withProject(artifacts[0], "p1", "Northwind launch")];
  assert.equal(filterGalleryArtifacts({ artifacts: rows, query: "northwind", filters: DEFAULT_GALLERY_FILTERS }).length, 1);
});
