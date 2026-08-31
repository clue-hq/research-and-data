# Stage-0 company pin and client-target exclusion fixes

**Date:** 2026-08-16
**Branch:** `platform/integration-onboarding-pilot`
**Status:** implementation and focused verification complete; browser journey resume remains

## Defects closed

- `Stage0StepPinProvider` incorrectly combined the selected product id with the account-wide
  `client_kb_version`. In the live company-v2/product-v1 state this requested the nonexistent
  resource `client_kb:<client>|<product>@2` and prevented `synthesize_icps@2` from running.
- FI-2 target-account reads treated the `workspace_client_binding` account as an ordinary prospect,
  so Insight Health appeared as its own target before discovery produced any real account.

## Implementation

- Trusted Stage-0 v2 tool pinning now freezes the account-wide company Client-KB as
  `client_kb:<client>|-@<company-version>`. The confirmed product remains a separate exact product
  pin. Product-KB retains its independent version and is not invented as a synthesis requirement.
- The Accounts list/count/page queries exclude the workspace client binding.
- Account detail and account-scoped Contacts return the existing tenant-safe `ACCOUNT_NOT_FOUND`
  envelope for the client identity, including a merged id whose survivor is the client.
- Composer validation refuses both the client account and contacts belonging to it.
- Account bulk membership actions treat the client identity as ineligible.
- The project API contract and Stage-0 scope comments now state the ratified independent company
  and product version policy.

## Verification

- Created the isolated database `clue_fix_stage0_accounts_20260816`; existing databases were not
  reset or modified for migration setup.
- New regression proves company Client-KB v2 plus selected Product-KB v1 resolves as company
  `client_kb:<client>|-@2` plus the exact product pin, with no fabricated Product-KB pin.
- New regressions cover list, detail, Contacts, composer context, and bulk action exclusion.
- Full touched-suite matrix: 103 tests passed across product selection, Accounts list/detail,
  Contacts, bulk actions, and composer context.
- Ruff passed for every changed Python file; mypy passed for all changed production modules;
  `git diff --check` passed.
- The machine's default `clue` database belongs to a foreign Alembic lineage
  (`e79f192828b1` is absent from this checkout), so verification correctly stopped there and moved
  to the new isolated database instead of changing shared state.

## Remaining acceptance boundary

- Resume the real browser journey at Project B: rerun ICP synthesis, complete ICP gate approval,
  then verify discovery produces genuine prospect rows. Confirm the Accounts page is empty before
  discovery and never renders the bound client as a target.
