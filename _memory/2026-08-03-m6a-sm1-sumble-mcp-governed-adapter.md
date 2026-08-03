# 2026-08-03 — M6A SM1 governed Sumble MCP adapter

## Request

Add Sumble MCP as an extensible account-enrichment transport, but retain deterministic governance,
durable operation/budget handling, provenance, reconciliation, and avoid conflicts with the
parallel `platform/c8-account-profiling-integration` worktree.

## Branch/worktree boundary

- Current branch: `platform/c8-exa-sumble-discovery`.
- Parallel account-deep branch inspected at
  `/Users/aryankeshri/conductor/workspaces/research-and-data/roseau`.
- The parallel branch owns deep composition, settings, provider-spend aggregation, committee
  ledgers, and Sumble people/teams transports.
- SM1 did not edit those shared/parallel-owned files and added no migration. It reuses the existing
  S1 `account_gap_operation` / `account_gap_snapshot` schema through a new isolated journal.

## Implemented

- `resolvers/sumble/mcp_client.py`
  - MCP protocol 2025-06-18 over Streamable HTTP.
  - injected OAuth token provider; JSON/SSE; sessions; initialize; initialized notification;
    paginated tools/list; tools/call; JSON-RPC correlation; catalog SHA-256.
  - exact structured result only; no natural-language parsing; no automatic paid retry.
- `resolvers/sumble/mcp_adapter.py`
  - exact fail-closed read-only tool policy; mutations/SQL/AI brief prohibited; signals and people
    disabled by default; contact-reveal argument detection.
  - live annotation and advertised JSON-Schema validation.
  - immutable plan + durable authorization + expected-value/provider/money caps + exact receipt
    settlement.
  - data-driven JSON-pointer bindings and artifact-backed snapshot resolver for any registered
    account field.
- `clue_api/sumble_mcp_journal.py`
  - real PostgreSQL/object-store implementation over the existing S1 parent/snapshot ledger.
  - parent lease/lineage/field/contract/window/budget checks under lock.
  - request/response artifacts, subject edges, receipts, spend-unknown quarantine, and zero-call
    terminal replay.
- Binding/acceptance spec:
  `docs/specs/M06A-SM1-sumble-mcp-governed-adapter.md`.

## Live provider findings

- Zero-credit calls on 2026-08-03 negotiated `Sumble 1.29.0` and MCP `2025-06-18`.
- The live `tools/list` returned 30 tools, including organization/jobs/people/technology/signals,
  list mutations, support, AI brief, and SQL/database tools.
- The current server permits `initialize` and `tools/list` with a deliberately invalid token,
  contrary to the earlier observed 401 behavior. The client retains 401 resource-metadata handling
  for protected calls.
- Principal paid tools require a non-empty `reason` and advertise read-only/non-destructive hints.
- No paid MCP tool was called.

## Verification

Passed:

- focused Ruff and mypy on all SM1 files;
- 13 MCP unit/adversarial tests (one opt-in live test skipped by default);
- opt-in live zero-credit initialize/catalog test;
- real PostgreSQL/filesystem journal acceptance on isolated database
  `clue_mcp_branch_20260803`;
- existing Sumble REST resolver and S1 DB tests together with MCP tests: 33 passed, 1 expected live
  skip;
- import-linter: 24 contracts kept, 0 broken;
- resolver static secret scan after test literals were made non-secret-shaped.

The shared local database was stamped at the parallel branch's Alembic head `f8a81c7e1563`, so it
was not modified. A branch-local named database was created/migrated for verification.
Both temporary databases created during diagnosis (`clue_mcp_branch_20260803` on the reachable
host instance and `clue_mcp_20260803` inside the Docker service) were verified to have zero active
connections and dropped after the final tests; they contained only disposable fixtures.

The full DB-backed suite has nine unrelated/pre-existing failures in agent catalog pins,
observability capture, Recipe 1 / composed-worker phase assumptions, exit-gate timing, an outdated
ICP tier-plan expectation, the uncommitted Stage-0 memory import, and toolbelt span capture. None
references an SM1 file. The sandboxed suite also cannot reach local Postgres for one ungated DSAR
test.

## Open activation gates

- Vault-backed OAuth authorization/refresh composition.
- Data-configured field bindings and price rules selected by the account-gap planner.
- Composition after the account-deep branch merges; do not duplicate its committee path.
- Explicitly authorized one-account/one-field paid MCP canary, durable claim and spend settlement,
  then fresh-process zero-call replay.
- Separate S2/personal-data authority before people or contact reveal; separate contract delta
  before signals.
