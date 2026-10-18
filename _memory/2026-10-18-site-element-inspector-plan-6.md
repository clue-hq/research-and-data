# Site element inspector plan 6 (headers and footers as templates) — 2026-10-18, trenton, site/publish-durability

Design docs/superpowers/specs/2026-10-18-site-header-footer-templates-design.md; plan
docs/superpowers/plans/2026-10-18-site-element-inspector-plan-6-header-footer.md (R1–R13).
Ledger .superpowers/sdd/2026-10-18-site-element-inspector-plan-6-header-footer/progress.md (deleted at the end;
its rulings and deferred minors are in the final message and below).

## Built (local commits, not pushed)
- shell.json = {header:{type,props}, footer:{type,props}} drawn as the page's first/last sections everywhere
  (pageWithShell / withEditedShellPage); SiteHeader/SiteFooter rewritten (every word editable); the menu follows
  the site's pages (menu._home / menu.<name> / menu._<n>, menuLabels, menuExtra); sticky/overlay on the header's
  root _edits; panel Header group; templates first in the catalog.
- Templates derived deterministically (lumen_api/fragments/site_templates.py) from the kit's captured nav/footer,
  minted through the fragment door and released at once (mint_site_template / mint_site_templates; ingestion hook
  LUMI0548; backfill subsystems/clue-design/scripts/derive_site_templates.py, dry run default, --apply).
- Final review fixes I1–I7 (I3 founder option a: an inline-SVG seller logo becomes the kit's logo file, primary
  else wordmark, so it can be replaced).
- Site agent fetch_logo (Brandfetch + logo ladder through the request start's own fetch and cache, stored as this
  workspace's blobs, kind account_logo); the turn's check now passes held workspace images as siteImages like the
  save does.

## Live check 2026-10-18 (lane trenton)
- Templates minted for Garner (ws_c080…) and Conduit (ws_3c96…). One agent turn each: "Start the header and
  footer from the brand's templates" — both saved ClonedSection header+footer from the templates.
  Oliver's agent called fetch_logo (found Embassy Suites / AC Hotels portfolio logos, rightly left them out).
- Editor walk on Oliver: account-line word typed + bold, sticky, overlay, 70% fill (canvas + published page:
  sticky top 0 after 1200 px scroll, first section starts under the header), seller logo replaced from the
  Library and put back, account logo shown + replaced from the Library; all undone (stored shell == agent's v85).
  Carmel: Garner's logo (kit file) replaced from the Library and put back (I3 proven).
- Found and fixed (tests first): L1 a template marked its source band superseded (raw nav/footer left the
  catalog); L2 a re-made template listed twice; L3 account line squeezed on desktop / menu-drawer row on phones /
  very wide account logo overflow; L4 an unchanged re-mint refused; L5 Garner's .nav_bg covered the account parts
  on phones; L6 no ellipsis / 12 px overflow on phones. Templates re-minted (Garner header frag_fd4ecde006d438a3,
  Conduit header frag_25c03a77b1b9cf16); the two sites still pin the first templates.
- Pre-existing (same on HEAD, stack up): test_agent_cloned_sections::test_approving_the_kit_turns_the_same_refusal
  _into_a_pin, test_campaign_shell born_draft / released_by_the_kit — re-run with the stack down.

## Open
- Prompt + images-and-logos lines (shell.json, account logo, fetch_logo) written but UNCOMMITTED (founder rule:
  skill changes wait for trials); the live turns above ran with them.
- Panel shows the stock image-preview.png for clone image slot fields (existing display quirk).
- On phones the seller's own CSS hides its header button (ruling: keep the seller's phone behaviour).
