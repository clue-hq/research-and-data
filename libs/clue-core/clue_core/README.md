# `clue_research/core/` — Core domain types & shared contracts

**Status:** created by M0.1 (ENG-101); implemented by M0.2 (ENG-108); extended by C7.0.

**Spec:** [`docs/specs/M00-foundations-and-shared-contracts.md`](../../../docs/specs/M00-foundations-and-shared-contracts.md) §M0.2

The shared kernel: the canonical typed contracts — `Entity`, `Claim`, `FieldDef`, the `Resolver` protocol, `SourceManifest`, and the claim/provenance helpers — that every other package imports and none re-implements. *Verifiability is a property of these types.*

C7.0 adds the frozen structured research-view seam in `research_view.py` and the executable
authority/block map in `research_view_species.py`. These contracts describe account/contact views,
reference-only receipts, governed evidence actions, and derivation/entailment protocols. They do
not add a dossier body, database schema, tool handler, composer implementation, or derived claim
flavor; those belong to later C7 slices.

## Modular boundary (M0.1 / ENG-101)

As the shared kernel, `core/` imports **nothing** else inside `clue_research` — every other package depends on it, never the reverse.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
