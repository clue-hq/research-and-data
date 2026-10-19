// D2 spike (Task 4): render a site's page to static HTML with its agent sections loaded from the
// compiled modules on disk, in a process with no network.
//
// The page JSON names its workspace and {name: digest}; each module is imported from
// data/compiled/<workspace>/<digest>.mjs and nowhere else (a digest missing there refuses, it never
// renders a blank section). The page renders with <Render> from @puckeditor/core/rsc, as the
// published route app/s/[site]/[[...route]]/page.tsx does.
//
// 1. Build once on the host. This bundles the spike's own code (config, sections, kit, brand
//    loader) into one file; packages (react, react-dom, Puck, zod) stay imports and load from
//    node_modules at run time. The static agent-section index is replaced by an empty one, so every
//    agent section in the output came from a module on disk:
//      npx tsx scripts/render-site.ts --bundle
// 2. Render, with no network:
//      docker run --rm --network none -v "$PWD":/w:ro -w /w node:24-alpine \
//        node /w/agent-runs/.render/render-site.mjs <site> [route] [--css <file>] > page.html
//    The HTML goes to stdout (the mount is read-only); timings go to stderr.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createElement, type ReactNode } from "react";
import { renderToString } from "react-dom/server";
import { Render } from "@puckeditor/core/rsc";
import type { Config, Data } from "@puckeditor/core";
import { loadBrand } from "../lib/brands";
import { basePathOf, readSite, type Site } from "../lib/store";
import { makeKit, type Kit } from "../puck/agent-kit";
import { makeConfig } from "../puck/config";

const WORKSPACE = /^[a-z0-9][a-z0-9-]{0,62}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const BUNDLE = path.join("agent-runs", ".render", "render-site.mjs");

type SectionModule = { render: (props: unknown, kit: Kit) => ReactNode };
type RuntimeSite = Site & { workspace?: string; agentSections?: Record<string, string> };

/** This site's modules, from its own workspace's folder only. */
export async function loadSections(workspace: string, sections: Record<string, string>): Promise<Record<string, SectionModule>> {
  if (!WORKSPACE.test(workspace)) throw new Error(`workspace "${workspace}" is not a workspace id`);
  const loaded: Record<string, SectionModule> = {};
  for (const [name, digest] of Object.entries(sections)) {
    const file = path.join(process.cwd(), "data", "compiled", workspace, `${digest}.mjs`);
    if (!DIGEST.test(digest) || !fs.existsSync(file)) {
      throw new Error(`section_module_missing: ${name} (${digest}) is not a module of workspace ${workspace}`);
    }
    loaded[name] = (await import(pathToFileURL(file).href)) as SectionModule;
  }
  return loaded;
}

export async function renderSite(site: string, route: string, css: string | null): Promise<{ html: string; ms: Record<string, number> }> {
  const ms: Record<string, number> = {};
  let t = performance.now();
  const stored = readSite(site) as RuntimeSite;
  const data = stored.pages[route] as Data | undefined;
  if (!data) throw new Error(`no page ${route} on site ${site}`);
  const brand = loadBrand(stored.brand);
  ms.read = Math.round(performance.now() - t);

  t = performance.now();
  const modules = await loadSections(stored.workspace ?? "", stored.agentSections ?? {});
  ms.importModules = Math.round(performance.now() - t);

  const basePath = basePathOf(site);
  const href = (value: string) =>
    value && value.startsWith("/") && !value.startsWith("//") ? `${basePath}${value === "/" ? "" : value}` : value;
  const kit = makeKit(href);
  const config = makeConfig(brand, { basePath, shell: stored.shell, site }) as Config & { components: Record<string, unknown> };
  for (const [name, module] of Object.entries(modules)) {
    // The same wrapper makeConfig gives a statically imported agent section, so the HTML matches.
    config.components[name] = {
      fields: {},
      render: (props: unknown) => createElement("div", { "data-agent-section": name }, module.render(props, kit)),
    };
  }

  t = performance.now();
  const body = renderToString(createElement(Render, { config, data }));
  ms.renderToString = Math.round(performance.now() - t);
  const head = `<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">` +
    (css ? `<style>${fs.readFileSync(css, "utf-8")}</style>` : "");
  return { html: `<!doctype html><html lang="en"><head>${head}</head><body>${body}</body></html>`, ms };
}

async function bundle(): Promise<void> {
  const { build } = await import("esbuild");
  await build({
    entryPoints: [__filename],
    outfile: BUNDLE,
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node22",
    jsx: "automatic",
    packages: "external",
    external: ["esbuild"],
    // Any import of the static index resolves to an empty one: agent sections come only from disk.
    plugins: [
      {
        name: "no-static-agent-sections",
        setup(b) {
          b.onResolve({ filter: /\/agent-sections$/ }, () => ({ path: "agent-sections", namespace: "empty-index" }));
          b.onLoad({ filter: /.*/, namespace: "empty-index" }, () => ({ contents: "export const AGENT_SECTIONS = {};", loader: "js" }));
        },
      },
    ],
    banner: { js: "// Built by `npx tsx scripts/render-site.ts --bundle`. Do not edit." },
    logLevel: "warning",
  });
  console.error(`wrote ${BUNDLE} (${fs.statSync(BUNDLE).size} bytes)`);
}

async function main() {
  const args = process.argv.slice(2);
  if (args[0] === "--bundle") return bundle();
  const cssAt = args.indexOf("--css");
  const css = cssAt >= 0 ? args[cssAt + 1] : null;
  const [site, route = "/"] = cssAt >= 0 ? args.filter((_, i) => i !== cssAt && i !== cssAt + 1) : args;
  const started = performance.now();
  const { html, ms } = await renderSite(site, route, css);
  process.stdout.write(html);
  console.error(JSON.stringify({ site, route, bytes: html.length, ms: { ...ms, total: Math.round(performance.now() - started) } }));
}

const entry = process.argv[1] ?? "";
if (entry.endsWith("render-site.ts") || entry.endsWith("render-site.mjs")) {
  main().catch((error: unknown) => {
    console.error(String(error instanceof Error ? error.message : error));
    process.exitCode = 1;
  });
}
