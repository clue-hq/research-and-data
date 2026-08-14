# Production context contract fixtures

`s0_contract_fixture.json` is the provider- and database-free S0 contract manifest for
`docs/specs/FI-production-deepagent-context-composition.md`.

It freezes:

- the three model-visible artifact media types;
- the Client-KB and active-project domain-reference shapes;
- model-authored versus constitution-injected fields for the future S4 read tools; and
- the seven required states: pre-recon, post-fast-recon, post-background-recon, Project A,
  Project B, product-unselected, and product-confirmed.

`tests/projections/test_production_context_contracts.py` validates every state through the strict
S1 Pydantic contracts without provider, network, artifact-store, or database access. The fixture
does not claim S3 production composition: until S3 attaches the two conditional artifacts, the
real worker's v2 envelope reports both as unavailable.
