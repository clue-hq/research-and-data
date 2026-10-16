# Wave 2 integration on trenton — merges, test record, review

All four Wave 2 lanes (website agent on Puck) merged into `puck/integration-wave1` (trenton) on
2026-10-13. Lane notes stay the per-lane record (`_memory/2026-10-12-wave2-*.md`); this note is the
integrated branch's record: what was merged, every test run and every failure, and the review.

## Merges (base of every lane: `8c1aa9e47`)

| Merge | What | Conflicts |
|---|---|---|
| `f8fce07dd` | A9 complete (`w2/a9-task-16b`; carried Lane A ≤ Task 17) | none |
| `d46b38a91` | Lane A complete (tip `4f3e2eaf2`, through `w2/a-task-29`) | chat-surface.tsx, editor-surface.tsx — Lane C's site editing lock vs Lane A Task 28's publish lock; both kept |
| `1371a4810` | Lane B complete (`w2/b-task-19` = `6a8c2b467`) | lumen_api/main.py, write-path governance core list, 3 tool-count tests — unions (authority 150, design_* grants 62, registry 150 names / 175 addresses) |
| `ecdb283db` | A9 fix wave (`w2/a9-task-FX-A..FX-D2`, tip `e4ce90fdd`) — A9 reopened after `f8fce07dd`; found missing by review unit K5 | none |

Hand-resolved merges across all of Wave 2 (the only merge-written code): `c9a3c18d8`, `dda6790cc`,
`d46b38a91`, `1371a4810` (`git show --remerge-diff <sha>`).

