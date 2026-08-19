import assert from "node:assert/strict";
import { test } from "node:test";
import {
  artifactToAutoOpen,
  type AutoOpenFeedArtifact,
} from "./artifact-auto-open";

const ACTIVE = "thread-active";

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
