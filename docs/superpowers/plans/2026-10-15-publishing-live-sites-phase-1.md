# Publishing Live Sites — Phase 1 (the live core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A published Puck site, for a workspace on the live list, is a normal interactive page: the
server-drawn HTML is taken over by the same React in the visitor's browser, agent sections may use
state, effects, handlers and timers, and the agent's previews show the page after it has come alive.

**Architecture:** The design API's hardened Chromium page keeps drawing the site, now with
`renderToString` and a per-route **page data** object, and checks in the same page that the browser
can take the HTML over without a mismatch. The publish package gains JavaScript files (a site-kit
**site runtime**, three tiny **host shims**, the agent section modules) served by the page origin's
existing `/p-assets/` route, an inline import map allowed by its hash, and a per-publish policy
(`delivery: "site_live"`). Publishing **checks** the rendered HTML instead of stripping it. Everything
is behind `LUMEN_SITE_LIVE_WORKSPACES`; with a workspace off the list, publishing is byte-identical.

**Tech Stack:** React 19.2.4, `@puckeditor/core` 0.23.0, zod 4, esbuild 0.28, `node --test` via tsx,
jsdom 29 (site-kit dev tests), Python 3.12, Playwright (sync), FastAPI (page origin), pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-publishing-live-sites-design.md` (§3, §4.1–§4.7, §5,
§10, §11, §15, §16 phase 1). Founder rulings: spec §2.

## Global Constraints

- Agent-written code never runs in a Python or Node process, and never on `app.cluehq.ai`: on the
  server only inside the hardened Chromium page (`lumen_api.hardened_browser`), in browsers only on
  the editor domain and the published page (D2).
- **Flag off is byte-identical:** for a workspace not in `LUMEN_SITE_LIVE_WORKSPACES`, the publish
  package (HTML, manifest, digests), the thumbnail, the agent's previews, the section checker and the
  agent's prompt are exactly as today. Existing tests stay green unchanged.
- Delivery name: `"site_live"`. Manifest key for the live part: `"live"`. Page data element:
  `<script type="application/json" id="clue-page-data">`. Hydration container: `<div id="clue-site">`.
  Hydrated signal: `window.__clueHydrated === true`.
- Env flag: `LUMEN_SITE_LIVE_WORKSPACES` — comma-separated workspace ids, default empty. It must
  appear with its default in `.env.example` (repo root) **and** `subsystems/clue-design/.env.example`
  in the commit that introduces it, and in the lane's local `.env` (CLAUDE.md parity rule).
- The live page policy (header; the meta form omits `frame-ancestors`):
  `default-src 'none'; script-src 'self' <hashes>; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none'; worker-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'`.
- Section rules in interactive mode keep refusing: `eval`, `Function`, `dangerouslySetInnerHTML`,
  `cookie`, dynamic `import(`, raw `<a>`, raw `<script>`, `<iframe>`, `<form>`, `<object>`, `<embed>`,
  and every brand rule (colours, type, corners, surfaces, motion classes, inline style).
- Wording a person reads (the publish refusal) and the new skill's text are **founder-reviewed before
  they are committed** (Tasks 6 and 11 say where to stop).
- Test first: every new test is run and seen failing for the right reason before the code that makes
  it pass. Never weaken an existing test to make it pass.
- Database tests only through `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh <file>` (it targets
  the throwaway DB `clue_trenton_wave1`); the lane DB `clue_trenton` is read-only. Never run broad
  suites with real keys or anything `*_live.py`. Never run the whole clue-design suite synchronously.
- Commit locally after each task, staging files by explicit path. No AI attribution, no
  `Co-Authored-By` line. Never push. Never `git stash`.
- After any change under `apps/frontend/packages/site-kit/src` or `bin/`, rebuild the bundles
  (`cd apps/frontend && npm run build -w @clue/site-kit`) before running a Python test that renders.

## Review Focus

1. **A section that throws only in the browser** (it reads `window` while drawing): the rest of the
   page must stay alive and visible; only that section is lost, and the failure is reported, never a
   blank page. Pinned in Task 3 (a per-section error boundary, tested in jsdom) and Task 4 (reported
   as a render warning).
2. **A clone or text that contains `</script>`** inside the page data: it must not end the inert
   data element early. Pinned in Task 6 (escaping test).
3. **A live site with no agent sections** (clones and built-in sections only): it still hydrates; the
   import map and shims are still valid. Pinned in Task 6 and Task 8.
4. **A workspace taken off the live list after a live publish**: its live publish keeps being served
   live (the page origin follows the manifest, not the flag); a republish goes back to static.
   Pinned in Task 7.
5. **A stored section module that imports a name the host does not export** (written before Task 2's
   check existed): the render fails loudly with the section named, never a half-hydrated page.
   Pinned in Task 4.

## Not in this plan (later phases, spec §16)

Forms, tracking and the lead email (phase 2); embeds (phase 3); head/body snippets (phase 4); review
group 4.3's fixes and the parity test (phase 5), including S1-5's linked-card refusal; the pages
domain move (group 4.5, in progress separately). Thumbnails stay static (JavaScript off) in this
phase. Open review finding K3-2 (agent code can navigate the editor frame) is not fixed here; the
relaxed rules make it easier to reach, so it is listed for the group 4.2 pass.

## File structure

| File | Responsibility |
|---|---|
| `apps/frontend/packages/site-kit/src/section-host.ts` (new) | The ONE definition of what agent code may import from react, react/jsx-runtime and zod: specifiers, export names, shim source, named-import check |
| `apps/frontend/packages/site-kit/src/live-page.tsx` (new) | `LivePageData`, `brandForPage`, `SiteRoot` (the tree both server and browser draw), `hydrateSite` |
| `apps/frontend/packages/site-kit/src/site-runtime.tsx` (new) | The published page's browser entry: reads the page data, loads sections, hydrates |
| `apps/frontend/packages/site-kit/src/render-core.tsx` | `renderSitePages({live})`: `renderToString` + wrapper + page data in live mode; static mode untouched |
| `apps/frontend/packages/site-kit/src/render-browser.tsx` | Live mode input; the hydration check inside the hardened page; uses `section-host` |
| `apps/frontend/packages/site-kit/src/config.tsx` | Per-section error boundary; `kit.editing` from `puck.isEditing` |
| `apps/frontend/packages/site-kit/src/agent-kit.tsx` | `Kit.editing` |
| `apps/frontend/packages/site-kit/src/check-section.ts` | `LintOptions.interactive`; element refusals |
| `apps/frontend/packages/site-kit/bin/compile-section.ts` | `interactive` input; named-import check |
| `apps/frontend/packages/site-kit/bin/build-bundles.mjs` | Builds `dist/site-runtime.js` and `dist/site-runtime-shims/*.js` |
| `apps/frontend/packages/site-editor/scripts/build.ts` | Shims from `section-host` (no hand list) |
| `subsystems/clue-design/apps/api/lumen_api/site_live.py` (new) | The flag; the live page assembly (import map, page data, runtime tag); the live preview document |
| `subsystems/clue-design/apps/api/lumen_api/site_render.py` | `render_site(live=)`, `RenderedPage.data`, JS-on live screenshot |
| `subsystems/clue-design/apps/api/lumen_api/site_sanitize.py` | `site_html_problems` (check, never rewrite) |
| `subsystems/clue-design/apps/api/lumen_api/site_publish.py` | `build_site_publish_package(live=)` |
| `subsystems/clue-design/apps/api/lumen_api/toolbelt/publishes.py` | Persist live assets; read the flag |
| `subsystems/clue-design/apps/api/lumen_api/site_kit_cli.py`, `site_turn_ports.py`, `main.py` | `interactive` compile; live renderer; flag wiring |
| `subsystems/design/clue_design/publishes.py` | `SITE_LIVE_DELIVERY`, `site_live_csp`, `delivery_csp(script_hashes=)`, `manifest_delivery` |
| `platform/page_origin/clue_page_origin/{reads.py,routes.py}` | Serve `site_live` with its per-publish policy |
| `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/{inputs.py,harness.py,workspace.py}` + `skills-live/` | Mount the interactive skill for live workspaces |
| `docker/backend/smoke.sh`, `tests/deploy/test_backend_image.py` | The image ships the runtime |

---

### Task 1: Spike — the same tree hydrates with zero mismatches (go / no-go)

The whole phase rests on one fact: Puck's client `Render`, drawn to a string, is taken over in a
browser by the same component with no mismatch, for a real site (clones, built-in sections, shell,
an agent section). Prove it before anything else. **If this task fails, stop and report to the
controller with the mismatch messages; do not work around it.**

**Files:**
- Create: `apps/frontend/packages/site-kit/test/hydration-spike.test.tsx`

**Interfaces:**
- Consumes: `makeConfig` (`src/config.tsx`), `garner()` / `site()` (`test/fixtures/garner.ts`),
  `render`/`schema` from `test/fixtures/section-example.tsx`.
- Produces: a ruling recorded in the ledger: **live mode draws with `Render` from
  `@puckeditor/core` on both sides** (static mode keeps `@puckeditor/core/rsc`).

- [ ] **Step 1: Write the spike test**

```tsx
// Spike (publishing live sites, phase 1 Task 1): the server's HTML for a real site is taken over in a
// browser (jsdom) by the same React tree with no hydration mismatch.
import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { Render } from "@puckeditor/core";
import type { Config, Data } from "@puckeditor/core";
import { makeConfig } from "../src/config";
import { garner, site as readSite } from "./fixtures/garner";
import { render as quoteRender, schema as quoteSchema } from "./fixtures/section-example";

const brand = garner();
const stored = readSite("garner-syracuse");

test("spike: every Garner route hydrates with zero recoverable errors", async () => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>");
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, navigator: dom.window.navigator });
  const { hydrateRoot } = await import("react-dom/client");
  const agentSections = { QuoteBand: { schema: quoteSchema, render: quoteRender as never } };
  for (const route of Object.keys(stored.pages)) {
    const data = structuredClone(stored.pages[route]) as Data;
    if (route === "/") data.content.push({ type: "QuoteBand", props: { id: "quote", surface: "brand", quote: "Fewer surprises.", attribution: "A buyer" } } as never);
    const config = makeConfig(brand, { basePath: "/acme", shell: stored.shell, agentSections }) as Config;
    const html = renderToString(createElement(Render as never, { config, data } as never));
    const container = dom.window.document.createElement("div");
    container.innerHTML = html;
    dom.window.document.body.appendChild(container);
    const errors: string[] = [];
    const root = hydrateRoot(container, createElement(Render as never, { config, data } as never), {
      onRecoverableError: (error) => errors.push(String((error as Error)?.message ?? error)),
    });
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.deepEqual(errors, [], `route ${route} hydrated with mismatches`);
    assert.ok(container.querySelector('[data-agent-section="QuoteBand"]') || route !== "/", "the agent section is there");
    root.unmount();
    container.remove();
  }
});
```

- [ ] **Step 2: Run it**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/hydration-spike.test.tsx`
Expected: PASS. If it FAILS: copy the error list into the ledger and stop (plan is blocked; the
controller decides with the founder). If client `Render` cannot render to a string in Node at all,
record the error and stop.

- [ ] **Step 3: Prove the test can fail**

Temporarily change the client tree to a different `data` (e.g. `content: data.content.slice(1)`),
run again, confirm it FAILS with a hydration error, then restore. Record "seen red" in the ledger.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/packages/site-kit/test/hydration-spike.test.tsx
git commit -m "site-kit: spike — a real site's server HTML hydrates in the browser with no mismatch (live publishing, phase 1)"
```

---

### Task 2: One definition of what agent code imports (review finding K2-1)

Today the renderer hands agent sections every export of react and zod, the editor a hand-written
list (`site-editor/scripts/build.ts:18-31`), and the write check never looks at names. One module now
decides, and all three hosts plus the compile check use it.

**Files:**
- Create: `apps/frontend/packages/site-kit/src/section-host.ts`
- Create: `apps/frontend/packages/site-kit/test/section-host.test.ts`
- Modify: `apps/frontend/packages/site-kit/src/render-browser.tsx:31-58` (use `hostModules`, `hostExportNames`, `shimSource`)
- Modify: `apps/frontend/packages/site-kit/bin/compile-section.ts:21-23,57-62` (`HOST_SPECIFIERS` from section-host; named-import check)
- Modify: `apps/frontend/packages/site-kit/package.json` (export `./section-host`)
- Modify: `apps/frontend/packages/site-editor/scripts/build.ts:16-46` (shims from section-host)
- Modify: `apps/frontend/packages/site-editor/src/client/host-globals.ts` (use `hostModules`)
- Test: `apps/frontend/packages/site-kit/test/compile-section.test.ts`, `apps/frontend/packages/site-editor/test/build.test.ts`

**Interfaces:**
- Produces (exported from `@clue/site-kit/section-host`):
  - `HOST_SPECIFIERS: readonly ["react", "react/jsx-runtime", "zod"]`
  - `type HostSpecifier = (typeof HOST_SPECIFIERS)[number]`
  - `hostModules(): Record<HostSpecifier, Record<string, unknown>>`
  - `hostExportNames(module: Record<string, unknown>): string[]` (sorted)
  - `shimSource(specifier: HostSpecifier, names: readonly string[]): string`
  - `foreignHostImports(moduleJs: string): string[]` — one message per named import the host lacks

- [ ] **Step 1: Write the failing tests**

`test/section-host.test.ts`:

```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { foreignHostImports, hostExportNames, hostModules, shimSource } from "../src/section-host";

test("every host hands over every export its library has, so a section loads the same everywhere", () => {
  const modules = hostModules();
  const react = hostExportNames(modules.react);
  for (const name of ["cache", "use", "useState", "useActionState", "startTransition"]) assert.ok(react.includes(name), name);
  assert.ok(hostExportNames(modules.zod).includes("toJSONSchema"));
  assert.ok(hostExportNames(modules["react/jsx-runtime"]).includes("jsx"));
  assert.ok(!react.includes("default"));
  assert.deepEqual(react, [...react].sort());
});

test("a shim re-exports the host's own copy and names a missing host plainly", () => {
  const source = shimSource("react", ["useState", "cache"]);
  assert.ok(source.includes('globalThis.__clueSectionHost && globalThis.__clueSectionHost["react"]'));
  assert.ok(source.includes("export const { useState, cache } = m;"));
  assert.ok(source.includes("export default m.default ?? m;"));
});

test("a named import the host does not have is refused by name", () => {
  const ok = 'import { useState as s } from "react";\nimport { z, toJSONSchema } from "zod";\nimport { jsx } from "react/jsx-runtime";';
  assert.deepEqual(foreignHostImports(ok), []);
  const bad = 'import { useStat, cache } from "react";\nimport { zz } from "zod";';
  assert.deepEqual(foreignHostImports(bad), [
    'the module imports "useStat" from "react", which react does not export',
    'the module imports "zz" from "zod", which zod does not export',
  ]);
});
```

Append to `test/compile-section.test.ts` (read the file first and follow its fixture style; it
already compiles `fixtures/section-example.tsx`):

```ts
test("K2-1: a section importing a name react does not export is refused at write time", async () => {
  const source = fs.readFileSync(new URL("./fixtures/section-example.tsx", import.meta.url), "utf-8")
    .replace('import { z } from "zod";', 'import { z } from "zod";\nimport { useNotAHook } from "react";\nvoid useNotAHook;');
  const result = await compileSection({ name: "QuoteBand", source, brand: garner() });
  assert.equal(result.ok, false);
  assert.ok(!result.ok && result.errors.some((e) => e.includes('"useNotAHook" from "react"')), JSON.stringify(result));
});
```

(If the TypeScript check refuses `useNotAHook` first, assert on either message: what matters is the
refusal; then add a second case using a real React export the editor's old list lacked, `cache`,
and assert it now compiles `ok`.)

In `apps/frontend/packages/site-editor/test/build.test.ts`, add:

```ts
test("K2-1: the editor's react shim hands over every react export, not a hand-written list", () => {
  const react = SHIMS["react.mjs"];
  assert.ok(react.names.includes("cache") && react.names.includes("use"));
});
```

(import `SHIMS` from `../scripts/build`.)

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/section-host.test.ts test/compile-section.test.ts`
Expected: FAIL — `Cannot find module '../src/section-host'`, and the K2-1 compile case compiles ok.
Run: `cd apps/frontend/packages/site-editor && npx tsx --test test/build.test.ts`
Expected: FAIL — `cache` is not in the editor's list.

- [ ] **Step 3: Write `src/section-host.ts`**

```ts
// What an agent section may import, decided once (review finding K2-1). A compiled section keeps
// three imports: react, react/jsx-runtime and zod. Every host — the hardened render page, the editor
// frame and the published page — hands over the SAME copy of each library through a shim that
// re-exports every name the library has, and the write check refuses a named import the library
// does not have. Before this, the editor handed over a hand-written short list, so a section could
// publish fine and then fail to open in the editor.
import * as React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import * as zod from "zod";

export const HOST_SPECIFIERS = ["react", "react/jsx-runtime", "zod"] as const;
export type HostSpecifier = (typeof HOST_SPECIFIERS)[number];

const RESERVED = new Set(
  ("break case catch class const continue debugger default delete do else enum export extends false finally for " +
    "function if import in instanceof new null return super switch this throw true try typeof var void while with " +
    "yield let static implements interface package private protected public await").split(" "),
);
const IDENTIFIER = /^[A-Za-z_$][\w$]*$/;

export function hostModules(): Record<HostSpecifier, Record<string, unknown>> {
  return {
    react: React as unknown as Record<string, unknown>,
    "react/jsx-runtime": jsxRuntime as unknown as Record<string, unknown>,
    zod: zod as unknown as Record<string, unknown>,
  };
}

/** Every name a shim re-exports from a library: all of its exports a module can bind by name. */
export function hostExportNames(module: Record<string, unknown>): string[] {
  return Object.keys(module).filter((name) => name !== "default" && IDENTIFIER.test(name) && !RESERVED.has(name)).sort();
}

/** The ES module that stands in for `specifier`: it re-exports the host's own copy, put on
 * globalThis.__clueSectionHost by whoever loads sections, before any section is imported. */
export function shimSource(specifier: HostSpecifier, names: readonly string[]): string {
  return [
    `const m = globalThis.__clueSectionHost && globalThis.__clueSectionHost[${JSON.stringify(specifier)}];`,
    `if (!m) throw new Error(${JSON.stringify(`The page has not shared ${specifier} with agent sections.`)});`,
    "export default m.default ?? m;",
    ...(names.length ? [`export const { ${names.join(", ")} } = m;`] : []),
    "",
  ].join("\n");
}

const NAMED_IMPORT = /import\s*\{([^}]*)\}\s*from\s*["'](react\/jsx-runtime|react|zod)["']/g;

/** One message per name a compiled module imports from a host library that the library lacks. */
export function foreignHostImports(moduleJs: string): string[] {
  const modules = hostModules();
  const errors: string[] = [];
  for (const match of moduleJs.matchAll(NAMED_IMPORT)) {
    const specifier = match[2] as HostSpecifier;
    const known = new Set(hostExportNames(modules[specifier]));
    for (const part of match[1].split(",")) {
      const name = part.trim().split(/\s+as\s+/)[0]?.trim();
      if (name && !known.has(name)) errors.push(`the module imports "${name}" from "${specifier}", which ${specifier} does not export`);
    }
  }
  return errors;
}
```

- [ ] **Step 4: Use it everywhere**

`bin/compile-section.ts`: delete the local `HOST_SPECIFIERS` export and import it from
`../src/section-host`; after the `foreign` check (line ~61) add:

```ts
    const missing = foreignHostImports(moduleJs);
    if (missing.length) return fail(missing);
```

Keep re-exporting `HOST_SPECIFIERS` from `compile-section.ts` (`export { HOST_SPECIFIERS } from "../src/section-host";`)
if any other file imports it from there (`grep -rn "HOST_SPECIFIERS" apps/frontend/packages`).

`src/render-browser.tsx`: replace the `HOST` constant, `RESERVED` and `shimFor` with:

```ts
const HOST = hostModules();
const shimFor = (specifier: HostSpecifier) => shimSource(specifier, hostExportNames(HOST[specifier]));
```

and build `shims` with `HOST_SPECIFIERS.map(...)`. (The render page's shim now throws a clear error
if the host is missing instead of failing on `undefined`; the host is always set before sections
load, so output is unchanged.)

`site-editor/scripts/build.ts`: delete `REACT_EXPORTS` and the local `shimSource`; import
`{ hostExportNames, hostModules, shimSource }` from `@clue/site-kit/section-host` and build:

```ts
const HOST = hostModules();
export const SHIMS: Record<string, { names: readonly string[]; specifier: HostSpecifier }> = {
  "react-jsx-runtime.mjs": { names: hostExportNames(HOST["react/jsx-runtime"]), specifier: "react/jsx-runtime" },
  "react.mjs": { names: hostExportNames(HOST.react), specifier: "react" },
  "zod.mjs": { names: hostExportNames(HOST.zod), specifier: "zod" },
};
export { shimSource };
```

Keep `export function shimSource` reachable from `scripts/build.ts` for the existing test
(`build.test.ts:39`); its expected text changes from "The site editor has not shared" to "The page
has not shared" — update that one assertion and say so in the commit message.

`site-editor/src/client/host-globals.ts`: `globalThis.__clueSectionHost = hostModules();`.

`site-kit/package.json` exports: add `"./section-host": "./src/section-host.ts"`.

- [ ] **Step 5: Run the tests and the builds**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/section-host.test.ts test/compile-section.test.ts test/render-core.test.tsx test/bundles.test.ts`
Run: `cd apps/frontend/packages/site-editor && npx tsx --test test/*.test.ts && npx tsx scripts/build.ts`
Run: `cd apps/frontend && npm run build -w @clue/site-kit`
Then the editor browser harness, which loads real sections through the shims:
`CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh tests/site_editor`
Expected: all PASS (21/21 in the harness).

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/packages/site-kit/src/section-host.ts apps/frontend/packages/site-kit/test/section-host.test.ts \
  apps/frontend/packages/site-kit/src/render-browser.tsx apps/frontend/packages/site-kit/bin/compile-section.ts \
  apps/frontend/packages/site-kit/test/compile-section.test.ts apps/frontend/packages/site-kit/package.json \
  apps/frontend/packages/site-editor/scripts/build.ts apps/frontend/packages/site-editor/src/client/host-globals.ts \
  apps/frontend/packages/site-editor/test/build.test.ts
git commit -m "site-kit: one definition of what agent sections import; every host hands over every export and the write check refuses a missing name (review K2-1)"
```

---

### Task 3: The live tree, page data, hydration and the per-section boundary (site-kit)

**Files:**
- Create: `apps/frontend/packages/site-kit/src/live-page.tsx`
- Create: `apps/frontend/packages/site-kit/test/live-page.test.tsx`
- Modify: `apps/frontend/packages/site-kit/src/config.tsx:154-166` (agent section wrapper: boundary)
- Modify: `apps/frontend/packages/site-kit/src/render-core.tsx:37-72` (live mode)
- Modify: `apps/frontend/packages/site-kit/test/render-core.test.tsx`

**Interfaces:**
- Consumes: `makeConfig` (Task-unchanged signature), Task 1's ruling (client `Render`).
- Produces (from `src/live-page.tsx`):
  ```ts
  export type LivePageData = {
    route: string;
    basePath: string;
    title: string;
    page: Data;
    shell: ShellData | null;
    brand: BrandData;               // trimmed by brandForPage
    sections: Record<string, string>; // agent section name -> module URL; {} from the renderer, filled by the publisher
  };
  export function brandForPage(brand: BrandData, page: Data, shell: ShellData | null): BrandData;
  export function SiteRoot(props: { config: Config; data: Data; onReady?: () => void }): JSX.Element;
  export function hydrateSite(input: {
    container: Element;
    data: LivePageData;
    agentSections: Record<string, AgentSectionModule>;
    report: (message: string) => void;
  }): { ready: Promise<void>; unmount: () => void };
  ```
- Produces (`render-core.tsx`): `renderSitePages({ ..., live?: boolean })` returns
  `{ pages: { route: string; html: string; data?: LivePageData }[]; ... }`.
  Live html: `<!doctype html><html lang="en"><head><title>…</title></head><body><div id="clue-site">…</div></body></html>`.

- [ ] **Step 1: Write the failing tests** (`test/live-page.test.tsx`)

```tsx
import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { brandForPage, hydrateSite, type LivePageData } from "../src/live-page";
import { renderSitePages } from "../src/render-core";
import { garner, site as readSite } from "./fixtures/garner";
import { render as quoteRender, schema as quoteSchema } from "./fixtures/section-example";

const brand = garner();
const stored = readSite("garner-syracuse");
const site = { title: "Garner for Syracuse", pages: stored.pages, shell: stored.shell };

function jsdom() {
  const dom = new JSDOM("<!doctype html><html><body></body></html>");
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, navigator: dom.window.navigator });
  return dom;
}

