import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function source(path: string) {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}
const surface = source("../../chat-shell/components/chat-surface.tsx");
const card = source("../components/research-progress-card.tsx");
const hook = source("../hooks/use-research-progress-controller.ts");

test("the card is pinned in the composer dock, one per project, polled while it exists", () => {
  assert.match(surface, /useResearchProgressController\(projectId/);
  assert.match(surface, /<ResearchProgressCard/);
  // Inside the composer frame, above the edit-targets bar and the composer.
  assert.ok(surface.indexOf("<ResearchProgressCard") < surface.indexOf("<ProjectComposer"));
  assert.match(hook, /pollMs = 5000/);
  assert.match(hook, /rotateMs = 4000/);
});

test("the card is the mockup and nothing more: no chevron, no dismiss, one state", () => {
  assert.match(card, /Account research/);
  assert.match(card, /Queued/);
  assert.match(card, /role="progressbar"/);
  assert.doesNotMatch(card, /chevron|Dismiss|expanded|details/i);
});
