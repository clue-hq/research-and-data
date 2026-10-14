import assert from "node:assert/strict";
import { test } from "node:test";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { loadDecision, SiteWorkingCopy } from "./site-working-copy";

const site = (heading: string) =>
  ({
    id: "d",
    title: "S",
    theme: {},
    shell: null,
    agent_sections: {},
    pages: { "/": { root: { props: {} }, content: [{ type: "CtaBand", props: { id: "cta", heading } }] } },
  }) as unknown as SiteDocument;

test("a load replaces the copy only when it is not older than what was written, and never mid-save", () => {
  assert.equal(loadDecision({ loadedVersion: 3, knownVersion: null, idle: false }), "adopt", "the first load");
  assert.equal(loadDecision({ loadedVersion: 4, knownVersion: 5, idle: true }), "stale", "read before our save landed");
  assert.equal(loadDecision({ loadedVersion: 4, knownVersion: 5, idle: false }), "stale");
  assert.equal(loadDecision({ loadedVersion: 5, knownVersion: 5, idle: false }), "defer", "edits are on their way");
  assert.equal(loadDecision({ loadedVersion: 6, knownVersion: 5, idle: false }), "defer");
  assert.equal(loadDecision({ loadedVersion: 5, knownVersion: 5, idle: true }), "adopt");
  assert.equal(loadDecision({ loadedVersion: 6, knownVersion: 5, idle: true }), "adopt", "someone else wrote");
});

test("an adopted load moves the revision only when the content changed", () => {
  const copy = new SiteWorkingCopy();
  assert.equal(copy.get(), null);
  assert.equal(copy.adoptLoad("d", site("A")), true);
  const first = copy.get()!.rev;
  assert.equal(copy.adoptLoad("d", site("A")), false, "the same content: nothing to push");
  assert.equal(copy.get()!.rev, first);
  assert.equal(copy.adoptLoad("d", site("B")), true);
  assert.ok(copy.get()!.rev > first);
  assert.equal(copy.get()!.site.pages["/"].content[0].props.heading, "B");
});

test("canvas proposals: accepted at the current revision (twice in a row), stale after an app change, unchanged when equal", () => {
  const copy = new SiteWorkingCopy();
  copy.adoptLoad("d", site("A"));
  const rev = copy.get()!.rev;
  assert.equal(copy.propose("d", site("A1"), rev), "accepted");
  assert.equal(copy.propose("d", site("A12"), rev), "accepted", "the frame's next flush shares the base");
  assert.equal(copy.get()!.rev, rev, "a frame-originated change does not move the revision");
  assert.equal(copy.get()!.site.pages["/"].content[0].props.heading, "A12");
  assert.equal(copy.propose("d", site("A12"), rev), "unchanged");
  const edited = copy.edit("d", site("dock"))!;
  assert.ok(edited > rev);
  assert.equal(copy.propose("d", site("late typing"), rev), "stale", "made over the copy before the dock edit");
  assert.equal(copy.get()!.site.pages["/"].content[0].props.heading, "dock");
  assert.equal(copy.propose("d", site("x"), edited + 1), "stale", "a revision the app never issued");
  assert.equal(copy.propose("other", site("x"), edited), "stale", "another document");
});

test("an app edit to another document, or with no copy, changes nothing", () => {
  const copy = new SiteWorkingCopy();
  assert.equal(copy.edit("d", site("A")), null);
  copy.adoptLoad("d", site("A"));
  assert.equal(copy.edit("other", site("B")), null);
  assert.equal(copy.get()!.site.pages["/"].content[0].props.heading, "A");
});

test("forget drops the copy; revisions never repeat, across documents too", () => {
  const copy = new SiteWorkingCopy();
  copy.adoptLoad("d", site("A"));
  const before = copy.get()!.rev;
  copy.forget();
  assert.equal(copy.get(), null);
  copy.adoptLoad("e", site("A"));
  assert.ok(copy.get()!.rev > before);
  assert.equal(copy.get()!.documentId, "e");
});

test("subscribers hear every change and nothing else", () => {
  const copy = new SiteWorkingCopy();
  let heard = 0;
  const stop = copy.subscribe(() => {
    heard += 1;
  });
  copy.adoptLoad("d", site("A"));
  copy.adoptLoad("d", site("A"));
  const rev = copy.get()!.rev;
  copy.propose("d", site("B"), rev);
  copy.propose("d", site("B"), rev);
  copy.propose("d", site("C"), rev - 1);
  copy.edit("d", site("D"));
  copy.forget();
  stop();
  copy.adoptLoad("d", site("E"));
  assert.equal(heard, 4, "adopt, accepted proposal, edit, forget");
});
