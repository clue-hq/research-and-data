# 2026-08-06 — M8D R8 contact research agents

## Scope

Implemented R8 only: separately approved R7 contacts execute as bounded `create_agent()` units on
the shared R2 fleet. R9 parallel/wait hardening and R10 credentialed live canaries/cutover remain
separate roadmap slices.

## Changes

- Added the exact contact state/identity lock, execution guard, coverage, review, and engine-owned
  finalization services.
- Composed the complete contact semantic-tool surface over the R4 governed result/evidence seam.
- Added depth-one facet child agents with exact field partition and child-turn lineage.
- Split contact reveal from independent validation, added durable wait/resume causation, and folded
  settled channel cost exactly once into job and run spend.
- Added exact selected-set contact aggregation and run-scoped production composition.
- Added migration `7bb3178d7580` for locks, facets, channel causation/cost, coverage, review,
  finalization intent, and fleet return state.
- Preserved R7 research-budget hashing while adding explicit all-in execution caps that include
  authorized channel acquisition and validation.

## Decisions and defects corrected during acceptance

- Prefer stable LinkedIn for identity locking; a verified email is a fallback anchor only, so an
  authorized reveal cannot mutate the running subject lock.
- Facet agents use a non-recursive subset of the otherwise complete parent tool surface.
- Fresh existing grounded claims satisfy coverage; stale/conflicted/evidence-less claims do not.
- Reveal success stops at `ready_to_validate`; validation is a distinct agent decision.
- Provider resume joins the already-caused operation under the next fenced turn rather than
  causing or charging again.
- Channel state ordering has a deterministic precedence because Postgres transaction timestamps
  may be equal.
- R7's research-only job cap was insufficient for authorized channel spend; execution now uses the
  exact research plus channel caps without changing the historical selection digest contract.
- A migration trigger originally read a table-specific column from the wrong event table; the
  trigger is now table-branch-specific.

## Verification

- Isolated R8 database suite: 4 passed, including actual shared-fleet parent/facet
  `langchain.agents.create_agent()` construction, deterministic Exa provider-boundary acquisition,
  C5 channel wait/validate/spend, finalization, replay, and exact-set aggregation.
- R7/C5/C6 regression set: 22 passed.
- Combined R0–R8 plus retained C4/C5/C6 matrix: 154 passed.
- Post-format R7/R8 plus C5/C6 exact-set/channel matrix: 26 passed.
- Migration downgrade to `02e552db75da`, upgrade to `7bb3178d7580`, and one-head check passed.
- Scoped Ruff check/format passed; changed-source mypy passed 11 files; all 24 import contracts
  remained green.

## Boundary

No internet or paid provider call was made for R8. Deterministic transports exercise the real
provider-facing durability and claim plumbing. R10 owns bounded credentialed Exa/Sumble live
account/contact canaries and provider-side receipt/spend evidence.
