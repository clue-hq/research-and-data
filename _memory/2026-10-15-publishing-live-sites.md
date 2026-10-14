# 2026-10-15 — Publishing live sites (founder direction) and review group 4.3

**Branch:** `puck/integration-wave1` (trenton).

## What happened
- Discussing review group 4.3 (editor vs published page), the founder learned published Puck sites are
  static (`renderToStaticMarkup`, sanitizer strips script/form/on*, CSP `script-src 'none'`). That was
  never their intent; it came from the isolation research line 235 turned into a hard rule by the
  integration plan's Contract 3, with no recorded founder ruling.
- Founder rulings 2026-10-15: whole-page hydration; sections may use handlers/state/effects/timers/
  window; guard by boundaries (page CSP: our endpoints + approved embeds, never the open web); forms and
  tracking in scope now (kit.Form, kit.track); PSL-listed pages domain required; kit.editing flag;
  keep refusing only eval/Function, dangerouslySetInnerHTML and brand rules; head/body snippets in scope
  now, CSP per site from snippet hosts, people-only, screen shows the hosts.
- Spec written: `docs/superpowers/specs/2026-10-15-publishing-live-sites-design.md` (awaits founder
  review; then writing-plans, one plan per phase).

## State of group 4.3
- Not started in code. The earlier per-finding fixes were re-cut into spec §13. Several earlier
  proposals assumed static publishing (e.g. refusing state/effects) and are void.

## Open decisions (spec §18)
Lead notifications (no email provider exists), leads/tracking screens (frames owed), first embed
providers, spam protection, whether K1-3 joins group 4.3.

## Still open from 2026-10-14
Group 4.5 (K3-6, S4-1 needs a migration OK, S4-3, S7-3, K3-7); now a prerequisite for production live
publishing (spec §12).

## Decisions later the same day (spec §18)
- Leads/tracking screens: founders design later; features built now. Embeds: Calendly, HubSpot,
  YouTube, Vimeo, Loom, Wistia. Lead email: yes, to workspace admins, via an outbox + background
  sender; email service not chosen yet (founder creates the account). Spam filtering: none now,
  Cloudflare Turnstile when needed (route keeps a size cap + rate limit only). K1-3 joins group 4.3.
- Scope of this round (founder): phase 1 live core (most important), phase 3 embeds, phase 4 snippets,
  phase 5 group 4.3 + K1-3, and the pages-domain prerequisite (group 4.5 + move). Phase 2 (forms,
  lead email, tracking) deferred to a later round — email service choice therefore not needed yet.

## Later 2026-10-15 — plan, group 4.5, first group 4.3 fixes
- Phase 1 plan written from code reads: `docs/superpowers/plans/2026-10-15-publishing-live-sites-phase-1.md`
  (12 tasks; Task 1 is a go/no-go hydration spike; skill text and the publish refusal wording stop for
  founder review). Execution method not chosen yet.
- Group 4.5 fixed by an Opus implementer, verified first-hand (diffs read, tests re-run): S4-1 `35c7d041d`
  (migration `abf95e465478`, single head; applied ONLY to the test DB `clue_trenton_wave1` — the lane DB
  `clue_trenton` needs `alembic upgrade head` before the stack runs this code; no duplicate labels there),
  K3-6 `c89572925` + runbook `f151c3407` + Worker comment `43c3a7c94`, S4-3 `58f9993bb`, S7-3 `c55287d17`.
- Group 4.3, architecture-independent fixes: K5-2 `4dc4ca79c` (one themeBlock for editor and publish),
  K1-2 `7508b3d0d`, K1-3 `935b115b8`, S2b-8 `84bea4ed4`, S6-2 size half `73e96999a` (icon drawn at stored size).
  Deferred to the live spec: K2-1 (phase 1 Task 2), S1-5, S2a-2, S6-2 colour, parity test (phase 5).
- Review docs: 62 open (1 Critical parked, 19 Important, 42 Minor).
- Pre-existing, not ours: `npx tsc --noEmit -p apps/frontend` reports errors in old test files
  (design-editor engine tests, brand-context, workspace-switcher); the gate is lint + build.

