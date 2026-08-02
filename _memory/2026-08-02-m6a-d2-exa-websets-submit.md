# 2026-08-02 — M6A D2 Exa Websets typed submit

Branch: `platform/c8-exa-sumble-discovery`

Status: D2 code boundary complete; successful-live gate remains open because the configured Exa
team lacks Websets API access.

## Delivered

- `clue_research.adapters.exa_websets`: pinned Websets v0 request/response types, `x-api-key`
  client, one-attempt POST, bounded safe GET retry, and secret-safe error/dispatch taxonomy.
- `clue_research.durable.discovery`: atomic plan-cap reservation under batch lock and a single
  `planned/failed_retryable -> submitting` dispatch claim.
- `clue_api.exa_websets_submit`: D1-backed fingerprint/externalId compilation, request/response
  artifact persistence, duplicate/uncertain lookup reconciliation, known terminal failure,
  unknown-spend block, exact replay, cost counters, and trace attributes.
- `scripts/09_exa_websets_d2_canary.py`: explicit database, observation, generation, 20-credit cap,
  and live-create opt-in for the Insight Health/Aura fixture.
- Detailed record: `docs/specs/M06A-D2-exa-websets-paid-submit.md`.

No provider-specific lifecycle table, migration, claim write, account materialization, poller,
webhook, or seal bypass was added. D3 remains the owner of completion retrieval/pagination/cost
settlement; D4 owns identity and claims.

## Verification

- Typed transport tests: 5 passed.
- Real PostgreSQL + filesystem artifact integration: 5 passed against the named
  `clue_discovery_fixture`, migrated to D1 head `283ab57486e8`.
- Covered one-create replay, 409 reconciliation, pre-dispatch retry, terminal auth replay,
  19-credit pre-spend rejection, exact request/response bytes, counters, and traces.
- Changed-surface `ruff check`, `ruff format --check`, and `mypy` pass.
- Final D0-D2 database regression passed (`tests/adapters/test_exa_websets_d2.py`,
  `tests/api/test_exa_websets_submit_d2.py`, D1 batch tests, and D0 contract/field-policy tests;
  only the opt-in D1 committed gate skipped).

An attempted combined run also included the synthetic Stage-0 fixture test against the already
populated authoritative fixture database. That one test correctly rejected the synthetic page
artifact under the deterministic onboarding id already occupied by the harvested-page artifact
(`onboarding input id replayed with different immutable content`). It is a test-environment fixture
collision, not a D2 regression; do not weaken the immutable replay guard to make it pass.

## Live attempt

The bounded two-company workload was attempted once using observation
`2026-08-02-d2-live-v1`. Exa returned HTTP 401 because the configured team does not have Websets
API access. The operation is durably `failed_terminal/not_charged`, with 20 units reserved and 0
realized. IDs:

- batch `3ba6c1c8-a086-5048-9f61-7bc7813342c6`;
- operation `302fd31e-9b2d-4a9d-a2c5-d6d0cc04c726`;
- provider request `0712a0c5dc125016c3296230e8a4e1ef`; and
- fingerprint `7b69772be54f9cbc325c6ceed8f26d29caa1deaa029bed65867629f058411482`.

A fresh-process exact replay made zero create and zero lookup calls and returned the same durable
operation/artifacts. This validates failure/replay behavior but cannot close the required success
gate because no Webset/provider operation id exists.

## Next boundary

Configure a key from an Exa team with Websets API access. Then approve a new observation and batch
generation (for example `--observation-window ...-v2 --generation 2 --allow-live-create`). Do not
reuse or mutate the terminal v1 fingerprint. A successful 201 plus a fresh-process zero-create
replay closes D2; only then begin D3.

## Live attempt v2 — 2026-08-03

After the configured key was replaced, the bounded two-company workload was attempted once using
observation `2026-08-02-d2-live-v2`, generation `2`. Exa again returned HTTP 401: the key resolved
to a team without Websets API entitlement, and the provider response explicitly required a Pro
plan for API access. This was not an exhausted-credit response. The attempt remained
`failed_terminal/not_charged`, with 20 units reserved and 0 realized. IDs:

- batch `25edb477-bdc1-502d-a66c-48a69b695ed2`;
- operation `9786885d-bb90-4e6f-8f6d-4526ab5fb606`;
- provider request `4f2db4f51d90f391896b09b7cf4a8cb7`; and
- fingerprint `aad721b7c0690189ff74daad32c2a1ffe99d7a3a9a9c6b8938e1c98166959c0d`.

A fresh-process replay made zero create and zero lookup calls and returned the same durable
operation/artifacts. The next paid attempt requires an API-enabled team/key plus a separately
approved observation and generation (v3/generation 3); neither terminal attempt may be reused.