After the merges: migration `57f948ca3545` (design_site_section) on clue_trenton; `.env` gained
CLUE_SITE_SECTION_LINK_SECRET (local random), CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES, LUMEN_SITE_KIT_DIST,
LUMEN_SITE_RENDER_CHROMIUM_SANDBOX, DEV_STACK_PAGES_PORT; helper rebuilt (engine `46678043d711`,
= both served wasm copies); site-kit + site-editor bundles built. Fixes made on the integrated branch:
`2ae9f44e0` (brand surfaces paint in the editor), `4d61f96ea` (site publish via `/site/publish`),
`843e36beb` (page origin on the checkout's own port; trenton 8049), `f29e0b418` (a test type error),
`639475541` (the inliner's shared cache — the site agent's render_page), `83734f598` (a stale Lane A test).

## How to run the Python tests without spending money

`clue_config.Secrets` reads `./.env` relative to the CURRENT directory and treats a blank value as
unset; `py_lumen_config` reads the repo-root `.env` by ABSOLUTE path and lets a blank env var beat it.
So:
- platform tests (run from the repo root): override every key that has a value with a dummy
  non-empty string (a call fails 401, nothing is billed);
- design tests (run from `subsystems/clue-design`, which has no `.env`): set those keys BLANK. A dummy
  key there switches on features gated on "a key exists" (the ingestion brief stage) and changes
  behaviour.
- run `apps/api/tests` and `apps/agent_runtime/tests` in separate pytest sessions — both hold a
  `test_site_tools.py`, and one session cannot collect both.
- use `-o faulthandler_timeout=240` and a per-file wall-clock limit: one design file can poll forever.
The review folder's `pytest-keyless.sh` does all of this.

## Test record (integrated tree, 2026-10-13)

| Suite | Result |
|---|---|
| frontend `npm test` | 3377 tests, 0 fail, 5 skip |
| frontend lint | 0 errors, 7 warnings (other lanes' files) |
| frontend `next build` | ok |
| site-editor | 37/37 + tsc clean |
| site-kit | 149 pass, 6 skip (need an extracted kit file) + tsc clean |
| Python platform, 33 Wave 2 test files | 461 passed, 4 skipped |
| Python design agent_runtime, 11 files | 83 passed |
| Python design api, 43 files (one pytest per file, blank keys) | 37 files green as run; after the fixes below every file green except three pre-Wave-2 failures (1, 4, 8) and the pre-Wave-2 hang (3) |
| real-browser editor tests (`CLUE_SITE_EDITOR_BROWSER=1`) | 4 passed (before the A/B merges) |

### Failures and their causes

1. `apps/api/tests/test_write_path_governance.py::test_converted_domain_mutations_are_only_called_from_the_toolbelt`
   — **predates Wave 2**: `lumen_api/asset_enrichment.py:51` calls `create_asset_record` outside the
   toolbelt, and that call exists at the base `8c1aa9e47`. Lane A lists it as known. Not fixed.
2. `apps/api/tests/test_a9_scenarios.py::test_scenario_1_…` — **caused by the first run's setup**, not the
   code: dummy keys made the brief stage run (LUMEN_INGESTION_BRIEF=1 + "a key exists"), the call got a
   401, the kit published briefless with LUMI090x codes, and the test (written for a keyless run) saw
   them. **Rerun with blank keys: 15 passed, 1 xfailed** (the xfail is A9's recorded known defect).
3. `apps/api/tests/test_api.py` **hangs** (hit the 900 s limit). The stack dump: an ingestion job on the
   embedded fleet worker sits in `lumen_api/ingestion_tasks.py:206 enqueue_and_collect` — a `while True`
   that sleeps until no `asset_analysis` task is pending, with no deadline; under test nothing processes
   those tasks, so the job never ends and the test's event-loop shutdown waits on it forever. **Predates
   Wave 2** (`ingestion_tasks.py` and both `asset_enrichment.py` are unchanged since `8c1aa9e47`); A9
   recorded the same defect as an out-of-lane chip. Not fixed (out of Wave 2's scope; needs a deadline or
   a stop signal in the wait loop). The hang then MOVED (test #12 on a rerun): the interrupted runs left
   design_job fleet tasks (4 claimed, 1 queued) and one `running` design_ingestion_job in
   clue_trenton_wave1, and each new session's embedded worker inherits them and waits forever. Marking
   them failed needs a write to the test database that the session's permission classifier refused —
   the founder's call. The one test Wave 2 added to this file (#23
   `test_logo_curation_keeps_the_kit_sections_the_engine_does_not_know`) passes run alone (with #22).
4. `apps/api/tests/test_api.py::test_reference_manifest_matches_config_contract_shape` — **predates
   Wave 2**: fails with the same assertion when run against the base `8c1aa9e47` (the asset record grew
   fields — usage, sources, asset_context, analysis_status, tags — and the test's contract shape did not).
5. `apps/api/tests/test_custom_component_publish.py` (4 tests) — **environment**: trenton had never run
   `npm ci` in `subsystems/clue-design/apps/custom-component-compiler` (no `typescript`). After `npm ci`:
   4 passed. The compiler package is unchanged since July.
6. **REAL CROSS-LANE BUG, fixed `639475541`:** `apps/api/tests/test_site_lane_b_scenarios.py` (4 failed) — the
   site agent's `render_page` (and every section shot) answered "the page could not be drawn (TypeError)".
   Lane B's screenshot port (`site_turn_ports.py`) calls `inline_asset_store_refs(..., cache=...)`, the
   parameter Lane A added for site export; Lane A Task 27 (`5565754b4`, no ZIP/PDF export) removed it, and
   Lane B's call was not on Lane A's branch. The keyword-only cache is back (each call still names every
   missing digest it met). New test in test_site_thumbnails.py (RED with the TypeError). Lane B
   scenarios 19/19.
7. `apps/api/tests/test_site_publish_routes.py::test_f_the_default_brand_loader_refuses_with_503` — **stale test
   premise, updated `83734f598`**: it relied on the app default being Lane A's `brand_loader_not_composed`
   stub, which Lane A's plan named temporary until Lane B composed the real loader. Lane B's
   `site_brand_loader_for` is now the default and the site publishes. The test installs the stub itself and
   still pins the 503 refusal. 18/18.
8. `apps/api/tests/test_workspace_seam_route_table.py::test_every_route_enforces_the_workspace_seam` — **predates
   Wave 2**: `GET /assets/upload-capabilities` (added 2026-09-21, `9cc82d08d`) answers a headerless request
   with 200 and has no ALLOWLIST entry; fails identically at the base.
9. Frontend type-check of TEST files (`npx tsc --noEmit -p apps/frontend`): 58 errors, all in test files
   and the vitest shim, all predating this merge; tests run through tsx, which ignores types, and the
   frontend gate (lint + build) does not type-check tests. Lane C's one (`site-save-controller.test.ts`)
   fixed in `f29e0b418`.

## The review (2026-10-13)

Review folder `.superpowers/review/2026-10-13-wave2/` (git-ignored): REVIEWER.md, 14 unit scopes,
reports, the controller's ledger (`progress.md`) and the verified list (`FINDINGS.md`). Bases:
`w2/review-base` (`7ee87b9fe`) for K1–K5; `w2/review-base-2` (after the A9 fix wave) for K6 and S1–S8.
Lesson: re-check every lane's branch tip for new commits immediately before tagging a review base — A9
reopened for a fix wave after its merge and the first tag missed 21 commits.
After the fix-wave merge: site-kit 167/173 (6 skip), site-editor 37/37, frontend 3377/0 fail, lint 0
errors, build ok; the fix wave's Python files and site render/publish/thumbnails/A9 scenarios green; Lane B
scenario `test_a_a_real_site_turn_end_to_end` updated for A9's new brand.md "classes" column (`ca2c66702`).

## 2026-10-14 — K units done, founder rulings, S units next
- All six contract units (K1–K6) reviewed and every finding verified first-hand: 35 open (3 Critical /
  18 Important / 14 Minor), 4 resolved by A9's fix wave, 1 duplicate (K4-4 = K3-3). Durable write-up:
  `docs/superpowers/verification/2026-10-14-wave2-contract-review-findings.md` (plain language; where,
  proof, fix direction per finding). The review folder stays the raw record.
- **K3-1 (founder):** no per-section isolation — decision D2 of 2026-10-09 stands (it rejected a sandbox
  per section). Take a simple fix now and harden later; WHICH simple fix is pending the founder. Do not
  re-offer per-section frames.
- **K4-2 (founder):** parked. Privacy and verification guards get a dedicated sprint after the basic
  layer works; K4-2 is not in this fix pass, and live site runs on trenton may proceed meanwhile.
- Next: verify S1's report, then S2–S8 two at a time (founder), each reviewed adversarially and
  thoroughly; then one fix pass, each fix test-first, then re-review the fix diffs only.

## 2026-10-14 — S units done; the whole review verified
- Area review complete: `docs/superpowers/verification/2026-10-14-wave2-area-review-findings.md` (every S
  finding in plain words, the cross-cutting analysis in seven groups, a suggested fix order, the privacy-sprint
  list and the unproven suspicions). Companion: the K write-up in the same folder.
- Before dispatch: a coverage check over all 474 Wave 2 files found ~4k non-test lines in no unit (folded
  into S3/S5/S6/S7/S2b); S2 split into S2a/S2b; REVIEWER.md gained S-unit rules (no cap, coverage table,
  verdict per ruling/focus/minor, prove C+I, privacy findings separate). Units ran two at a time, one
  test-DB user per pair.
- Totals: S = 60 (3C/18I/39M); with K's 35 open → **95 open (6C/36I/53M)**; K4-2 parked (privacy sprint).
  Controller re-grades: S2a-1 → Critical (matches S1-1), S5-1 → Important (controller found `require()`
  inlines host files into a section and render prints them).
- The six Criticals: K1-1, K3-1 (founder choosing the simple fix), K4-2 (parked), S1-1 (Puck's
  module-global resolveData cache resets clone slots across pages and saves), S2a-1 (⌘Z in a clone slot runs
  Puck's own history and saves an old page), S7-1 (Chromium sandbox can't start in the backend container
  under Docker's default seccomp: smoke.sh blocks every backend release).
- Blockers before any live walk / merge to main: S2b-2 (React StrictMode disposes the site save controller:
  NO site save works on any dev stack), S7-1.
- Next: the founder's calls (K3-1 fix, K1-7 wording, K6-4, S7-1 posture), then one fix pass in the doc's §5
  order, each fix test-first, then re-review the fix diffs; then the behavioural pass (must publish a site
  through the real route — S8: no automated test does).

## 2026-10-14 — editor sync fix (review group 1) implemented
Plan `docs/superpowers/plans/2026-10-14-site-editor-sync-fix.md` (founder approved the design: server
truth → app working copy with a revision counter → frame displays and proposes edits stamped with
their base revision; Puck's own state switched off). Commits `7242d51e3..0b9aed43d` (10 commits, after
the plan `cb24b14e3`), each test-first, each regression proven RED on the previous code:
- S2b-2 StrictMode (controller attach/dispose) · S2b-4 ordered queue, a landed step drops saves built
  before it, `requestReloadWhenIdle` · S3-3 routes report the produced version (all four) · S2a-1
  `keys.ts` (editable text → browser undo, else server undo, Dvorak/QWERTZ safe) + Puck history reset ·
  S2a-4 selection by id · S1-1 no clone `resolveData` · S1-2 blur only on real change · S1-4 redraw when
  HTML unchanged · protocol v2 (`rev`/`baseRev`) · K3-5 frame buffers updates while sections load ·
  K1-4/S2b-3/K3-3 `SiteWorkingCopy` + `loadDecision` + per-visit loads · K3-3 standalone reload only for
  others' writes (`siteReloadWanted`).
- Test harness: `apps/frontend/src/features/site-editor/hooks/testing/site-session-bridge.ts` — real
  session + real FrameController over an in-memory bridge (origin/window/nonce rules kept) + fake server
  with CAS and gates. Scenario test asserts canvas = app copy = server after every step.
- Gates green: frontend gate (design-system, lint 0 errors / 7 old warnings, build), app 3395/0,
  site-kit 170, site-editor 49, typechecks clean, browser harness 14/14 across 5 files, design API
  site write/publish/scenario files green. Lane C's harness speaks protocol v2.
- Gotcha: trenton's `site-editor/scripts/dev.ts` watcher rebuilds `dist/` on every source change, so a
  browser test always sees current source; to prove RED, swap the old file in, rebuild, run, restore.
- Owed: independent review of the fix diff (running), the live walk on trenton (no site document exists
  in clue_trenton; making one needs an agent run = founder's go), Phase 2 (instant undo) plan.
