# W4 Lane B — Image + Button schemas (parallel worktree brief)

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans.
> **Process rule (founder, binding): Opus agents implement; the orchestrating session
> reviews every diff INLINE itself — never via a reviewer subagent.** TDD throughout.

**Worktree:** branch `feature/w4-lane-b-image-button`, already cut from
`integration/frontend-design-part-iv-v2` (trunk). Local commits only, one commit per
control group, **never push**, no AI attribution. Merge-back: **lane B merges into the
trunk FIRST** (before lane C) — coordinate with the trunk session when done.

**Parent plan:** `docs/superpowers/plans/2026-08-17-website-editor-integration.md` (read
its Global Constraints + the W4 preamble rulings F1–F3). **Binding spec:**
`docs/specs/website-editor-integration/web-inspector-mapping-contract.md` (§ numbers below)
+ `decisions-recorded.md` (item numbers below). Cite the ruling/§ number in every commit
that applies a delta.

## Scope

- **W4.2 Image schema** (plan text): link/new-tab props; Replace = file input → asset
  upload via BFF → `upsert_asset` + `replace_asset` ops; Mode (minus Tile); radius via the
  W4.1 facets. Contract rows: 11 (Link-to appears for images, optional per ruling), 12
  (Replace keeps the dummy's direct-upload UX), 13 (Fit→`contain`, Fill→`cover`,
  Stretch→`fill`; **Tile dropped**), 14 (radius). §2 deltas for this schema: padding 4→2
  where present.
- **W4.3 Button schema**: link props (15); variant map minus Critical (16: Primary→
  `primary`, Secondary→`secondary`, Transparent→`ghost`); token color buttons → token
  popover reusing the ColorControl Theme-tab pattern (17) → `bg-`/`text-` facets.
- Same TDD pattern as W3: harvested fixture → failing adapter tests (hydrate + apply per
  control) → wire → browser-verify → commit.

## Substrate you inherit (already on the trunk — consume, don't rebuild)

- **Radius facets (W4.1, both engine copies):** `radiusFacet` + `radiusTopLeft/TopRight/
  BottomLeft/BottomRightFacet` in `webClassFacets.ts` (+ registry entries `radius`,
  `radiusTopLeft`, …). Value = token suffix (`rounded-lg`→`"lg"`, `rounded-[8px]`→
  `"[8px]"`); set writes arbitrary px as `rounded-[Npx]`. **Two binding warnings:**
  (a) bare `rounded`/`rounded-tl` parses **null** (owned for removal, never reported) —
  the Shape section must render null as its designed empty/default, NEVER as `0`, and must
  never write `rounded-[0px]` for an untouched field; (b) **ruling F2 (founder,
  2026-08-18): "Radius (all)" CLEARS per-corner overrides** — an all-corners write chains
  the four corner facets' clears (each facet clearing only its own family, so the §4 facet
  law holds) then sets `radiusFacet`. Unmodeled side utilities (`rounded-t-*` etc.) stay
  untouched. NO engine change is authorized — this is adapter-level (`apply.ts`).
- **Theme feed (W4.0 + F3):** `ThemeColorsContext` in `web-inspector.tsx` carries the
  document's real tokens (already **filtered — `palette-*` hidden**, ruling F3) built by
  `adapter/theme-options.ts::buildThemeColorOptions`; `ColorControl` takes an optional
  `options` prop (fixture fallback); `themeColorForToken` resolves a hydrated token label
  → real swatch color. W4.3's token buttons (17) consume this context — the write emits
  the token LABEL, and `apply.ts` lowercases labels into `text-<token>`/`bg-<token>`
  facet writes (existing `tokenTextColor` case is the pattern; add the bg counterpart).
- **Write discipline (W3.2, do not re-derive):** events carry W3.1 addressing
  `{selectionId, artifactId, documentVersion}` with the null-means-ignore contract;
  `useInspectorWrites` listens; `useWebManualEdits` runs one in-flight mutation with
  `base_version`, 409 → quiet reload note, 422 → first diagnostic inline (W3.3 ruling:
  inline only — never add failure UI). Free-text inputs draft locally, commit on
  blur/Enter (R3).