## Closing — phase 1 built (2026-10-15)
Plan `docs/superpowers/plans/2026-10-15-publishing-live-sites-phase-1.md`, 12 tasks, executed task by
task (Opus implementers, reviewed per task; ledger `.superpowers/sdd/2026-10-15-publishing-live-sites-phase-1/`).
Workspaces on `LUMEN_SITE_LIVE_WORKSPACES` now publish live sites: one tree for server and browser, the
site runtime + shims + sections as publish files under one hashed import map, checked (never stripped),
`delivery: site_live`, served by the page origin under its own policy; interactive agent sections
(state, effects, handlers, timers) with eval/raw HTML/cookies/foreign elements still refused; one error
boundary per agent section; the agent previews the page alive and has the approved
making-a-section-interactive skill. Other workspaces are unchanged (static, stripped).

Commits (`git log --oneline abf0c53c5..HEAD`, oldest last), plus the Task 12 records commit on top:
f02340713 site agent skill (making a section interactive, founder-approved) · b94431dec live preview loads
the runtime as a data: module · 2d1edc166 live previews + interactive sections in live workspaces ·
eb883bc07 one error boundary for agent sections · 28dbb8d58 kit.editing · 2e3858fd2 interactive sections
lint · 938906a45 design API publishes live sites (real-browser proof) · 7d5b869ed page origin serves live
pages under their own policy · 1f97769c9 CSP meta before the import map · fd3818bd9 live site package ·
280560b74 live site policy · 7b586e706 site runtime + shims + live render check · fbe5501a3 the live page
· a23b15240 one definition of section imports (K2-1) · c0c466460 hydration spike.
Task 12: the backend image's smoke check now also requires `dist/site-runtime.js` and
`dist/site-runtime-shims/react.js` (red→green in `tests/deploy/test_backend_image.py`).

Gate (Task 12, all green): frontend design-system:build + lint (0 errors, 8 warnings — one new in this
phase: unused `_shell` param in site-kit `live-page.tsx`) + build; `npm test` 3431 pass / 5 skip;
site-kit tests 197 pass / 6 skip (A9_SCENARIO_KIT env-gated) + tsc; site-editor 64 pass + tsc;
`tests/site_editor` (browser) 21, `tests/page_origin` 34, `tests/deploy` 283, `tests/design/test_publish_delivery.py` 9;
design files one at a time all pass (site_render 41, publish_package 24, sanitize 9, live_browser 1,
publish_routes 18, site_kit_cli 10, turn_ports 15, turn_executor 14, thumbnails 13, lane_a 9, lane_b 19);
agent runtime site tests pass (harness 25, workspace 15, tools 12, render_tool 5, sections_tool 5, package 4).
Ruff: root-config files changed this phase are clean; `subsystems/clue-design` is outside root ruff
and its phase-added lines follow the files' existing long-line style.
Pre-existing, not this phase: `test_write_path_governance.py` fails 1 on `asset_enrichment.py:51`
(neither file changed since abf0c53c5).

Owed:
- Founder approval of the publish-refusal wording `_UNSAFE_MARKUP` in `lumen_api/site_publish.py`
  (committed as drafted).
- Two proposed base-prompt lines for live workspaces (name the skill in "How to work" step 1;
  render_page's hydration notes) — proposed in chat, awaiting the founder; not part of the plan.
- Lane DB: `alembic upgrade head` on `clue_trenton` before the stack runs this branch (S4-1 migration
  `abf95e465478` is only on the test DB).
- Live walk (founder-triggered; live agent runs spend money): put one workspace on
  `LUMEN_SITE_LIVE_WORKSPACES`, restart the design API and workers, ask for an interactive section,
  publish, open the published page in the in-app browser and click it.

## Phase 1 closed (2026-10-15, SDD)
- 12 tasks done with Opus implementers, every task reviewed by the controller; final whole-branch review
  found F1 (live screenshot had no hard deadline — fixed `ea5271a10`), F2 (unused param, `c7c096db8`),
  F3 (readable hydration notes for the agent, `74846787f`). Late Task 3 fix `eb883bc07` (one error
  boundary in site-kit; the editor's failed-section marker restored). Founder-approved skill
  `f02340713` and live-only prompt lines `0de710806`. Range abf0c53c5..ea5271a10.
- Still owed: founder OK on the publish-refusal wording (`_UNSAFE_MARKUP`, committed as drafted); the
  in-app-browser walk (needs: `alembic upgrade head` on lane DB clue_trenton, a workspace on
  LUMEN_SITE_LIVE_WORKSPACES, a stack restart, and — for an agent-written interactive section — one paid
  live run). Rebuild site-kit (`npm run build -w @clue/site-kit`) wherever the stack runs.
