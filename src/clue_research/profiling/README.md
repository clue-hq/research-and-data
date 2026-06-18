# `clue_research/profiling/` — Deep Profiling (modes M2/M3/M4)

**Status:** reserved by M0.1 (ENG-101) — empty until M8.

**Spec:** [`docs/specs/M08-deep-profiling.md`](../../../docs/specs/M08-deep-profiling.md)

Pass B deep profiling: account profiling, `account.resonance.*`, committee discovery, contact profiling, and `contact.facet.*`.

## Modular boundary (M0.1 / ENG-101)

May import only `core/`, `config/`, and `obs/` from within `clue_research`. Components communicate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
