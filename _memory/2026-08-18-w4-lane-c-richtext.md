# 2026-08-18 — W4 Lane C: rich-text session + custom-component props form (in progress)

Branch: `feature/w4-lane-c-richtext-components` (this workspace, stuttgart; renamed from
`integration/frontend-design-part-iv-v5` at founder instruction — the stale pre-cut lane
pointer at `ae8a8abb` was a strict ancestor and was deleted). Brief:
`docs/superpowers/plans/2026-08-18-w4-lane-c-brief.md`. SDD ledger (rulings, review record,
verification detail): `.superpowers/sdd/2026-08-18-w4-lane-c-brief/progress.md`; scout map:
`…/scout-report.md`.

## W4.8a DONE — rich-text session port (commits `2fd6350d`..`53ff5233`; reviewed inline; browser-verified)

- **Brief correction (load-bearing):** the lane brief's "web-rich-text-runtime.js is
  API-injected — nothing to host" is FALSE. `lumen_api/web_bridge.py:424-444` injects only a
  lazy loader for `/vendor/web-rich-text-runtime.js` resolved against the PARENT origin.
  `apps/frontend` now vendors the bundle: verbatim runtime mirror at
  `src/features/design-editor/iframe/webRichTextRuntime.ts` + Lexical ^0.49.0 ×7 deps +
  esbuild iife/minify in `scripts/copy-design-vendor.mjs` (predev/prebuild). Parent app never
  imports Lexical. (W2.1's "nothing to host" memory conflated the loader with the bundle —
  rich text was never exercised, so the 404 never surfaced.)
- Canvas owns the toolbar (`web-rich-text-toolbar.tsx`, logic verbatim from the source, CSS
  module with literal source-token values) rendered through a **portal to body** —
  `.artifactWorkspace`'s `transform` would otherwise re-root and clip the ported
  `position:fixed` math. Session state mirrors up via `onRichTextSessionChange` (passive
  effect + ref). Commit = ONE `set_rich_text` through the existing manual-edits controller
  (`adapter/rich-text-commit.ts`, page by node membership). Error slot:
  `richTextError ?? writes.error`.
- **Lane rulings** (full text in the ledger): design API on **8013** (8012 held by the
  walla-walla brand-kit lane — never kill another lane's server); dblclick sessions gated on
  the editing dock (cancel-on-edit-start outside Edit); item-3 Link-to predicate = the
  toolbar's own actionable-selection predicate; toolbar ColorPanels inherit F3 on OFFERED
  swatches while the command's `knownTokens` stays unfiltered (filtering it would strand
  stale `palette-*` classes beside the new token).
- Verified live end-to-end on 3050/8050/8013 with lane doc
  `doc_c582718f5ceb4fb28cc5de7c5f8d44fb` (v6 after verification): gate, session mount,
  bold-on-range commit (v3, neighbors untouched), unsafe-href refusal + valid link (v4),
  Escape cancel, menu Undo (v5) / Redo (v6), `<a><strong>` markup in the re-render. Gates
  574/574, lint, ds-build, build.

## Environment (Lane C)

