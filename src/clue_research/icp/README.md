# `clue_research/icp/` — ICP & Research-Schema Compiler

**Status:** reserved by M0.1 (ENG-101) — empty until M3.

**Spec:** [`docs/specs/M03-icp-and-research-schema-compiler.md`](../../../docs/specs/M03-icp-and-research-schema-compiler.md)

The versioned ICP spec model, the research-schema compiler (ICP → typed field plan, scoring vs deep tags), industry packs, and the scoring rubric model.

## Modular boundary (M0.1 / ENG-101)

May import only `core/`, `config/`, and `obs/` from within `clue_research`. Components communicate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
