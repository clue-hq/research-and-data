# Conduit Fresh native onboarding and website test

- User authorized a new empty Conduit workspace, fresh full brand/onboarding capture, then a Conduit-for-Hyatt page generated through Clue's normal chat/design agent. Preserve the original four workspaces, stopped discovery, and old drafts. No remote push or finished-page/assets seeding.
- New workspace Conduit Fresh runs at localhost:3020 using the official local frontend manager, existing platform APIs/workers, local database/storage, and the user's existing membership. IDs and operational receipts are in ignored `.local-setup/conduit-fresh-native/`.
- Preflight found no onboarding-start control for an additional provisioned workspace. The user explicitly approved scoped server-side Clerk session-token retrieval after automatic approval review initially rejected it. Clerk-issued BAPI tokens lack the origin claim required by Clue; no auth bypass, token persistence, or token disclosure occurred. This route was abandoned.
- Fixed the native setup screen's missing-website recovery instead. A typed missing-domain error offers a company URL field; its normal repository posts through the authenticated BFF. No provisioning/auth/contract changes. Double-click latch and retry regression test failed before implementation, then passed. 27 focused checks passed; full frontend design-system build/lint/build passed with two pre-existing unused-helper warnings.
- Browser-submitted conduit.ai successfully started one normal onboarding run and one ingestion job at 00:03:56 local. Auto-discovery true; six pages selected. At 00:05 capture was on page 2/6; lineup/reviews/catalog completed, overview running. Capture quality, kit approval, and native website generation still pending.

- Fresh brand capture succeeded after roughly 14 minutes: homepage, Agents, Inbox, customer index,
  and two customer stories; 40 reusable sections, none marked degraded. Approved the kit through
  the native UI; all 40 sections released. 110 raster renditions are at least 1000px on one side.
  Tiny tracking/utility assets are still registered and should not be counted as usable artwork.
- The research branch completed all 15 persisted steps/documents, but its aggregate failed when
  catalog aliases resolved to the same product and attempted a duplicate research-step key. Fixed
  stable product-ID deduplication (0495b025); 45 focused checks passed, including an isolated DB
  red/green regression. Do not reset the failed record or claim an end-to-end onboarding pass.
- Submitted a normal Home chat request in Conduit Fresh for a Conduit-for-Hyatt website. Clue's
  own Head of ABM handed it to the native design agent; no separate page implementation or asset
  seeding. First design run completed with warnings and saved version 1. Trace confirms fresh kit,
  12 successful skill reads, six captured sections pinned/rebound plus composed campaign header
  and footer. Desktop visual inspection confirms the Agents aurora hero, original typography and
  product visuals. Native mobile preview is readable; render checks report no horizontal overflow.
- First-page gaps: Hyatt corporate logo absent after provider loyalty-mark mismatch and official
  fallback failures. A generic optional /brand 404 abort bug is being fixed/tested separately.
  Browser inspection also found two lower Learn more links still relative to localhost/book-demo,
  despite the agent's report that every CTA was corrected. Require a native follow-up and verify
  actual links; do not equate agent self-review or succeeded runtime status with full acceptance.

- Fixed optional official-brand-page failures in the generic logo ladder (2c5cfbeb): missing
  optional /brand pages no longer discard previously discovered valid logo candidates. Focused
  logo/transport checks passed; loaded into the four owned idle workers without restarting APIs
  or frontends. Native follow-up fetched and inspected Hyatt's real corporate wordmark from its
  official investor site, then saved page version 2 with balanced Conduit/Hyatt header.
- Version 2 preserves the captured Agents atmospheric hero, fonts, visuals and six source bands.
  Desktop/mobile rendered inspection confirms the header and layout. The model's report calling
  three engine tiles empty was wrong: those lazy images appear when scrolled into view. Do not
  treat the compressed full-page screenshot alone as evidence that captured assets are missing.
- Native agent could not safely fix the two unbound hrefs because source inspection stopped at
  12k characters; the section has 42,268 HTML / 195,384 CSS characters. Added bounded independent
  source pagination (fc021090, 78 focused tests). Pagination alone does not make a tiny link edit
  efficient. A supervised bounded exact-anchor repair is in progress: retain immutable source,
  CSS/assets, pin bindings and human overrides; mint through existing workspace-scoped lineage.
  Existing raw repair re-pins with empty bindings and scopes already-scoped CSS again, so do not
  use it as a blind wrapper. Page version 2 still has two localhost/book-demo links until the
  new capability passes tests and Clue itself completes a native correction.

- Completed exact-href capability in e06071b2. Parent reviewed production diff and caught
  nested CSS namespace and degradation-preservation cases. 215 offline checks passed;
  65 existing fragment persistence/repair DB checks passed on the earlier disposable DB.
  The first DB attempt hit sandbox socket PermissionError; explicit isolated rerun passed.
  Reloaded only four recorded idle fleet workers; APIs and frontend instances stayed up.
- Final normal chat correction succeeded in 102.8 seconds and saved native page version 3.
  Trace confirms the updated repair/edit skills were read and one exact-href repair called.
  Three inherited /book-demo values changed in one derived fragment; the existing explicit
  CTA binding remained authoritative, so this fixed the two remaining bad destinations.
  No image generation, independent page implementation, or manually seeded source assets.
- Closing verification: native browser shows version 3, all nine rendered CTA destinations
  point to the official Conduit demo URL, and the repaired band retains its desktop/mobile
  styling and product visuals. Restored desktop hero view and kept the native tab available.
  All five frontend listeners and three shared API listeners remain reachable. Receipts live
  in ignored .local-setup/conduit-fresh-native/; source originals and earlier drafts retained.
  No remote push. Remaining limits: full research aggregate rerun after alias-dedup fix is
  not live-verified; tiny utility assets still clutter the library; this one-brand native
  acceptance is not a cross-brand production quality guarantee.
