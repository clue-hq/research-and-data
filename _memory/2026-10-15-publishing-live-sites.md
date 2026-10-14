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
