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

test("the card sizes its own dock, so the composer is never clipped behind it", () => {
  const shellCss = source("../../chat-shell/components/chat-shell.module.css");
  // The dock's basis is hand-budgeted per content (174px, 210px with the edit-target bar); the
  // card is taller than the whole box, so its presence has to switch the basis to `auto`.
  assert.match(shellCss, /\.composerDockWithResearchCard\s*\{\s*flex-basis:\s*auto;/);
  assert.match(
    shellCss,
    /\.shellPanelOpen \.composerDockWithResearchCard\s*\{\s*flex-basis:\s*auto;/,
  );
  assert.match(surface, /research\.card \|\| chat\.queueControl\.paused \? styles\.composerDockWithResearchCard/);
});

test("the prime rule names the two ARV2 launch tools and waits for the transcript", () => {
  // Ruling R7: the plan named the OLD lane's `launch_account_research`, which would have primed
  // nothing. A rename of either tool must break a test, not the feature.
  const effect = surface.slice(
    surface.indexOf("const knownResearchLaunchIds"),
    surface.indexOf("const shell = useEditorShellController"),
  );
  assert.ok(effect.length > 0, "the research prime effect is where this test expects it");
  assert.match(effect, /"launch_arv2_account_research"/);
  assert.match(effect, /"launch_arv2_person_research"/);
  assert.doesNotMatch(effect, /"launch_account_research"/);
  // The first snapshot waits for the transcript, or it banks an empty set and re-primes forever.
  assert.match(effect, /if \(chat\.loading\) return;/);
});
