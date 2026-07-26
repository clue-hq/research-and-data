# Phase C7 engineering handoff

**From:** C6 platform deepagent and skills

**Next session:** C7.0 contract freeze and prerequisite audit

**Governing scope:** `docs/specs/PC-phase-c-agentic-layer.md §C7`

## Starting state

C6 supplies a production-composable, default-off backend agent runtime: isolated virtual
workspaces, immutable folder resources, governed models and C5 tools, durable turns/context/
history/delegation/finalization, Head-of-ABM Stage 0, specialist fresh wakes, the bounded
per-account research agent, one-owner routing, body-free projections, canary comparison,
operations telemetry, and terminal-workspace cleanup.

The account vertical is composed in the fleet, not merely declared as an injection seam:
`GovernedAccountProfiler` prepares and resumes the deterministic `account-research-unit@1`
execution inside the existing DEEP slot. C7 must not bypass that ownership boundary.

C7 must consume these seams rather than create a second agent loop, truth store, execution
journal, workspace backend, coverage evaluator, or handoff path.

## C7.0 first-session work

Freeze the C7 types and ownership map before migration or tool code:

1. `claim_derivation` edge and entailment-verdict contracts;
2. dossier/block/reference projections whose sentences resolve to claims or supported derived
   claims;
3. `compose_dossier` and snapshot re-check tool descriptors, typed outputs, operation ids, and
   replay class;
4. coverage-and-gaps appendix input from C1 projections;
5. production `HandoffCommitteeReader` contract and the removal condition for
   `narrative_emit_skipped`;
6. DSAR reachability for derivation rationale, dossier artifacts, snapshots, and projections.

## Mandatory C8 prerequisites

Close these before their first C7 consumer:

- merge conflict equality must use the field's `equality_mode`;
- retention-expired claims must be ineligible to win `current_value`;
- personal text in `faithfulness_verdict.rationale` must be erased/redacted by DSAR;
- presigned evidence access must have an explicit workspace/scope policy;
- the real `HandoffCommitteeReader` must replace the current handoff gap;
- per-product fit/contact-class changes must be resolved where the C7 output contract needs them.

Each closure needs a named test. Do not group them into an unbounded C8 cleanup branch.

## C7 exit evidence

- every rendered sentence is a claim or supported derived claim with visible provenance;
- superseded/erased/expired/conflicted supports stale or exclude dependents until re-judged;
- fixture dossiers render losslessly and deterministically from references;
- the HANDOFF gap marker disappears only after real narrative emission;
- erased personal content is absent from rationale, snapshots, dossier artifacts, projections,
  and cold replay;
- full repository, migration, import-contract, adversarial, DSAR, and eval gates remain green.
