# M8C V0 — Failure ledger

- **Parent acceptance:** `M8C-V0-offline-database-acceptance.md`
- **Scope:** M8C C0–C7 offline/database acceptance on
  `platform/c8-account-profiling-integration`
- **Recorded:** 2026-08-05
- **Status:** no open V0 product-code failure; one open repository test-isolation debt; V1 live
  behavior remains untested and separately gated

This ledger separates observed defects from environmental gates and missing live evidence. A
passing fake transport is not provider evidence, an expected skip is not a failure, and a failure
caused by reusing shared test state is not attributed to M8C production code without a clean-state
reproduction.

## 1. Summary

| Class | Open | Resolved | Disposition |
|---|---:|---:|---|
| Actual failures | 0 | 2 root causes | corrected and rerun on the prerequisite-populated database |
| Flaky or order-dependent behavior | 1 | 2 manifestations | reusable-database seed isolation remains repository test debt |
| Untested requirements | 11 V1 gates | 0 | cannot close without an explicitly authorized bounded live canary |
| Expected configuration/provider gates | 7 gate groups | — | fail-closed by design; satisfy only for the bounded environment being exercised |
| Unrelated repository failures/findings | 1 format gate, 1 warning | — | outside the V0-owned change; no unrelated clean-database pytest failure |

The final V0 evidence remains **324/324** for the populated C0–C7/M8B matrix and **3,412 passed,
25 skipped, 0 failed** for the clean-database repository suite.

## 2. Actual failures

These were real defects in the test implementation because the prerequisite-populated database was
valid and the tests were expected to coexist with it. Neither defect was accepted as a provider or
production failure.

| ID | Observed failure and root cause | Impact | Correction | Final evidence | Status |
|---|---|---|---|---|---|
| AF-01 | The recorded `_CommitteeTransport` reused one Sumble Teams id and one People request id for every simulated operation. The database correctly rejected the duplicate global `(source_key, provider_operation_id)` identity. | The first populated run produced provider-operation uniqueness failures; later statements on the rollback-only connection cascaded into `InFailedSQLTransaction`. | Generate provider-like unique ids per fake transport while retaining the captured schema. Production uniqueness and coordinator behavior were not weakened. | Previously affected Sumble group: 23/23; populated matrix: 324/324. | Resolved |
| AF-02 | S2D and O2 tests asserted whole-table row counts rather than the exact workspace/account authority. The legitimate prerequisite operation shifted expected counts. | Valid multi-tenant/pre-populated state produced false zero/one-operation failures. | Scope assertions to the test request's `workspace_id` and `account_id`. | Populated matrix: 324/324. | Resolved |

The initial populated run's multiple failing test cases collapse to these two root causes. The
aborted-transaction messages were a consequence of AF-01 inside the test connection, not a third
independent production defect.

**Open actual V0 failures: none.**

## 3. Flaky or order-dependent behavior

| ID | Behavior | Classification | Current status | Closure requirement |
|---|---|---|---|---|
| OD-01 | A broader C5 run on an already-used session database reported 24 failures, principally source-manifest redefinition and discovery-cardinality assumptions. The affected set passed from a clean database. C6 later reproduced the same reused-database seed/order pollution, while a fresh full-suite database passed. | Order/isolation debt in repository test seeds; not random provider behavior and not reproduced as an M8C product failure on clean state. | Open, non-blocking for V0's required fresh-isolated-database gate. | Make shared seed helpers idempotent or transaction-local, remove global cardinality assumptions, and add an explicit second-run/reused-database regression command. |
| OD-02 | Fixed provider ids made fake acquisition tests depend on whether another test or prerequisite fixture had already persisted the captured id. | Order-dependent test double. | Resolved by AF-01. | Covered by prerequisite-populated V0 rerun. |
| OD-03 | Whole-table S2D/O2 counts depended on database contents outside the tested tenant/account. | Order- and state-dependent assertion. | Resolved by AF-02. | Covered by prerequisite-populated V0 rerun. |

V0 deliberately requires a fresh isolated database for release acceptance. That is the correct
destructive-migration and reproducibility boundary, but it does not erase OD-01; OD-01 remains a
separate repository-harness cleanup item.

## 4. Untested requirements

All 55 C0–C7 mechanical exit gates are mapped to executable fake/offline tests. The following
provider-behavior requirements remain untested because V0 made no Exa, Sumble, validator, channel,
or model request. They are the eleven binding V1 gates, not implied failures:

