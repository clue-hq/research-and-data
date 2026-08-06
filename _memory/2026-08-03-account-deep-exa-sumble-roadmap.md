# 2026-08-03 — Account-deep Exa + Sumble integration roadmap

## Request

Persist the accepted requirements and a sliced implementation plan for target-locked Exa Deep
account profiling, Sumble organization-map/buying-committee acquisition, durable user research
direction, and production account-deep composition. This session was planning/documentation only.

## Branch and baseline

- Working branch: `platform/c8-account-profiling-integration`.
- Baseline commit: `cb7a275`.
- The local `platform/c8-exa-sumble-discovery` branch and this branch had zero commits of divergence
  when checked, so no merge was required.
- Unrelated pre-existing modified/untracked files were left untouched.

## Decisions recorded

- The harness remains non-linear and conversational. Discovery completion never auto-launches deep
  research, and directive confirmation is an action-scoped spending gate rather than a new global
  project phase.
- The existing `AccountDeepOrchestrator` remains the per-account unit. Add a set-scoped full-unit
  launcher while retaining independently invokable profiling, committee, and contact tools.
- User direction has two persistence species: project-scoped advisory memory for future context and
  an append-only confirmed `ResearchDirective` for exact execution authority.
- Exa Websets stays discovery-only. Target-locked Exa Search Deep/Deep-Reasoning gets a separate
  structured request, operation, snapshot, dollar receipt, verification, and replay contract.
- Sumble REST v9 supplies bounded organization/team/person facts. Existing provider-neutral logic
  owns committee-role/persona inference. The first committee release performs no contact reveals.
- Paid submit/poll is split from claim materialization. Pending external work resumes through a
  provider-neutral DEEP `WAITING_EXTERNAL` seam without holding a claim transaction.
- The healthcare source profile is a versioned workspace/ICP override admitting Sumble jobs, a
  named official-page resolver, Exa Deep, and deliberately mapped Sumble technology; it excludes
  Parallel Task for the first integration.
- S2 mechanical work may start against S1's mechanical seam, but live S2/V1 release remains gated
  on the S1 paid canary unless governance explicitly changes that gate.

## Artifacts

- Added `docs/specs/M8B-exa-sumble-account-deep-integration-roadmap.md` with binding requirements,
  current deltas, field/source roles, directive and fixture contracts, provider-neutral acquisition
  seam, slices A0–V1, ownership boundaries, sequencing, and release acceptance.
- Linked the companion roadmap from M06A S2 and distinguished target-locked Exa Deep from the
  separately deferred general-purpose Exa Search agent tool.

## Verification and close

- Documentation-only; no migrations, code, provider calls, or spend.
- Targeted whitespace validation passed for the two spec files before staging.
- Final staged-diff validation and local commit are recorded in git history.
- Recommended next implementation slice: A0 contract and authority freeze, followed by the
  additive synthetic account-deep fixture and provider lanes against frozen seams.
