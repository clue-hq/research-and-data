# `clue_research/narrative/` — Value Narrative & Handoff

**Status:** reserved by M0.1 (ENG-101) — empty until M12.

**Spec:** [`docs/specs/M12-value-narrative-and-handoff.md`](../../../docs/specs/M12-value-narrative-and-handoff.md)

The per-persona value narrative (account claims × client knowledge) and the `account_handoff` contract object + provenance index — where this subsystem's output is assembled.

## Modular boundary (M0.1 / ENG-101)

May import only `core/`, `config/`, and `obs/` from within `clue_research`. Components communicate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
