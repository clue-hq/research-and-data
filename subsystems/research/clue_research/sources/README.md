# `clue_research/sources/` — Source Layer & Source Intelligence

**Status:** reserved by M0.1 (ENG-101) — empty until M4.

**Spec:** [`docs/specs/M04-source-layer-and-source-intelligence.md`](../../../docs/specs/M04-source-layer-and-source-intelligence.md) §M4.1/§M4.6

The provider-agnostic source layer: the trust-tiered `Resolver` waterfall engine (stop-at-first-confident), the source registry / manifests, and the config-bounded source planner.

## Modular boundary (M0.1 / ENG-101)

Provider-agnostic. This package holds the `Resolver` protocol and the waterfall engine and **must not** import any provider SDK — those live only in `resolvers/<provider>/`.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