Ports: frontend **3050**, platform API **8050**, design API **8013** (ruling — brief said
8012). Launch recipe = the trunk memory's, with `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES`
extended to include `http://localhost:3050` for BOTH the platform API and the frontend
process (the frontend throws at startup otherwise). `.env` + `apps/frontend/.env.local`
copied from the istanbul workspace. `lumen-api-helper` built in-worktree. Port-check before
every launch (the trunk's twice-proven rule). Browse daemon: sign-in replay
(`/onboarding/sign-in-email` → `onboarding+clerk_test_20260814@example.com` / `pass@123` →
`424242` → workspace) — synthetic `dblclick` via `$B js` starts sessions; `$B press "Meta+z"`
did NOT reach the W3.4 window shortcut (menu path works; recheck by hand).

## W4.8a-retheme DONE — ruling 24 amended (founder, 2026-08-18 evening)

Founder challenged the toolbar's out-of-theme look; chose **retheme, don't relocate** (the
relocate-into-inspector option is noted in the ledger as the W4.8b-predicate pattern, not
chosen for now). Contract §6 (24) carries the dated amendment: behavioral parity baseline
stays the source editor; visual baseline is now the platform inspector. The CSS module was
re-skinned onto `--clue-ds-*` tokens (:root-scoped — required, since the toolbar portals to
body where the `--chat-shell-*` aliases don't reach) + the chat-shell inspector idioms;
no tsx/logic change. Executed inline by the orchestrator (Opus pool session-limited until
22:00 IST; one-CSS-module scope). Gates + live browser verification recorded in the ledger.
Found & noted: `--chat-shell-card-shadow` / `--chat-shell-disabled` are referenced in
chat-shell.module.css but defined nowhere — avoided here; a dummy-frontend quirk to flag
at a doc/UX pass.

## W4.8b DONE — conditional Link-to (commits `fd00b58b` + `16255ef5`; reviewed inline; browser-verified)

Contract item 3 live: the TEXT schema's Link-to is ABSENT by default and exists only while
the session's selection is actionable (the ledgered predicate; structured arm deliberately
dropped — that arm serves the toolbar's block controls only). Writes are range-link
COMMANDS (`set_link`/`remove_link` via new imperative canvas controls), validated with the
shared grammar; invalid href → the W3.3 header error line (node-stamped). Empty-URL commit
on a linked range = remove_link (lane ruling). The implementer's `setRichTextInteractionActive`
addition is load-bearing (the bridge's 180ms blur-commit + the runtime's frozen
lastSelection) — without it the URL field would settle the session it edits. Browser-proven:
absent/present matrix, prefill, ftp:// refusal, set_link persist (v12), remove_link persist
(v13), post-session absence. W4.8a founder sign-off came with a founder-executed toolbar
RETHEME (`40ad951f`, ruling 24 amended in contract §6: behavior = source parity, skin =
inspector design language). Deferred minors in the ledger: mixed-state removal only via
toolbar; section born collapsed; chats-route dummy mount now shows no text Link-to
(sanctioned but visible).

## W4.7 DONE — custom-component props form (commits `826301b7` + `ee8b4eb2` + fix
`a4e0c03e`; reviewed inline; browser-verified 2026-08-18/19)

Contract item 34 live. Seeding (all via live 8013 API): web account
`acc_403fa12213464a9cbb2a9a1dab3663db`, slug `lane-c-pricing-card`, artifact
`ccart_765fe726…c210925c` (schema: headline string / accent enum blue|green / planCount
number / showBadge boolean; defaults blue/Pricing/3/true). Verification doc = the DERIVED
account-bound `doc_b778a805381c4831844c490e30701719` (instance `cclanec1` in `secc`;
a doc gets account_id ONLY via derive; insert must target a section — LUMW0011). Compiler
recipe note: `npm ci` in `subsystems/clue-design/apps/custom-component-compiler` first
(503 CCI0002 "Cannot find package 'typescript'" is the symptom).

Port: pure decision module mirrors the source `CustomPropControl` branch-for-branch;
`pageIdForNode` extracted to `page-address.ts` (rich-text commit refactored onto it);
banner-delimited "Component properties" inspector section, ContainerControls only,
inspector-native, chrome excluded; whole-props `set_custom_component_props` through the
manual-edits controller. Ledgered ruling: loading/failed artifact → form ABSENT.
**Escape defect found in browser & fixed (`a4e0c03e`):** both Enter/Escape end focus and
the span's blur-settle fired same-task with the pre-key draft closure — Escape committed
the garbage it abandoned. Fix = pure `customComponentDraftKeyAction`/
`…KeySuppressesBlur` + a skip-next-blur-settle ref; deliberate deviation from the
source's wiring (same hazard upstream; semantics = "Escape sends nothing"). All six
behaviors browser-verified; seeded props restored through the fixed form. Gates 634/634,
lint, ds-build, build. Implementer report: `.superpowers/sdd/…/task-5-report.md`
(residual notes: `layoutOnly` not yet consumed by web-inspector so full container view
shows beneath the form — pre-existing lane A/B state; footer hint unconditional, source
parity; post-commit remount flicker, same as rich-text).

## Open / next

- Full W4.8+W4.7 combined browser pass, whole-branch review, close-out. Lane C merges
  AFTER lane B (rebase on the updated trunk first).
- Carried caveat (source semantics): a rich-text commit landing while another write is in
  flight is silently dropped after the Lexical session destroyed itself — unrecoverable;
  same upstream.
