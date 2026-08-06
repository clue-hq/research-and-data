# M8D R0 entity-research contract fixtures

These fixtures freeze the authority boundary before the active entity-research implementation is
changed.

- `r0_contract_fixture.json` is the canonical valid account/contact contract bundle. `$name`
  values are local fixture references resolved only by the contract test.
- `r0_forbidden_flows.json` mutates the canonical bundle into every old or prohibited flow in the
  R0 battery. A case passes only when Pydantic rejects it with its expected contract reason.
- `r0_schema_fingerprints.json` freezes the canonical JSON-schema digest of every public R0
  contract. R5 deliberately added a separately frozen `committee_source_keys` authority so an
  enumeration provider is never attached to an unrelated account field, and an explicit
  `confirmed_empty_discovery` result disposition so a grounded zero-member committee is durable
  rather than confused with a missing projection. Any further schema widening requires an
  explicit fixture and acceptance-document revision.

These are contract fixtures, not provider responses. They make no network, database, model, or
provider call and authorize no spend.
