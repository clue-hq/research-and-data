# G7 — the missing Tailwind runtime: why generated pages had no layout

Date: 2026-08-19. Branch `integration/frontend-design-part-iv-v2`.
Scope: the design subsystem's preview render path (fleet/agent side) + the
reconciliation of the platform canvas half.

## The mechanism (read this first)

A website document's **entire layout layer lives in Tailwind utility classes**
(`flex flex-col gap-10 items-center min-h-screen mx-auto max-w-[900px] px-6
py-24 text-center`, plus color utilities like `bg-dark`). The renderer
(`crates/lumen-web/src/render.rs:184-225`) emits, in **editor** mode:

- `:root` custom properties for the theme tokens,
- a `<style type="text/tailwindcss">` block (the theme, NOT compiled CSS),
- `@layer base` semantic defaults (what `data-variant` / `data-button` styling
  rides on), and
- **optionally** `<script src="{tailwind_runtime_src}">`.

There are **no utility rules in that CSS**. The Tailwind v4 **browser runtime**
is what compiles them at load time. In **delivery** mode neither the tailwindcss
block nor the runtime is emitted at all — export/publish compiles utilities
statically via `scripts/web_static_css.mjs`.

So: no runtime ⇒ theme styling (headings, buttons, colors-by-token) still
renders, and the whole layout layer is silently deleted. That is exactly the
reported symptom (content stacked top-left) and exactly why it looks like a
partially-working page rather than an obvious failure.

Two independent consumers supply the runtime, and each was broken differently:

| surface | how it gets the runtime | what was wrong |
| --- | --- | --- |
| design-runtime preview renders (the fleet-side screenshots the visual reviewer grades) | `LumenWebTools.render_web_preview` **inlines the file's bytes** into the html before Playwright `set_content` (`tailwind_runtime_src=None` on the render call) | the file it read did not exist in this checkout |
| the shells (design editor at 3000, platform canvas at 3030) | pass `?runtime_src=/vendor/tailwind-browser.js`; the server emits a `<script src>` the srcdoc iframe resolves against the **parent** origin | the frontend's view mode omitted `runtime_src` entirely until 2026-08-19 01:20 |

## Root cause, preview path (the one this work fixed)

`web_substrate.py` read exactly one path:
`<repo_root>/apps/editor/public/vendor/tailwind-browser.js`, missing ⇒
`tailwind_runtime_missing: true` and render bare.

That path is **gitignored** (`subsystems/clue-design/.gitignore:38`) and
**nothing in the repo produced it**. It is a copy of
`apps/editor/node_modules/@tailwindcss/browser/dist/index.global.js`. The
website-editor integration plan already said so in as many words —
"closing the upstream build gap: no script produces this file anywhere today"
(`docs/superpowers/plans/2026-08-17-website-editor-integration.md:172`) — and
the frontend solved it for **itself** with `apps/frontend/scripts/
copy-design-vendor.mjs`, wired into its `predev`/`prebuild`. The design
subsystem never got the equivalent.

### Answering the founder's hypotheses

- **An env var disabling it?** No. Before this change *no* Tailwind-related env
  var existed anywhere in either repo (`grep -i tailwind` over both
  `.env.example` files: nothing).
- **A missing / incomplete `.env` entry?** No. The mechanism was a hardcoded
  filesystem path with no env seam at all — a correct `.env` could not have
  helped, and no `.env` line could have broken it.
- **Then what?** A **generated, gitignored asset that no build step generates**.

### Why the pre-merge MVP editor never hit it

Because the file is gitignored, it lived only in a *working tree*, never in a
commit. In the havana MVP tree someone had hand-copied it once (the code still
points at a `public/vendor/README.md` that was never tracked either), and it
simply stayed there for the life of that checkout — every render after it
worked. The monorepo merge copied the *tracked* tree only, so every fresh
checkout since has had a preview renderer with no runtime. Nothing regressed in
code; an undeclared local prerequisite stopped being present.

## The fix

1. `lumen_agent/tools/web_substrate.py` — new `tailwind_runtime_path(repo_root)`
   with an ordered search path, replacing the single hardcoded path:
   1. `LUMEN_TAILWIND_RUNTIME` (absolute-path override; **set-but-missing
      resolves to None**, it does not fall through — an operator who named a
      path is told it is wrong),
   2. `apps/editor/public/vendor/tailwind-browser.js`,
   3. `apps/editor/node_modules/@tailwindcss/browser/dist/index.global.js`.
   Hop 3 is the load-bearing one for the fleet worker, which never runs the
   editor's npm scripts: a plain `npm install` under `apps/editor` now suffices.
   The miss also logs a `logger.warning` naming every path it searched (it was
   previously only a field in the tool's JSON result).
2. `scripts/vendor_tailwind_runtime.sh` — the missing producer for hop 2 (the
   URL the shells fetch). Best-effort like `copy_canvaskit_assets.sh`; wired
   into `apps/editor`'s `predev`/`prebuild`. This also fixes the design editor
   at :3000, which was serving **404** on `/vendor/tailwind-browser.js`.
3. `subsystems/clue-design/.env.example` — documents `LUMEN_TAILWIND_RUNTIME`
   as the deployment seam (commented out; dev should leave it unset).
4. Tests in `apps/agent_runtime/tests/test_web_substrate.py` (6): precedence,
   package fallback, override wins, override-pointing-nowhere ≠ fallthrough,
   absent-everywhere, and a real-checkout resolution test.

## Proof

**Surface (a) — the preview render path**, on the founder's document
`doc_a37154cd822352b898ef6ac96fd733f2` ("Insight Health"), reproducing
`render_web_preview`'s html assembly verbatim (design API editor render →
inline the resolved runtime) and measuring in Chromium at 1440×900:

