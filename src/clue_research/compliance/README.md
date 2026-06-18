# `clue_research/compliance/` — Compliance & Personal-Data Governance

**Status:** reserved by M0.1 (ENG-101) — empty until M10.

**Spec:** [`docs/specs/M10-compliance-and-personal-data.md`](../../../docs/specs/M10-compliance-and-personal-data.md)

Compliance & personal-data governance: jurisdiction resolution, use-class tagging, the appropriateness/use gate, the three postures as config, lawful basis + DSAR/erasure.

## Modular boundary (M0.1 / ENG-101)

May import only `core/`, `config/`, and `obs/` from within `clue_research`. Components communicate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
