# 2026-08-20 — Phase AD0 COMPLETE: the ad shell is lifted, corrected, and audited

Branch `integration/frontend-design-part-iv-v4`. Plan:
`docs/superpowers/plans/2026-08-20-ad-editor-integration-execution-plan.md`. Ledger:
`.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/progress.md`. Contract:
`docs/specs/ad-editor-integration/ad-inspector-mapping-contract.md` (frozen v1).

## What AD0 shipped

| Task | Commits | What landed |
|---|---|---|
| AD0.1 | `f66a353a`, `5c3e5c78`, `0e652c23` | Re-lift of the co-founder's 23-file ad-schema delta, pinned at **`32658ff`** on `codex/chat-shell` in the read-only checkout `/Users/aryankeshri/Documents/clue-hq/clue-frontend`. Wholesale copy where our file was byte-identical to parent `c7f2bc5`; 3-way hunk application where the platform had diverged (Ruling 1). |
| AD0.2 | none (clean audit) | CSS/icon audit — no drift found; three deferred minors recorded. |
| AD0.3 | `e2881f4b` | `RadiusControls` hoisted into `inspector-primitives` (verbatim move, MD5-proven). |
| AD0.4 | `1342fc1d`, `9c405745` | The eight §2 contract deltas applied to the ad surface + Gate G-E, plus three review fixes (preset default `1024x1024` → `1200x1200`; button-fallback lock hidden; zoom default onto a real menu step). |
| AD0.5 | this note | The exit audit. |

Gate at exit: `npm run design-system:build && npm test && npm run lint && npm run build` — all
green, **890/890** tests, lint silent, build 20/20 static pages.

Root `make check`: ruff clean, mypy **726 files clean**, `lint-imports` **26 kept / 0 broken**,
pytest **5 failed / 2816 passed / 2437 skipped** — the five are **exactly** the pre-existing reds
recorded in `_memory/2026-08-19-chat-flow-slice6-closeout.md` (3× `test_pilot_budget_controls.py`,
1× `test_unified_agent_gate_migration.py`, 1× `test_o3_account_deep_behavior.py`). Corroborated
independently: `git diff --name-only a38defae..HEAD` is 32 `apps/frontend/` files + 2 `docs/`
files and **zero backend paths**, so none of the five can belong to AD0.

**Trap worth remembering:** an earlier `make check` in this session reported **83** failures. The
cause was environmental, not the branch — this audit had copied `istanbul`'s `.env` into the repo
root, so `CLUE_DATABASE_URL` was set, the DB-gated suites stopped skipping and ran against the
*shared* `clue-pg-istanbul` database (which the migration conventions explicitly forbid), and two
`tests/test_config_settings.py` cases assert on auth settings the borrowed `.env` overrode.
**Never leave a borrowed `.env` in place when running `make check`.**

## The audit's verdict — and three findings for the AD2 mount tasks
*(Orchestrator correction 2026-08-20: an earlier draft routed F1–F3 at AD1 — wrong. AD1 is pure
engine substrate with no mounts. F1 is exactly AD2.1's scope [feed widening + the
`toProjectArtifact` type mapping, both already steps there]; F2 is exactly AD2.7's step 2
[`editor-surface.tsx` gains the ad dock]; F3 resolves in AD2.7's session wiring [gate the web
session/theme fetch by artifact kind when the scene session mounts beside it]. Nothing about
AD1's shape changes.)*

Full evidence: `.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/task-ad0.5-report.md`.

**What passed.** On the artifact route, a real scene document resolves to `kind: "ad"` and the
shell renders the honest empty state: `[aria-label="Empty ad output canvas"]`, zero iframes, the
real document title in the tab, the ad header (zoom + Edit + Export). The zoom menu is 29 steps
10–150% @5% with `25%` checked and a real 320px scroll cap. The export menu is PNG/SVG/PDF with
no transparency row anywhere. Every AD0.4 schema renders its designed sections with **no eye
toggle on any of them**, no image "Link to", and `button` falling through to the Canvas schema
without a lock button. Parity against the live dummy at `32658ff` shows **zero unexplained
deltas** — every visual difference maps to a §2 row, Gate G-E, or an orchestrator ruling. The
`.imageCanvas` / `.imageOutputStage` rules are byte-identical between the two trees.