const bodyOf = (html: string) => html.slice(html.indexOf('<div id="clue-site">') + '<div id="clue-site">'.length, html.lastIndexOf("</div></body>"));

test("a page's data carries only the clones that page uses", () => {
  const page = stored.pages["/"];
  const used = new Set(page.content.filter((c: { type: string }) => c.type === "ClonedSection").map((c: { props: { fragmentId: string } }) => c.props.fragmentId));
  const trimmed = brandForPage(brand, page, stored.shell);
  assert.deepEqual(new Set(Object.keys(trimmed.clones)), used);
  assert.deepEqual(trimmed.kit, brand.kit);
});

test("live mode draws each route into #clue-site and returns its page data; static mode is unchanged", () => {
  const live = renderSitePages({ site, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000, live: true });
  const home = live.pages[0];
  assert.ok(home.html.includes('<body><div id="clue-site">') && home.html.endsWith("</div></body></html>"));
  assert.equal(home.data?.route, "/");
  assert.equal(home.data?.basePath, "/acme");
  assert.deepEqual(home.data?.sections, {});
  const still = renderSitePages({ site, brand, basePath: "/acme", agentSections: {}, maxOutputBytes: 10_000_000 });
  assert.equal(still.pages[0].data, undefined);
  assert.ok(!still.pages[0].html.includes('id="clue-site"'));
});

