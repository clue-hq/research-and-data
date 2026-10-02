import assert from "node:assert/strict";
import { test } from "node:test";
import {
  galleryCardTarget,
  type GalleryCardArtifact,
} from "./gallery-card-target";

function card(overrides: Partial<GalleryCardArtifact> = {}): GalleryCardArtifact {
  return { id: "artifact-1", title: "Landing page", type: "website", ...overrides };
}

test("an account-list card opens the target-accounts surface, not a tab", () => {
  assert.deepEqual(
    galleryCardTarget(card({ id: "accounts-1", title: "Target accounts", type: "table" })),
    { surface: "target-accounts" },
  );
});

test("a website card opens a web artifact tab", () => {
  assert.deepEqual(galleryCardTarget(card()), {
    artifact: { id: "artifact-1", kind: "web", title: "Landing page" },
    surface: "artifact",
  });
});

test("every other card keeps the gallery's own kind derivation (ad)", () => {
  for (const type of ["canvas", "presentation"] as GalleryCardArtifact["type"][]) {
    assert.deepEqual(galleryCardTarget(card({ type })), {
      artifact: { id: "artifact-1", kind: "ad", title: "Landing page" },
      surface: "artifact",
    });
  }
});
