# 2026-06-18 — Spec docs + Linear milestones & issues

## Goal
Convert the architecture doc set into detailed build specs, decomposed into milestones + Linear issues
(user-driven; "research subsystem" Linear project, `research-and-data` label, modular/DRY foundation,
target = EOD 2026-06-20).

## What was done
- **Architecture docs given a checked-in home:** `docs/architecture/` now holds all 6 docs (overview,
  substrate `clue-hq-research-layer-architecture`, staged-flow `clue-hq-discovery-and-research-staged-architecture`,
  Doc B stage0, Doc C signal-exec-cost, Doc D compliance). The 2 originals were recovered from
  `.context/attachments/`. `.context/` is git-excluded (`.git/info/exclude`), so docs there would never commit.
- **`CLAUDE.md` + `AGENTS.md`** updated to point at `docs/architecture/` and fold in the four required
  outputs, output contract, two-tier signals, campaign orchestration, compliance gates. (Earlier session.)
- **Spec docs** in `docs/specs/`:
  - `_conventions.md` — DRY backbone: shared contracts (claim, current_value, account_entity, Resolver,
    field_definition, source_manifest, ICP spec, account_handoff), naming/taxonomies, modularity rules,
    stack, spec template, milestone dependency table, open-decisions register.
  - `README.md` — master index: 14-milestone map + full 65-issue list + dependency order.
  - `M00`…`M13` — 14 exhaustive per-milestone specs (one §M#.# section per issue). Authored + verified
    by a Workflow (author→verify pipeline). M4 failed on a socket error in the run and was regenerated
    separately (it is the largest, 74 KB).
- **Linear (Engineering team / project "Research Subsystem", id 2c743aca-0c49-4b3b-b845-6ff23e957fd1):**
  - 15 labels: `research-and-data` + 14 `layer:*` (one per milestone).
  - 14 milestones M0→M13 (each desc has layer/depends/priority/spec path).
  - **65 issues, ENG-100 … ENG-164**, status Todo, unassigned, priority per milestone, labels
    `research-and-data` + the layer label, milestone set, body = detailed spec summary + `Spec:` backlink.
  - blockedBy dependency graph: 118 edges across 64 issues (curated from substrate §11 build order),
    wired via a Workflow (running at time of writing — verify it finished cleanly).

## Decomposition (priority, deps)
M0 Foundations(Urgent) → M1 ClaimStore(Urgent) → M2 Identity, M3 ICP/Schema, M4 SourceLayer (High) →
M5 Stage0, M6 Discovery+PassA, M7 DurableExec → M8 DeepProfiling, M9 Verification → M10 Compliance,
M11 Tier-4 LLM (last, behind judge), M12 Narrative/Handoff, M13 Review/Observability.
Build principle: **substrate before agents; LLM synthesis last.**

## Key decisions / assumptions
- Team = Engineering; project + labels + milestones did not exist, created fresh.
- Per-layer labels in addition to the main label (user confirmed).
- Issue titles normalized to `M#.# — <desc>`.
- Clay = one permanent-until-proven-otherwise **swappable resolver** (per the attached Clay note), per-field
  insourcing decided by measured yield — reflected in M4.4/M4.2 specs.
- Dependency graph is **curated** (authored from the build order), not parsed from free text, to stay accurate.

## State of working files (regenerable scratch, in /tmp — not committed)
- `/tmp/research_issues.json` (65 staged issues w/ bodies), `/tmp/research_idmap.json` (ikey→ENG-###),
  `/tmp/research_deps.json` (child ikey→[blocker ikeys]).

## Open / follow-ups
- **Nothing committed/pushed.** Only `readme.md` is git-tracked; all new docs are untracked on branch
  `project-memory-instructions`. Commit/push only when the user asks.
- Linear **project target date** shows the June *month* (MCP `targetDateResolution` has no day-level option);
  exact EOD-2026-06-20 is in the project description. Cosmetic.
- Issue-level deps are also documented in each issue body + spec; the formal blockedBy wiring is the curated
  spine, not every transitive edge.
- Verify the wire-deps workflow (`w5ndbzszp`) reported 0 errors.
