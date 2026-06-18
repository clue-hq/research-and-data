# `clue_research/review/` — Review, Feedback & Observability

**Status:** reserved by M0.1 (ENG-101) — empty until M13.

**Spec:** [`docs/specs/M13-review-feedback-observability.md`](../../../docs/specs/M13-review-feedback-observability.md)

Tier-1 human review surface, disposition → training-data capture, the source-yield / scoring learning loop, and the client-facing cost & progress surface.

## Modular boundary (M0.1 / ENG-101)

May import only `core/`, `config/`, and `obs/` from within `clue_research`. Components communicate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
