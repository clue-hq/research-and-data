# Production context contract fixtures

`s0_contract_fixture.json` is the provider- and database-free S0 contract manifest for
`docs/specs/FI-production-deepagent-context-composition.md`.

It freezes:

- the three model-visible artifact media types;
- the Client-KB and active-project domain-reference shapes;
- model-authored versus constitution-injected fields for the final S4 `@2` read tools; and
- the seven required states: pre-recon, post-fast-recon, post-background-recon, Project A,
  Project B, product-unselected, and product-confirmed.

`tests/projections/test_production_context_contracts.py` validates every state through the strict
S1 Pydantic contracts without provider, network, artifact-store, or database access. The fixture
does not claim S3 production composition: until S3 attaches the two conditional artifacts, the
real worker's v2 envelope reports both as unavailable.

`s4b_tool_contract_fixture.json` freezes the amended S4-B `@2` Client-KB discovery and inspection
contract. It records the complete/model-visible/trusted input split, strict input/output schema
hashes, page and byte ceilings, cursor binding, refusal taxonomy, and compatibility boundary. The
already-published preliminary `@1` tools are not rewritten; S4-C implements `@2` and S4-D is the
first slice authorized to register it in the production toolbelt/profile/recipe surfaces.
