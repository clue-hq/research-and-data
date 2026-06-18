# `clue_research/claimstore/` — Claim Store & Merge Policy

**Status:** reserved by M0.1 (ENG-101) — empty until M1.

**Spec:** [`docs/specs/M01-claim-store-and-merge-policy.md`](../../../docs/specs/M01-claim-store-and-merge-policy.md)

The append-only typed-claim store, the deterministic `current_value` merge policy, and the field registry. **The one shared substrate** every component reads from and writes to.

## Modular boundary (M0.1 / ENG-101)

May import only `core/`, `config/`, and `obs/` from within `clue_research`. Components communicate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
