# 2026-09-29 — research page cleanup (founder ruling)

Removed from the account overview / insights / contact pages and drawers (no replacement UI):
- per-sentence tags ("Needs verification", "Interpretation", "Research gap", "Source quote"),
  qualification suffixes, per-section gap lists, the research-quality banner
  (`research-quality-notice.tsx` deleted), committee/contact membership tags, "Unverified"
  influence (an unknown influence renders "—"), popover extras (report excerpt, qualifications,
  seller passages). Frontend = pre-`6541ecc6d` presentation; functional bits kept
  (project-aware links, outreach-ineligible mailto, supporting-claim popover evidence).
- backend: "All research findings", the Watch-outs → "Research notes" rename, unknown-key
  sections and read-time `annotate_sentences` are gone (`quality_pages.read_page`). Recipes'
  `restricted` flags are honoured again (Watch-outs hidden on overview, Context only in Insights'
  Internal notes — kept by founder answer "keep watch-outs like it was before").
- Insights "Contact insights" section removed (recipe + prompt; migration `5e1c0a9d7b24` deletes
  the stored recipe row, renumbers Context only=4 / Miscellaneous=5).
- A `*.research_finding` no live block of that subject cites (any page, same generation) and not
  `invalid` → an item in that page's Miscellaneous (`quality_presentation.uncovered_findings`;
  insights for accounts, contact page for people; overview has none). Object findings render
  their text values as sentences, never JSON.
- Custom rail excludes agent-registered research fields (`promoted_by LIKE 'agent:%'`).

Not changed: the narrative skills (account/person-research-narrative v2) still mention Contact
insights — they are hash-pinned in launch-v4-r23/r24, so a wording fix needs a new launch version.

Verification: focused DB suites green (advisory, owned-narrative, pages, send-line, recipes,
blocks, page_db, runner, account_workspace, new custom-field test); migration down/up on the test
DB; frontend lint + design-system build + next build green; accounts tsx tests 175 pass, 5
Zafran-fixture failures pre-existing (they import none of the changed files).
Owed: founder's browser check of overview / insights / contact pages and drawers.
