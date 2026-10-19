import assert from "node:assert/strict";
import { test } from "node:test";
import { artifactsToAutoOpen } from "./artifact-auto-open";
import { chatShellKindForCard, isWebsiteKind } from "./artifact-kind";
import { chatDockContent } from "./chat-dock";
import { chatSurfacePaneParams, chatSurfaceUrlState } from "./chat-surface-params";
import { galleryCardTarget } from "./gallery-card-target";
import { openArtifactFromParam } from "./open-artifact-param";

// Contract 8: "site" is a kind of its own everywhere a kind travels. A card that
// carries its document kind opens in exactly that editor; a card without one keeps
// the gallery's historical derivation (website → web, anything else → ad).

test("a card that carries its document kind opens in that editor", () => {
  assert.equal(chatShellKindForCard({ type: "website", documentKind: "site" }), "site");
  assert.equal(chatShellKindForCard({ type: "website", documentKind: "web" }), "web");
  assert.equal(chatShellKindForCard({ type: "canvas", documentKind: "ad" }), "ad");
});

test("a card without a document kind keeps the historical derivation", () => {
  assert.equal(chatShellKindForCard({ type: "website" }), "web");
  assert.equal(chatShellKindForCard({ type: "canvas" }), "ad");
  assert.equal(chatShellKindForCard({}), "ad");
});

test("a site is a website to the marketer", () => {
  assert.equal(isWebsiteKind("site"), true);
  assert.equal(isWebsiteKind("web"), true);
  assert.equal(isWebsiteKind("ad"), false);
  assert.equal(isWebsiteKind("scene"), false);
  assert.equal(isWebsiteKind(null), false);
});

test("the gallery, ?open= and auto-open all route a site card to the site editor", () => {
  assert.deepEqual(
    galleryCardTarget({ id: "a1", title: "Landing", type: "website", documentKind: "site" }),
    { artifact: { id: "a1", kind: "site", title: "Landing" }, surface: "artifact" },
  );
  assert.deepEqual(
    openArtifactFromParam({
      openId: "a1",
      artifacts: [{ id: "a1", title: "Landing", type: "website", documentKind: "site" }],
    }),
    { id: "a1", kind: "site", title: "Landing" },
  );
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: "t1",
      artifacts: [
        {
          documentKind: "site",
          id: "a1",
          originThreadId: "t1",
          title: "Landing",
          type: "website",
          updatedAt: "2026-10-11T09:00:00.000Z",
        },
      ],
      knownArtifactIds: new Set(),
    }),
    [{ id: "a1", kind: "site", title: "Landing" }],
  );
});

test("editing a site docks the site inspector, never the ad inspector", () => {
  assert.equal(
    chatDockContent({ artifactKind: "site", editing: true, panelOpen: true, surface: "artifact" }),
    "site-inspector",
  );
  assert.equal(
    chatDockContent({ artifactKind: "site", editing: false, panelOpen: true, surface: "artifact" }),
    "conversation",
  );
});

test("surface=site round-trips through the pane vocabulary", () => {
  const parsed = chatSurfaceUrlState({ surface: "site", edit: "1" });
  assert.equal(parsed.surface, "artifact");
  assert.equal(parsed.editing, true);
  assert.deepEqual(
    chatSurfacePaneParams({
      artifactKind: "site",
      editing: true,
      inspectorSelection: "canvas",
      panelOpen: true,
      rawSurface: undefined,
      surface: "artifact",
    }),
    { edit: "1", selection: undefined, surface: "site" },
  );
  // A deep link that lands on the artifact surface before its tab exists keeps "site".
  assert.equal(
    chatSurfacePaneParams({
      artifactKind: null,
      editing: false,
      inspectorSelection: "canvas",
      panelOpen: true,
      rawSurface: "site",
      surface: "artifact",
    }).surface,
    "site",
  );
});
