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