- **Engine access:** ALWAYS through `designBffConfig()`
  (`features/design-editor/data/design-bff.ts`) — the engine's `new URL(path, apiBaseUrl)`
  contract; never hand-build a config, never call the design API origin from the browser.
- **Hydrate/apply are the contract's executable tables** (`adapter/hydrate.ts`,
  `adapter/apply.ts`) — append your schema's mappings in clearly schema-labeled blocks
  (lane A edits the same files in parallel; labeled blocks keep the merge mechanical).
  `hydrate` already maps `objectFit` and image/button `href`/`new_tab` — check what
  exists before adding.

## W4.2 specifics

- **Asset upload:** discover the design API's real asset endpoint from
  `subsystems/clue-design/apps/api/lumen_api/main.py` (assets/upload routes) — the plan
  sketch says `POST /assets` via the BFF; verify the exact path + response shape, then
  `upsert_asset` + `replace_asset` operations through `applyWebOperations`. The dummy's
  file input UX is preserved verbatim (ruling 12).
- **Fixtures:** seed YOUR OWN document (see environment) with an image node carrying a
  real uploaded asset, a linked image, and radius classes (`rounded-[8px]`,
  `rounded-tl-[4px]`) — harvest wire-true `WebNode` JSON for the adapter tests.
- Radius UI: the dummy Shape section (all + 4 corners). Hydrate via the five facets;
  per-corner writes per corner facet; all-corners per F2 above.

## W4.3 specifics

- Variant: hydrate has the button-variant map — extend/verify against row 16's trimmed
  option set (Critical dropped from options; engine `outline`/`link` variants have no
  dummy slot — hydrate them to the closest honest display only if the contract table
  already says so; otherwise leave unmapped per §6(5) omission rule).
- Token color buttons: reuse the Theme-tab pattern (options from context, label emission);
  bg writes `bg-<token>` via `webClassFacets.bgColor`, text via `textColor`.

## Environment (yours alone — do not touch the trunk's 3030/8030/8010)

- Ports: **frontend 3040, platform API 8040, design API 8011.** Launch recipe:
  `_memory/2026-08-17-w01-shell-lift-file-set.md` §launch recipe, with these ports and
  `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` including `http://localhost:3040`.
  **MANDATORY:** `LUMEN_CORE_HELPER=<repo>/subsystems/clue-design/target/release/lumen-api-helper`
  (build once if absent: `cargo build -p lumen-api-helper --release`), and **before every
  launch `lsof -nP -iTCP:<port> -sTCP:LISTEN` → kill stale listeners** (EADDRINUSE dies
  silently in logs; this trap fired twice on the trunk).
- Postgres 55040 is shared. **Seed your OWN web document** (`POST :8011/documents`
  `{doc_kind:"web", title:"Lane B test doc"}` with
  `X-Workspace-Id: ws_8040294627e146ae93f753ec0d3e1726`, then `POST …/web/operations` to
  add an image node, a button, a linked image) — never edit the trunk's
  `doc_31126145a0aa4753920629ae323a301b` (undo-stack/version crosstalk).
- Test login: `/onboarding/sign-in-email` → `onboarding+clerk_test_20260814@example.com`
  / `pass@123` → code `424242` → workspace `ws_8040…`. Browser automation: the gstack
  `/browse` skill only.
- Lint traps: frontend runner is `tsx --test` (NOT vitest); no sync `setState` in
  effects; no render-time ref writes; presentation components never import `data/`/engine;
  don't shadow `document`; `public/vendor/**` is generated.

## Gates & done

Per task: `cd apps/frontend && npm test && npm run lint && npm run design-system:build &&
npm run build` green; browser-verify on your stack (edit → persist through reload → undo
works); commit citing rulings. Done means: contract §1 rows for image+button demonstrably
live, §2 deltas applied, §3 rows still inert, F2 radius semantics proven in the browser
(set all → corners clear), token popover lists the filtered real tokens. Close with a
`_memory/` note + tell the trunk session you're ready to merge (B merges first).
