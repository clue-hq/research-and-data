# 2026-08-18 — W4 Lane B COMPLETE: Image (W4.2) + Button (W4.3) schemas

Branch: `feature/w4-lane-b-image-button` (this workspace's branch renamed onto the lane name
per founder instruction; the trunk-cut pointer at `ae8a8abb` was a strict ancestor and was
replaced — HEAD carries one extra session-note commit over the cut). Brief:
`docs/superpowers/plans/2026-08-18-w4-lane-b-brief.md`. Process: SDD, Opus implemented,
Fable reviewed every diff inline (no reviewer subagents), controller browser-verified each
task on the lane's own stack. SDD ledger (rulings R-B1–R-B6 + per-task records):
`.superpowers/sdd/2026-08-18-w4-lane-b-brief/progress.md` (gitignored scratch — the rulings
that matter long-term are restated here).

## Delivered (6 commits, 14 files, all in apps/frontend; engine untouched)

- `ebd53aaa` W4.2 hydrate: radius facets → Shape state. Display vocabulary: `[Npx]`→bare
  number, named scale (`lg`/`full`) verbatim, absent/bare-`rounded` → `""` NEVER `"0"`.
  `state.radius` hydrates the full 5-field record for EVERY node (the dummy default
  `{all:"0", corners:"4"}` lies about real nodes). New wire-true fixtures
  `HARVESTED_IMAGE_PAGE` (+ classes-variants) from the lane's own seeded doc.
- `0e10f5bb` W4.2 apply: fillMode→objectFit (row 13, image-only); url/openInNewTab →
  FULL-props resend (image props; buttons via engine `buildWebButtonProps`; command-form
  buttons refused — row 36 agent-only); radius commits: numeric→`rounded-[Npx]`,
  empty→clear, non-numeric→NO write; **F2: `radius.all` set chains the four corner-facet
  clears + the all set in ONE set_node_classes op**; empty-all clears only the all family.
- `a0773fe4` W4.2 wiring: Tile dropped (row 13 §2); RadiusControls + LinkSection URL adopt
  local-draft + blur/Enter commit (R3 model; `InspectorInput` gained optional `onCommit`);
  scan button = one `radius.all` commit under F2 (web); ad-side image-inspector keeps dummy
  fan-out via optional `onApplyAll`; controller gained `setRadiusAll` (corner mirror).
- `594532c0` W4.2 Replace image (row 12): `data/assets.ts` `uploadWebAsset` — multipart
  POST `/api/clue/design/assets` via the BFF (proxy forwards content-type+raw body; no
  hand-set Content-Type); `use-replace-image.ts` follows the upstream WebEditorApp flow —
  upload → `[upsertAssetOp (new only), replaceAssetOp]` ONE batch, intent `replace_image`,
  re-entrancy-gated; failure → the manual-edits inline error slot (`reportError`, W3.3:
  inline only); preview src hydrates the node's real asset
  (`/api/clue/design/assets/{id}/bytes`) with the `unoptimized` condition extended (the
  Next optimizer fetches without session cookies → would 401).
- `a238780a`+`b8b311ba` W4.3 Button: Critical dropped (row 16 §2); `buttonLabel` →
  variant via `buildWebButtonProps` (command form preserved); `tokenBackgroundColor` apply
  case (mirror of tokenTextColor); `TokenColorField` — the dummy chip trigger opens a
  token-grid popover (ColorControl Theme-tab classes, no tab strip/custom picker; F3-filtered
  ThemeColorsContext; label emission); button Layout → `paddingAxes="two"` (R3 §2). Fix
  round: `WEB_BUTTON_DUMMY_TOKENS` (Primary/White) merged UNDER `hydrated` at the button
  controller site — DEFAULT_STATE's White/Content belong to the AD image-inspector's chips
  and must not move.

## Browser verification (controller, lane stack, doc v1→v15)

All on seeded `doc_298a0c3a512640fbb6823b68b8016733` (ws_8040…): hydration exact for both
schemas; Mode/variant/token/padding/link writes each rewrote ONLY their facet family
(byte-exact class strings verified via the design API after every write); **F2 proven live**
(all=12 cleared `rounded-tl-[4px]`+`rounded-tr-[6px]` in one op, corner fields mirrored);
real multipart upload → upsert+replace batch = ONE undo step (⌘Z reverted, ⇧⌘Z redid);
token popover = 30 F3-filtered tokens with real swatches; non-numeric radius commit = no
write; bare `rounded` never rendered as 0; full-reload persistence after every group.
Screenshots: /tmp/laneb-t2-image-schema.png, /tmp/laneb-t3-replace-image.png,
/tmp/laneb-t4-button-schema.png.

## Lane environment (for the merge session / future re-verification)

Ports frontend 3040 / platform API 8040 / design API 8011 (per the brief; all port-checked
before launch). `.env` + `apps/frontend/.env.local` copied from the istanbul trunk
workspace; helper binary built in this worktree
(`subsystems/clue-design/target/release/lumen-api-helper`). Test login + workspace per the
brief. Lane B seeded its OWN doc + assets (`asset_c42b6ba24117` teal, `asset_20c8f4f4e196`
amber); the trunk's `doc_31126…` untouched.

## Recorded rulings/notes with future reach

- **R-B1 radius vocabulary** (see delivered list) — lane A/C inherit it if they touch radius.
- **R-B4 wholesale-props discipline**: any future props-writing control MUST resend full
  props from the current node (engine builder for buttons); command-form buttons get no
  link-field writes (row 36). Props writes refuse nodes missing identity fields
  (image w/o asset_id, button w/o label/variant) — refuse, never invent.
- **R-B5/R-B6 as shipped**: preview-src hydration + token-chip popover patterns are reusable
  for lane A's container/canvas color work (`TokenColorField` in web-inspector.tsx).
- Upload client handles BOTH FastAPI refusal shapes (bare-string 413/400 detail + object
  ingest errors) — verified against lumen_api main.py.
- Deferred minors (accepted): NUMERIC_RADIUS regex duplicated in RadiusControls + apply.ts
  (presentation may not import the adapter; cited both sides); asset-change-without-reselect
  preview drift (accepted-drift class); token popup stays open on pick (matches ColorControl
  Theme tab — one-line Popover.Close if the founder ever wants dismissal).
- Observation (pre-existing, not lane B's): editor-render srcdoc cites asset bytes at the
  design API's exempt `/asset-store/{digest}` route directly (W2.1-era, main.py:745).
- Incident: the T3 implementer died mid-task on an account session-limit API error; resumed
  the same agent with a re-establish-tree-state-first instruction — clean recovery, no rework.

## State / next

W4.2 + W4.3 done ⇒ **Lane B scope complete; merges into the trunk FIRST (before lane C),
per ruling F1.** Gates at close: frontend 600/600, lint, design-system:build, build (run
independently by the controller). Coordinate the merge with the trunk session
(`integration/frontend-design-part-iv-v2` workspace); after B merges, lane C rebases.