| ID | Untested live requirement | Evidence required to close |
|---|---|---|
| UT-01 | Exact development database/workspace/project/ICP/discovery-batch preconditions. | Record the chosen bounded canary ids and prove their sealed prerequisite lineage before traffic. |
| UT-02 | User-confirmed directive and selected-contact receipt under live composition. | Persist and inspect the exact approved directive, contact selection, fields, sources, channels, and caps used by the canary. |
| UT-03 | Live Sumble professional snapshot semantics, or governed reuse of the already-live exact snapshot. | Show real Sumble request/response/receipt lineage, or prove that the selected fresh live snapshot is exact and reusable without another call. |
| UT-04 | Live contact-targeted Exa Search request and structured response. | Capture real endpoint traffic, exact person/employer target lock, structured output, evidence spans, provider request id, and terminal semantics. |
| UT-05 | Live selected-channel acquisition and independent validation. | After its contract and vendor binding are accepted, exercise one separately approved channel through acquisition, corroboration/reachability, and use/identity gates. |
| UT-06 | Immutable live request, response, snapshot, evidence, and provider identifiers. | Inspect durable artifacts and exact subject/provider lineage after the live calls. |
| UT-07 | Live typed-claim materialization and promotion. | Prove identity binding, use decision, verification state, freshness, and promoted research-view output from the live artifacts. |
| UT-08 | Real native units/dollars and receipt reconciliation. | Reconcile provider-reported units/cost with durable operation receipts and the project budget without double settlement. |
| UT-09 | Detached fleet waiting and resume under real provider latency. | Observe `WAITING_EXTERNAL`, durable wake/re-offer, resume, and no duplicate account/committee/provider work. |
| UT-10 | Content-contract consumption of the live governed claim references. | Produce the account-contact-persona bundle and safe channel eligibility/fallback from live-derived refs, without a research-provider call in the consumer. |
| UT-11 | Fresh-process live replay. | Restart composition and prove equivalent governed output with zero provider/validator/model traffic and zero new spend. |

The combined M8C release criterion for a bounded live provider/model canary therefore remains open.
If the accepted field plan does not require a model call, the V1 record must say so rather than
manufacturing model traffic merely to satisfy wording.

## 5. Expected configuration and provider gates

These are intentional fail-closed boundaries. Encountering one means the environment or authority
is not ready for that operation; it does not mean the offline implementation failed.

| ID | Gate | Current expected behavior |
|---|---|---|
| EG-01 | Explicit paid-call authorization | No V1 provider call occurs until the bounded account/contact/channel and caps are authorized. |
| EG-02 | Credentials and entitlement | Missing Exa/Sumble/validator credentials, unavailable endpoints, or unproven person-import/enrichment entitlement stop before accepted live traffic. A catalog probe alone is insufficient. |
| EG-03 | Contact Exa activation | Production contact Exa preparation is default-off; enabling it must bind the admitted exact source plan and durable coordinator. |
| EG-04 | Channel validator composition | Channel enrichment stays fail-closed until a concrete independently accepted validator-backed coordinator is registered. Enabling the feature without it must fail startup. |
| EG-05 | Reveal and personal-data authority | Contact reveals remain independently selected and default-denied unless the directive, selected-contact receipt, channel, provider, validator, jurisdiction, use policy, and separate budgets all pass. |
| EG-06 | Fresh snapshot reuse | A reusable exact fresh Sumble/Exa snapshot causes zero new provider traffic; missing or stale authority may proceed only through an eligible, budgeted acquisition. |
| EG-07 | Runtime test infrastructure | Redis, MinIO/S3, and destructive committed-operation tests run only when their explicit environment gates are enabled against owned infrastructure. |

The final repository suite's 25 skips are fully accounted for:

- 12 Redis lock-suite cases plus 2 Redis-backed admission/merge cases;
- 7 MinIO-backed S3 storage cases;
- 2 explicitly gated committed-operation tests requiring a throwaway database;
- 1 zero-spend Sumble MCP live-auth/catalog probe; and
- 1 identity-binding fixture case skipped because the seeded manifests contain no weak-prior
  source.

These skipped tests do not cover the paid V1 canary and must not be counted as live provider
evidence.

## 6. Unrelated repository failures and findings

| ID | Finding | Effect on V0 | Status |
|---|---|---|---|
| UR-01 | Repository-wide Ruff format check names `subsystems/research/clue_research/profiling/committee/sources.py` and `tests/api/test_c7_handoff_cutover.py`. Both were pre-existing and outside the V0-owned diff. | Ruff lint and all V0-owned/scoped formatting passed; the global format-only gate remains red until those files are formatted by their owner. | Open, unrelated |
| UR-02 | One existing Starlette/httpx deprecation warning appears in the clean full suite. | Non-failing; no M8C assertion or runtime path failed. | Open warning, unrelated |

There was **no unrelated pytest failure** on the final fresh isolated full-suite database. The
untracked/user-owned workspace files shown by `git status` were preserved and are not test
findings.

## 7. Release reading

- **V0:** accepted mechanically. No open V0 product-code failure.
- **Repository harness:** OD-01 and UR-01 remain real cleanup work, but neither is live-provider
  evidence or a reason to misreport V0 as failed.
- **M8C as a live capability:** not accepted until UT-01–UT-11 close in V1.
- **Provider/configuration gates:** remain fail-closed; bypassing them would invalidate, not advance,
  acceptance.
