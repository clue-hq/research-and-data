# 2026-10-19 — site render failed on 'unsafe-eval' (Oliver's site, Conduit doc_ce85194b…, v116)

**Root cause (proved):** the design API's render page runs the site-kit bundle through Playwright's
`add_script_tag`; Chromium lets eval through while that DevTools call runs (and its microtasks), not
after a real wait. zod 4's `allowsEval` probe ran during that window → "yes" (cached); after the
agent sections' `await import(data:)`, zod's first fast-parser compile (`new Function`) hit the page
CSP (`script-src 'unsafe-inline' data:`) → render.failed. Hit any site with ≥1 agent section (even
pinned-unused) AND a measured kit (`responsive_type`, 10-18) or any inspector `_edits`. The unused
PlainLegalFooter pin on Oliver's site was incidental. Repro: plain page with the same CSP — eval
allowed sync/microtask inside add_script_tag, BLOCKED after setTimeout / import(data:).

**Fix (founder go 2026-10-19, both):** `site-kit/src/jitless.ts` (`z.config({ jitless: true })`,
export `@clue/site-kit/jitless`) imported FIRST by render-browser.tsx, site-runtime.tsx (published
page) and the site editor's main.tsx (its own copy deleted). Tests watched RED→GREEN:
`test_site_render.py::test_an_agent_section_renders_beside_a_measured_kit_and_an_element_edit`,
`test_site_live_browser.py::test_the_published_page_never_asks_to_evaluate_a_string`.
Checks: test_site_render 49/49, live browser 3/3, site-kit 410, site-editor 127, editor browser 65,
lint + tsc clean; Oliver v116 renders as saved (456104 chars). Not pushed.
