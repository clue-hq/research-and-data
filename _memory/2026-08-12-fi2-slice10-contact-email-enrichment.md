# 2026-08-12 — FI-2 Slice 10 Contact email enrichment

## Ratified behavior

- Reuse the existing Contacts-row `Look up` control; preserve its visual design.
- Exa Websets and Sumble v9 People are independent acquisition sources.
- Matching normalized values display once. Conflicting values both display with provider labels.
  One provider result displays alone; two no-results display an empty value.
- No verification/corroboration badge is user-facing. Results remain backend metadata and
  `verification_status=unverified`; never update `contact_entity.verified_email`.
- Independent deliverability validation remains deferred in the stricter C5 path.
- No approval/spend-gate UI or budget-based blocking while the budget-control switch is off.
  Realized provider units and cost still persist.

## Implementation

- Added default-off `CLUE_FRONTEND_CONTACT_EMAIL_LOOKUP_ENABLED` and poll cadence settings.
- Added reversible Alembic head `fee9d89bca93` with lookup, per-provider attempt and artifact-link
  tables. The stable monthly fingerprint and atomic provider-state claims prevent duplicate kickoff.
- Added the provider-neutral service and production Exa/Sumble adapters. Both lock to one exact
  LinkedIn person; Sumble explicitly selects `email` and pins the documented 10-credit maximum.
- Persisted response artifacts, exact provider operation/request references, realized economics,
  unverified tenant-private `core.work_email` claims, strong target identity binding, lawful basis,
  use decisions and DSAR subject edges. Suppressed contacts fail before provider dispatch.
- Added authenticated POST start/poll routes under `/frontend/v1`; browser calls ride the existing
  same-origin BFF, whose server session supplies the bearer and `X-Clue-Workspace-Id`. Mutations
  require `research.launch`; backend authorization remains enabled.
- Replaced the 700 ms false-success hook with real mutation/poll state. The frontend displays
  pending, address, no-result, withheld, unavailable/retry and failure states honestly.
- Split the client-safe mutation/error code out of the server-only read repository after the
  production build correctly rejected a Client Component import of `server-only`.
- Updated the Contacts read/detail wire contract, frontend Zod models, source manifest, Sumble
  contract helpers, DSAR artifact reach, Accounts API contract and defect ledger.
- Hardened the read projection against resurrection: it re-resolves every provider claim through
  the live workspace-scoped claim seam and current display policy. A superseded/expired/erased or
  newly restricted claim is rendered withheld even though the immutable provider attempt retains
  its historical claim reference.

## Browser acceptance

- Used an isolated pgvector PostgreSQL database and the exact Insight Health onboarding identity
  seed, plus durable Account/Contact integration state. The browser was authenticated through Clerk
  and selected the seeded workspace normally.
- Verified `/accounts` → Acme preview → Contacts through the real browser, BFF and FastAPI.
- Matching state: Dana's two provider observations collapsed to one `dana@acme.test` address with
  no verification badge or source commentary.
- Unconfigured state: with provider adapters programmatically disabled, Chris changed from
  `Look up` to `Try again`; PostgreSQL held two `provider_not_configured` rows with zero units, zero
  cost, zero artifacts/claims and a blank canonical verified email.
- Conflict state: deterministic provider doubles advanced the same durable lookup to
  `chris@acme.ai (Sumble)` plus `chris@acme.test (Exa)`. Both unverified governed claims and both
  artifacts survived page and direct Contact-profile reload; canonical verified email stayed blank.
- One rejected Exa request occurred during the first disposable-server attempt because an empty
  shell variable did not override the repository `.env` secret loader. It returned 401 before a
  Webset existed. The API was stopped immediately; the acceptance launcher thereafter injected
  `Secrets(...=None)` and asserted both providers disabled. The failed disposable lookup was
  explicitly inspected and removed before the clean rerun. Do not use empty environment strings to
  disable secrets in future acceptance launchers.

## Verification

- Frontend: 174/174 tests, ESLint, design-system build and optimized Next production build pass.
- Backend focused: 108 API/read/provider/DSAR/source-manifest tests pass on the isolated browser
  database, including a DSAR no-resurrection check that tombstones both lookup claims, removes
  their blobs and returns no email from the retained operation history.
- Static: Ruff, mypy over all 635 source files and all 25 import contracts pass.
- Database: head-to-base-to-head migration smoke passes; `alembic heads` returns only
  `fee9d89bca93`.
- Full repository run on a second disposable pgvector database: 4,375 passed, 23 skipped, 36
  failed. One Slice-10-related source-manifest assertion was corrected and passes in isolation. The
  remaining 35 are the previously logged LF-TEST-001 through LF-TEST-005 clusters: shared-DB
  migration/order contamination, retired Stage-0 resource assertion, excluded-design logging
  scan, stale durable-turn current-instruction fixture and Lane-E model-role fixture drift.

## Deployment boundary

- The feature remains default-off. No paid successful Exa/Sumble canary was run in this slice.
  Enable only after product credentials/entitlement are configured and run a separately authorized
  paid canary; the offline provider-contract, durable-service and real browser integration paths are
  complete.
