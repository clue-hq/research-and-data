# 2026-08-06 — M8D entity research agent and shared fleet roadmap

## Outcome

- Added `docs/specs/M8D-entity-research-agents-and-shared-fleet-refactor-roadmap.md` as the
  discussion-approved successor for future account/contact entity-agent orchestration.
- M8D preserves M8B/M8C provider, durability, claim, governance, replay, committee, selection, and
  handoff evidence while superseding their active entity-agent ownership/composition.
- Added narrow pointers from the specs index and the M8B/M8C headers.

## Binding clarifications recorded

- Head-of-ABM remains the user-facing `deepagents.create_deep_agent()`; account and contact units
  use `langchain.agents.create_agent()` exactly.
- Account and contact research are separately user-approved runs over one shared mechanical fleet
  substrate; account research never automatically launches contact research.
- Contact selection may include committee or non-committee identity-resolved contacts.
- Governed tools persist complete raw/normalized/evidence/claim-delta/cost state before returning
  a complete research-result projection or lossless index/read surface to the agent.
- Account agents form an office-coherent committee or explicit partial/review result.
- Optional facets are depth one, one or two children, non-recursive, and share the parent budget.
- Entity jobs end only through engine-accepted finalization; review items are durable.
- R0–R10 sequence starts with forbidden-flow contracts and cleanup/quarantine before replacement.

## Verification and scope

- `git diff --check` passed for the scoped documentation.
- Cross-reference targets and index entries resolve locally.
- No product code, runtime configuration, database, provider call, credential, or spend changed.
- Unrelated tracked and untracked working-tree changes were preserved.
