# Discovery enriches firmographics from AI Ark (2026-10-27)

Branch `feat/discovery-enrich-firmographics` (from main `9b6927b52`). Founder ruling 2026-10-27:
the target-accounts table's company facts (industry, revenue band, headcount + range, HQ,
LinkedIn, Twitter) are filled by discovery from AI Ark, not by deep research.

## Built
- `AiArkClient.companies_for_domains(domains, max_pages)`: one `/v1/companies` search per round,
  pages of 100 (0.1 credit/record), cap `CLUE_ARV2_DISCOVERY_FIRMOGRAPHICS_MAX_PAGES` (10; 0 = off).
- `arv2/discovery_firmographics.py`: `resolve_company` (the strict rule: on the account's domain
  by AI Ark filing OR the record's own website; <5-staff pages set aside when several; exact name
  match after case/accents/punctuation/&/suffixes; ties → homepage website, then staff; else none),
  `firmographic_drafts` (deep research's mapping, cut to the 8 table fields, stamped
  `account_discovery` + `resolved_by`), `ai_ark_firmographics_on_file`.
- Discovery driver enriches each round's landed accounts after the round (best-effort).
- Deep research (`company_lock`, v1 `_lookup_company`) keeps its AI Ark call but skips fields
  already on file from AI Ark.

## Trial / live evidence
- Manual trial: 135 real companies (Garner + Conduit + a fresh 43): strict rule 0 wrong picks.
  AI Ark files a group with each of its hotels/schools under one domain (Wanda 52, Millennium 90);
  biggest page is not the parent; parent websites can carry a route (Shangri-La `/group`).
- Live discovery on nashville (Garner "US employer benefits"): 3 rounds → 3 searches, 6/7
  resolved; eHealth missed (filed under ehealthinsurance.com, website eHealth.com) → website
  rule added `de2dfee9d`. Second run: 2/2 resolved.
- Deep research live (Savannah River Nuclear Solutions, single AI Ark record): company_lock
  saved legal/founded/type/tech facts as `research:provider_record` but NONE of the 6 table
  fields discovery had (v4 saves AI Ark facts under `research:provider_record`, filtered before
  the write). PlanSource (2 records) never reaches the save, as before.
- Revenue (founder 2026-10-27, "take whatever band AI Ark has"): AI Ark's range is now saved as
  `core.annual_revenue` `{amount_min, amount_max, currency: USD (assumed, marked), as_of:
  last_updated, estimate_kind: provider_estimate}`; the field's schema gained `amount_min`/`amount_max`
  and `amount` is no longer required (validator has no anyOf) — migration `802fa1e6c449`. The accounts
  table reads annual revenue first (as the account page does), then the band. The band rule also read
  a range's top as the next bucket (AI Ark `5M-10M` → refused); a range's top is now its bucket's edge.
  `core.annual_revenue` is a discovery field, so deep research skips it too.

## Owed / notes
- `tests/arv2/test_quality_relationships_db.py` fails on main too (not this change).
- Tests that build `Secrets`/`Settings` from env must run with only `CLUE_DATABASE_URL` set.
