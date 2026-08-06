# M6A-SM1 — Governed Sumble MCP client and account-gap adapter

**Status:** mechanical/client/database gate `PASS` on 2026-08-03 and reverified on 2026-08-04;
zero-credit live `initialize` + `tools/list` gate `PASS`; OAuth-authorized paid tool canary and
production composition remain `OPEN`. The 2026-08-04 paid-canary attempt reached Sumble's
authenticated authorization page, but Sumble disabled authorization because the account was on
the Free plan; no access token, paid-dispatch lease, provider call, or charge was created.

**Branch:** `platform/c8-exa-sumble-discovery`

**Provider contract:** Sumble Streamable HTTP MCP at `https://mcp.sumble.com/`, MCP protocol
`2025-06-18`. The dynamic tool catalog is pinned by SHA-256 for every planned call.

**Authoritative provider references:**

- `https://docs.sumble.com/api/mcp.md`
- `https://mcp.sumble.com/.well-known/oauth-protected-resource`
- `https://mcp.sumble.com/.well-known/oauth-authorization-server`

## 1. Outcome

SM1 introduces MCP as another Sumble transport without weakening the platform's provider
governance. It does not let an agent call arbitrary server-advertised tools. The implemented path
is:

```text
live tools/list
    -> immutable catalog fingerprint
    -> exact read-only tool + argument + field-binding plan
    -> policy and personal-data gate
    -> existing S1 parent operation budget reservation
    -> one claimed account_gap_snapshot
    -> one tools/call attempt
    -> exact response artifact + credit receipt, or spend-outcome-unknown
    -> data-driven snapshot resolver
    -> registered FieldDef -> ordinary tier-1 claim/provenance path
```

The catalog makes capabilities discoverable; it does not grant authority. A new Sumble response
field can be bound through a versioned JSON-pointer `SumbleMcpFieldBinding`, so adding it does not
require another provider-specific normalizer. The platform field must still exist in the field
registry before a claim can be produced.

## 2. Delivered modules

### 2.1 Streamable-HTTP client

`subsystems/research/clue_research/resolvers/sumble/mcp_client.py` provides:

- injected OAuth access-token provider; no environment lookup or credential persistence;
- MCP `initialize`, `notifications/initialized`, paginated `tools/list`, and `tools/call`;
- JSON and SSE response handling;
- session-id and protocol-version headers;
- exact JSON-RPC request/response correlation;
- typed authentication, retryable transport, protocol, and tool errors;
- canonical tool-catalog hashing; and
- deterministic result admission: `structuredContent` or exactly one JSON text block only.

The HTTP layer performs one attempt. In particular, it never retries `tools/call`.

### 2.2 Capability and spend governance

`subsystems/research/clue_research/resolvers/sumble/mcp_adapter.py` provides:

- an exact tool-name allowlist plus capability classes;
- mandatory live `readOnlyHint=true` and `destructiveHint=false` annotations;
- fail-closed rejection of list mutations, signal feedback, support writes, Intelligence Briefs,
  and database/SQL tools;
- signals disabled by default, matching the existing M6A deferral;
- people/contact reveal disabled by default and a recursive email/phone/reveal argument detector;
- local validation of the advertised JSON Schema's required keys, property boundaries, local
  references, primitive types, enums/constants, ranges, lengths, and collection bounds;
- an immutable plan covering tenant/run/account lineage, catalog and provider contract, exact
  arguments, field bindings, observation window, expected value, provider cap, monetary cap, and
  charge-reconciliation rule;
- an exact durable authorization proof;
- a single-attempt governed adapter; and
- provider-receipt or explicitly pinned fixed-unit settlement. A missing, malformed, non-finite,
  or over-cap receipt becomes `spend_outcome_unknown`, never a guessed charge.

The default read-only allowlist is organization enrichment, job enrichment/title lookup,
confirmed technology, and technology catalog lookup. Sumble people, signals, account-profile,
saved-list, AI-brief, SQL, support, and mutation tools require a separate contract change or remain
prohibited.

### 2.3 Durable S1 journal

`platform/api/clue_api/sumble_mcp_journal.py` adapts the governed invocation to the existing
`account_gap_operation` / `account_gap_snapshot` ledgers. It intentionally adds no migration.

Before dispatch it verifies under a PostgreSQL lock that:

1. the exact S1 parent operation exists and owns the active acquisition lease;
2. workspace, project run, account, provider contract, policy version, and observation window
   match;
3. the MCP bindings equal the parent operation's explicitly selected fields for that source;
4. aggregate per-tool provider reservations fit under the parent reservation;
5. the monetary cap equals the configured cents-per-credit conversion and fits under the parent;
   and
6. the durable authorization covers the exact plan and current catalog fingerprint.

The journal stores sanitized request and response artifacts, account-local artifact-subject edges,
provider request id, provider units, credits remaining, and monetary charge. A terminal successful
snapshot is loaded and hash/reconciliation-checked from the artifact store on replay, producing
zero provider calls. A response whose charge cannot be reconciled is preserved as an
unreconciled artifact and the snapshot becomes terminal `spend_outcome_unknown`.

The parent S1 coordinator remains responsible for field outcomes, claim reconciliation, the final
operation receipt, and one-time project spend settlement. SM1 does not create a second accounting
path.

### 2.4 Data-driven resolver

