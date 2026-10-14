import assert from "node:assert/strict";
import { test } from "node:test";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import {
  SECTION_LINK_REFRESH_MS,
  acceptsFrameEdits,
  frameSyncFor,
  initialRoute,
  linksFresh,
  siteFrameMode,
  siteInitKey,
} from "./site-frame-sync";

const site = (sections: Record<string, string> = {}) =>
  SiteDocumentSchema.parse({
    id: "doc-a",
    title: "A",
    theme: {},
    pages: { "/": { root: { props: {} }, content: [] }, "/analysis": { root: { props: {} }, content: [] } },
    shell: null,
    agent_sections: sections,
  });

test("a booted frame gets an init first, then replace_site for each new revision of the working copy", () => {
  const key = siteInitKey("doc-a", site(), 1);
  assert.deepEqual(frameSyncFor({ frameReady: true, initKey: key, sentInitKey: null, sentRev: null, rev: 3 }), { kind: "init" });
  assert.deepEqual(frameSyncFor({ frameReady: true, initKey: key, sentInitKey: key, sentRev: 3, rev: 3 }), { kind: "none" });
  assert.deepEqual(frameSyncFor({ frameReady: true, initKey: key, sentInitKey: key, sentRev: 3, rev: 4 }), { kind: "replace", rev: 4 });
  assert.deepEqual(frameSyncFor({ frameReady: false, initKey: key, sentInitKey: null, sentRev: null, rev: 3 }), { kind: "none" });
});

test("Review focus 2: another document, new agent sections or a rebooted frame each need a fresh init", () => {
  const base = siteInitKey("doc-a", site(), 1);
  assert.notEqual(siteInitKey("doc-b", site(), 1), base, "switching documents re-initialises");
  assert.notEqual(siteInitKey("doc-a", site({ AnalysisSteps: "a".repeat(64) }), 1), base, "a new agent section re-initialises");
  assert.notEqual(siteInitKey("doc-a", site(), 2), base, "a frame that booted again re-initialises");
  assert.equal(siteInitKey("doc-a", site(), 1), base);
});

test("Review focus 4: section links older than eight minutes are refetched before an init", () => {
  assert.equal(linksFresh(0, SECTION_LINK_REFRESH_MS - 1, 2), true);
  assert.equal(linksFresh(0, SECTION_LINK_REFRESH_MS, 2), false);
  assert.equal(linksFresh(0, SECTION_LINK_REFRESH_MS * 10, 0), true, "a site with no agent sections has nothing to refresh");
});

test("Review focus 5: the frame edits, and the app accepts edits, only while editing and unlocked", () => {
  assert.equal(siteFrameMode({ editing: true, locked: false }), "edit");
  assert.equal(siteFrameMode({ editing: true, locked: true }), "preview");
  assert.equal(siteFrameMode({ editing: false, locked: false }), "preview");
  assert.equal(acceptsFrameEdits({ editing: true, locked: false }), true);
  assert.equal(acceptsFrameEdits({ editing: true, locked: true }), false);
  assert.equal(acceptsFrameEdits({ editing: false, locked: false }), false);
});

test("an init opens the page the user was on when the site still has it, else home", () => {
  assert.equal(initialRoute(site(), "/analysis"), "/analysis");
  assert.equal(initialRoute(site(), "/gone"), "/");
  assert.equal(initialRoute(site(), null), "/");
});
