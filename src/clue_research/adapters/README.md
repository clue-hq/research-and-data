# `clue_research/adapters/` — Source Layer — modality adapters

**Status:** reserved by M0.1 (ENG-101) — empty until M4.

**Spec:** [`docs/specs/M04-source-layer-and-source-intelligence.md`](../../../docs/specs/M04-source-layer-and-source-intelligence.md) §M4.3

Modality adapters (fetch → adapt → extract), one per source sub-package (`adapters/<source>/`). Isolates source/modality SDKs from everything downstream.

## Modular boundary (M0.1 / ENG-101)

Allowed to import source/modality SDKs, and only inside a per-source sub-package (`adapters/<source>/`), so those SDKs are isolated from everything downstream.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