`SumbleMcpSnapshotResolver` is network-free. It reads an artifact-backed `SumbleMcpSnapshot`,
selects a requested registered field through JSON pointers, creates a grounded `ResolvedField`,
and delegates claim construction to the shared resolver substrate. Provider cost is attributed
once to the configured charge field.

## 3. Live contract findings

The zero-credit live probe on 2026-08-03 negotiated server `Sumble 1.29.0` and returned a 30-tool
catalog. Contrary to the earlier observed/documented challenge behavior, the live server currently
allows `initialize` and `tools/list` with an invalid bearer token. Protected data calls still use
the injected OAuth token and the client handles a `401` resource-metadata challenge.

The live catalog confirmed these important details:

- every principal paid enrichment tool requires a non-empty `reason` for audit logging;
- organization, job, people, and confirmed-tech tools advertise read-only/idempotent annotations;
- email and phone are explicit high-cost people attributes;
- tools include both valuable read paths and unsafe/unwanted mutation, support, AI-brief, and SQL
  paths; and
- outputs advertise open object schemas, so the exact catalog hash and response artifact are more
  reliable lineage anchors than a hand-maintained global output model.

No paid MCP tool was called in SM1.

## 4. Parallel-worktree treaty

The account-deep worktree `platform/c8-account-profiling-integration` owns production deep-phase
composition, Sumble committee acquisition, shared settings, shared durable exports, and provider
spend aggregation. SM1 does not edit any of those files.

SM1 adds only uniquely named MCP client/adapter/journal modules, isolated tests, and this spec. It
does not alter:

- `platform/api/clue_api/run_composition.py`;
- `libs/clue-config/clue_config/settings.py`;
- `subsystems/research/clue_research/durable/__init__.py`;
- `subsystems/research/clue_research/durable/provider_spend.py`;
- the parallel branch's `resolvers/sumble/people.py`, `teams.py`, or
  `committee_transport.py`; or
- the account-deep orchestrator.

After the branches merge, account-deep composition may inject this MCP client behind its existing
external-wait/provider seams. People and contact reveal must retain the S2 eligibility,
jurisdiction, use-class, identity-binding, and separate reveal-budget gates; SM1's default policy
does not bypass them.

## 5. Acceptance evidence

| Gate | Result |
|---|---|
| JSON and SSE MCP transport, session propagation, pagination, catalog pinning | PASS |
| OAuth challenge parsing and secret non-disclosure | PASS, fixture |
| Live zero-credit `initialize` and 30-tool `tools/list` | PASS |
| Exact JSON-only result admission | PASS |
| Mutation, SQL, signals, and contact-reveal fail-closed policy | PASS |
| Advertised input-schema validation before reservation | PASS |
| Receipt settlement, over-cap/missing receipt quarantine, no paid retry | PASS |
| Arbitrary registered field through data-driven JSON-pointer binding | PASS |
| Real PostgreSQL + filesystem request/response artifacts and receipt | PASS |
| Fresh-journal terminal replay with zero provider calls | PASS |
| Paid OAuth-authorized tool call | OPEN — 2026-08-04 OAuth blocked by Sumble Free plan |
| Production account-deep composition | OPEN — owned after branch integration |

### 5.1 Paid-canary attempt — 2026-08-04

The explicitly authorized one-account/one-field canary was prepared for Insight Health AI using
`FindMatchAndEnrichOrganizations` in match mode, with no contact reveal or people capability. The
current live server still negotiated MCP `2025-06-18`, identified itself as Sumble `1.29.0`, and
advertised catalog fingerprint
`c25e286bb3dd4a32c4ed8176aa62e9bc16e25326a24f23d03ebf2409e8e4794d`. The bounded canary
arguments passed the local policy and the exact live advertised input-schema validator.

The configured Sumble REST API key was correctly rejected as an MCP OAuth credential. Dynamic
OAuth registration and PKCE authorization then reached the authenticated Sumble page, which
reported that MCP is enabled only on paid plans and disabled its authorization controls for the
Free account. The callback was stopped before any token or paid-dispatch lease existed. Therefore:

- provider credits consumed: `0`;
- paid `tools/call` attempts: `0`;
- access/refresh token files created: `0`;
- the real response-to-artifact-to-claim-to-settlement chain remains unproven; and
- the paid-canary acceptance row above remains `OPEN`, rather than being promoted from mechanical
  evidence.

The mechanical boundary was reverified separately: all MCP unit/adversarial tests passed, the
zero-credit live catalog probe passed, and the real isolated-PostgreSQL request/response artifact,
receipt, and zero-call replay test passed. Those results do not substitute for the blocked paid
provider response.

The database test ran on the isolated `clue_mcp_branch_20260803` database because the shared local
database was already stamped with the parallel account-deep branch's Alembic head. The shared
database was not modified.

## 6. Remaining integration gate

SM1 is a complete transport/governance/resolver slice, not production activation. Activation after
the branch merge requires:

1. a vault-backed OAuth token/refresh provider and user authorization UX;
2. data-configured field bindings and pricing rules selected by the field planner;
3. composition into the selected account-gap or account-deep source seam;
4. an explicitly authorized one-account/one-field paid canary;
5. verification of the canary's raw response shape, credit receipt, durable claim, conflict policy,
   project spend settlement, and fresh-process zero-call replay; and
6. separate policy enablement before any people, contact reveal, or deferred signal capability.
