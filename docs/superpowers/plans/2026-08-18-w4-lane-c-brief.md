# W4 Lane C — Rich-text session + Custom-component props form (parallel worktree brief)

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans.
> **Process rule (founder, binding): Opus agents implement; the orchestrating session
> reviews every diff INLINE itself — never via a reviewer subagent.** TDD throughout.

**Worktree:** branch `feature/w4-lane-c-richtext-components`, already cut from
`integration/frontend-design-part-iv-v2` (trunk). Local commits only, commit per task,
**never push**, no AI attribution. Merge-back: **lane C merges LAST** — after lane B has
merged into the trunk, rebase onto the updated trunk, then merge.

**Parent plan:** `docs/superpowers/plans/2026-08-17-website-editor-integration.md`
(Global Constraints + the W4 preamble rulings F1–F3). **Binding spec:**
`docs/specs/website-editor-integration/web-inspector-mapping-contract.md` +
`decisions-recorded.md`. Cite ruling/§ numbers in commits.

## Scope

- **W4.8 Conditional Link-to (rich-text ranges)** — plan text: rich-text session port
  (double-click → Lexical session, **toolbar as-is per ruling 24** — it is canvas UI, not
  inspector chrome, and was explicitly kept); Link-to section visibility bound to live
  range selection (contract item 3's conditional Link-to); link edits go through the
  toolbar's validated href path.
- **W4.7 Custom-component props form** — port `WebCustomComponentInspector`'s
  schema-driven form section (checkbox/select/number/text per manifest `props_schema` →
  `set_custom_component_props`); **status/republish/Edit-with-AI chrome stays OUT**
  (contract item 34 scope: "the schema-driven props form", nothing more). Selection of a
  custom component today falls to the §5 layout-only fallback — your form section joins
  that view, it does not replace the fallback for other unknown kinds.
- Order: W4.8 first (bigger, riskier), then W4.7.

## Substrate you inherit (already on the trunk)

- **Engine modules extracted (W1.1):** `features/design-editor/engine/webRichText.ts` is
  the rich-text engine slice, already import-adjusted; `webDocuments.ts` carries
  `set_custom_component_props` operations and the manifest/props types. All engine calls
  go through `designBffConfig()` (`features/design-editor/data/design-bff.ts`) — never a
  hand-built config, never a browser call to the design API origin.
- **Bridge seams (W2.2):** `use-web-bridge-selection.ts` is the verbatim
  `useWebBridgeSelection` port and ALREADY carries the rich-text callback seams the
  session needs (plus move/resize seams — leave those; rulings 29/§7-6 govern them).
  The canvas (`web-artifact-canvas.tsx` + `useWebRender`) owns the per-render nonce.
- **Source of truth for the port:** the design subsystem's dev editor —
  `subsystems/clue-design/apps/editor/src/` (`WebEditorApp.tsx` rich-text session wiring,
  the toolbar component, `WebCustomComponentInspector`). Port semantics exactly; adapt
  only for this repo's lint (below) and the BFF config. The `web-rich-text-runtime.js` is
  injected into the srcdoc BY THE DESIGN API (verified W2.1) — nothing to host.
- **Write discipline (W3.2):** one in-flight mutation, `base_version` per apply, 409 →
  quiet reload note, 422 → first diagnostic inline (W3.3: inline only, no new failure UI).
  Rich-text session commits flow through the engine's own rich-text apply path — port its
  concurrency semantics as-is; do not invent a second write path.
- **Inspector wiring pattern:** `web-inspector.tsx` hosts the schema views; the Link-to
  section (`LinkSection`) already exists — item 3 makes its *visibility* conditional on a
  live range selection inside a rich-text session. Hidden = absent (§2 style), not
  disabled.
- Hydrate/apply (`adapter/`) are shared with lanes A+B — if you touch them at all, append
  in clearly labeled blocks; most of W4.8's logic should live in the session port, not the
  adapters.

## Environment (yours alone — do not touch the trunk's 3030/8030/8010 or lane B's 3040/8040/8011)

- Ports: **frontend 3050, platform API 8050, design API 8012.** Launch recipe:
  `_memory/2026-08-17-w01-shell-lift-file-set.md` §launch recipe with these ports and
  `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` including `http://localhost:3050`.
  **MANDATORY:** `LUMEN_CORE_HELPER=<repo>/subsystems/clue-design/target/release/lumen-api-helper`;
  **before every launch `lsof -nP -iTCP:<port> -sTCP:LISTEN` → kill stale listeners**
  (the silent-EADDRINUSE trap fired twice on the trunk).
- Postgres 55040 shared. **Seed your OWN document** (`POST :8012/documents` with
  `X-Workspace-Id: ws_8040294627e146ae93f753ec0d3e1726`) containing rich formatted text
  (ranges with links) and a custom component instance with a real `props_schema` manifest
  (find/create one via the design API's custom-component endpoints — discover them in
  `lumen_api/main.py`). Harvest wire-true fixtures from it for tests. Never touch the
  trunk's `doc_31126…`.
- Test login: `/onboarding/sign-in-email` → `onboarding+clerk_test_20260814@example.com`
  / `pass@123` → `424242` → `ws_8040…`. Browser automation: gstack `/browse` only.
- Lint traps: `tsx --test` runner (NOT vitest); no sync `setState` in effects; no
  render-time ref writes; presentation never imports `data/`/engine; don't shadow
  `document`. Lexical packages: check `apps/frontend/package.json` before assuming — add
  the exact versions the source editor uses if absent.

## Gates & done

Per task: `cd apps/frontend && npm test && npm run lint && npm run design-system:build &&
npm run build`; browser-verify on your stack. Done means: double-click opens the rich-text
session with the source's toolbar (ruling 24), range-select shows Link-to and its edits
persist through the validated href path (item 3), session close returns to normal
selection cleanly; a selected custom component shows the schema-driven props form and a
prop edit persists via `set_custom_component_props` (item 34) with the chrome absent;
undo/redo still behaves over rich-text and prop writes. Close with a `_memory/` note +
tell the trunk session you're ready (C merges after B).
