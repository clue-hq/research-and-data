# D2 spike: loading agent-written sections at runtime (option A, no iframes)

A throwaway experiment in this spike app (Task 4 of the Puck integration). The question behind it:
in production, the website agent writes a section as a React/TSX file; can the platform load that
section's **compiled** code into Puck at runtime — per workspace, in the editor and in the server
render — instead of importing it statically through `puck/agent-sections/index.ts` as the spike does
today. Option A means loading the module directly (`await import(url)`), not isolating it in an
iframe. The deliverable is this note; it informs Lane B task B6 (store compiled modules per
workspace) and Lane C task C9 (load them in the editor).

What the experiment built, all under `trials/puck-spike/`:

- `scripts/compile-section.ts` — runs the section check (lint + type-check), bundles the file with
  esbuild (ESM, automatic JSX, `react`/`react/jsx-runtime`/`zod` kept external), writes
  `data/compiled/<workspace>/<sha256>.mjs`, prints `{name, digest, propsSchema, ms}`.
- `app/compiled/[workspace]/[digest]/route.ts` — serves a module only when that digest exists under
  that workspace, 404 otherwise; `Content-Type: text/javascript`.
- `app/edit-runtime/[site]/{page.tsx,client.tsx}` — the editor with this site's agent sections
  imported at runtime from `/compiled/...`, fields derived from each section's own zod schema.
- `scripts/render-site.ts` — renders a page to static HTML with `<Render>` from
  `@puckeditor/core/rsc`, loading the modules from disk; built once with esbuild, run in a
  `node:24-alpine` container with `--network none`.
- `scripts/hostile/*.tsx` — six hostile fixtures, plus four `scripts/hostile/evasion/*.tsx` probes
  that pass the stricter check.

Two experiment-only sites (not committed, data-only): `rt-cl3` (the five cl3 components over two
pages) and `rt-e5` (E5's `AnalysisSteps`). Modules compiled into workspaces `ws-a` and `ws-b`.
Timings are from this machine (Apple silicon, Docker 29.8.1, dev server on :3047).

## The six questions

| # | Question | Answer | Numbers / evidence |
|---|---|---|---|
| 1 | Can a compiled module be loaded at runtime into Puck's config, in the editor and the server render? | **Yes, both.** Editor: `await import("/compiled/<ws>/<digest>.mjs")` then added to the config `makeConfig` builds; `<Puck>` renders it. Server: imported from disk, added to the config, `renderToString(<Render>)`. | 6/6 fixtures loaded in the editor; all drew in the canvas. Server render of 3 pages succeeded. Editor import of 5 modules: **~140 ms** total (perModule 8–28 ms). Server `renderToString`: **5–15 ms**. |
| 2 | Do in-place editing and fields work on it? | **Yes.** Fields are derived from each section's zod JSON-Schema: string→text/textarea (`contentEditable` for prose), enum→select, array/object→nested fields, image key→the brand asset picker. Inline text edits in the canvas, panel edits (select, text, asset) all flow to the stored props. | Inline edits verified on PhotoHero.headline, nested AnalyticsFeatures.items[].headline, ProviderInsights/AudienceBand/SplitCta, and AnalysisSteps.heading. Panel: headingRole select changed the `<h1>` class; ctaLabel text and the asset picker both updated the canvas. 1 non-blocking React warning (see below). |
| 3 | How long from write to visible? | **~1.5 s of real work; ~12 s wall including a cold editor page compile.** Writing the file is instant; compile (lint + type-check + bundle + load) ~0.9–1.5 s; the editor then imports the module in 8–28 ms and draws it in <1 s. The dev-server's first compile of the `/edit-runtime` route dominates the 12 s. | 3 runs of a brand-new section: compile_wall 1.33–1.55 s; editor open→drawn 0.81–0.91 s; **total write→drawn 11.9–12.2 s**. Novel Tailwind classes (`columns-2`, `indent-8`, `decoration-dotted`) got CSS and applied (columnCount=2), because `@source "../puck/agent-sections"` is not where compiled modules live — see the CSS finding. |
| 4 | Does the strict check refuse six hostile sections? | **Refuses 4 of the 6 by name; the other 2 (infinite loop, huge output) have no banned identifier and pass — correctly flagged as a finding.** The lint gained an AST-based banned-identifier pass (`window/document/globalThis`, `fetch/XMLHttpRequest/WebSocket/eval/Function/import(`, `dangerouslySetInnerHTML`, `localStorage/cookie/setTimeout/setInterval`, any `on[A-Z]` handler). | NetworkCall, CookieRead, ParentFrame, InjectedScript → **refused** with a reason. InfiniteLoop, HugeOutput → **pass** (resource abuse names nothing banned). All 5 cl3 + both AnalysisSteps still pass (no false positive). **4 evasion probes that pass the check and still act** (see findings). |
| 5 | Does a page with agent sections render to static HTML in a no-network process? | **Yes.** `node:24-alpine` with `--network none` (confirmed offline). HTML is byte-identical to the live `/s/<site>` page. | 3 pages rendered offline, exit 0: rt-cl3 `/` 62 KB, `/more` 60 KB, rt-e5 `/` 265 KB. Container wall ~0.35 s (first ~1.6 s). `.brand-root` DOM **identical** to `/s/` on all 3; screenshot diff 0.0% (rt-cl3) / 0.12–0.14% (rt-e5, the only motion is its autoplaying hero video frame). |
| 6 | Can workspace A ever load workspace B's module? | **Not by naming it** — the per-workspace route and the renderer both refuse a digest outside the workspace, and path traversal. **But a loaded module runs with the host's privileges**, and a check-passing module read another workspace's files off disk in the server render. Digest-routing isolates *which module you can name*, not *what a module can do*. | Route: cross-workspace digest, path traversal, uppercase, short digest, unknown workspace → all **404**; own digest → 200. Renderer: ws-a site naming ws-b's digest (and `../ws-b/...`) → **`section_module_missing`, exit 1**. Counter: a `process.getBuiltinModule("node:fs")` section (passes the check) **read and leaked `data/compiled/ws-b/` contents** into ws-a's HTML. |

## Findings (the honest failures)

1. **The check is a denylist, not a sandbox (questions 4 & 6).** Four probes pass the stricter lint
   and still act at runtime, because they never spell a banned name:
   - a network beacon via a plain `<img src="https://…">` — **the request fired from the editor**
     (option A runs the module on the editor's own origin, with the marketer's cookies);
   - a `fetch` reached through `(()=>0).constructor("return fetch")()` — named nowhere;
   - filesystem read via `process.getBuiltinModule("node:fs")` — **leaked another workspace's bytes**
     in the server render;
   - `top`/`parent` reached without the word `window` (the editor stayed up; a reachable navigation
     target would have been attempted).
   React blocked a `javascript:` URL on its own. The two resource-abuse fixtures (infinite loop,
   20k-row output → 32 MB HTML) pass the check: the loop ran until killed; in the container
   `--init` + `timeout` bounded it (exit 137 at the limit), but with no limit it ran unbounded.
2. **Isolation must be defence-in-depth, not just the digest route.** Serving-path isolation
   (route + renderer refuse foreign/traversal digests) held in every case. What it does **not** give
   is runtime containment: once a module is loaded, option A has it share the host's React, origin,
   cookies and (server-side) filesystem and process. Production needs the network/fs boundary from
   the process, not the identifier namespace.
3. **One React, shared (question 1 note).** The editor exposes its own `react`, `react/jsx-runtime`
   and `zod` on `globalThis.__clueSectionHost` and an import map rewrites the module's three kept
   imports to re-export them. Verified in the browser: the module's `jsx` and `zod.z` are the host's
   (hooks/context/validation all one copy). The server bundle keeps packages external so Node
   resolves one copy from `node_modules`.
4. **`contentEditable` works, with one caveat.** Inline editing flows to props. A React console
   warning *"two children with the same key"* appears because several fixtures key list items on a
   content string (`key={item.headline}`), which collides the instant you edit one to match another.
   Non-blocking here; production field-generation should inject stable keys or the agent skill should
   require them.
5. **CSS is the open production question (question 3).** In this spike Tailwind's dev scan
   (`@source "../puck/agent-sections"`) picks up every novel class because the *source* files live
   there — but compiled modules live in `data/compiled/`, which is **not** scanned, and in
   production the agent's source may not be on the serving box at all. A feasibility check shows
   Tailwind's own API (`@tailwindcss/node` `compile` + `@tailwindcss/oxide` `Scanner`) can build the
   exact utilities one compiled module needs against the app's theme in **~12 ms** (e.g. 998 bytes /
   9 rules for the quote section). So B6/C9 should **compile per-module CSS at compile time and store
   it with the module**, not rely on a global scan.