| probe | before (no runtime) | after |
| --- | --- | --- |
| hero inner `display` | `block` | `flex` (`flex-direction: column`) |
| `padding-top` (`py-24`) | `0px` | `96px` |
| `max-width` (`max-w-[900px]`) | `none` | `900px` |
| left offset / width (`mx-auto`) | `0` / `1440` | `270` / `900` (centered) |
| body height (`min-h-screen`) | `77px` | `900px` |
| hero background (`bg-dark`) | `rgba(0,0,0,0)` | `rgb(17,24,39)` |

Screenshots `/tmp/g7/preview_before.png` (content stacked top-left, white) vs
`/tmp/g7/preview_after.png` (centered, full-height, dark). `tailwind_runtime_path`
resolves; `tailwind_runtime_missing` can no longer be set in this checkout.

**Surface (b) — the platform canvas at :3030.** Mounted the design API's
`runtime_src=/vendor/tailwind-browser.js` render in a srcdoc iframe at the app's
own origin under the canvas's real sandbox (`allow-scripts`, i.e. an opaque
origin): `GET /vendor/tailwind-browser.js` → **200**, zero failed requests, zero
console errors, and inside the frame `display:flex`, `padding-top:96px`,
`max-width:900px`, left `270`, `bg-dark` applied. Screenshot
`/tmp/g7/canvas_srcdoc.png`.

## Reconciling the founder's broken canvas with slice 3's working one

Both observations are correct; they are different builds.
`apps/frontend/.../hooks/use-web-render.ts` passed `editing ? TAILWIND_RUNTIME_SRC
: null` — and the pane's default is **Edit OFF**, so the canvas as first opened
fetched a render with no runtime. That is the founder's screenshot. Commit
`888feeaa` ("the view render keeps the Tailwind runtime", 2026-08-19 01:20)
made the runtime ride in both modes; slice 3's walk ran after it and saw layout.
**No frontend change is needed and none was made** (a slice-3 implementer owns
`apps/frontend/` concurrently).

One thing to not misread: the slice-3 document
(`doc_7b2c6ffe137a5bd9beba32745d77ce35`) still renders with left-aligned,
full-bleed lower sections and large empty bands. Verified: the runtime IS live
for it (`max-width:1180px`, `padding-top:80px`, centered at left 130 on the
upper sections). Those lower sections simply carry no container classes, and the
bands are missing imagery — **authoring quality, not the runtime**. Which is the
point: the visual reviewer could not catch that because its own previews had no
layout at all.

## Production-deployment implication (checklist lines)

- **Any image that runs design preview renders (the fleet worker / design API
  in-process worker) MUST carry the Tailwind browser runtime**, at one of:
  `apps/editor/public/vendor/tailwind-browser.js`,
  `apps/editor/node_modules/@tailwindcss/browser/dist/index.global.js`, or a
  path named by `LUMEN_TAILWIND_RUNTIME`. A Python-only image satisfies none of
  these by default; the miss is now a `logger.warning` plus
  `tailwind_runtime_missing` in the tool result, and should be alerted on.
- **Any image that serves the editor/canvas shells must serve
  `/vendor/tailwind-browser.js`** at the shell's own origin (the frontend's
  `predev`/`prebuild` `copy-design-vendor.mjs`; the design editor's
  `vendor_tailwind_runtime.sh`). A 404 there is a fully unstyled canvas.
- **Any image that runs export/publish additionally needs `apps/editor`'s node
  modules** — `scripts/web_static_css.mjs` resolves `@tailwindcss/node` and
  `@tailwindcss/oxide` out of `apps/editor/node_modules`, and delivery-mode
  renders have no runtime at all, so a failed static compile publishes an
  unstyled page. (Pre-existing; recorded here because it is the same family.)
- Joins the already-recorded `LUMEN_CORE_HELPER` deployment requirement
  (`_memory/2026-08-19-genweb-slice2-document-birth.md`).

## Notes / follow-ups

- The two vendoring scripts (`subsystems/clue-design/scripts/
  vendor_tailwind_runtime.sh` and `apps/frontend/scripts/copy-design-vendor.mjs`)
  copy the same bytes for two different servers. Deliberate — the subsystems do
  not share a build — but if a third consumer appears, make it a seam.
- Launch recipes (`/tmp/slice0-relaunch-8010.sh`, `/tmp/slice15_fleet_worker.sh`)
  need **no** change: the fix is not env-driven in dev. They do now depend on
  `apps/editor` being `npm install`ed, which this workspace already is.
- **No restart needed for the running fleet worker** — the runtime path is read
  at call time and the first search-path hop now exists on disk. The **design
  editor at :3000 does** need one: Next wires the static `public/` middleware at
  boot and that directory did not exist when the running server started, so it
  still 404s on `/vendor/tailwind-browser.js` (its `predev` now regenerates it).
- `pytest apps/api/tests` has **16 standing reds in this checkout**, all from a
  missing `apps/custom-component-compiler/node_modules` (compile → 503). Proven
  identical at the parent commit in a throwaway worktree. Unrelated to G7 but
  the same species of fault — an npm artifact nothing declares or installs — and
  it means the design API suite is not a clean gate here. Wants an owner.
