# Lane 3 slice 4 — entity tags on traces — 2026-09-15

Branch `lane3/sice1b` (unpushed), after slice 3. Design
`docs/superpowers/specs/archive/2026-09-15-lane3-slice4-entity-tags-design.md`; plan
`docs/superpowers/plans/2026-09-15-lane3-slice4-entity-tags.md`. SDD (Opus implementers, controller
reviews); the SDD workspace was deleted after the final review.

## What shipped

bc4ed85d3 + ec72b26f7 `clue_obs.langfuse.tag_entities` (per-trace accumulator seeded by
`propagate_trace` at the trace root and mutated in place, so child tasks and threads share one set;
re-emits the whole set as `entity:<id>` tags and the `entities` metadata list on an `entities.tagged`
event) · bc90b8f75 + d6f699f78 the research job (its subject first, every entity either write path
was asked to write, each committee member as it is born in `committee_step` and the on-demand
person launch) · 2a71536c7 `read_account_research` (and its pinned V2) and `read_claims` tag the
turn's trace with the entity they served; `read_project_accounts` is not tagged.

## Decisions and rulings

- D1 both forms: `entity:<id>` tags (exact filter) and `entities` metadata (contains filter).
- D2 the job tags its subject and what it wrote, not what its tools read.
- The SDK merges nested `propagate_attributes` (outer trace name/session/tags survive an inner
  call) — probed 2026-09-15; the accumulator still re-emits the whole set so the trace is right
  whether Langfuse unions or last-writes.
- A `ContextVar.set` in a child task never reaches its siblings: the accumulator's SET OBJECT is
  shared (seeded at the root, `set.update` in place); `held[1] |= ids` would be tuple item
  assignment and raise.
- Both `ToolRuntime.write_each` and `ToolRuntime.write` record entities before writing (a refused
  draft still names an entity the job worked on; `lookup_people` records are batch-written).

## The erasure query (R13 hands deletion to ARV2's D10)

Traces with tag `entity:<contact id>` (or metadata `entities` contains the id) → delete through the
Langfuse API → record the deleted trace ids in the erasure audit. Until D10, the operator uses the
same filter in the Langfuse UI.

## The coverage audit (2026-09-15) — what is and is not measured

Measured on Postgres (and in Langfuse): chat turns (`agent_model_call` with cost), the onboarding
lane's Exa and OpenRouter calls and its synthesis turns, the persona-evidence tool, every
account/person job hop and model round, discovery, the display prewrite. NOT on Postgres (founder
ruling 2026-09-15: leave as is): non-graph gateway completions (value narrative — old-lane
`clue_research.narrative`, live; the design leg's exit judge, live; the Stage-0 claim extractor and
the judges) — visible in Langfuse with settled cost; the old lane's Stage-0 Exa tier-3 / Sumble
resolver calls and the Sumble gap enrichment (live, Sumble priced at 0 cents/credit in the lane) —
httpx spans only; the design subsystem's image/ad-DNA calls (R12 hold) — nothing. Recorded in the
parent note's §8.

## Verification and owed steps

Per task: focused suites + ruff + mypy (4 pre-existing) + lint-imports (27/0); whole-branch run
recorded in the ledger before deletion. Owed, founder-triggered: one turn that reads an account's
claims shows the `entity:<account id>` tag on its trace; the Langfuse project's retention set for
the pilot (acceptance item 9); the slice 3 live proofs. Next: the held design slice (R12), the
erasure lane (R13).
