# M06A S1 Sumble account-gap enrichment acceptance

- **Overall S1 gate:** `OPEN` pending the bounded paid live-provider canary
- **Mechanical/provider-contract status:** `PASS` on 2026-08-03
- **Live-provider status:** organization endpoint/normalizer proven live through the shared
  pre-seal waterfall; S1 jobs and confirmed-technology endpoints remain `OPEN`
- **Branch:** `platform/c8-exa-sumble-discovery`
- **Implementation commit:** `ae05542` (`feat(enrichment): add durable Sumble S1 account gaps`)
- **Migration:** `bd0b7e62a2b4` (single head)
- **Pinned provider contract:** Sumble REST `v9`, OpenAPI SHA-256
  `c6f1324366a94844932ee3522caee6aa9f428f7d958a9956bea3425d18e2811c`

This record covers selected-account company gaps only. It does not authorize Sumble people/teams,
contact reveals, signals, Priority Signals, Intelligence Briefs, or whole-list enrichment.

## 1. Eligibility and explicit field planning

The production tool is `enrich_account_gaps@1`, owned by the Head-of-ABM profile and withheld from
the Stage-0 conversation surface. One invocation addresses one canonical account and an explicit
map of field keys to positive expected-value credits. The provider cap is separately explicit.

Before any operation row or HTTP request, preflight requires:

- an active project run in `DEEP`;
- the exact current immutable discovery seal and account membership;
- the workspace-local canonical survivor and primary domain;
- exactly one tier-1 human checkpoint claim with selected disposition, eligible tier, and matching
  project-run, batch, seal, ICP key, and ICP version;
- a field definition whose ordered tier plan contains the corresponding Sumble source;
- a genuinely missing, conflicting, or low-confidence current value;
- positive expected value for every selected field and aggregate expected value at least equal to
  the provider-credit cap; and
- exact opt-in for the unbounded confirmed-technology endpoint.

The approved S1 field surface is deliberately closed:

| Field | Sumble source | Endpoint role |
|---|---|---|
| `core.employee_count` | `sumble_organizations` | selected paid organization attribute |
| `core.primary_domain` | `sumble_organizations` | free organization identity attribute |
| `core.industry` | `sumble_organizations` | selected paid organization attribute |
| `core.hq_location` | `sumble_organizations` | selected paid headquarters-country attribute |
| `account.hiring_velocity_eng` | `sumble_jobs` | bounded engineering-job evidence |
| `core.primary_tech_stack` | `sumble_tech_stack` | confirmed technology evidence; unbounded call |

Organization requests select only the paid attributes present in the field plan. Jobs and
technology first depend on a matched organization id, preventing orphan calls against an inferred
or fuzzy account.

## 2. Durable acquisition and spend semantics

Migration `bd0b7e62a2b4` adds three tenant-bound ledgers:

- `account_gap_operation` for the immutable seal/account/field/cap request and aggregate receipt;
- `account_gap_snapshot` for each organization, jobs, or technology request/response; and
- `account_gap_field_result` for terminal missing/resolved/corroborated/conflict outcomes and exact
  claim lineage.

The database enforces request uniqueness, same-window field non-overlap, tier-claim and result-claim
lineage, terminal immutability, snapshot completeness before success, bounded charges unless the
technology call was explicitly approved, and one project-run budget reservation shared with D6 and
E1. Provider credits and monetary allocation remain separate durable units.

Every request is captured before dispatch. Every successful provider response is stored as a
content-addressed artifact before its snapshot becomes terminal. Response receipts preserve the
provider request id, credits used, credits remaining, configured money conversion, and provider
contract version. The final receipt reconciles all snapshots, fields, and claim ids.

A transport/schema failure after dispatch is conservatively terminal
`spend_outcome_unknown`; automatic retry is prohibited. A process restart during a dispatch
quarantines the possibly paid snapshot after the in-flight grace period. A realized unbounded-tech
charge above the explicitly authorized parent cap is recorded and settled honestly, then the
operation fails terminally rather than hiding the overage.

## 3. Claim preservation and field reconciliation

Successful snapshots are read by the existing snapshot-only Sumble resolvers; the resolvers do not
make network calls. Claims are typed, workspace-scoped, source-keyed, tied to the raw response
artifact, and replay-deduplicated by canonical value plus artifact identity.

Exa and Sumble claims are never superseded merely because a provider returned later. After each
Sumble claim is written, the shared corroborator and field-specific merge policy run over all live
claims. Agreement can produce `corroborated`; disagreement produces a durable `conflict` containing
both claim ids. The tested technology disagreement retains the Exa and Sumble claims independently
and leaves `current_value.conflict=true`.

## 4. Production composition and privacy

S1 has its own default-off switch, `CLUE_SUMBLE_ACCOUNT_GAP_ENRICHMENT_ENABLED`, and fails closed if
enabled without `CLUE_SUMBLE_API_KEY`. `CLUE_SUMBLE_CENTS_PER_CREDIT` is a nonnegative explicit
allocation; zero means monetary cost is unknown/not allocated, not free provider usage.

The production API and fleet composition roots inject the same starter into the toolbelt. S1 is a
synchronous bounded coordinator over durable snapshots, so it needs no second poll loop. Restart
convergence happens through the same tool and persisted operation.

All input, endpoint request, endpoint response, and final receipt artifacts are indexed to the
account through the discovery artifact-subject ledger. The acceptance test proves enumeration,
tombstoning, and terminal replay without recreating subject edges or provider calls.

## 5. Verification evidence

The database-backed acceptance uses a real PostgreSQL transaction and real filesystem artifact
storage, while replacing only the external HTTP transport with responses validated by the pinned
v9 models. It proves:

- three endpoint calls produce three independent terminal snapshots;
- exact five-credit settlement and 2.5-cent configured project cost;
- hiring materialization plus an Exa/Sumble technology conflict with both claims retained;
- direct and post-DSAR terminal replay make zero additional HTTP calls and duplicate no claim;
- terminal operation and field mutation are rejected by PostgreSQL;
- already-confident fields, unjustified caps, and unapproved technology fail with zero provider
  calls and zero operation rows; and
- production composition is default-off and missing credentials fail closed.

Additional gates completed:

- full mypy: 484 source files, no issues;
- import-linter: 24 contracts kept, 0 broken;
- tracked-source Ruff lint: pass;
- targeted S1/adapter/authority/profile tests: pass; and
- isolated Alembic `head -> base -> head`: pass, after which both temporary test databases were
  removed.

The full repository test run has one unrelated pre-existing failure in
`tests/memory/test_memory_offline.py`: `trial/stage0_runtime.py` imports the memory substrate outside
its intended seam. Thirteen unrelated tracked files also predate this slice's Ruff-format baseline.
All S1-owned files pass format, lint, type, contract, unit, and PostgreSQL acceptance checks.

## 6. Remaining live-provider gate

The later P0-P3 repair reused S1's Sumble adapter and shared claim materializer for two live
REST-v9 `/organizations` requests. Both returned the pinned request/credit/organization envelope,
charged 2 credits, and produced durable `core.industry` claims. This closes live contract risk for
the organization endpoint and shared normalizer, but it did not execute the S1 parent ledger or its
jobs/confirmed-technology endpoints. The overall post-selection S1 gate therefore remains `OPEN`
until a selected account exercises those S1-specific snapshots and terminal fresh-process replay.
