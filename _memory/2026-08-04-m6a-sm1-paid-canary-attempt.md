# 2026-08-04 — M6A SM1 paid MCP canary attempt

## Request

Thoroughly test the unclosed Sumble MCP path: an OAuth-authorized paid tool response through the
durable artifact, claim, spend-settlement, and fresh-process zero-call replay chain.

## Live result

- The configured `CLUE_SUMBLE_API_KEY` is a REST credential and Sumble returned an MCP `401` when
  it was used as the bearer token. It was not reused as OAuth authority.
- Sumble dynamic client registration and PKCE authorization reached the authenticated account in
  Chrome.
- Sumble showed the account as Free, stated that MCP is enabled only on paid plans, and disabled
  authorization. No OAuth token was issued.
- The pending callback was stopped before the durable paid-dispatch lease. No paid `tools/call`
  occurred and zero credits were consumed.
- No access-token or refresh-token file was created.

The paid canary therefore remains `OPEN`; do not describe the live MCP data path as proven.

## Contract evidence

- Live MCP protocol: `2025-06-18`.
- Live server: Sumble `1.29.0`.
- Live catalog fingerprint:
  `c25e286bb3dd4a32c4ed8176aa62e9bc16e25326a24f23d03ebf2409e8e4794d`.
- A one-account `FindMatchAndEnrichOrganizations` match request for Insight Health AI, with no
  people/contact reveal and no paid attributes, passed the exact live advertised schema and the
  local default governance policy.

## Mechanical verification

- `tests/resolvers/test_sumble_mcp.py`: passed with the opt-in live test skipped.
- Opt-in live zero-credit initialize/catalog test: passed.
- `tests/api/test_sumble_mcp_journal.py` plus resolver MCP tests on a freshly migrated isolated
  PostgreSQL database: passed (`....s.........`).
- The database test covered durable reservation, request/response artifact bindings, provider
  receipt settlement, terminal snapshot persistence, and a fresh-journal replay with zero provider
  calls. Its tool result remained simulated, so it does not close the paid-live gate.

Both temporary databases named `clue_mcp_canary_20260804` (host and Docker-local instances) were
verified to have zero active connections and dropped. Temporary OAuth/probe scripts were deleted.

## Retry gate

Upgrade/enable MCP for the Sumble account, then rerun the same one-account organization canary.
Success requires an actual `tools/call` response, exact raw response artifact, registered-field
claim, provider/project spend settlement, and a fresh-process replay proving zero additional
provider calls.