test("the browser takes the live HTML over with no mismatch", async () => {
  const dom = jsdom();
  const agentSections = { QuoteBand: { schema: quoteSchema, render: quoteRender as never } };
  const live = renderSitePages({ site, brand, basePath: "/acme", agentSections, maxOutputBytes: 10_000_000, live: true });
  for (const page of live.pages) {
    const container = dom.window.document.createElement("div");
    container.innerHTML = bodyOf(page.html);
    dom.window.document.body.appendChild(container);
    const reports: string[] = [];
    const run = hydrateSite({ container, data: page.data as LivePageData, agentSections, report: (m) => reports.push(m) });
    await run.ready;
    assert.deepEqual(reports, [], page.route);
    run.unmount();
  }
});

test("Review focus 1: a section that throws only in the browser is lost alone, and reported", async () => {
  const dom = jsdom();
  const home = structuredClone(stored.pages["/"]);
  home.content.push({ type: "Fragile", props: { id: "fragile", surface: "page" } });
  const Fragile = {
    schema: quoteSchema,
    render: (() => {
      if (typeof window !== "undefined" && (window as { __clueBrowser?: boolean }).__clueBrowser) throw new Error("reads window while drawing");
      return null;
    }) as never,
  };
  const live = renderSitePages({ site: { ...site, pages: { "/": home } }, brand, basePath: "", agentSections: { Fragile }, maxOutputBytes: 10_000_000, live: true });
  (dom.window as unknown as { __clueBrowser: boolean }).__clueBrowser = true;
  const container = dom.window.document.createElement("div");
  container.innerHTML = bodyOf(live.pages[0].html);
  dom.window.document.body.appendChild(container);
  const reports: string[] = [];
  const run = hydrateSite({ container, data: live.pages[0].data as LivePageData, agentSections: { Fragile }, report: (m) => reports.push(m) });
  await run.ready;
  assert.ok(reports.some((m) => m.includes("Fragile") && m.includes("reads window while drawing")), JSON.stringify(reports));
  assert.ok(container.querySelector(".brand-root"), "the rest of the page is still there");
  run.unmount();
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/live-page.test.tsx`
Expected: FAIL — `Cannot find module '../src/live-page'`.

- [ ] **Step 3: Write `src/live-page.tsx`**

```tsx
// A live site page (publishing live sites, phase 1): what the server draws and the browser takes
// over. The server (render-core, inside the hardened page) and the browser (site-runtime, and the
// render page's own hydration check) draw the SAME tree — SiteRoot around Puck's client Render — so
// React finds exactly the HTML it expects. A tree with an extra component on one side only would move
// React's ids and break the take-over.
import { createElement, useEffect } from "react";
import { Render, type Config, type Data } from "@puckeditor/core";
import type { AgentSectionModule } from "./agent-kit";
import type { BrandData } from "./brand";
import { makeConfig } from "./config";
import type { ShellData } from "./shell";

export type LivePageData = {
  route: string;
  basePath: string;
  title: string;
  page: Data;
  shell: ShellData | null;
  brand: BrandData;
  sections: Record<string, string>;
};

/** The brand a page needs: everything but the clones it does not use (clones carry captured HTML
 * and CSS and are the bulk of a brand). */
export function brandForPage(brand: BrandData, page: Data, _shell: ShellData | null): BrandData {
  const used = new Set(
    (page.content ?? [])
      .filter((item) => item.type === "ClonedSection")
      .map((item) => String((item.props as { fragmentId?: unknown }).fragmentId ?? "")),
  );
  return { ...brand, clones: Object.fromEntries(Object.entries(brand.clones).filter(([id]) => used.has(id))) };
}

export function SiteRoot({ config, data, onReady }: { config: Config; data: Data; onReady?: () => void }) {
  useEffect(() => onReady?.(), [onReady]);
  return createElement(Render as never, { config, data } as never);
}

export function liveConfig(data: LivePageData, agentSections: Record<string, AgentSectionModule>): Config {
  return makeConfig(data.brand, { basePath: data.basePath || undefined, shell: data.shell ?? undefined, agentSections }) as Config;
}

/** Takes the server's HTML in `container` over. `ready` resolves after the first commit; every
 * mismatch, every error a section boundary caught and every uncaught error goes to `report`. */
export function hydrateSite(input: {
  container: Element;
  data: LivePageData;
  agentSections: Record<string, AgentSectionModule>;
  report: (message: string) => void;
}): { ready: Promise<void>; unmount: () => void } {
  // Imported here, not at the top: render-core (Node) imports this module and has no DOM.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { hydrateRoot } = require("react-dom/client") as typeof import("react-dom/client");
  const config = liveConfig(input.data, input.agentSections);
  const say = (kind: string) => (error: unknown) =>
    input.report(`${kind}: ${error instanceof Error ? error.message : String(error)}`);
  let resolve: () => void = () => undefined;
  const ready = new Promise<void>((done) => (resolve = done));
  const root = hydrateRoot(input.container, createElement(SiteRoot, { config, data: input.data.page, onReady: () => resolve() }), {
    onRecoverableError: say("mismatch"),
    onCaughtError: say("section failed"),
    onUncaughtError: say("page failed"),
  });
  return { ready, unmount: () => root.unmount() };
}
```

If `require` is unavailable under the package's ESM build, use a top-level
`import { hydrateRoot } from "react-dom/client";` instead and keep render-core from importing this
module's `hydrateSite` (render-core only needs `SiteRoot`, `brandForPage` and `LivePageData`; move
`hydrateSite` into `src/hydrate.ts` if the Node import fails). Record the choice in the ledger.

- [ ] **Step 4: Name the failing section in the boundary** (`src/config.tsx`)

Add above `makeConfig`:

```tsx
/** One agent section that fails while drawing in the browser takes only itself down: the rest of
 * the page stays alive (Review focus 1 of live publishing). The message names the section. Renders no
 * element of its own, so the server HTML is unchanged. */
class SectionBoundary extends Component<{ name: string; children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    if (error instanceof Error) error.message = `${this.props.name}: ${error.message}`;
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}
```

(`import { Component } from "react";`). Change the agent section render (config.tsx:162) to:

```tsx
        render: (props: never) => (
          <div data-agent-section={name}>
            <SectionBoundary name={name}>{module.render(props, kit)}</SectionBoundary>
          </div>
        ),
```

Note `module.render` is now called inside the boundary's children expression, i.e. still during the
wrapper's render; for the boundary to catch it, wrap the call in a component:
`const Drawn = () => module.render(props, kit) as React.ReactElement;` defined at module level per
section (inside the `Object.entries(...).map`), and render `<SectionBoundary name={name}><Drawn {...props} /></SectionBoundary>`.
Verify with the Review-focus test that the message names `Fragile`.

- [ ] **Step 5: Live mode in `render-core.tsx`**

```tsx
import { renderToString } from "react-dom/server";
import { SiteRoot, brandForPage, type LivePageData } from "./live-page";
// …
export type RenderedSitePage = { route: string; html: string; data?: LivePageData };
// in renderSitePages' input: live?: boolean
// inside the route loop, replacing the body/html lines:
    let body: string;
    let pageData: LivePageData | undefined;
    if (input.live) {
      body = `<div id="clue-site">${renderToString(createElement(SiteRoot, { config, data }))}</div>`;
      pageData = {
        route,
        basePath: input.basePath,
        title,
        page: data,
        shell: input.site.shell ?? null,
        brand: brandForPage(input.brand, data, input.site.shell ?? null),
        sections: {},
      };
    } else {
      body = renderToStaticMarkup(createElement(Render as never, { config, data } as never));
    }
    const html = `<!doctype html><html lang="en"><head><title>${escapeHtml(title)}</title></head><body>${body}</body></html>`;
    // size accounting unchanged
    pages.push(pageData ? { route, html, data: pageData } : { route, html });
```

The live `config` must be the one `liveConfig(pageData, agentSections)` would build in the browser
(same `basePath` normalisation: `input.basePath || undefined`, same shell) — it already is.

- [ ] **Step 6: Run the tests**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/live-page.test.tsx test/render-core.test.tsx test/hydration-spike.test.tsx test/agent-kit.test.tsx test/sections.test.tsx`
Expected: all PASS; the existing render-core tests (static mode) pass unchanged.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/packages/site-kit/src/live-page.tsx apps/frontend/packages/site-kit/test/live-page.test.tsx \
  apps/frontend/packages/site-kit/src/config.tsx apps/frontend/packages/site-kit/src/render-core.tsx \
  apps/frontend/packages/site-kit/test/render-core.test.tsx
git commit -m "site-kit: the live page — one tree for server and browser, per-page data, hydration, and a failing agent section taken down alone"
```

---

### Task 4: The site runtime, its bundle, and the hydration check in the render page

**Files:**
- Create: `apps/frontend/packages/site-kit/src/site-runtime.tsx`
- Modify: `apps/frontend/packages/site-kit/bin/build-bundles.mjs`
- Modify: `apps/frontend/packages/site-kit/src/render-browser.tsx` (live input; hydration check)
- Modify: `apps/frontend/packages/site-kit/test/bundles.test.ts`
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_render.py:63-69,396-434` (`RenderedPage.data`, `render_site(live=)`)
- Test: `subsystems/clue-design/apps/api/tests/test_site_render.py`

**Interfaces:**
- Consumes: Task 2 (`hostModules`, `hostExportNames`, `shimSource`, `HOST_SPECIFIERS`), Task 3
  (`hydrateSite`, `LivePageData`, `renderSitePages({live})`).
- Produces:
  - `dist/site-runtime.js` (ES module) and `dist/site-runtime-shims/{react,react-jsx-runtime,zod}.js`.
  - Runtime contract: reads `#clue-page-data` (JSON `LivePageData` with `sections` = name → URL), sets
    `globalThis.__clueSectionHost = hostModules()`, `await import(url)` per section, hydrates
    `#clue-site`, then sets `window.__clueHydrated = true`; logs each report with `console.error("[clue-site] " + message)`.
  - Python: `RenderedPage(route: str, html: str, data: dict | None = None)`;
    `render_site(site, brand, sections, *, base_path, routes=None, live=False, …)`; in live mode the
    warnings include one line per hydration report: `"hydration on <route>: <message>"`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/frontend/packages/site-kit/test/bundles.test.ts`:

```ts
test("the build writes the site runtime as one ES module and a shim per host library", () => {
  execFileSync(process.execPath, ["bin/build-bundles.mjs"], { cwd: root });
  const runtime = fs.readFileSync(path.join(root, "dist", "site-runtime.js"), "utf-8");
  assert.ok(runtime.includes("clue-page-data") && runtime.includes("__clueHydrated") && runtime.includes("__clueSectionHost"));
  for (const file of ["react.js", "react-jsx-runtime.js", "zod.js"]) {
    const shim = fs.readFileSync(path.join(root, "dist", "site-runtime-shims", file), "utf-8");
    assert.ok(shim.startsWith("const m = globalThis.__clueSectionHost"), file);
  }
  assert.ok(fs.readFileSync(path.join(root, "dist", "site-runtime-shims", "react.js"), "utf-8").includes(" cache"));
});
```

Append to `subsystems/clue-design/apps/api/tests/test_site_render.py` (read its top first: it has
the `_browser_and_bundle` skip fixture and fixture helpers `garner_brand()`/`garner_site()` from
`site_kit_support`; reuse them):

```python
def test_live_render_returns_page_data_and_takes_the_html_over_without_a_mismatch() -> None:
    site = garner_site()
    result = site_render.render_site(site, garner_brand(), [], base_path="/acme", live=True)
    home = result.pages[0]
    assert '<body><div id="clue-site">' in home.html
    assert home.data is not None and home.data["route"] == "/" and home.data["sections"] == {}
    assert not [w for w in result.warnings if w.startswith("hydration")], result.warnings


def test_a_section_that_draws_differently_in_the_browser_is_reported_by_route() -> None:
    module_js = (
        'import { jsx } from "react/jsx-runtime";\n'
        'import { z } from "zod";\n'
        'export const schema = z.object({ id: z.string(), surface: z.string() }).strict();\n'
        'export function render() { return jsx("p", { children: typeof window.__clueRender === "object" && document.getElementById("clue-site") ? "browser" : "server" }); }\n'
    )
    site, sections = site_with_agent_section("Drift", module_js)  # helper below
    result = site_render.render_site(site, garner_brand(), sections, base_path="", live=True)
    assert any(w.startswith("hydration on /: mismatch") for w in result.warnings), result.warnings


def test_review_focus_5_a_stored_module_importing_a_missing_name_fails_by_name() -> None:
    module_js = 'import { useNotAHook } from "react";\nexport const schema = null;\nexport function render() { useNotAHook(); return null; }\n'
    site, sections = site_with_agent_section("Broken", module_js)
    with pytest.raises(site_render.SiteRenderError) as refused:
        site_render.render_site(site, garner_brand(), sections, base_path="", live=True)
    assert "useNotAHook" in refused.value.message


def test_static_render_is_unchanged_and_carries_no_page_data() -> None:
    result = site_render.render_site(garner_site(), garner_brand(), [], base_path="/acme")
    assert all(page.data is None for page in result.pages)
    assert 'id="clue-site"' not in result.pages[0].html
```

Add the helper to `site_kit_support.py` (follow its style):

```python
def site_with_agent_section(name: str, module_js: str) -> tuple[dict[str, Any], list[Any]]:
    """garner-syracuse with one agent section ``name`` appended to its home page, and its module."""
    from lumen_api.site_render import SectionModule

    site = garner_site()
    digest = hashlib.sha256(module_js.encode("utf-8")).hexdigest()
    site["pages"]["/"]["content"].append({"type": name, "props": {"id": name.lower(), "surface": "page"}})
    site["agent_sections"] = {name: digest}
    return site, [SectionModule(name=name, digest=digest, module_js=module_js, css="", props_schema={})]
```

(If `garner_site()` does not exist under that name, use the fixture function the file already uses to
load `garner-syracuse.json` as a stored site with `id`, `title`, `theme`, `pages`, `shell`,
`agent_sections`.)

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/bundles.test.ts` → FAIL (no `site-runtime.js`).
Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_render.py -k "live or review_focus_5 or static_render_is_unchanged"`
Expected: FAIL — `render_site() got an unexpected keyword argument 'live'`.

- [ ] **Step 3: Write `src/site-runtime.tsx`**

```tsx
// The published page's browser entry (publishing live sites, phase 1). Built by bin/build-bundles.mjs
// into dist/site-runtime.js, one ES module with React, Puck's Render, zod and this kit inside. The
// page loads it as <script type="module" src="/p-assets/<sha>.js">; its import map points react,
// react/jsx-runtime and zod at /p-assets shims that hand over THIS module's copies.
import type { AgentSectionModule } from "./agent-kit";
import { hydrateSite, type LivePageData } from "./live-page";
import { hostModules } from "./section-host";

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
```

(A section that failed to load is left out of `agentSections`; Puck then draws nothing for it and
React reports the mismatch, so the page still comes alive around it.)

- [ ] **Step 4: Build it** (`bin/build-bundles.mjs`)

Append (and update the header comment list):

```js
import fs from "node:fs/promises";
// …after the render-browser build:
await build({
  absWorkingDir: root,
  entryPoints: ["src/site-runtime.tsx"],
  outfile: path.join(dist, "site-runtime.js"),
  bundle: true,
  platform: "browser",
  format: "esm",
  target: "chrome120",
  jsx: "automatic",
  minify: true,
  legalComments: "none",
  define: { "process.env.NODE_ENV": '"production"' },
  logLevel: "warning",
  banner,
});
const { HOST_SPECIFIERS, hostExportNames, hostModules, shimSource } = await import("../src/section-host.ts");
```

The script is plain `node`; it cannot import `.ts`. Instead, build a tiny Node bundle of
`src/section-host.ts` to a temp file with esbuild (`platform: "node", format: "esm", bundle: true,
write: true, outfile: <tmp>/section-host.mjs`) and `import()` it, or compute the shims inside the
esbuild of a small entry `bin/write-shims.ts` run with `node --import tsx`. Choose the esbuild-temp
route (no new runtime dependency); then:

```js
const host = await import(pathToFileURL(tmpSectionHost).href);
const modules = host.hostModules();
await fs.mkdir(path.join(dist, "site-runtime-shims"), { recursive: true });
const SHIM_FILES = { react: "react.js", "react/jsx-runtime": "react-jsx-runtime.js", zod: "zod.js" };
for (const specifier of host.HOST_SPECIFIERS) {
  await fs.writeFile(path.join(dist, "site-runtime-shims", SHIM_FILES[specifier]), host.shimSource(specifier, host.hostExportNames(modules[specifier])));
}
```

- [ ] **Step 5: Live mode and the hydration check in `src/render-browser.tsx`**

Add `live?: boolean` to `Input`. After `renderSitePages(...)` (pass `live: input.live === true`), when
live, for each page:

```tsx
    if (input.live) {
      for (const page of rendered.pages) {
        const start = page.html.indexOf('<div id="clue-site">') + '<div id="clue-site">'.length;
        const container = document.createElement("div");
        container.innerHTML = page.html.slice(start, page.html.lastIndexOf("</div></body>"));
        document.body.appendChild(container);
        const reports: string[] = [];
        const run = hydrateSite({ container, data: page.data!, agentSections, report: (m) => reports.push(m) });
        await Promise.race([run.ready, new Promise((done) => setTimeout(done, 3000))]);
        run.unmount();
        container.remove();
        for (const message of reports) rendered.warnings.push(`hydration on ${page.route}: ${message}`);
      }
    }
```

The result already carries `pages` (with `data`) and `warnings`. The render page's 20 s deadline
(`site_render._CloseAtDeadline`) still bounds everything, including effects.

- [ ] **Step 6: Python `render_site(live=)`** (`site_render.py`)

```python
@dataclass(frozen=True)
class RenderedPage:
    """One route of a rendered site: a whole HTML document, without the site's compiled CSS. In live
    mode ``data`` is the page's data (site-kit ``LivePageData``) the published page hydrates from."""

    route: str
    html: str
    data: JsonObject | None = None
```

`render_site(..., live: bool = False, ...)`: add `"live": live` to `payload`, and build pages with
`RenderedPage(route=str(page["route"]), html=str(page["html"]), data=page.get("data") if live else None)`.
Update its docstring with one sentence on live mode.

- [ ] **Step 7: Rebuild and run**

Run: `cd apps/frontend && npm run build -w @clue/site-kit`
Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/bundles.test.ts test/live-page.test.tsx`
Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_render.py`
Expected: all PASS (the existing render tests unchanged).

- [ ] **Step 8: Commit**

```bash
git add apps/frontend/packages/site-kit/src/site-runtime.tsx apps/frontend/packages/site-kit/bin/build-bundles.mjs \
  apps/frontend/packages/site-kit/src/render-browser.tsx apps/frontend/packages/site-kit/test/bundles.test.ts \
  subsystems/clue-design/apps/api/lumen_api/site_render.py subsystems/clue-design/apps/api/tests/test_site_render.py \
  subsystems/clue-design/apps/api/tests/site_kit_support.py
git commit -m "site-kit + design API: the site runtime and its shims, and a live render that checks in the hardened page that the browser takes its HTML over cleanly"
```

---

### Task 5: The live page policy and its delivery name (`clue_design.publishes`)

**Files:**
- Modify: `subsystems/design/clue_design/publishes.py:543-563`
- Test: find the module's own tests (`grep -rln "SITE_DELIVERY_CSP\|manifest_delivery" tests subsystems/design`) and add there; else create `tests/design/test_site_live_policy.py`.

**Interfaces:**
- Produces:
  - `SITE_LIVE_DELIVERY = "site_live"`
  - `site_live_csp(script_hashes: Sequence[str], *, meta: bool) -> str` — `script_hashes` are
    `"sha256-<base64>"` tokens, emitted quoted and sorted.
  - `delivery_csp(*, meta: bool = False, delivery: str = "web", script_hashes: Sequence[str] = ()) -> str`
  - `manifest_delivery(manifest) -> "web" | "site" | "site_live"`
  - `live_script_hashes(manifest) -> tuple[str, ...]` — from `manifest["live"]["script_hashes"]`, each validated as `sha256-[A-Za-z0-9+/]{43}=`; anything else dropped.

- [ ] **Step 1: Write the failing tests**

```python
from clue_design.publishes import (
    SITE_LIVE_DELIVERY, delivery_csp, live_script_hashes, manifest_delivery, site_live_csp,
)

HASH = "sha256-" + "A" * 43 + "="


def test_the_live_policy_runs_only_our_own_files_and_the_hashed_import_map() -> None:
    header = site_live_csp([HASH], meta=False)
    assert header == (
        "default-src 'none'; script-src 'self' 'sha256-" + "A" * 43 + "='; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none'; "
        "worker-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'"
    )
    assert site_live_csp([HASH], meta=True) == header.removesuffix("; frame-ancestors 'self'")
    assert "unsafe-eval" not in header and "'unsafe-inline'" not in header.split("style-src")[0]


def test_a_manifest_names_its_delivery_and_only_well_formed_hashes_are_used() -> None:
    assert manifest_delivery({"delivery": SITE_LIVE_DELIVERY}) == "site_live"
    assert manifest_delivery({"delivery": "site"}) == "site"
    assert manifest_delivery({"delivery": "anything"}) == "web"
    manifest = {"delivery": "site_live", "live": {"script_hashes": [HASH, "sha256-x' 'unsafe-eval", 7]}}
    assert live_script_hashes(manifest) == (HASH,)
    assert delivery_csp(delivery="site_live", script_hashes=(HASH,)) == site_live_csp([HASH], meta=False)
```

- [ ] **Step 2: Run to see it fail** (`ImportError: SITE_LIVE_DELIVERY`), via `pytest-keyless.sh <file>`.

- [ ] **Step 3: Implement**

```python
#: A LIVE Puck site publish (publishing live sites, phase 1): the page runs its own files from
#: /p-assets (the site runtime, the host shims, the agent section modules) and the one inline import
#: map, allowed by its hash. Nothing else runs; it may connect only to its own origin; it frames and
#: submits nothing (forms, embeds and snippets come in later phases and widen this per site).
SITE_LIVE_DELIVERY = "site_live"
_HASH_TOKEN = re.compile(r"^sha256-[A-Za-z0-9+/]{43}=$")


def site_live_csp(script_hashes: Sequence[str], *, meta: bool) -> str:
    hashes = "".join(f" '{token}'" for token in sorted(set(script_hashes)) if _HASH_TOKEN.fullmatch(token))
    policy = (
        f"default-src 'none'; script-src 'self'{hashes}; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none'; "
        "worker-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"
    )
    return policy if meta else policy + "; frame-ancestors 'self'"


def delivery_csp(*, meta: bool = False, delivery: str = "web", script_hashes: Sequence[str] = ()) -> str:
    if delivery == SITE_LIVE_DELIVERY:
        return site_live_csp(script_hashes, meta=meta)
    if delivery == "site":
        return SITE_DELIVERY_CSP_META if meta else SITE_DELIVERY_CSP_HEADER
    return DELIVERY_CSP_META if meta else DELIVERY_CSP_HEADER


def manifest_delivery(manifest: object) -> str:
    """Which policy a publish is served under, from its manifest's ``delivery`` field."""
    if isinstance(manifest, dict) and manifest.get("delivery") in ("site", SITE_LIVE_DELIVERY):
        return str(manifest["delivery"])
    return "web"


def live_script_hashes(manifest: object) -> tuple[str, ...]:
    live = manifest.get("live") if isinstance(manifest, dict) else None
    hashes = live.get("script_hashes") if isinstance(live, dict) else None
    return tuple(h for h in (hashes or []) if isinstance(h, str) and _HASH_TOKEN.fullmatch(h))
```

(add `import re` and `from collections.abc import Sequence` if absent.)

- [ ] **Step 4: Run** the new tests and the existing users of `delivery_csp`/`manifest_delivery`:
`pytest-keyless.sh tests/page_origin/test_routes.py`, `pytest-keyless.sh tests/page_origin/test_site_delivery_db.py`. All PASS.

- [ ] **Step 5: Commit**

```bash
git add subsystems/design/clue_design/publishes.py <the test file>
git commit -m "design: the live site policy — own files and one hashed import map, nothing else"
```

---

### Task 6: The live publish package — check, never strip (founder-reviewed wording)

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/site_live.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_sanitize.py` (add `site_html_problems`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_publish.py:143-233` (`live` parameter)
- Test: `subsystems/clue-design/apps/api/tests/test_site_publish_package.py`, `test_site_sanitize.py`

**Interfaces:**
- Consumes: Task 4 (`render_site(live=True)`, `RenderedPage.data`, the dist files), Task 5
  (`SITE_LIVE_DELIVERY`, `site_live_csp`, `PUBLISH_ASSET_MEDIA_TYPES`).
- Produces (`site_live.py`):
  - `LIVE_WORKSPACES_ENV = "LUMEN_SITE_LIVE_WORKSPACES"`; `live_sites_enabled(workspace_id: str) -> bool`
  - `@dataclass(frozen=True) class LiveRuntime: runtime_js: bytes; shims: dict[str, bytes]` (keys = host specifiers)
  - `live_runtime() -> LiveRuntime` (reads `site_kit_dist()/site-runtime.js` and `site-runtime-shims/*`; raises `SiteRenderError(RENDER_FAILED, "...run npm run build -w @clue/site-kit...")` when missing)
  - `import_map_json(urls: Mapping[str, str]) -> str` (sorted keys, compact separators)
  - `script_hash(text: str) -> str` → `"sha256-<base64>"`
  - `live_page_html(html: str, data: Mapping, *, section_urls: Mapping[str, str], import_map: str, runtime_url: str) -> str`
- Produces (`site_sanitize.py`): `site_html_problems(html: str) -> tuple[str, ...]` (what the cleaner would remove; empty = clean).
- Produces (`site_publish.py`): `build_site_publish_package(..., live: bool = False)`; refusal code `site_publish.unsafe_markup`.

- [ ] **Step 1: Write the failing tests**

In `test_site_sanitize.py`:

```python
def test_a_clean_page_has_no_problems_and_a_forbidden_element_is_named() -> None:
    assert site_html_problems('<!doctype html><html><head><title>t</title></head><body><p>hi</p></body></html>') == ()
    problems = site_html_problems('<html><body><iframe src="https://x.example"></iframe><img src="https://t.example/p.gif"></body></html>')
    assert problems == ("stripped <iframe> and its content", "stripped src=https://t.example/p.gif on <img>")
```

In `test_site_publish_package.py` (reuse the file's `blobs` fixture and its site/brand helpers;
mirror `test_a_site_package_is_script_free_with_its_policy_manifest_and_rebased_links`):

```python
def test_a_live_package_ships_its_runtime_shims_and_sections_and_is_served_under_its_own_policy(blobs: DesignBlobStore) -> None:
    package = _build(blobs, live=True)  # the file's existing builder helper, with live passed through
    manifest = package.manifest
    assert manifest["delivery"] == "site_live"
    live = manifest["live"]
    runtime = live_runtime()
    assert live["runtime"] == hashlib.sha256(runtime.runtime_js).hexdigest()
    assert set(package.assets) == {r["digest"] for r in live["assets"]}
    assert all(r["extension"] == "js" and r["media_type"] == "text/javascript; charset=utf-8" for r in live["assets"])
    home = next(page for page in package.pages if page.route == "/")
    import_map = re.search(r'<script type="importmap">(.*?)</script>', home.html).group(1)
    assert live["script_hashes"] == [script_hash(import_map)]
    assert f'<meta http-equiv="Content-Security-Policy" content="{html.escape(site_live_csp(live["script_hashes"], meta=True), quote=True)}">' in home.html
    assert f'<script type="module" src="/p-assets/{live["runtime"]}.js"></script>' in home.html
    data = json.loads(re.search(r'<script type="application/json" id="clue-page-data">(.*?)</script>', home.html).group(1))
    assert data["route"] == "/" and data["basePath"] == "/acme"


def test_review_focus_2_page_data_cannot_end_its_element_early(blobs: DesignBlobStore) -> None:
    page = live_page_html(
        "<!doctype html><html><head></head><body><div id=\"clue-site\"></div></body></html>",
        {"title": "</script><script>alert(1)</script>"},
        section_urls={}, import_map="{}", runtime_url="/p-assets/x.js",
    )
    assert "</script><script>alert(1)" not in page
    assert "\\u003c/script>" in page


def test_review_focus_3_a_live_site_without_agent_sections_still_ships_the_host_shims(blobs: DesignBlobStore) -> None:
    package = _build(blobs, live=True, with_agent_section=False)
    assert len(package.manifest["live"]["assets"]) == 4  # the runtime and three shims


def test_markup_a_published_page_cannot_carry_refuses_the_live_publish(blobs: DesignBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site_publish, "site_html_problems", lambda html: ("stripped <iframe> and its content",))
    with pytest.raises(SitePublishRefused) as refused:
        _build(blobs, live=True)
    assert refused.value.code == "site_publish.unsafe_markup"


def test_a_live_package_is_deterministic(blobs: DesignBlobStore) -> None:
    assert _build(blobs, live=True).package_digest == _build(blobs, live=True).package_digest


def test_without_live_the_package_is_byte_identical(blobs: DesignBlobStore) -> None:
    assert _build(blobs).package_digest == _build(blobs, live=False).package_digest
```

Read the file's existing package-building helper and extend it with `live` and
`with_agent_section` keyword arguments rather than writing a second builder.

- [ ] **Step 2: Run to see them fail** (`ImportError: site_html_problems`, `live` unexpected).

- [ ] **Step 3: `site_html_problems`** (`site_sanitize.py`)

```python
def site_html_problems(html: str) -> tuple[str, ...]:
    """What :func:`sanitize_site_html` would remove from ``html``. A LIVE page is checked, never
    rewritten: React takes the published HTML over in the browser and must find exactly what it drew,
    so a page with anything to remove is refused instead (publishing live sites, phase 1)."""
    return sanitize_site_html(html).removed
```

Update the module docstring's first paragraph: "strip, never refuse" holds for static site pages; a
live page is checked with `site_html_problems` and refused.

- [ ] **Step 4: `site_live.py`**

```python
"""Live Puck sites (publishing live sites, phase 1): which workspaces publish them, and how a live
page is put together around the server's HTML.

A live page is the hardened render's HTML plus, in this order: the site's CSS and our head (as a
static page has), the inline import map (head) that points react, react/jsx-runtime and zod at the
host shims, the page data as inert JSON, and the site runtime as a module script. The runtime and the
shims are site-kit's build output (``dist/site-runtime.js``, ``dist/site-runtime-shims/``); every
file is published by its sha256 under ``/p-assets/``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

from . import web_export
from .site_render import RENDER_FAILED, SiteRenderError, site_kit_dist

LIVE_WORKSPACES_ENV = "LUMEN_SITE_LIVE_WORKSPACES"
SHIM_FILES = {"react": "react.js", "react/jsx-runtime": "react-jsx-runtime.js", "zod": "zod.js"}


def live_sites_enabled(workspace_id: str) -> bool:
    listed = {part.strip() for part in os.environ.get(LIVE_WORKSPACES_ENV, "").split(",") if part.strip()}
    return workspace_id in listed


@dataclass(frozen=True)
class LiveRuntime:
    runtime_js: bytes
    shims: dict[str, bytes]


def live_runtime() -> LiveRuntime:
    dist = site_kit_dist()
    runtime = dist / "site-runtime.js"
    shims = {specifier: dist / "site-runtime-shims" / name for specifier, name in SHIM_FILES.items()}
    missing = [path for path in (runtime, *shims.values()) if not path.is_file()]
    if missing:
        raise SiteRenderError(
            RENDER_FAILED,
            f"the site runtime is not built ({missing[0]} is missing): run `npm run build -w @clue/site-kit` in apps/frontend",
        )
    return LiveRuntime(runtime_js=runtime.read_bytes(), shims={s: p.read_bytes() for s, p in shims.items()})


def import_map_json(urls: Mapping[str, str]) -> str:
    return json.dumps({"imports": dict(sorted(urls.items()))}, separators=(",", ":"), sort_keys=True)


def script_hash(text: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


def _inert_json(value: object) -> str:
    # "<" escaped everywhere, so no string in the data can end or confuse the inert element.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).replace("<", "\\u003c")


def live_page_html(html: str, data: Mapping[str, object], *, section_urls: Mapping[str, str], import_map: str, runtime_url: str) -> str:
    page_data = {**data, "sections": dict(sorted(section_urls.items()))}
    head = f'<script type="importmap">{import_map}</script>\n'
    tail = (
        f'<script type="application/json" id="clue-page-data">{_inert_json(page_data)}</script>'
        f'<script type="module" src="{runtime_url}"></script>'
    )
    return web_export._inject_before_head_close(html, head).replace("</body>", tail + "</body>", 1)
```

(Check that `web_export._inject_before_head_close` exists with that name — it is used by
`site_publish.py`; and that the rendered page has exactly one `</body>`.)

- [ ] **Step 5: Live branch in `build_site_publish_package`** (`site_publish.py`)

Add `live: bool = False`. When `live`:

```python
    render = render_site(site, brand, sections, base_path=site_address.link_path, node_bin=node_bin, live=live)
    # …
    if live:
        runtime = live_runtime()
        files: dict[str, bytes] = {hashlib.sha256(runtime.runtime_js).hexdigest(): runtime.runtime_js}
        shim_urls: dict[str, str] = {}
        for specifier, data in runtime.shims.items():
            digest = hashlib.sha256(data).hexdigest()
            files[digest] = data
            shim_urls[specifier] = f"/p-assets/{digest}.js"
        modules = pinned_modules(site, sections)
        section_urls = {module.name: f"/p-assets/{module.digest}.js" for module in modules}
        for module in modules:
            files[module.digest] = module.module_js.encode("utf-8")
        runtime_digest = hashlib.sha256(runtime.runtime_js).hexdigest()
        import_map = import_map_json(shim_urls)
        hashes = [script_hash(import_map)]
```

In the page loop, for live pages: `whole = site_page_html(page, render.css)`; `problems =
site_html_problems(whole)`; if any, raise
`SitePublishRefused("site_publish.unsafe_markup", _UNSAFE_MARKUP)` where `_UNSAFE_MARKUP` is the
wording below; otherwise `cleaned = live_page_html(whole, page.data, section_urls=..., import_map=...,
runtime_url=f"/p-assets/{runtime_digest}.js")` (no sanitizer call), then our head as today. For
static pages keep `sanitize_site_html(...)` exactly as today.

Manifest when live: `"delivery": SITE_LIVE_DELIVERY`, plus

```python
        "live": {
            "runtime": runtime_digest,
            "script_hashes": hashes,
            "assets": [
                {"digest": d, "extension": "js", "media_type": PUBLISH_ASSET_MEDIA_TYPES["js"]} for d in sorted(files)
            ],
        },
```

`"asset_digests": sorted(files)`; the CSP meta uses `delivery_csp(meta=True, delivery=SITE_LIVE_DELIVERY,
script_hashes=hashes)`; `package_digest` hashes `asset_digests` = `sorted(files)`; the returned
`PublishPackage(assets=files, ...)`. Static path: every line byte-identical.

**Refusal wording — STOP for founder review before committing.** Proposed `_UNSAFE_MARKUP`:
"This page has something a live page can't carry (for example a frame or a script). Ask the agent to
fix the section, then publish again." Write it, run the tests, then hand the wording to the controller,
who asks the founder; commit only the approved text.

- [ ] **Step 6: Run**

Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_publish_package.py`
Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_sanitize.py`
Expected: all PASS, the existing static tests unchanged.

- [ ] **Step 7: Commit** (after the wording is approved)

```bash
git add subsystems/clue-design/apps/api/lumen_api/site_live.py subsystems/clue-design/apps/api/lumen_api/site_sanitize.py \
  subsystems/clue-design/apps/api/lumen_api/site_publish.py subsystems/clue-design/apps/api/tests/test_site_publish_package.py \
  subsystems/clue-design/apps/api/tests/test_site_sanitize.py
git commit -m "design API: a live site package — runtime, shims and sections as publish files, one hashed import map, page data; checked, never stripped"
```

---

### Task 7: The page origin serves live pages under their own policy

**Files:**
- Modify: `platform/page_origin/clue_page_origin/reads.py:20-43,71-120` (`script_hashes` on served types)
- Modify: `platform/page_origin/clue_page_origin/routes.py:44-55` and every `_page_headers(...)` call
- Modify: `tests/page_origin/conftest.py` (`FakePageReads.publish(..., delivery, script_hashes)`)
- Test: `tests/page_origin/test_routes.py`, `tests/page_origin/test_site_delivery_db.py`

Note: group 4.5's fix (K3-6) also edits `reads.py` (`workspace_for_hostname`). Rebase on it; do not
undo it.

**Interfaces:**
- Consumes: Task 5 (`delivery_csp(delivery, script_hashes)`, `live_script_hashes`, `manifest_delivery`).
- Produces: `ServedPublish.script_hashes: tuple[str, ...] = ()`, `ServedPage.script_hashes: tuple[str, ...] = ()`;
  `_page_headers(digest, *, noindex, delivery="web", script_hashes=())`.

- [ ] **Step 1: Write the failing tests**

`tests/page_origin/test_routes.py` (follow the file's client/edge fixtures):

```python
HASH = "sha256-" + "B" * 43 + "="


def test_a_live_site_page_is_served_under_its_own_policy_with_its_import_map_hash(client, reads) -> None:
    reads.publish("acme-site", "<html>live</html>", routes={"/": "<html>live</html>", "/analysis": "<html>a</html>"},
                  delivery="site_live", script_hashes=(HASH,))
    for path in ("/acme-site", "/acme-site/analysis", "/acme-site/manifest.json"):
        response = client.get(path, headers=edge())
        assert response.headers["content-security-policy"] == site_live_csp([HASH], meta=False), path


def test_a_live_sites_javascript_is_served_as_javascript_and_immutable(client, reads) -> None:
    data = b"export default 1;\n"
    digest = hashlib.sha256(data).hexdigest()
    reads.assets[(WS, digest)] = ("text/javascript; charset=utf-8", data)
    response = client.get(f"/p-assets/{digest}.js", headers=edge())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
```

`tests/page_origin/test_site_delivery_db.py` — Review focus 4 (the origin follows the manifest, not the flag):

```python
def test_review_focus_4_a_live_publish_stays_live_whatever_the_flag_says(...) -> None:
    # write a publish whose manifest is {"delivery": "site_live", "live": {"script_hashes": [HASH]}, ...}
    # the way this file's existing site test writes its publish; set LUMEN_SITE_LIVE_WORKSPACES="" with
    # monkeypatch; GET the page; assert the header is site_live_csp([HASH], meta=False).
```

(Write it fully, copying the existing site-delivery test in that file and changing the manifest and
the expected header.)

- [ ] **Step 2: Run to see them fail** — `FakePageReads.publish() got an unexpected keyword argument 'script_hashes'`.

- [ ] **Step 3: Implement**

`reads.py`: add `script_hashes: tuple[str, ...] = ()` to `ServedPublish` and `ServedPage`; in
`active_publish` and `active_page`, `script_hashes=live_script_hashes(manifest)`.

`routes.py`: `_page_headers(digest, *, noindex, delivery="web", script_hashes=())` sets
`"Content-Security-Policy": delivery_csp(delivery=delivery, script_hashes=script_hashes)`; pass
`script_hashes=publish.script_hashes` / `served.script_hashes` at the three call sites.

`conftest.py`: `publish(..., delivery="web", script_hashes=())` writes
`**({"delivery": delivery} if delivery in ("site", "site_live") else {})` and
`**({"live": {"script_hashes": list(script_hashes)}} if script_hashes else {})` into the manifest, and
builds `ServedPublish`/`ServedPage` with `script_hashes=tuple(script_hashes)`.

- [ ] **Step 4: Run** `pytest-keyless.sh tests/page_origin/test_routes.py`, `pytest-keyless.sh tests/page_origin/test_site_delivery_db.py`, `pytest-keyless.sh tests/page_origin/test_main.py`. All PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/page_origin/clue_page_origin/reads.py platform/page_origin/clue_page_origin/routes.py \
  tests/page_origin/conftest.py tests/page_origin/test_routes.py tests/page_origin/test_site_delivery_db.py
git commit -m "page origin: a live site page is served under its own policy, from its manifest"
```

---

### Task 8: Publishing chooses live by the flag, persists the files, and a real browser proves the page comes alive

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/publishes.py:96-106,224-245`
- Modify: `.env.example` (repo root, beside `LUMEN_SITE_RENDER_CHROMIUM_SANDBOX`), `subsystems/clue-design/.env.example` (same place), the lane's `.env` (add the line with the default)
- Create: `subsystems/clue-design/apps/api/tests/test_site_live_browser.py`
- Test: `subsystems/clue-design/apps/api/tests/test_site_publish_package.py` (persist test)

**Interfaces:**
- Consumes: Task 6 (`build_site_publish_package(live=)`, `live_sites_enabled`), Task 5 (`site_live_csp`).
- Produces: `publish_site_document` publishes live exactly when `live_sites_enabled(repository.workspace_id)`;
  `_commit_publish_package` persists `manifest["live"]["assets"]` records with the bytes.

- [ ] **Step 1: Write the failing tests**

Persist test (mirror `test_the_publish_core_persists_a_site_package` in the same file):

```python
def test_the_publish_core_persists_a_live_sites_javascript_by_digest(blobs: DesignBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMEN_SITE_LIVE_WORKSPACES", blobs.workspace_id)
    ref = _publish_through_the_core(blobs)  # the existing test's helper / steps
    manifest = _stored_manifest(blobs, ref)  # read back the way the existing test does
    assert manifest["delivery"] == "site_live"
    for record in manifest["live"]["assets"]:
        media_type, data = blobs.read_blob(record["digest"])
        assert media_type == "text/javascript; charset=utf-8"
        assert hashlib.sha256(data).hexdigest() == record["digest"]


def test_a_workspace_off_the_list_publishes_the_static_page_exactly_as_before(blobs: DesignBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMEN_SITE_LIVE_WORKSPACES", "")
    ref = _publish_through_the_core(blobs)
    assert _stored_manifest(blobs, ref)["delivery"] == "site"
```

`test_site_live_browser.py` — the phase's acceptance test, in a real (non-hardened) Chromium:

```python
"""A live site package, served the way the page origin serves it, comes alive in a real browser:
no console error, no policy violation, and an agent section with state responds to a click
(publishing live sites, phase 1, Task 8)."""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from clue_design.publishes import delivery_csp

# reuse test_site_publish_package's package builder and its `blobs` fixture via site_kit_support

COUNTER_JS = (
    'import { jsx, jsxs } from "react/jsx-runtime";\n'
    'import { useState } from "react";\n'
    'import { z } from "zod";\n'
    'export const schema = z.object({ id: z.string(), surface: z.string() }).strict();\n'
    "function Counter() { const [n, setN] = useState(0);\n"
    '  return jsxs("button", { id: "counter", onClick: () => setN(n + 1), children: ["clicked ", n] }); }\n'
    'export function render() { return jsx(Counter, {}); }\n'
)


def _serve(package) -> tuple[str, ThreadingHTTPServer]:
    pages = {f"/acme{'' if p.route == '/' else p.route}": p.html.encode() for p in package.pages}
    files = {f"/p-assets/{d}.js": data for d, data in package.assets.items()}
    hashes = package.manifest["live"]["script_hashes"]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in pages:
                body, kind = pages[self.path], "text/html; charset=utf-8"
                extra = {"Content-Security-Policy": delivery_csp(delivery="site_live", script_hashes=hashes)}
            elif self.path in files:
                body, kind, extra = files[self.path], "text/javascript; charset=utf-8", {}
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            for key, value in extra.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server


def test_a_live_site_comes_alive_and_an_agent_section_with_state_answers_a_click(blobs) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    package = build_live_package_with_section(blobs, "Counter", COUNTER_JS)  # helper: Task 6's builder + site_with_agent_section
    origin, server = _serve(package)
    try:
        with playwright.sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            errors: list[str] = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(origin + "/acme", wait_until="load")
            page.wait_for_function("window.__clueHydrated === true", timeout=10_000)
            assert page.locator("#counter").inner_text() == "clicked 0"
            page.locator("#counter").click()
            assert page.locator("#counter").inner_text() == "clicked 1"
            assert errors == [], errors
            browser.close()
    finally:
        server.shutdown()
```

Write `build_live_package_with_section` in `site_kit_support.py` next to `site_with_agent_section`
(it calls `build_site_publish_package(..., live=True)` with the module, `base_path`/`site_address`
giving `link_path="/acme"` the way the existing package tests construct a `PublicSiteAddress`).
Note the page data's brand still names `/asset-store/<sha>` images; this server does not serve them,
so broken images are expected and are not console *errors* (`img` 404s are network errors, logged
as "Failed to load resource" with type `error` in Chromium). If they appear in `errors`, filter
messages starting with `Failed to load resource` that mention `/asset-store/` and say so in a
comment.

- [ ] **Step 2: Run to see them fail** (the core still publishes static; the browser test fails at
`__clueHydrated` or at the click).

- [ ] **Step 3: Implement**

`toolbelt/publishes.py::_commit_publish_package` — persist both record lists:

```python
    live = package.manifest.get("live") or {}
    web_export.persist_publish_assets(
        blobs,
        package.assets,
        [*(package.manifest["custom_components"].get("assets") or []), *(live.get("assets") or [])],
    )
```

`publish_site_document`: `live=live_sites_enabled(repository.workspace_id)` passed to
`build_site_publish_package` (import from `..site_live`). Check `repository.workspace_id` exists on
the repository object (it is used as `repository.workspace_id` in `publish_web_document`'s call above).

`.env.example` (root, after `LUMEN_SITE_RENDER_CHROMIUM_SANDBOX=1`) and `subsystems/clue-design/.env.example`:

```
# Live Puck sites (publishing live sites, phase 1): the workspaces whose published sites run their
# JavaScript in the visitor's browser (comma-separated workspace ids). Empty = every site publishes
# static, exactly as before. docs/superpowers/specs/2026-10-15-publishing-live-sites-design.md
LUMEN_SITE_LIVE_WORKSPACES=
```

Add `LUMEN_SITE_LIVE_WORKSPACES=` to the lane `.env` at the same place (parity; value stays empty
until the founder lists workspaces).

- [ ] **Step 4: Run**

Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_publish_package.py`
Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_live_browser.py`
Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_publish_routes.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_api/toolbelt/publishes.py .env.example subsystems/clue-design/.env.example \
  subsystems/clue-design/apps/api/tests/test_site_live_browser.py subsystems/clue-design/apps/api/tests/test_site_publish_package.py \
  subsystems/clue-design/apps/api/tests/site_kit_support.py
git commit -m "design API: workspaces on LUMEN_SITE_LIVE_WORKSPACES publish live sites; a real browser proves the page comes alive and answers a click"
```

(`.env` is not tracked; do not add it.)

---

### Task 9: The section rules for live workspaces (`interactive` mode)

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/check-section.ts:51-58,157-191`
- Modify: `apps/frontend/packages/site-kit/bin/compile-section.ts` (input `interactive`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_kit_cli.py:192-197`
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py:202-214` (`DurableSiteSectionPort(interactive=)`)
- Test: `apps/frontend/packages/site-kit/test/check-section.test.ts`, `test/compile-section.test.ts`, `subsystems/clue-design/apps/api/tests/test_site_kit_cli.py`

**Interfaces:**
- Produces: `LintOptions.interactive?: boolean`; compile input `{name, source, brand, interactive?: boolean}`;
  `compile_section_source(*, name, source, brand, interactive: bool = False)`;
  `DurableSiteSectionPort(..., interactive: bool = False)`.

- [ ] **Step 1: Write the failing tests** (`check-section.test.ts`; read its helpers first — it lints
inline source strings with `lint(source, options)`)

```ts
const interactive = { interactive: true } as const;
const section = (body: string, imports = "") => `import { z } from "zod";\n${imports}import type { Kit } from "@/puck/agent-kit";\nexport const schema = z.object({ id: z.string(), surface: z.string() }).strict();\n${body}\nexport function render(props: z.infer<typeof schema>, kit: Kit) { return <kit.Shell surface={props.surface}><Inner /></kit.Shell>; }\n`;

test("interactive: state, effects, handlers, timers and page reads are allowed", () => {
  const source = section(
    `function Inner() {
  const [open, setOpen] = useState(false);
  useEffect(() => { const t = setTimeout(() => setOpen(true), 10); const w = window.innerWidth; void w; return () => clearTimeout(t); }, []);
  return <button className="font-body text-body" onClick={() => setOpen(!open)} aria-expanded={open}>Toggle</button>;
}`,
    'import { useEffect, useState } from "react";\n',
  );
  assert.deepEqual(lint(source, interactive), []);
  assert.ok(lint(source).some((e) => e.includes('"onClick" is an event handler')), "static mode is unchanged");
});

test("interactive: eval, Function, raw HTML, cookies, dynamic import and foreign elements are still refused", () => {
  for (const [code, expected] of [
    ["eval('1')", '"eval"'],
    ["new Function('return 1')", '"Function"'],
    ["document.cookie", '"cookie"'],
    ["import('x')", '"import("'],
  ] as const) {
    const errors = lint(section(`function Inner() { ${code}; return null; }`), interactive);
    assert.ok(errors.some((e) => e.includes(expected)), `${code}: ${JSON.stringify(errors)}`);
  }
  for (const tag of ["script", "iframe", "form", "object", "embed"]) {
    const errors = lint(section(`function Inner() { return <${tag} />; }`), interactive);
    assert.ok(errors.some((e) => e.includes(`<${tag}>`)), tag);
  }
  const raw = lint(section(`function Inner() { return <div dangerouslySetInnerHTML={{ __html: "x" }} />; }`), interactive);
  assert.ok(raw.some((e) => e.includes("dangerouslySetInnerHTML")));
});
```

`compile-section.test.ts`: the interactive input compiles the accordion-like section `ok`, and the
same source without `interactive` is refused. `test_site_kit_cli.py`: `compile_section_source(...,
interactive=True)` sends `"interactive": true` in the CLI payload (follow the file's existing way of
asserting the payload, or run the real CLI on a small interactive source if the file does that).

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement** (`check-section.ts`)

```ts
export type LintOptions = { extraSurfaces?: string[]; buttonLooks?: string[]; cardLooks?: string[]; motions?: string[]; interactive?: boolean };

/** In a live workspace a section runs in the visitor's browser (publishing live sites, founder
 * 2026-10-15): it may keep state, handle events, run effects and timers and read the page. Where it
 * can send data is the published page's policy's job, not this check's. What stays refused has its
 * own reason, below. */
const INTERACTIVE_BANNED: Record<string, string> = {
  eval: "runs code the check never saw",
  Function: "runs code the check never saw",
  dangerouslySetInnerHTML: "writes raw HTML",
  cookie: "reads or sets cookies; a section keeps its state in React or in localStorage",
};
const FOREIGN_ELEMENTS: Record<string, string> = {
  script: "<script> is not allowed in a section; its code is the section itself",
  iframe: "<iframe> is not allowed in a section",
  form: "<form> is not allowed in a section",
  object: "<object> is not allowed in a section",
  embed: "<embed> is not allowed in a section",
};
```

`bannedNames(source, interactive = false)`: use `interactive ? INTERACTIVE_BANNED : BANNED`; skip the
`on[A-Z]` rule when interactive; keep the `import(` and raw `<a>` rules in both; add, in both modes,
`if (FOREIGN_ELEMENTS[tag]) add(FOREIGN_ELEMENTS[tag])` for JSX elements (static mode gains the
foreign-element refusals too: they were silently stripped at publish before, so refusing them earlier
changes no published page). The "a section is static" message in static mode stays verbatim.
`lint` passes `options.interactive === true` to `bannedNames`. Update the file's header comment.

`bin/compile-section.ts`: input type gains `interactive?: boolean`; `lint(source, { ...lintOptionsFor(brand), interactive: input.interactive === true })`.

`site_kit_cli.compile_section_source(*, name, source, brand, interactive: bool = False)` sends
`"interactive": interactive`. `DurableSiteSectionPort.__init__(..., interactive: bool = False)` stores it
and passes it in `compile`.

- [ ] **Step 4: Run** site-kit `check-section.test.ts`, `compile-section.test.ts`; `pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_kit_cli.py`; `pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_turn_ports.py`. All PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/packages/site-kit/src/check-section.ts apps/frontend/packages/site-kit/bin/compile-section.ts \
  apps/frontend/packages/site-kit/test/check-section.test.ts apps/frontend/packages/site-kit/test/compile-section.test.ts \
  subsystems/clue-design/apps/api/lumen_api/site_kit_cli.py subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py \
  subsystems/clue-design/apps/api/tests/test_site_kit_cli.py
git commit -m "site-kit: interactive sections for live workspaces — state, effects, handlers and timers allowed; eval, raw HTML, cookies and foreign elements still refused"
```

---

### Task 10: `kit.editing` — sections stay still in Edit mode

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/agent-kit.tsx:12-55`
- Modify: `apps/frontend/packages/site-kit/src/config.tsx` (agent section render)
- Test: `apps/frontend/packages/site-kit/test/agent-kit.test.tsx`

**Interfaces:**
- Produces: `Kit.editing: boolean`; `makeKit(href, brand)` returns `editing: false`; the agent section
  wrapper passes `{ ...kit, editing: Boolean(props.puck?.isEditing) }`.

- [ ] **Step 1: Write the failing test**

```tsx
test("a section learns from kit.editing whether the marketer is editing it", () => {
  const seen: boolean[] = [];
  const Probe = { schema: z.object({ id: z.string(), surface: z.string() }), render: ((_p: unknown, kit: Kit) => (seen.push(kit.editing), null)) as never };
  const config = makeConfig(garner(), { agentSections: { Probe } }) as Config;
  const render = (config.components.Probe as { render: (p: unknown) => ReactElement }).render;
  renderToStaticMarkup(render({ id: "p", surface: "page", puck: { isEditing: true } }));
  renderToStaticMarkup(render({ id: "p", surface: "page", puck: { isEditing: false } }));
  renderToStaticMarkup(render({ id: "p", surface: "page" }));
  assert.deepEqual(seen, [true, false, false]);
});
```

- [ ] **Step 2: Run to see it fail** (`kit.editing` is `undefined`).

- [ ] **Step 3: Implement**

`agent-kit.tsx`: add to `Kit`:
```ts
  /** True while the marketer edits this page in the editor's Edit mode: show the section's first
   * state and start nothing (no timers, no autoplay), so a click selects it instead of driving it. */
  editing: boolean;
```
and `editing: false` in `makeKit`'s object.

`config.tsx` agent section (inside the per-section `Drawn` component from Task 3):
`module.render(props, { ...kit, editing: Boolean((props as { puck?: { isEditing?: boolean } }).puck?.isEditing) })`.

- [ ] **Step 4: Run** `npx tsx --test test/agent-kit.test.tsx test/live-page.test.tsx test/render-core.test.tsx` and the editor harness (`CLUE_SITE_EDITOR_BROWSER=1 … tests/site_editor`). All PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/packages/site-kit/src/agent-kit.tsx apps/frontend/packages/site-kit/src/config.tsx apps/frontend/packages/site-kit/test/agent-kit.test.tsx
git commit -m "site-kit: kit.editing tells a section the marketer is editing it, so interactive pieces stay still"
```

---

### Task 11: The agent sees the page alive, and is taught interactivity (founder-reviewed skill)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_live.py` (`live_preview_document`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_render.py:464-503` (`capture_site_screenshot(live_document=)`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py:43-82` (`PlatformSiteRenderer(live=)`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:12006-12026` (flag wiring)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/inputs.py:96` (`live_sites: bool = False`)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/harness.py:39,342-353,403,468` (mount `skills-live`)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py:35,631` (copy `skills-live`)
- Create: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/skills-live/making-a-section-interactive/SKILL.md`
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/SKILLS-CHANGELOG.md`
- Test: `subsystems/clue-design/apps/api/tests/test_site_turn_ports.py`, the harness's tests (`grep -rln "system_prompt_with_skills" subsystems/clue-design/apps/agent_runtime/tests`), `test_site_turn_executor.py`

**Interfaces:**
- Consumes: Task 4 (`render_site(live=)`), Task 6 (`live_runtime`, `SHIM_FILES`), Task 9 (`interactive`).
- Produces:
  - `live_preview_document(page: RenderedPage, css: str, modules: Sequence[SectionModule], runtime: LiveRuntime) -> str` — self-contained: CSS inline, import map of `data:` shim URLs, sections as `data:` module URLs, the runtime inline as `<script type="module">`, its own CSP meta `default-src 'none'; script-src 'unsafe-inline' data:; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'`.
  - `capture_site_screenshot(page, css, *, …, live_document: str | None = None)` — when given, loads it with JavaScript ON, waits for `window.__clueHydrated === true` (up to the remaining timeout; on timeout it shoots anyway), then the font settle; keeps `reduced_motion="reduce"`.
  - `PlatformSiteRenderer(read_blob=None, *, live: bool = False)`; `render()` renders live when `live`, and remembers `(page, modules)` by `sha256(html)`; `screenshot()` builds the live document (asset refs inlined in the HTML, the CSS **and** the page data JSON) when it has one for that html.
  - `SiteTurnInputs.live_sites: bool = False`; `system_prompt_with_skills(workspace, *, allow_new_sections=True, live=False)`.

- [ ] **Step 1: Write the failing tests**

`test_site_turn_ports.py`:

```python
def test_a_live_renderer_shows_the_page_after_its_effects_ran(monkeypatch) -> None:
    module_js = (
        'import { jsx } from "react/jsx-runtime";\nimport { useEffect, useState } from "react";\nimport { z } from "zod";\n'
        'export const schema = z.object({ id: z.string(), surface: z.string() }).strict();\n'
        'function Late() { const [on, setOn] = useState(false); useEffect(() => setOn(true), []);\n'
        '  return jsx("div", { style: { height: 600, background: on ? "#000" : "#fff" } }); }\n'
        'export function render() { return jsx(Late, {}); }\n'
    )
    site, sections = site_with_agent_section("Late", module_js)
    live = PlatformSiteRenderer(live=True)
    html, css, warnings = live.render(site, garner_brand(), sections, route="/")
    dark_live = _dark_share(live.screenshot(html, css, width=1440))
    still = PlatformSiteRenderer(live=False)
    html_s, css_s, _ = still.render(site, garner_brand(), sections, route="/")
    dark_static = _dark_share(still.screenshot(html_s, css_s, width=1440))
    assert dark_live > dark_static + 0.02, (dark_live, dark_static)


def _dark_share(png: bytes) -> float:
    from PIL import Image
    image = Image.open(io.BytesIO(png)).convert("L")
    pixels = list(image.getdata())
    return sum(1 for p in pixels if p < 20) / len(pixels)
```

(The fixture section uses an inline style only because it is a hand-written test module that never
passes the checker; say so in a comment.)

Harness test (in the agent runtime's site tests):

```python
def test_live_workspaces_get_the_interactive_skill_and_others_do_not(tmp_path) -> None:
    on = system_prompt_with_skills(tmp_path, live=True)
    off = system_prompt_with_skills(tmp_path, live=False)
    assert "### Skill: making-a-section-interactive" in on
    assert "making-a-section-interactive" not in off
    assert off == system_prompt_with_skills(tmp_path)  # flag off: byte-identical
```

`test_site_turn_executor.py`: with `LUMEN_SITE_LIVE_WORKSPACES` set to the test workspace, the
executor's inputs carry `live_sites=True`, the renderer `live=True` and the section port
`interactive=True`; unset → all False (follow how the file already inspects the built inputs, e.g. a
`site_turn_runner` stub that records `inputs`).

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement the preview**

`site_live.py`:

```python
_PREVIEW_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' data:; style-src 'unsafe-inline'; img-src data:; "
    "font-src data:; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"
)


def _data_module(source: str | bytes) -> str:
    text = source.decode("utf-8") if isinstance(source, bytes) else source
    return "data:text/javascript;charset=utf-8," + urllib.parse.quote(text)


def live_preview_document(page: RenderedPage, css: str, modules: Sequence[SectionModule], runtime: LiveRuntime) -> str:
    """The live page as one self-contained document for the agent's screenshot inside the hardened
    page (no network): CSS inline, shims and sections as data: modules, the runtime inline."""
    import_map = import_map_json({specifier: _data_module(data) for specifier, data in runtime.shims.items()})
    html = live_page_html(
        site_page_html(page, css),
        page.data or {},
        section_urls={module.name: _data_module(module.module_js) for module in modules},
        import_map=import_map,
        runtime_url="",
    )
    html = html.replace('<script type="module" src=""></script>', f"<script type=\"module\">{runtime.runtime_js.decode('utf-8')}</script>")
    meta = f'<meta http-equiv="Content-Security-Policy" content="{_PREVIEW_CSP}">'
    return web_export._inject_before_head_close(html, meta)
```

(imports: `urllib.parse`, `Sequence`, `RenderedPage`, `SectionModule`, `site_page_html` from
`.site_render`.) If the runtime text contains `</script>`, replace it with `<\/script>` before
inlining — add that line and a unit assertion.

`site_render.capture_site_screenshot`: new keyword `live_document: str | None = None`. When given,
skip the sanitizer and `site_page_html`, open `hardened_page(javascript=True, …same viewport/scale/
reduced_motion…)`, `set_content(live_document, wait_until="load")`, then
`shot.wait_for_function("window.__clueHydrated === true", timeout=timeout_ms)` inside a
`try/except PlaywrightTimeout: pass` (shoot anyway), then the font settle and the same
screenshot/clip logic. Static path byte-identical.

`site_turn_ports.PlatformSiteRenderer`:

```python
    def __init__(self, read_blob: Any = None, *, live: bool = False) -> None:
        self.read_blob = read_blob
        self.live = live
        self._inlined: dict = {}
        self._live_pages: dict[str, tuple[Any, list[Any]]] = {}

    def render(self, site, brand, sections, *, route):
        # … as today, plus live=self.live; when live, remember the page and its modules:
        if self.live:
            self._live_pages[hashlib.sha256(page.html.encode("utf-8")).hexdigest()] = (page, modules)
        return page.html, result.css, list(result.warnings)

    def screenshot(self, html, css, *, width, section_only=False):
        remembered = self._live_pages.get(hashlib.sha256(html.encode("utf-8")).hexdigest()) if self.live else None
        # inline asset refs in html and css as today; when remembered, also in the page data:
        live_document = None
        if remembered is not None:
            page, modules = remembered
            data = page.data
            if self.read_blob is not None and data is not None:
                text, _missing = inline_asset_store_refs(json.dumps(data), self.read_blob, cache=self._inlined)
                data = json.loads(text)
            live_document = live_preview_document(
                site_render.RenderedPage(route=page.route, html=html_inlined, data=data), css_inlined, modules, live_runtime()
            )
        return site_render.capture_site_screenshot(..., live_document=live_document)
```

(Keep the existing names for the inlined html/css variables; write the whole method out.)

`main.py` (site turn executor, around line 12006):

```python
            live = live_sites_enabled(workspace_id)
            # … renderer=PlatformSiteRenderer(read_blob=blobs.read_blob, live=live),
            inputs = replace(
                inputs,
                live_sites=live,
                sections=DurableSiteSectionPort(store=store, invocations=invocations, run_id=envelope.run_id,
                                                brand=inputs.brand, interactive=live),
            )
```

`inputs.py`: `live_sites: bool = False` with a docstring line. `harness.py`: `"/skills-live/**"` in
the read-only list (line 39); `system_prompt_with_skills(workspace, *, allow_new_sections=True,
live=False)` uses `folders = ["skills", *(["skills-e5"] if allow_new_sections else []), *(["skills-live"]
if live and allow_new_sections else [])]`; `build_site_agent(..., live: bool = False)` passes it;
`run_site_agent_turn` passes `live=inputs.live_sites` (line ~468). `workspace.py`: add
`"skills-live"` to the materialized names (line 35) and copy it next to `skills-e5` only when
`inputs.live_sites` (line 631).

- [ ] **Step 4: The skill — STOP for founder review before committing**

Write this draft to `skills-live/making-a-section-interactive/SKILL.md`, run the tests, then hand the
text to the controller, who shows it to the founder. Commit only the approved text, and add the
approved version to `SKILLS-CHANGELOG.md`.

````markdown
---
name: making-a-section-interactive
description: Use when a section needs to respond to the visitor — tabs, an accordion, a carousel, a calculator, something that appears as the visitor scrolls.
---

# Making a section interactive

This site's published pages run your section's React code in the visitor's browser. A section can
keep state, respond to clicks and run effects.

## What you can use

- React's hooks, imported from "react": useState, useEffect, useRef, useMemo and the rest.
- Event handlers on any element: onClick, onChange, onKeyDown and the rest.
- Timers: setTimeout, setInterval, requestAnimationFrame. Clear them when the effect ends.
- The page itself, inside an effect: window and document, to read the scroll position, the window's
  size or a media query, or to watch an element with IntersectionObserver.

## Three rules

1. **Draw the same thing on the server and in the browser.** The page is drawn first on the server,
   then the browser takes it over. If the two drawings differ, the browser redraws and the visitor
   sees the page jump. So never read window, document, the time, random numbers or storage while
   drawing: read them in an effect. The first drawing is the section's first state (the first tab
   open, the first slide shown).
2. **Stay still while the marketer edits.** `kit.editing` is true in the editor's Edit mode. Then
   show the first state and start no timers, so a click selects the section instead of driving it.
3. **Stay on the brand.** Colours, type, corners, surfaces and motion come from the brand, as in
   writing-a-section. No eval or new Function, no dangerouslySetInnerHTML, no <script>, <iframe> or
   <form>, and no cookies.

## Example: an accordion

```tsx
import { useState } from "react";
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.string(),
  heading: z.string().min(1),
  items: z.array(z.object({ question: z.string().min(1), answer: z.string() })),
}).strict();

function Items({ items, editing }: { items: z.infer<typeof schema>["items"]; editing: boolean }) {
  const [open, setOpen] = useState(0);
  return (
    <div className="mt-stack-default divide-y divide-line-subtle border-y border-line-subtle">
      {items.map((item, index) => (
        <div key={index} className="py-4">
          <button
            className="w-full text-left font-title text-title"
            aria-expanded={open === index}
            onClick={() => (editing ? undefined : setOpen(open === index ? -1 : index))}
          >
            {item.question}
          </button>
          {open === index ? <p className="mt-2 font-body text-body text-ink-secondary">{item.answer}</p> : null}
        </div>
      ))}
    </div>
  );
}

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <h2 className="brand-heading font-headline text-headline">{props.heading}</h2>
      <Items items={props.items} editing={kit.editing} />
    </kit.Shell>
  );
}
```

render_page shows the page after it has come alive, and its notes name any place where the server
and the browser drew different things ("hydration"). Fix those before you finish.
````

Check the example passes `lint(..., { interactive: true })` with Garner's options (add it as a case
in `check-section.test.ts`: the skill's example must lint clean, so the skill never teaches something
the check refuses).

- [ ] **Step 5: Run**

Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_turn_ports.py`
Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_turn_executor.py`
Run the agent runtime's site harness tests (`pytest-keyless.sh subsystems/clue-design/apps/agent_runtime/tests/<the site harness test file>`).
Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/check-section.test.ts`
Expected: all PASS.

- [ ] **Step 6: Commit** (after the skill text is approved)

```bash
git add subsystems/clue-design/apps/api/lumen_api/site_live.py subsystems/clue-design/apps/api/lumen_api/site_render.py \
  subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py subsystems/clue-design/apps/api/lumen_api/main.py \
  subsystems/clue-design/apps/agent_runtime/lumen_agent/site/inputs.py subsystems/clue-design/apps/agent_runtime/lumen_agent/site/harness.py \
  subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py \
  subsystems/clue-design/apps/agent_runtime/lumen_agent/site/skills-live/making-a-section-interactive/SKILL.md \
  subsystems/clue-design/apps/agent_runtime/lumen_agent/site/SKILLS-CHANGELOG.md \
  subsystems/clue-design/apps/api/tests/test_site_turn_ports.py subsystems/clue-design/apps/api/tests/test_site_turn_executor.py \
  apps/frontend/packages/site-kit/test/check-section.test.ts <the harness test file>
git commit -m "site agent: in live workspaces the agent's previews show the page alive, its sections may be interactive, and it is taught how"
```

---

### Task 12: The image ships the runtime; gates; records

**Files:**
- Modify: `docker/backend/smoke.sh:28` (add the runtime to the bundle check)
- Modify: `tests/deploy/test_backend_image.py:144-152`
- Modify: `docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md` (Contract 3: one line pointing to the live spec for live workspaces)
- Modify: `docs/superpowers/specs/2026-10-15-publishing-live-sites-design.md` (status: phase 1 built)
- Modify: `_memory/2026-10-15-publishing-live-sites.md` (closing entry)

- [ ] **Step 1: Failing test** — in `test_backend_image.py`, assert the smoke check names
`/app/apps/frontend/packages/site-kit/dist/site-runtime.js`. Run: `pytest-keyless.sh tests/deploy/test_backend_image.py` → FAIL.

- [ ] **Step 2: Implement** — extend the `check "site-kit bundles"` line in `smoke.sh` with
`-a -f /app/apps/frontend/packages/site-kit/dist/site-runtime.js -a -f /app/apps/frontend/packages/site-kit/dist/site-runtime-shims/react.js`.
Run the test → PASS.

- [ ] **Step 3: The whole gate** (every line must pass; record each result in the ledger)

```bash
cd apps/frontend && npm run design-system:build && npm run lint && npm run build
cd apps/frontend && npm test
cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts test/*.test.tsx && npx tsc --noEmit
cd apps/frontend/packages/site-editor && npx tsx --test test/*.test.ts && npx tsc --noEmit
CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh tests/site_editor
.superpowers/review/2026-10-13-wave2/pytest-keyless.sh tests/page_origin
.superpowers/review/2026-10-13-wave2/pytest-keyless.sh tests/deploy
```

and, one design file at a time (never the whole design suite):
`test_site_render.py`, `test_site_publish_package.py`, `test_site_sanitize.py`, `test_site_live_browser.py`,
`test_site_publish_routes.py`, `test_site_kit_cli.py`, `test_site_turn_ports.py`, `test_site_turn_executor.py`,
`test_site_thumbnails.py`, `test_site_lane_a_scenarios.py`, `test_site_lane_b_scenarios.py`, and the
agent runtime's site harness tests. `ruff check` and `ruff format --check` on every Python file changed.

- [ ] **Step 4: Records** — the integration plan's Contract 3 gets: "Live workspaces
(`LUMEN_SITE_LIVE_WORKSPACES`) publish under `docs/superpowers/specs/2026-10-15-publishing-live-sites-design.md`
instead: checked, not stripped; `delivery: site_live`." The spec's status line: "Phase 1 built
(<date>, commits …)". The memory file: what landed, the gate results, and the owed live check
(below).

- [ ] **Step 5: Commit**

```bash
git add docker/backend/smoke.sh tests/deploy/test_backend_image.py docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md \
  docs/superpowers/specs/2026-10-15-publishing-live-sites-design.md _memory/2026-10-15-publishing-live-sites.md
git commit -m "publishing live sites phase 1: the image ships the site runtime; records"
```

**Owed after the plan (founder-triggered, not part of any task):** a live walk on the trenton stack —
put one workspace on `LUMEN_SITE_LIVE_WORKSPACES`, restart the design API and workers, ask the agent
for an interactive section, publish, open the published page in the in-app browser and click it.
Live agent runs spend money: only with the founder's go.
