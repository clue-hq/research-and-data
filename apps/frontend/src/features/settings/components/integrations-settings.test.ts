import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// There is no React renderer here: the wiring is asserted on the source text, as in
// use-projects-screen-controller.test.ts. The card itself is tested through crmOverviewCard.
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("Integrations is a live section, no longer coming soon", () => {
  assert.doesNotMatch(read("./settings-screen.tsx"), /"integrations"\]/);
  assert.doesNotMatch(read("./settings-coming-soon.tsx"), /integrations/);
  assert.match(read("../data/settings-read.ts"), /case "integrations":[\s\S]*readCrmIntegration\(\)/);
  const page = read("../../../app/(protected)/settings/[[...section]]/page.tsx");
  assert.match(page, /case "integrations":[\s\S]*<IntegrationsSettings/);
  assert.match(page, /pageWorkspace=\{session\?\.principal\.workspace_id \?\? null\}/);
});

test("the overview reuses the chat's connect mechanism and refreshes when connected", () => {
  const hook = read("../../integrations/hooks/use-crm-settings-connect.ts");
  assert.match(hook, /requestConnect\(mode\)/);
  assert.match(hook, /requestConnectLink\(id, provider, fetch, pageWorkspace\)/);
  assert.match(hook, /router\.refresh\(\)/);
  assert.match(hook, /window\.location\.reload\(\)/);
  assert.match(read("../../integrations/components/crm-connect-dialogs.tsx"), /useCrmConnectionWatch\(/);
});