## Recommendation for B6 and C9

- **B6 (store compiled modules per workspace):** adopt this content-addressed shape — compile with
  esbuild (ESM, JSX automatic, react/jsx-runtime/zod external), key by `sha256(code)`, store under
  the workspace, and keep `{name: digest}` on the document (the platform's custom-component artifact
  pattern). Serve per workspace from the session's workspace, **never from a URL segment** as this
  spike does. **Also compile and store the module's CSS** (Tailwind node+oxide, ~12 ms) alongside it.
  Keep the lint's banned-identifier pass as a cheap first gate **but do not trust it as the security
  boundary** — add the runtime boundary (below) and keep the pre-insert type-check.
- **C9 (load at runtime in the editor):** the import-map + shared-host-React mechanism here works and
  edits in place; reuse it. Derive fields from the stored propsSchema, and inject **stable list
  keys** so inline edits don't collide.
- **The boundary that this spike proves is missing:** option A gives no containment. For the **server
  render**, keep the no-network, read-only, time-and-memory-bounded subprocess this spike used
  (`--network none --init`, `timeout`, read-only mount scoped to *one* workspace's modules — not a
  shared root, which the fs-read probe walked). For the **editor**, where a loaded section runs with
  the marketer's session, option A (same origin) lets a section beacon out or read cookies; a
  sandboxed iframe (`sandbox` without `allow-same-origin`, a null-origin preview) is the honest
  containment, at the cost of the shared-React ergonomics — this is the B6/C9 trade-off to decide
  with the founder. At minimum, publish must re-run the full check **and** render the section in the
  bounded subprocess, and refuse a missing/stale module (A7's `section_module_missing`).

## Decision (founder, 2026-10-09)

D2 is decided: **the separate-domain editor.** The whole Puck editor runs on its own domain, with
no login there, embedded in app.cluehq.ai as one frame. Agent code runs on the server only in the
locked container, and published HTML is sanitized. A per-section sandbox was not adopted. See the
readiness map (`docs/superpowers/specs/2026-10-08-puck-production-readiness-map.md` §5, §6, §9),
the plan's "D2" section, and the research report
(`docs/superpowers/specs/2026-10-09-code-first-builder-isolation-research.md`).
