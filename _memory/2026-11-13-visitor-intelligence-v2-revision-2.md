# 2026-11-13 — Visitor intelligence: WVI-5 v2, revision 2 (design only, no code)

- Doc: `docs/specs/WVI-5-v2-visitor-intelligence-on-puck-sites.md`, rewritten to stand on its own and to
  explain why each piece exists (§4 is the step-by-step mechanism). Re-checked on `origin/main @ cc31d0f91`.
  It cites files and functions, not line numbers.
- Founder rulings 2026-11-13 are D1-D25 in its §9. The ones that change scope: every published site is
  tracked and the live setting stays as it is (D1); old-engine pages are not supported (D2); page views are
  counted at the edge from day one (D3); clicks are recorded on every named element, once per click, with a
  link-or-button flag (D5); Slack is its own sprint and branch (D7); no custom-domain warning or push (D8);
  this design replaces the live-sites spec's unbuilt tracking (D9); two-part build, part 1 everything but
  screens with a throwaway test page, part 2 the screens (D21); Head of ABM tool in part 1, website agent
  summary in part 2 (D13).
- Also edited: a superseded note in `docs/superpowers/specs/2026-10-15-publishing-live-sites-design.md` §7,
  and the planned cookie exception in `docs/specs/pages-hosting-runbook.md` §9 step 10 (D10).
- Open items O1-O5 in the doc: screen frames from the co-founder; QR link format with the direct-mail work
  (branch `codex/illumio-usbank-demo`); the consent prompt on Clue pages (ruled the same day, D25: Clue pages show
  their own prompt where consent must be waited for; mechanism in part 1, designed prompt in part 2; its wording and look are
  still open); confirm `LUMEN_SITE_LIVE_WORKSPACES=*` on every publishing
  process; the details marked "(proposed)".
- State at hand-off: committed locally on `docs/visitor-intelligence-v2`, cut from `origin/main`, not pushed.
  No code has been written. Next: the founder reads the doc; then a part 1 implementation plan.
- Found on main since revision 1 (2026-10-18): page origin and edge Worker unchanged; header and footer are
  ordinary sections (`header`, `footer`); nearly every section part carries an element name; published
  pages lock `document.cookie` (`site-kit/src/cookie-lock.ts`); CRM integration through Composio with
  writes; Head of ABM v87, recipe 47; last fleet kind `crm_write`; migration head `802fa1e6c449`.
