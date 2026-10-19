// The published page's browser entry (publishing live sites, phase 1). Built by bin/build-bundles.mjs
// into dist/site-runtime.js, one ES module with React, Puck's Render, zod and this kit inside. The
// page loads it as <script type="module" src="/p-assets/<sha>.js">; its import map points react,
// react/jsx-runtime and zod at /p-assets shims that hand over THIS module's copies.
import type { AgentSectionModule } from "./agent-kit";
import { lockCookies } from "./cookie-lock";
import { hydrateSite, type LivePageData } from "./live-page";
import { hostModules } from "./section-host";

// Review K3-7: no section on a published page can set a cookie on the shared pages domain. Runs when
// this module loads, before any section is imported.
lockCookies();

declare global {
  interface Window {
    __clueHydrated?: boolean;
  }
}

async function main(): Promise<void> {
  const element = document.getElementById("clue-page-data");
  const container = document.getElementById("clue-site");
  if (!element || !container) return;
  const data = JSON.parse(element.textContent ?? "{}") as LivePageData;
  (globalThis as { __clueSectionHost?: unknown }).__clueSectionHost = hostModules();
  const report = (message: string) => console.error(`[clue-site] ${message}`);
  const agentSections: Record<string, AgentSectionModule> = {};
  for (const [name, url] of Object.entries(data.sections)) {
    try {
      agentSections[name] = (await import(/* @vite-ignore */ url)) as AgentSectionModule;
    } catch (error) {
      report(`section ${name} did not load: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  const run = hydrateSite({ container, data, agentSections, report });
  await run.ready;
  window.__clueHydrated = true;
}

void main();
