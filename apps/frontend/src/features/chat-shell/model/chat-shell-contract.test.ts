import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function source(path: string) {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}
const surface = source("../components/chat-surface.tsx");
const stage = source("../components/artifact-stage.tsx");
const tabs = source("../components/artifact-tabs.tsx");
const tab = source("../../accounts/components/project-target-accounts.tsx");
const hook = source("../../accounts/hooks/use-discovery-status.ts");

test("the shell polls discovery every 5 s while live and opens the surface on the launch signal", () => {
  assert.match(surface, /useDiscoveryStatus\(projectId/);
  // The launch signal's own effect: the decision, then the open it must perform. Matched as one
  // span so it cannot be satisfied by the pre-existing gallery-card `shell.openTargetAccounts()`
  // call elsewhere in the file — delete the effect's open and this fails.
  assert.match(surface, /discoveryLaunchToOpen\(\{[\s\S]*?openTargetAccounts\(\);\s*setDiscoveryPrime\(/);
  // And the mount snapshot waits for the conversation, so a replayed backlog opens nothing.
  assert.match(surface, /if \(chat\.loading\) return;/);
  // Only landed tool parts are banked: a launch seen while still running must still open the
  // surface when it completes (live walk, 2026-09-12).
  assert.match(surface, /part\.kind === "tool" && part\.state === "output-available" \? \[part\.toolCallId\]/);
  assert.match(surface, /for \(const id of completedToolCallIds\(chat\.transcript\)\) known\.add\(id\);/);
  assert.match(hook, /pollMs = 5000/);
  assert.match(hook, /discoveryRunLive\(/);
});

test("the tab label spins while a run is live, and the tab refetches on every tick", () => {
  assert.match(surface, /targetAccountsBusy=\{discovery\.live\}/);
  // Discovery ticks AND research-progress reads both refetch the tab: a researched account's
  // status and fields appear without a reload (live walk, 2026-09-12).
  assert.match(surface, /targetAccountsRefreshToken=\{discovery\.tick \+ research\.tick\}/);
  assert.match(stage, /targetAccountsBusy=\{targetAccountsBusy\}/);
  assert.match(stage, /refreshToken=\{targetAccountsRefreshToken\}/);
  assert.match(tabs, /targetAccountsBusy \? \(\s*<ProjectIcon className=\{styles\.galleryTabSpinner\} name="loader"/);
  // The refetch effect's actual deps line — `refreshToken` alone matched the prop declaration,
  // so it could not fail while the prop existed.
  assert.match(tab, /\}, \[active, attempt, projectId, refreshToken\]\);/);
});
