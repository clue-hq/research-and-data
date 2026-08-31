import assert from "node:assert/strict";
import test from "node:test";
import { ProjectArtifactSchema } from "@/features/projects/model/project-workspace";
import { DesignArtifactListItemSchema } from "../model/artifact";
import {
  fixtureDesignArtifactRepository,
  type DesignArtifactRepository,
} from "./artifact.repository";
import { loadGalleryFeed } from "./gallery-feed";

// Chat-flow slice 1: the gallery feed loader, extracted from the artifact
// page so the chats route mounts the SAME feed. Fixture-mocked through the
// repository seam — the loader's contract is the {cards, documentIds} shape
// and the empty-feed refusal posture, not the transport.

function listItem(overrides: Record<string, unknown> = {}) {
  return DesignArtifactListItemSchema.parse({
    id: "art-1",
    projectId: "prj-1",
    // Deliberately distinct from `id`: the map's direction (artifact id →
    // design-document id) is load-bearing for the canvas mount.
    documentId: "doc-1",
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

test("the feed serves gallery cards plus the artifact→document map", async () => {
  const feed = await loadGalleryFeed(
    fixtureDesignArtifactRepository([
      listItem(),
      listItem({
        id: "art-2",
        documentId: "doc-2",
        title: "Pricing page",
        updatedAt: "2026-08-17T10:00:00+00:00",
      }),
    ]),
    "prj-1",
  );

  // Newest-updated first — the repository's own ordering survives mapping.
  assert.deepEqual(
    feed.cards.map((card) => card.id),
    ["art-1", "art-2"],
  );
  assert.deepEqual(feed.documentIds, { "art-1": "doc-1", "art-2": "doc-2" });
});

test("the cards are wire-shaped for the rail: the gallery's own ProjectArtifact", async () => {
  const feed = await loadGalleryFeed(
    fixtureDesignArtifactRepository([listItem()]),
    "prj-1",
  );

  const card = ProjectArtifactSchema.parse(feed.cards[0]);
  assert.equal(card.id, "art-1");
  assert.equal(card.title, "Launch landing page");
  assert.equal(card.type, "website");
  assert.equal(card.originThreadId, "thread-9");
  // Timestamps normalized to the schema's canonical Z form.
  assert.equal(card.createdAt, "2026-08-14T09:15:00.000Z");
  assert.equal(card.updatedAt, "2026-08-18T09:15:00.000Z");
});

test("a project outside the feed is legitimately empty, not a refusal", async () => {
  const feed = await loadGalleryFeed(
    fixtureDesignArtifactRepository([listItem()]),
    "prj-other",
  );

  assert.deepEqual(feed, { cards: [], documentIds: {} });
});

test("a failed list read degrades to the empty feed", async () => {
  const refusing: DesignArtifactRepository = {
    async get() {
      throw new Error("unused");
    },
    async list() {
      throw new Error("backend unreachable");
    },
  };

  const feed = await loadGalleryFeed(refusing, "prj-1");
  assert.deepEqual(feed, { cards: [], documentIds: {} });
});

test("a card that fails to map degrades to the empty feed, never a crash", async () => {
  // An unparseable timestamp throws inside `toProjectArtifact`; the loader's
  // try covers the mapping, so the page renders an empty gallery instead of
  // 500ing (the artifact page's ratified posture, carried to the chats
  // route).
  const feed = await loadGalleryFeed(
    fixtureDesignArtifactRepository([
      listItem({ updatedAt: "not a timestamp" }),
    ]),
    "prj-1",
  );

  assert.deepEqual(feed, { cards: [], documentIds: {} });
});
