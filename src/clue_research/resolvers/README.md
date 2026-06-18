# `clue_research/resolvers/` — Source Layer — concrete resolvers

**Status:** reserved by M0.1 (ENG-101) — empty until M4.

**Spec:** [`docs/specs/M04-source-layer-and-source-intelligence.md`](../../../docs/specs/M04-source-layer-and-source-intelligence.md) §M4.4/§M4.5

Concrete `Resolver` implementations, one per provider sub-package (`resolvers/clay/`, `resolvers/apollo/`, …). Swapping a provider is confined to its sub-package.

## Modular boundary (M0.1 / ENG-101)

The **only** place (besides `adapters/<source>/`) allowed to import a provider SDK (Clay, Apollo, ZoomInfo, BuiltWith, Exa, Parallel, Firecrawl, CRM, …), and only inside a per-provider sub-package. The provider name never appears anywhere downstream.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
