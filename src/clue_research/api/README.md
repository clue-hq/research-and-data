# `clue_research/api/` — FastAPI app layer (placeholder)

**Status:** placeholder created by M0.1 (ENG-101); wired by M5 (front edge) and M13 (review surface).

**Spec:** [`docs/specs/M00-foundations-and-shared-contracts.md`](../../../docs/specs/M00-foundations-and-shared-contracts.md) §M0.1

The FastAPI app layer — the front-edge surface (M5) and the review surface (M13). Placeholder only in M0.

## Modular boundary (M0.1 / ENG-101)

**Nothing else in `clue_research` may import `api/`.** It is the outermost layer; dependencies point inward only.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
