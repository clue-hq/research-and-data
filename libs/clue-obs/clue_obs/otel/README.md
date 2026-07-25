# `clue_research/obs/` — Observability & tracing skeleton

**Status:** created by M0.1 (ENG-101); implemented by M0.5 (ENG-125).

**Spec:** [`docs/specs/M00-foundations-and-shared-contracts.md`](../../../docs/specs/M00-foundations-and-shared-contracts.md) §M0.5

Observability & tracing skeleton: `traced_step()` named spans and metric emitters, with the faithfulness-judge and appropriateness/use-gate spans reserved as **distinct** names.

## Modular boundary (M0.1 / ENG-101)

May import only `core/`, `config/`, and `obs/` from within `clue_research`. Components communicate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
