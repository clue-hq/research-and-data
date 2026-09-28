import assert from "node:assert/strict";
import { test } from "node:test";
import {
  artifactsToAutoOpen,
  type AutoOpenFeedArtifact,
} from "./artifact-auto-open";

const ACTIVE = "thread-active";

test("update-only timestamps open both: the older new file first, then the edit", () => {
  assert.deepEqual(artifactsToAutoOpen({
    activeThreadId: ACTIVE,
    knownArtifactIds: new Set(["edited"]),
    knownUpdates: new Map([["edited", "2026-09-14T09:00:00Z"]]),
    artifacts: [card("new", { createdAt: "2026-09-14T10:00:00Z" }),
      card("edited", { createdAt: undefined, updatedAt: "2026-09-14T11:00:00Z" })],
  }).map((artifact) => artifact.id), ["new", "edited"]);
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
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-new")],
      knownArtifactIds: new Set(),
    }),
    [{ id: "doc-new", kind: "web", title: "Document doc-new" }],
  );
});

test("every document born into the active thread opens, in feed order", () => {
  assert.deepEqual(
    artifactsToAutoOpen({ activeThreadId: ACTIVE, artifacts: [card("d0"), card("d1"), card("d2")], knownArtifactIds: new Set() }),
    [
      { id: "d0", kind: "web", title: "Document d0" },
      { id: "d1", kind: "web", title: "Document d1" },
      { id: "d2", kind: "web", title: "Document d2" },
    ],
  );
});

test("an artifact already in the feed at mount is never auto-opened", () => {
  // The cold-load case: the replayed backlog re-fires `leg.opened`, which
  // re-runs `router.refresh()` and hands down the SAME feed. Everything in it
  // was snapshotted at mount, so nothing opens.
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-known")],
      knownArtifactIds: new Set(["doc-known"]),
    }),
    [],
  );
});

test("a document born into a DIFFERENT thread never opens here", () => {
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-elsewhere", { originThreadId: "thread-other" })],
      knownArtifactIds: new Set(),
    }),
    [],
  );
});

test("one document opens exactly once — the caller banks what it saw", () => {
  const feed = [card("doc-new")];
  const known = new Set<string>();
  const first = artifactsToAutoOpen({
    activeThreadId: ACTIVE,
    artifacts: feed,
    knownArtifactIds: known,
  });
  assert.deepEqual(first.map((artifact) => artifact.id), ["doc-new"]);
  // The transport banks every id it has now seen (including the one it just
  // opened), so the next feed delivery — and any tab the user has since
  // closed — is inert.
  for (const artifact of feed) known.add(artifact.id);
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: feed,
      knownArtifactIds: known,
    }),
    [],
  );
});

test("no active thread means no auto-open", () => {
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: null,
      artifacts: [card("doc-new")],
      knownArtifactIds: new Set(),
    }),
    [],
  );
});

test("several new documents at once all open, oldest-born first", () => {
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [
        card("doc-older", { createdAt: "2026-08-19T10:00:00.000Z" }),
        card("doc-newest", { createdAt: "2026-08-19T12:00:00.000Z" }),
        card("doc-middle", { createdAt: "2026-08-19T11:00:00.000Z" }),
      ],
      knownArtifactIds: new Set(),
    }).map((artifact) => artifact.id),
    ["doc-older", "doc-middle", "doc-newest"],
  );
});

test("a document with no usable createdAt ranks oldest", () => {
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [
        card("doc-undated", { createdAt: undefined }),
        card("doc-dated", { createdAt: "2000-01-01T00:00:00.000Z" }),
      ],
      knownArtifactIds: new Set(),
    }).map((artifact) => artifact.id),
    ["doc-undated", "doc-dated"],
  );
  // …and an undated document still opens when it is the only candidate.
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-undated", { createdAt: undefined })],
      knownArtifactIds: new Set(),
    }).map((artifact) => artifact.id),
    ["doc-undated"],
  );
});

test("an exact createdAt tie keeps feed order", () => {
  // The sort is stable, so documents born in the same instant (the multi-
  // artifact leg's whole point) stay in the order the feed served them.
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-first"), card("doc-second")],
      knownArtifactIds: new Set(),
    }).map((artifact) => artifact.id),
    ["doc-first", "doc-second"],
  );
});

test("the known set only silences the ids in it", () => {
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [
        card("doc-known", { createdAt: "2026-08-19T23:00:00.000Z" }),
        card("doc-new"),
      ],
      knownArtifactIds: new Set(["doc-known"]),
    }).map((artifact) => artifact.id),
    ["doc-new"],
  );
});

test("a non-website artifact opens as an ad tab, matching the gallery rule", () => {
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-canvas", { type: "canvas" })],
      knownArtifactIds: new Set(),
    }).map((artifact) => artifact.kind),
    ["ad"],
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
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("doc-pageless", { title: "LinkedIn ad", type: "canvas" })],
      knownArtifactIds: new Set(),
    }),
    [{ id: "doc-pageless", kind: "ad", title: "LinkedIn ad" }],
  );
});

test("an empty feed decides nothing", () => {
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [],
      knownArtifactIds: new Set(),
    }),
    [],
  );
});

test("a newly updated design file reopens once; replay and another thread never steal focus", () => {
  const artifact = { id: "design", type: "website" as const, title: "Campaign page", originThreadId: "thread", createdAt: "2026-09-14T08:00:00Z", updatedAt: "2026-09-14T09:00:00Z" };
  const knownUpdates = new Map([[artifact.id, "2026-09-14T08:00:00Z"]]);
  const args = { activeThreadId: "thread", artifacts: [artifact], knownArtifactIds: new Set([artifact.id]), knownUpdates };
  assert.deepEqual(artifactsToAutoOpen(args).map((opened) => opened.id), [artifact.id]);
  assert.deepEqual(artifactsToAutoOpen({ ...args, activeThreadId: "other" }), []);
  knownUpdates.set(artifact.id, artifact.updatedAt);
  assert.deepEqual(artifactsToAutoOpen(args), []);
});

test("an updated document whose tab is already open is not re-opened — the person's own edit stays an edit", () => {
  // A manual edit bumps the document's version, so the next feed delivery
  // lists the document as "updated". Its tab is already in front; re-opening
  // it would reset edit mode and the selection on every change (2026-09-20).
  const args = {
    activeThreadId: ACTIVE,
    artifacts: [card("editing", { updatedAt: "2026-09-20T12:01:00Z" })],
    knownArtifactIds: new Set(["editing"]),
    knownUpdates: new Map([["editing", "2026-09-20T12:00:00Z"]]),
  };
  assert.deepEqual(artifactsToAutoOpen({ ...args, openArtifactIds: new Set(["editing"]) }), []);
  // The same update with the tab CLOSED still opens it, exactly as before.
  assert.deepEqual(
    artifactsToAutoOpen({ ...args, openArtifactIds: new Set(["other"]) }).map((opened) => opened.id),
    ["editing"],
  );
});

test("a NEW document is never in the open set, so births open exactly as before", () => {
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: ACTIVE,
      artifacts: [card("born"), card("open-already")],
      knownArtifactIds: new Set(["open-already"]),
      openArtifactIds: new Set(["open-already"]),
    }).map((opened) => opened.id),
    ["born"],
  );
});
