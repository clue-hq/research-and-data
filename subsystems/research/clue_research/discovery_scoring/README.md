# `clue_research/discovery_scoring/` — Discovery (mode M1) + Pass A Scoring

**Status:** reserved by M0.1 (ENG-101) — empty until M6.

**Spec:** [`docs/specs/M06-discovery-and-pass-a-scoring.md`](../../../docs/specs/M06-discovery-and-pass-a-scoring.md)

Mode-M1 grounded account discovery plus the Pass A two-tier deterministic scoring engine, tiering, the human checkpoint, and the coverage-confidence estimator.

## Modular boundary (M0.1 / ENG-101)

May import only `core/`, `config/`, and `obs/` from within `clue_research`. Components communicate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
