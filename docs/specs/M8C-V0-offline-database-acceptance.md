# M8C V0 — Offline and database acceptance

- **Parent roadmap:** `M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- **Branch:** `platform/c8-account-profiling-integration`
- **Recorded:** 2026-08-05
- **Status:** mechanically accepted with fake transports on clean and prerequisite-populated
  isolated databases; V1 remains the separate live-provider gate
- **Failure ledger:** `M8C-V0-failure-ledger.md`

V0 verifies the integrated mechanics of M8C C0–C7. It does not claim Exa, Sumble, channel-provider,
validator, or model behavior. Every provider activation switch was explicitly disabled for the
repository-wide run, and the fixture harness used recorded in-process transports only.

## 1. Frozen executable matrix

`tests/fixtures/contact_research/v0_acceptance_matrix.json` maps all 55 C0–C7 exit gates to named
executable tests. It also freezes the eleven V0 categories, the synthetic prerequisite bootstrap,
supporting pre-spend/use/freshness/DSAR/enum checks, and the migration/static/full-suite commands.
`tests/contact_research/test_v0_acceptance_manifest.py` fails when a gate, category, command gate,
test file, or test function is absent.

The matrix covers:

- directive, selection, successor, cancellation, and independent-contact authority;
- ready Sumble People/Teams snapshot materialization and organization-map representation;
- exact contact subject, merged identity, same-name, and mandatory provider-lineage negatives;
- Exa contact compiler, parser, acquisition, snapshot, cost, and replay mechanics;
- independently authorized channel acquisition, corroboration, validation, identity promotion,
  objection, retention, and erasure;
- exact effective source-plan and pre-spend authority;
- crash, concurrency, waiting, resume, cancellation, and fresh-process replay;
- governed reference-only content handoff and safe fallback; and
- the existing M8B account/committee regression boundary.

## 2. Prerequisite-populated database evidence

The dedicated database `roseau_m8c_v0_fixture_20260805a` was created empty and migrated to the
single Alembic head before the repository-owned synthetic harness ran. The harness inserted the
real prerequisite shape rather than a company-row shortcut:

- workspace, product/project, confirmed ICP, discovery batch/manifest/seal, and approved tier;
- confirmed account research directive and exact account-deep launch;
- one ready fake Sumble Teams/People acquisition with immutable requests, responses, snapshots,
  artifacts, receipt, attempts, eligibility, and pre-spend decisions;
- one account run paused honestly at `committee_discovered`; and
- nine grounded tier/committee/professional claims across 21 verified artifacts.

The simulated provider ledger recorded 28 fake credits and 14 fake cents across four recorded
transport calls. Those values test settlement only; they are not paid provider traffic or spend.
A fresh-process replay returned the same operation, snapshots, receipt, launch digest, references,
and nine claims with `provider_calls_this_process=0`.

After that durable prerequisite state already existed, the complete focused C0–C7/M8B matrix
passed: **324 passed, 0 failed**.

## 3. Findings and corrections

The first populated-database matrix exposed two test-harness defects that clean-database suites
could not reveal.

### 3.1 Recorded provider ids were reused as operation ids

Every `_CommitteeTransport` instance returned the same captured Sumble Teams operation id and
People request id. The database correctly enforces `(source_key, provider_operation_id)` as a
global provider identity, so a second simulated operation collided with the already-persisted
fixture. Recovery then showed a secondary aborted-transaction error because the rollback-only test
connection intentionally reuses one transaction.

The fake transport now gives every simulated provider operation unique provider-like ids while
preserving the captured response schema and all other fixture fields. The database uniqueness
constraint and production coordinator were not weakened.

### 3.2 Assertions counted unrelated tenants' rows

S2D eligibility and O2 preparation tests asserted total row counts for the entire committee
operation and eligibility tables. On a valid populated database, the one fixture operation changed
expected `0` to `1` and expected `1` to `2` even though the tested workspace behaved correctly.

Those assertions now count only the exact test workspace and account. This matches the production
authority boundary and retains the zero-call/one-operation guarantees under realistic shared-state
conditions.

After both corrections, the previously failing Sumble group passed **23/23**, followed by the
complete **324/324** populated-database matrix.

## 4. Final verification

- Final untouched full-suite database: `roseau_m8c_v0_full_20260805b`, created empty and migrated
  to head after the populated-database corrections.
- Complete repository suite: **3,412 passed, 25 skipped, 0 failed**, with one existing
  Starlette/httpx deprecation warning.
- Dedicated migration database: all three migration tests passed, including
  `upgrade head -> downgrade base -> upgrade head` and the M0/base invariants.
- Alembic: exactly one head, `4d9b02f218dc`.
- Mypy: zero issues across 539 source files.
- Import-linter: 24 contracts kept across 606 files and 5,049 dependencies.
- Ruff lint: all `libs`, `subsystems`, `platform`, and `tests` files passed.
- Ruff format: all V0-owned files and 995 in-scope files passed. Two unrelated pre-existing tracked
  files remain outside this change: `profiling/committee/sources.py` and
  `tests/api/test_c7_handoff_cutover.py`.

All isolated V0 databases were dropped after their evidence was captured. No shared development
database, live provider state, discovery seal, or user-owned file was reset or rewritten.

## 5. Acceptance boundary

V0 proves offline mechanics and database durability only. M8C still requires V1 for one explicitly
authorized, bounded account/contact canary proving real provider traffic, live response semantics,
durable receipts and costs, detached wait/resume, content handoff, and fresh-process zero-provider
replay. Missing credentials, fake transports, and this V0 acceptance cannot satisfy V1.

Observed failures, order-dependent behavior, untested requirements, expected gates, and unrelated
repository findings are classified separately in `M8C-V0-failure-ledger.md`.
