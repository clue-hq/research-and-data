# `clue_research/stage0/` — Stage 0 Front Edge

**Status:** reserved by M0.1 (ENG-101) — empty until M5.

**Spec:** [`docs/specs/M05-stage0-front-edge.md`](../../../docs/specs/M05-stage0-front-edge.md)

Stage 0 front edge: client reverse-profiling → Client Knowledge Base, ICP synthesis, and the import + hybrid-lookalike entry scenarios.

## Modular boundary (M0.1 / ENG-101)

May import only `core/`, `config/`, and `obs/` from within `clue_research`. Components communicate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
