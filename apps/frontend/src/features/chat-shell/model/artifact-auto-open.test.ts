import assert from "node:assert/strict";
import { test } from "node:test";
import {
  artifactToAutoOpen,
  type AutoOpenFeedArtifact,
} from "./artifact-auto-open";

const ACTIVE = "thread-active";

test("update-only timestamps rank an edited file above an older new file", () => {
  assert.equal(artifactToAutoOpen({
    activeThreadId: ACTIVE,
    knownArtifactIds: new Set(["edited"]),
    knownUpdates: new Map([["edited", "2026-09-14T09:00:00Z"]]),
    artifacts: [card("new", { createdAt: "2026-09-14T10:00:00Z" }),
      card("edited", { createdAt: undefined, updatedAt: "2026-09-14T11:00:00Z" })],
  })?.id, "edited");
});

function card(
  id: string,
  overrides: Partial<AutoOpenFeedArtifact> = {},
): AutoOpenFeedArtifact {
  return {
    createdAt: "2026-08-19T10:00:00.000Z",
    id,
    originThreadId: ACTIVE,
    title: `Document ${id}`,
    type: "website",
    ...overrides,
  };
}

test("a document born into the active thread opens itself", () => {
  assert.deepEqual(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-new")],
      knownArtifactIds: new Set(),
    }),
    { id: "doc-new", kind: "web", title: "Document doc-new" },
  );
});

test("an artifact already in the feed at mount is never auto-opened", () => {
  // The cold-load case: the replayed backlog re-fires `leg.opened`, which
  // re-runs `router.refresh()` and hands down the SAME feed. Everything in it
  // was snapshotted at mount, so nothing opens.
  assert.equal(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-known")],
      knownArtifactIds: new Set(["doc-known"]),
    }),
    null,
  );
});

test("a document born into a DIFFERENT thread never opens here", () => {
  assert.equal(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-elsewhere", { originThreadId: "thread-other" })],
      knownArtifactIds: new Set(),
    }),
    null,
  );
});

test("one document opens exactly once — the caller banks what it saw", () => {
  const feed = [card("doc-new")];
  const known = new Set<string>();
  const first = artifactToAutoOpen({
    activeThreadId: ACTIVE,
    artifacts: feed,
    knownArtifactIds: known,
  });
  assert.equal(first?.id, "doc-new");
  // The transport banks every id it has now seen (including the one it just
  // opened), so the next feed delivery — and any tab the user has since
  // closed — is inert.
  for (const artifact of feed) known.add(artifact.id);
  assert.equal(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: feed,
      knownArtifactIds: known,
    }),
    null,
  );
});

test("no active thread means no auto-open", () => {
  assert.equal(
    artifactToAutoOpen({
      activeThreadId: null,
      artifacts: [card("doc-new")],
      knownArtifactIds: new Set(),
    }),
    null,
  );
});

test("several new documents at once: the newest by createdAt wins", () => {
  assert.equal(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [
        card("doc-older", { createdAt: "2026-08-19T10:00:00.000Z" }),
        card("doc-newest", { createdAt: "2026-08-19T12:00:00.000Z" }),
        card("doc-middle", { createdAt: "2026-08-19T11:00:00.000Z" }),
      ],
      knownArtifactIds: new Set(),
    })?.id,
    "doc-newest",
  );
});

test("a document with no usable createdAt ranks oldest", () => {
  assert.equal(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [
        card("doc-undated", { createdAt: undefined }),
        card("doc-dated", { createdAt: "2000-01-01T00:00:00.000Z" }),
      ],
      knownArtifactIds: new Set(),
    })?.id,
    "doc-dated",
  );
  // …but an undated document still opens when it is the only candidate.
  assert.equal(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-undated", { createdAt: undefined })],
      knownArtifactIds: new Set(),
    })?.id,
    "doc-undated",
  );
});

test("an exact createdAt tie is broken by feed order — first wins", () => {
  // The feed is served newest-updated-first, so the first row of a tie is the
  // most recently touched one. Deterministic either way: the rule never
  // depends on object identity or iteration accident.
  assert.equal(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-first"), card("doc-second")],
      knownArtifactIds: new Set(),
    })?.id,
    "doc-first",
  );
});

test("the known set only silences the ids in it", () => {
  assert.equal(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [
        card("doc-known", { createdAt: "2026-08-19T23:00:00.000Z" }),
        card("doc-new"),
      ],
      knownArtifactIds: new Set(["doc-known"]),
    })?.id,
    "doc-new",
  );
});

test("a non-website artifact opens as an ad tab, matching the gallery rule", () => {
  assert.equal(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-canvas", { type: "canvas" })],
      knownArtifactIds: new Set(),
    })?.kind,
    "ad",
  );
});

test("genad2 Task 5 (d): a ZERO-PAGE newborn ad still opens its tab", () => {
  // `open_design_leg@4` births the ad with `pages: {}` — no artboard until a
  // later agent turn authors one. The rule must NOT start suppressing that tab:
  // the whole point of F2's auto-open is watching the design land, and the
  // pageless neutral state (`scene-pageless.ts`) is what the tab shows while it
  // has not. This decision reads only the feed card, which carries no page
  // information at all, so a pageless ad is indistinguishable here — pinned so
  // a future "don't open empty documents" instinct fails a test instead of
  // silently breaking the birth flow.
  assert.deepEqual(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-pageless", { title: "LinkedIn ad", type: "canvas" })],
      knownArtifactIds: new Set(),
    }),
    { id: "doc-pageless", kind: "ad", title: "LinkedIn ad" },
  );
});

test("an empty feed decides nothing", () => {
  assert.equal(
    artifactToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [],
      knownArtifactIds: new Set(),
    }),
    null,
  );
});

test("a newly updated design file reopens once; replay and another thread never steal focus", () => {
  const artifact = { id: "design", type: "website" as const, title: "Campaign page", originThreadId: "thread", createdAt: "2026-09-14T08:00:00Z", updatedAt: "2026-09-14T09:00:00Z" };
  const knownUpdates = new Map([[artifact.id, "2026-09-14T08:00:00Z"]]);
  const args = { activeThreadId: "thread", artifacts: [artifact], knownArtifactIds: new Set([artifact.id]), knownUpdates };
  assert.equal(artifactToAutoOpen(args)?.id, artifact.id);
  assert.equal(artifactToAutoOpen({ ...args, activeThreadId: "other" }), null);
  knownUpdates.set(artifact.id, artifact.updatedAt);
  assert.equal(artifactToAutoOpen(args), null);
});
