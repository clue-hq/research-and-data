# Proxon 1:1 landing pages (Q2, Betterment) — hand-built and seeded to production (2026-10-15)

## What exists now (production, Proxon workspace ws_fdda197a24aa4a798f7032c4f0e8210e)
- Documents: Q2 `doc_3acd148e378148649430b8f4d186fa87`, Betterment `doc_0ea93cbf14004960b28e83f556f48e26`
  (web docs, kit brand_kit_ing_3de766394479443eb7a239f05c494ff8 v1, account_id stamped to the design_account rows).
- Open at app.cluehq.ai/projects/prj_5742c57f51e454369d2ee5b51ebcd644/artifacts/<doc id>; listed on /artifacts.
- Gallery link: two design_leg_document rows on the CLOSED Betterment ad leg 5bdbf7b2-… (positions 1, 2).
  Deliberately not the open Q2 leg (an open leg's next turn could fan a design run onto the page).
- 21 new design_web_fragment rows + 35 artifact blobs (source_key seed:proxon_abm_pages_2026_10_14).
  Verified: both renders 200, 41 font URLs + 2 logo images per page all 200 via design-public proxy.

## How it was built (Claude drove the web agent's own tools by hand, local lane DB clue_nashville_proxon)
- Driver patched only harness_web.run_deepagent_web_turn; tools = LumenWebTools; ledger saved via
  POST /documents/{id}/web/operations. Scripts live in the session scratchpad (not in the repo).
- Page: campaign header shell (variant: supplied PROXON wordmark + account logo baked) → Proxon hero
  (repair) → priorities (variant of "AI adoption is exploding") → how it works (repair of "AI is already in
  the building") → proof (composed, numbered-row anatomy) → offer (variant, YC/Bookface line removed) →
  campaign footer (variant, PROXON wordmark). Logo strip dropped by founder call.
- Copy: landing-copy/{q2,betterment}-landing-page-copy.md, shortened per founder approval. Account names are
  hard-coded (NOT {{account.name}} markers) — time call.
- Logos: Q2 = founder-supplied SVG; Betterment = logo-ladder light_lockup; Proxon = founder-supplied wordmark.

## Platform defects found (unfixed, worth owning)
- Every captured Proxon fragment's root CSS carries `min-height:100vh` (body rule rewritten to the wrapper)
  → each pinned band is ≥ one viewport tall; short bands leave dead space. Fixed per page by raw repairs.
- Raw-lane repair/compose with a clone's *scoped* CSS (as inspect_cloned_section hands it) keeps the OLD
  `.lumen-frag-<id>` prefix → colour variables never reach the new fragment (blue accent + buttons vanish).
  Workaround: rewrite the old class to `:root` before passing CSS (cssscope maps :root to the wrapper).
- inspect_cloned_section truncates CSS at 12k chars; the real sources are ~100k, so the agent cannot remix
  a band faithfully from what the tool returns.
- repair_cloned_section refuses a CSS-only change as `fragment.repair_unchanged` (compares HTML only).
- mint_campaign_shells needs apps/editor node_modules (Tailwind toolchain) on the worker.
- Proxon sections are light by default; dark only under a `data-theme="dark"` wrapper inside the fragment.

## Not done
- Publishing to a public URL; per-account derive with markers; Proxon kit primary logo still the "P" mark.
