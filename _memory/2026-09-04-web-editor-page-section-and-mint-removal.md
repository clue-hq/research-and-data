# 2026-09-04 — web editor: Page section repaired, sample-site mint green removed

## What happened
Founder tried to add a second page to the Ramp campaign document (`doc_7ad66d87091f536c97ffc417b0b0691b`)
from the web inspector's Page section (F5 T18/T19, flagged neutral controls, landed 2026-09-03).
The section had ONE Name/Route pair (editing the LIVE page) above a bare "Add a page" box that
derived its route from the name silently. The founder typed the new page's name into the live
page's Name box → home page renamed/re-routed to `/issuing`, then `/issue` (history envelopes
3–6, all `set_page_meta` on `home`); Add then collided with the page just renamed
("That route is already used by another page"). Restored by posting two `set_page_meta`
operations (name "Home", route "/") at base_version 6 → version 7.

## Changes (frontend, `apps/frontend`)
1. **Page section → two groups.** "This page" (Name, Route, Remove page) and "New page" (Name,
   Route suggested from the name until edited, Add page). `inspector-page-field.ts`:
   `routeFieldDecision(draft, current, siblings: PageRef[])`, `addPageDecision(name, routeDraft,
   pages)`, `suggestedRouteForName`, `routeTakenMessage(pageName)` (a local collision NAMES the
   holding page), `PAGE_NAME_TAKEN_MESSAGE` (id = name slug; duplicate names refused locally).
   No placeholder ("Pricing" is gone). CSS `.inspectorPageGroup` caption.
2. **Selection colour** inside inspector inputs was a 24% mint override → deleted; inherits the
   global `::selection` light blue `#dce7ff`.
3. **Canvas Background swatch** showed the shared default seed (`#00F59B`) because the canvas
   schema was never hydrated. `use-web-editing-session.ts` now exposes `canvasHydrated`
   (`surface-page` theme token → `backgroundColor` + `tokenBackgroundColor` label); both
   inspector mounts pass it when no node is selected and key the canvas inspector on it so
   a theme that lands after mount re-seeds once (web lane hydrates at mount, not live).
4. **Fixture palette removed** (`INSPECTOR_THEME_COLORS`, six sample-site colours). The Theme
   tab shows the document's real palette or nothing; `fixtureFallback` parameter retired from
   `ColorControl`/`BackgroundFillControl` and all callers. `DEFAULT_STATE` seeds neutral
   (`#FFFFFF` bg, `#000000` text); `ColorControl` default `#FFFFFF`; button chip fallback →
   `state.backgroundColor`. Dead `projects/components/canvas-inspector.tsx` deleted. Test hexes
   and comments swept; no `00F59B` remains outside the palette module's own history note.

## Verification
`npm run lint` clean (2 pre-existing warnings in canvasOperations.ts), `npm test` 2102/2102,
`npm run build` (see commit). Dev server recompiled with no errors.

## Open (not done here)
- Multi-page still unexercised end-to-end by the agent; founder plan: add page by hand, then
  ask the agent to fill `/issuing` (tools work per ACTIVE page via `switch_page`).
- Two architectural asks queued for a spec: select-and-annotate (extend ad "edit targets" to
  web + per-target comment box) and human text edits on cloned sections (amends D-F3; needs a
  per-node text-override or richer slot value).

## Follow-up (same day): add_page refused by a STALE HELPER BINARY
After the Page section fix the founder's Add page failed with `unknown variant add_page, expected
one of insert_node, …, set_page_meta, set_custom_css` — the engine's serde enum as compiled into
`subsystems/clue-design/target/release/lumen-api-helper` built **Aug 28**, while
`WebOperation::AddPage/RemovePage` landed **Sep 3** (`e123ae68e`). `scripts/dev_stack.sh` pins
`LUMEN_CORE_HELPER` to that release binary for the DESIGN API only (the fleet worker leaves it
empty → `cargo run`, debug profile, rebuilt on demand — which is why agent runs never hit it).
The wasm handshake stamps only lumen-core, so the stale helper passed (AGENTS.md §1 caveat,
now bitten a second time). Fix: `cargo build -p lumen-api-helper --release` + stack cycle;
`LUMEN_CORE_HELPER=` now declared in root/subsystem `.env.example` and `.env` with the rebuild
rule beside it. **Class fix still open:** a helper-freshness preflight in the design API (compare
the binary's build stamp against the crates' content hash across the FULL crate graph, refuse
loudly), or have dev_stack.sh run the release build before `up`.

## Next initiative (designed, not started): annotations + human names + clone text edits
Spec `docs/superpowers/specs/2026-09-04-web-editor-annotations-and-clone-text-edits-design.md`
(rulings R-A1..R-A6; D-F3 amended with a per-node text-override map). Plan
`docs/superpowers/plans/2026-09-04-web-editor-annotations-and-clone-text-edits.md` — 4 slices,
16 tasks (names → annotations end to end → engine overrides + inline clone editor → quick action).
Key facts the plan rests on: bridge already hovers/selects/dblclick-edits `[data-node-id]`
elements; ad-lane edit targets exist (web gated off); `WebTurnRequest.target_node_ids` +
`_describe_web_turn_targets` exist but the platform never passes web targets; `WebNode.name`
exists but nothing sets it; fragment inner elements carry no ids.
