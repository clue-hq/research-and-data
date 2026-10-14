// The site render inside the design API's hardened Chromium page (D2, founder ruling 2026-10-11).
// Bundled by bin/build-bundles.mjs into dist/render-browser.js: ONE classic script with React,
// react-dom/server, Puck's <Render>, zod and this kit inlined. lumen_api/site_render.py loads it
// into a page whose CSP allows only inline script and data: modules, after an inert JSON script
// #clue-render-input that holds the render's input.
//
// What it does: reads and removes the input, exposes its own react, react/jsx-runtime and zod on
// globalThis.__clueSectionHost, imports each agent section from a data: URL whose three host
// imports are rewritten to data: shims over those copies (one React, one zod), renders, and answers
// on window.__clueRender — frozen once written, and only trusted by Python when it carries the
// render's nonce (which no section can read: the input is gone before any section loads).
import type { AgentSectionModule } from "./agent-kit";
import type { BrandData } from "./brand";
import { RenderRefusal, renderSitePages, sectionPropsSchema, type StoredSite } from "./render-core";
import { HOST_SPECIFIERS, hostExportNames, hostModules, shimSource, type HostSpecifier } from "./section-host";

type Input = {
  mode: "render" | "schema";
  nonce: string;
  maxOutputBytes: number;
  site?: StoredSite;
  brand?: BrandData;
  basePath?: string;
  routes?: string[];
  sections: { name: string; moduleJs: string }[];
};
type Channel = { done: boolean; nonce: string; size: number; code: string | null; error: string | null; result: unknown };

const HOST = hostModules();
const freeze = Object.freeze;
const channel: Channel = Object.seal({ done: false, nonce: "", size: 0, code: null, error: null, result: null });
Object.defineProperty(window, "__clueRender", { value: channel, writable: false, configurable: false });

const dataUrl = (source: string) => "data:text/javascript;charset=utf-8," + encodeURIComponent(source);

const shimFor = (specifier: HostSpecifier) => shimSource(specifier, hostExportNames(HOST[specifier]));

async function loadSection(moduleJs: string, shims: Record<string, string>): Promise<Record<string, unknown>> {
  const source = moduleJs.replace(
    /(\bfrom\s*|\bimport\s*)(["'])(react\/jsx-runtime|react|zod)\2/g,
    (_match, keyword: string, _quote: string, specifier: string) => `${keyword}${JSON.stringify(shims[specifier])}`,
  );
  return (await import(dataUrl(source))) as Record<string, unknown>;
}

function finish(nonce: string, fields: Partial<Channel>): void {
  Object.assign(channel, fields);
  channel.nonce = nonce;
  channel.done = true;
  freeze(channel);
}

async function main(): Promise<void> {
  const element = document.getElementById("clue-render-input");
  const input = JSON.parse(element?.textContent ?? "{}") as Input;
  element?.remove();
  const nonce = input.nonce;
  // WebRTC is not covered by the page's CSP; the launch flags and the proxy refuse it as well.
  for (const name of ["RTCPeerConnection", "webkitRTCPeerConnection", "RTCDataChannel"]) {
    try {
      delete (globalThis as Record<string, unknown>)[name];
    } catch {
      // A non-configurable global stays; the network layers below the page still refuse it.
    }
  }
  (globalThis as Record<string, unknown>).__clueSectionHost = HOST;
  const shims = Object.fromEntries(HOST_SPECIFIERS.map((specifier) => [specifier, dataUrl(shimFor(specifier))]));
  try {
    const loaded: Record<string, Record<string, unknown>> = {};
    for (const section of input.sections) loaded[section.name] = await loadSection(section.moduleJs, shims);
    if (input.mode === "schema") {
      const result = sectionPropsSchema(Object.values(loaded)[0] ?? {});
      finish(nonce, { size: JSON.stringify(result).length, result });
      return;
    }
    const agentSections = Object.fromEntries(Object.entries(loaded).map(([name, module]) => [name, module as unknown as AgentSectionModule]));
    const rendered = renderSitePages({
      site: input.site as StoredSite,
      brand: input.brand as BrandData,
      basePath: input.basePath ?? "",
      routes: input.routes,
      agentSections,
      maxOutputBytes: input.maxOutputBytes,
    });
    finish(nonce, { size: rendered.size, result: { pages: rendered.pages, tailwindTheme: rendered.tailwindTheme, warnings: rendered.warnings } });
  } catch (error) {
    finish(nonce, {
      code: error instanceof RenderRefusal ? error.code : "render.failed",
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

void main();
