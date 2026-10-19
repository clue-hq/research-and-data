# Discovery excludes the seller's existing customers (2026-10-16)

Branch `feat/discovery-excludes-customers` (from main bb70d8003), 14 commits, LOCAL, not pushed.
Spec docs/superpowers/specs/2026-10-16-discovery-excludes-seller-customers-design.md (founder-approved,
incl. §4.7 skill wording); plan docs/superpowers/plans/2026-10-16-discovery-excludes-seller-customers.md.

## Founder rulings
- No saved customer table; the agent decides who is a customer; list lives in brand context
  (`proof/customers.md`, body only). Head of ABM fills `exclude` on every discovery call; code enforces.
- Seller's own domains always excluded. Agent per-company customer check and cross-project rejection
  memory are NOT in this piece.

## Evidence (live, playground)
- Exa /search deep: Conduit 17/29, $0.025. Exa Agent xhigh: Conduit 28/29 (+Beckon, Hilton, Fairmont;
  wynwoodhouse.us = wrong company), Alt Carbon 13/15 (+John Good Group; missed Frontier, Mitsubishi;
  BCG/LGT/SwissRe/UBS weak NextGen mentions). $1, ~4-5 min each.
- Manual Alt Carbon reference: Microsoft (only in PR), MOL, NextGen, Frontier, Mitsubishi(?), Celonis,
  Climeworks, CEEZER, Cur8, Shopify; via Frontier: Stripe, Google, Meta, Watershed/Match.

## What shipped (code)
- Migration ddf063300a0b: onboarding step/run kind `customers`; disposition `excluded_by_brief` +
  `excluded_by_entry`.
- Onboarding: background `customers` step (CLUE_ONBOARDING_CUSTOMERS_EFFORT=xhigh), domain check
  (customer_domains.py, PublicMediaTransport), `proof/customers.md`; `customers` run kind;
  scripts/backfill_existing_customers.py (dry run default).
- Discovery: `launch_arv2_discovery@3` with `exclude`; driver skips excluded + seller domain
  (latest full onboarding run's company_domain) at tick/search/verify, records excluded_by_brief,
  summary counts + Import line; Exa Import (CLUE_ARV2_DISCOVERY_IMPORT_WAIT_S=120).
- Head of ABM v72, stage0-interview v45, manual v18, recipe0-stage0 v35; toolbelt default @3.

## Owed
- Task 12 live check (~$4, founder go): customers run for Conduit + Alt Carbon, one discovery each;
  confirms Import CSV identifier (1 vs 0), per-item grounding for the Source column, Import cost.
- Deploy order: migration, workers, then API (old worker refuses a brief with `exclude`).
- Deferred minors listed in the final message (path URLs in exclude, whitespace label, finish
  failure discards result, sequential checks, Import retry/Stop, pending-row overwrite, backfill
  crash window, signed URL in raw).
- Pre-existing red: tests/arv2/test_import_guard.py (project_documents → knowledge_bytes).

## Live check 2026-10-16 (nashville stack, arv2 test account)
- Customers pages v2 written (Conduit 32, Alt Carbon 17); live fixes in 3348154c7.
- Agent traces: Head of ABM v72 reads proof/customers.md (needs ~10 rounds + run_python to parse the
  table; it called the file "a large YAML document"), excludes `direct` rows + seller, leaves
  weak_mention (Fairmont, Hilton) out of `exclude`. A 14:01 Conduit turn launched with no exclude
  because the first customers page was still being written.
- Conduit (search source): 31 excluded entries, 10 added, $0.39, no customer surfaced.
- Alt Carbon run 1 (websets): Exa returned Google + Microsoft, both `excluded_by_brief`; 1 added, dry.
  Wake turn relaunched once (search source, 4 searches = 1 + 3 top-ups, round_cap, $1.40, 1 added,
  27 gate-excluded), then stopped and asked before widening. No third run.
- BUG FOUND + FIXED (24ec92dfb): Import sent csv identifier 1; Exa counts columns from 0, so every
  Import completed with count 0 (0/24 read; 24/24 at identifier 0, reproduced with our import_csv
  bytes). Now identifier 0; get_import -> ImportStatus(status, count); an empty completed Import is
  not attached (brief_import_unavailable guard); summary reports Exa's count.
- Owed: one websets run on the fixed code to prove Exa itself keeps the customers out (Import count
  should equal the domains sent; excluded_by_brief should then be ~0 for customers).
- Probe Imports left in the Exa account (titles "identifier probe*", "confirm identifier*"); harmless.
