import assert from "node:assert/strict";
import test from "node:test";
import type { ProjectDocument } from "@/features/projects/model/project-documents";
import { selectedProjectDocument } from "@/features/projects/model/project-documents";
import { galleryCardTarget } from "@/features/chat-shell/model/gallery-card-target";
import { DEFAULT_GALLERY_FILTERS, documentGalleryCards, filterGalleryArtifacts, galleryTypeOptions, groupGalleryArtifacts, normalizeGalleryArtifact, sortGalleryArtifacts } from "./project-gallery";

const icp: ProjectDocument = { id: "icp-v1", path: "audience/icp-regional.md", kind: "icp-definition", title: "Regional clinics", version: 1, status: "proposed", updatedAt: "2026-09-14T09:00:00Z", icpKey: "regional" };
const persona: ProjectDocument = { ...icp, id: "persona-v1", path: "audience/persona-regional.md", kind: "audience-persona", title: "Personas — regional", updatedAt: "2026-09-14T10:00:00Z" };
const plan: ProjectDocument = { ...icp, id: "plan", kind: "project-plan", path: "project/plan.md", title: "Plan" };

test("Gallery includes saved plans, ICPs and personas without manufacturing design metadata", () => {
  const cards = documentGalleryCards([icp, persona, plan]);
  assert.deepEqual(cards.map((card) => card.document), [icp, persona, plan]);
  for (const card of cards) {
    assert.equal(card.source, undefined);
    assert.equal(card.imagePath, undefined);
    assert.equal(card.account, undefined);
    assert.equal(card.size, undefined);
    assert.equal(card.originThreadId, undefined);
    assert.equal(card.collateralTypeLabel, "Documents");
    assert.deepEqual(galleryCardTarget(card), { surface: "plan", documentPath: card.document!.path });
  }
});

test("new versions update a card without changing identity or selecting an old revision", () => {
  const updated = { ...icp, id: "icp-v2", version: 2 };
  assert.equal(documentGalleryCards([icp])[0].id, documentGalleryCards([updated])[0].id);
  assert.equal(selectedProjectDocument([updated, plan], icp.path), updated);
  assert.equal(selectedProjectDocument([updated, plan]), plan);
  assert.equal(selectedProjectDocument([updated, plan], "missing.md"), null);
});

test("documents share Gallery search, sorting, grouping and conditional type filtering", () => {
  const design = normalizeGalleryArtifact({ id: "web", type: "website", title: "Campaign site", originThreadId: "thread", editedLabel: "Edited today", updatedAt: "2026-09-14T09:30:00Z" });
  const cards = [design, ...documentGalleryCards([icp, persona])];
  assert.equal(galleryTypeOptions([design]).includes("documents"), false);
  assert.equal(galleryTypeOptions(cards).includes("documents"), true);
  assert.deepEqual(sortGalleryArtifacts(cards, "edited-desc").map((card) => card.title), [persona.title, design.title, icp.title]);
  assert.equal(filterGalleryArtifacts({ artifacts: cards, filters: DEFAULT_GALLERY_FILTERS, query: "regional clinics" })[0].document, icp);
  assert.equal(filterGalleryArtifacts({ artifacts: cards, filters: { ...DEFAULT_GALLERY_FILTERS, collateralTypes: ["documents"] }, query: "" }).length, 2);
  assert.equal(groupGalleryArtifacts(cards, "type").find((group) => group.label === "Documents")?.artifacts.length, 2);
});
