# 2026-08-05 — merge Exa/Sumble discovery into account profiling

## Merge boundary

- Destination: `platform/c8-account-profiling-integration` at `ad55af6` before merge.
- Source: local `platform/c8-exa-sumble-discovery` at `18d1449`.
- `origin/platform/c8-exa-sumble-discovery` was fetched at `cb7a275`; it is an ancestor of the
  local source tip. The five local commits through `18d1449` add the P0-P3 repair and governed
  Sumble MCP adapter/canary record, so the local tip is the complete source state.
- The worktree already had the merge in progress. Five additive conflicts were resolved without
  touching unrelated unstaged/untracked files.

## Integration decisions

- Kept independent Exa account-deep, Sumble pre-seal discovery-gap, S1 account-gap, and S2
  committee authorization settings.
- Composed both the discovery-gap resolver and account-deep committee workers in `fleet_main`.
- Included discovery-gap, committee-acquisition, and external-research reservations in the shared
  project-run provider-spend total.
- Exported all three durable seams and retained the destination's tenant-local policy-aware exact
  Stage-0 readiness replay check.
- Added Alembic merge revision `d0f7a2858e40` joining discovery-gap head `6e8737f21ec4` and
  account-deep head `a83e52bebc7c`; the repository has one head again.

## Verification

- Ruff passed on the full changed source surface; Python compileall passed.
- Sumble resolver/MCP tests passed with the opt-in live test skipped.
- On isolated database `roseau_c8_merge_20260805`, Alembic `upgrade head -> downgrade base ->
  upgrade head` passed.
- DB-backed MCP journal, discovery-gap, Stage-0, D1 spend, Exa E1, Sumble S2B, and fleet wiring
  tests passed; two explicit committed-gate tests remained intentionally skipped.
- Mypy passed for 523 source files. Import-linter kept all 24 contracts. Alembic reports the sole
  head `d0f7a2858e40`.
- The isolated host and container diagnostic databases were confirmed idle and dropped.
- No provider authorization flags were enabled; no Exa, Sumble, OpenRouter, contact-reveal, or
  paid MCP request ran. The paid Sumble MCP canary remains open pending paid-plan OAuth access.
