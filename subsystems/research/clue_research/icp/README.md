# `clue_research/icp/` — ICP & Research-Schema Compiler

**Status:** M3.3 (industry packs framework) implemented; M3.1 / M3.2 / M3.4 to follow.

**Spec:** [`docs/specs/M03-icp-and-research-schema-compiler.md`](../../../docs/specs/M03-icp-and-research-schema-compiler.md)

The versioned ICP spec model, the research-schema compiler (ICP → typed field plan, scoring vs deep tags), industry packs, and the scoring rubric model.

## Modular boundary (M0.1 / ENG-101)

May import the shared base — `core/`, `config/`, `obs/`, and `db/` (the persistence access contract, M0.3) — **and read/write the claim-store substrate (`claimstore/`)**, which is how components communicate (conventions §2: "the claim store is the only shared substrate; components communicate by reading/writing typed claims … never by calling each other"). M3.3 specifically *authors* `field_definition` rows via the M1.3 registry — "new fields = rows in the field registry" (conventions §2/§3) — and reuses `claimstore.{register_field, load_pack, SeedField, list_fields, get_field}` rather than forking the registry.

It must **not** import sibling component packages (`identity/`, `sources/`, `resolvers/`, `adapters/`, `stage0/`, `discovery_scoring/`, `verification/`, …) or any provider SDK. The source layer (M4) is referenced by `source_key` **string** only; the `source_manifest` join is late-bound (M4 owns it).

> Note (M3.3): the earlier scaffold said "only core/config/obs". That stub was narrower than the authoritative rules — it omitted `db/` (explicitly allowed by M0.1) and the claim-store substrate access that conventions §2 mandates as the communication channel, and even contradicted its own next sentence. The boundary above is the spec-grounded one; the machine-enforced `[tool.importlinter]` contracts (run `make contracts`) place **no** restriction on `icp → claimstore` (the worker-independence contract covers only `resolvers/adapters/verification/discovery_scoring`).

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