**Ruling 6 is CLOSED.** The real `.inspectorDock` band is **374–480px** (not the ~280px the
ruling assumed): 480px at 1600/1280 viewports, compressing to 374px at 1100px. The four
alignment toggles (`.alignmentControlQuad`) share one row across the whole band.

**F1 — the chats route cannot reach an ad artifact, structurally.** The feed query ends
`WHERE d.doc_kind = 'web'` (`design_leg_wiring.py:458`), *and* the frontend mapper
`toProjectArtifact` hardcodes `type: "website"` while the open rule is
`type === "website" ? "web" : "ad"`. Both chats-route entries (gallery click, F2b auto-open)
consume that feed, so `chatDockContent` can never return `"ad-inspector"`.

**F2 — the artifact route docks no ad inspector either.** `editor-surface.tsx:82-85` gates the
dock on `artifactKind === "web"`; `ImageInspector` has no call site on that route.

**Net: the AD0.4 inspector surface is not merely inert — it is currently unmountable.** AD2.1's
feed widening is necessary but not sufficient; the artifact route needs its own ad branch too
(that branch is AD2.7's step 2 in the execution plan), or the ad dock will only ever appear on
the chats route.

**F3 — one console error per ad-artifact load.** `EditorSurface` calls `useWebEditingSession`
unconditionally, which calls `useWebTheme` with no kind guard, so an ad document triggers
`GET …/documents/{id}/web/theme` → **409**. Caught, non-fatal, nothing renders wrong — but the
AD0 checklist's "zero console errors" row is therefore **not met** on the artifact route.
Deliberately not fixed in the audit: the minimal fix threads artifact kind into a hook the live
web editor shares, and AD2.7 rewires that seam anyway (the scene session mounts beside the web
one, kind-gated).

## Operational facts AD1 will need

- **Reaching an ad artifact needs the real stack.** Fixture mode cannot: `FIXTURE_ARTIFACTS`
  (including AD0.4's Ruling-4 `doc_ad_fixture` row) has no production caller — both pages
  construct `backendDesignArtifactRepository()`.
- **The seeded audit document is left in the dev DB on purpose (AD2 reuses it):**
  - document **`doc_ad0auditscene0000000000000001`** (`doc_kind: scene`, title "AD0 exit-audit ad")
  - workspace `ws_8040294627e146ae93f753ec0d3e1726`, project `prj_79aa603b3c3853898045e3cfa414e136`
  - thread `thr_ad0_exit_audit`, leg `0549a6cf-0767-53f6-b0f0-2795bdf0ceca`
  - route `/projects/prj_79aa603b…/artifacts/doc_ad0auditscene0000000000000001`
  - idempotent seeder:
    `.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/seed_ad0_audit_doc.py`
  - the scene payload is the engine's own empty-document shape, cloned from a real engine row.
- **The `colombo` workspace has no `.env` and no `apps/frontend/.env.local`** — copy them from
  the sibling `istanbul` workspace (both gitignored). There is also no `clue-pg-colombo`
  container; the shared dev DB is `clue-pg-istanbul` on `localhost:55040`.
- **Two launch traps, both new:**
  1. The **frontend** validates `CLUE_APP_ORIGIN ∈ CLUE_AUTH_CLERK_AUTHORIZED_PARTIES`
     (`src/auth/config.ts:82`), not just the platform API. Miss it and every route 500s.
  2. The **platform** session expires independently of the Clerk session — a `goto` lands on
     `/sign-in?reason=session_expired` while Clerk still says "You're already signed in". Do not
     re-run the whole login: `goto /select-workspace` and re-pick the workspace.
- **Ports:** 8030 and 8010 were held by long-lived uvicorn processes launched from the
  `istanbul` workspace (`PPID 1`). This audit used 3031/8031 rather than killing them. The
  design API is not needed for the AD0 empty state at all — the artifact read goes straight to
  Postgres.
- **The dummy runs.** `/Users/aryankeshri/Documents/clue-hq/clue-frontend` at `32658ff` serves
  its ad inspector at
  `/projects/10m-landing-page-campaign/artifacts/ad-1?kind=ad&edit=1&selection=<sel>`
  (`chat-shell-view.tsx:55`). Its own dock is 480px, so comparisons are like-for-like. Its
  inspector screenshots come out washed out in headless (an unsettled `.artifactWorkspace`
  opacity transition) — assert on the DOM, not the pixels.

## Deferred minors carried out of AD0

- AD0.1: `.layerRowAccented` renders the dummy's own `#007d83` fallback (the `-default` token is
  undefined in BOTH trees — parity by design; changing it needs a founder ruling).
- AD0.1: web-inspector review-menu tick compares raw `selection` — exact dummy parity at
  `32658ff`, not a defect.
- AD0.2: `inspectorSectionCompact` has no CSS rule in either tree — the compact prop renders a
  dead class token; dummy parity by design, founder ruling before any "fix".
- AD0.2: two orphan SVGs on disk (`size-chevron`, `unlock`) referenced nowhere — pre-existing.
- AD0.2: four active/open classes exist only as compound selectors — reparenting those elements
  later silently drops the styling (relevant to the §7 icon-family reconciliation).
- AD0.3: `RadiusCorner`/`RadiusValues` stay non-exported (verbatim); export when a consumer needs
  them.
- AD0.4 → **AD2.4**: `hydrated` carries static §2 defaults — reconcile when real hydration lands
  (single source of initial state).
- AD0.4 → **AD4.0**: Custom W/H are component-local `useState` — move onto presentation state
  when the `update_page` write lands; the local draft is not reset on a preset round-trip.
- AD0.4 → **AD3.1**: font-size "min 1" is not input-enforced — the apply adapter clamps at
  commit; `InspectorInput` stays a plain text input (dummy parity).
- AD0.4: the dummy layer tree still lists a "Button" row; clicking it now shows the Canvas
  schema. §2.7 hides the button *schema*; the layer list is scaffolding AD2 replaces.
- AD0.4: three export CSS rules are deliberately left unreferenced so Gate G-E's "restore
  verbatim" stays a pure JSX revert.
- **AD0.5 → AD2.7:** F3 (the ad-document 409 on `…/web/theme`) and F2 (the artifact route's
  missing ad dock — AD2.7 step 2).
- **AD0.5 → AD2.1:** F1 (feed widening + the `toProjectArtifact` type mapping).

## Method notes

- Browser work ran on the gstack browse daemon (headless, 1600x1000), per the founder's standing
  rule. Login: `onboarding+clerk_test_20260814@example.com` / `pass@123` / code `424242`.
- Because F1+F2 leave the ad inspector unmountable, the schema surface was proven the way AD0.4
  proved it: a temporary harness page mounting the real `ImageInspector` inside the real
  `.chatBody > .inspectorDock` at pinned widths (480/400/374). **The harness was deleted before
  the gate**, and the production build's route list carries no trace of it.

## Addendum 2026-08-20 (late): AD1.1–AD1.5 complete (paused before AD1.6 by founder instruction)
Commits 3d8ff650..933a4c8d. Vendor pipeline live (real wasm 813KB gz, stamp 7b992f8c6ec8); both
bundler configs proven load-bearing (turbopack failure was real → resolveAlias remedy); 26 engine
modules extracted (25 byte-identical + renderAdapter's D7 deletion-only pruning), 296 scene tests,
suite 1187/1187, env reads zero (guard proven non-vacuous). Key rulings: 8 (renderDiagnostics/
kitFonts/libraryFonts → AD1.6 — forward-import defects in the plan), 9 (wasm-gated tests → AD1.6),
11 (tsconfig target ES2020), 12 (fetch defaults → defaultDesignFetch — receiver-unsafe bare fetch
was a plan defect; class fully closed incl. wasmEngine:393). Ledger: .superpowers/sdd/
2026-08-20-ad-editor-integration-execution-plan/progress.md. Dev server :3032 may still be running.
