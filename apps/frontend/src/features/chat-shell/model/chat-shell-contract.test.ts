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
  assert.match(surface, /discoveryLaunchToOpen\(\{/);
  assert.match(surface, /shell\.openTargetAccounts\(\)/);
  assert.match(hook, /pollMs = 5000/);
  assert.match(hook, /discoveryRunLive\(/);
});

test("the tab label spins while a run is live, and the tab refetches on every tick", () => {
  assert.match(surface, /targetAccountsBusy=\{discovery\.live\}/);
  assert.match(surface, /targetAccountsRefreshToken=\{discovery\.tick\}/);
  assert.match(stage, /targetAccountsBusy=\{targetAccountsBusy\}/);
  assert.match(stage, /refreshToken=\{targetAccountsRefreshToken\}/);
  assert.match(tabs, /targetAccountsBusy \? \(\s*<ProjectIcon className=\{styles\.galleryTabSpinner\} name="loader"/);
  assert.match(tab, /\[active, attempt, data, projectId, refreshToken\]|refreshToken/);
});
