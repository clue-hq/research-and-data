# `clue_research/synthesis/` — Tier-4 LLM Synthesis

**Status:** reserved by M0.1 (ENG-101) — empty until M11.

**Spec:** [`docs/specs/M11-tier4-llm-synthesis.md`](../../../docs/specs/M11-tier4-llm-synthesis.md)

Tier-4 LLM synthesis resolvers (Exa Deep, Parallel Task) and the synthesis fields — added **last**, behind the verification layer, as the least-trusted source.

## Modular boundary (M0.1 / ENG-101)

May import only `core/`, `config/`, and `obs/` from within `clue_research`. Components communicate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
