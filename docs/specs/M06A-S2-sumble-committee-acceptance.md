# M06A S2A — Sumble committee contract and normalizer acceptance

- **Parent boundary:** `M06A-exa-websets-sumble-discovery-integration.md`, Slice S2
- **Expanded roadmap:** `M8B-exa-sumble-account-deep-integration-roadmap.md`, A0 and S2A
- **Implementation branch:** `platform/c8-account-profiling-integration`
- **S1 dependency:** consume commit `ae05542`; do not rebuild S1 in this slice
- **Provider API:** Sumble REST `v9`
- **Pinned OpenAPI SHA-256:**
  `8eac8f9b74afb74f1bd4f593ee2baa4547d2ca80947feea581e91e551a97c887`
- **Contract captured:** 2026-08-03
- **S2A status:** mechanical contract/normalizer gate `PASS`; S2B durability not started

This acceptance record freezes the wire-level contract for Sumble Teams and People before durable
acquisition is added. S2A is pure provider-local modeling, request construction, normalization, and
recorded-fixture verification. It makes no live Sumble request, adds no operation table, binds no
production committee source, and reveals no email or phone.

## 1. Authoritative sources

The implementation contract was checked against:

- `https://docs.sumble.com/api/api`
- `https://docs.sumble.com/api/core-data/teams`
- `https://docs.sumble.com/api/core-data/people`
- `https://docs.sumble.com/our-data/filter-reference`
- `https://api.sumble.com/openapi.json?version=v9`

The docs/OpenAPI boundary is interpreted fail-closed. Endpoint prose governs semantic restrictions
when a shared OpenAPI enum is broader. In particular, the generated person-attribute enum contains
`email` and `phone` for reuse across response shapes, while Teams prose says contact details are
not available for `related_people`. S2A explicitly whitelists non-contact attributes and rejects a
snapshot containing either contact field.

## 2. Decided contract

### 2.1 Teams

- `POST /v9/teams` is synchronous.
- S2 uses filter mode with exactly one canonical Sumble `organization_id` per request.
- `limit` and `offset` bound returned teams; `max_per_team` independently bounds related people and
  job posts.
- The select list is explicit. S2 never uses `"all"`, because that list and its cost can grow.
- `team_id`, name, and `sumble_url` are free identity fields returned by the endpoint.
- Each returned team costs one base credit, plus one per selected team attribute, plus one per
  returned related person, plus one per returned job post.
- `breadcrumbs` are the provider-returned parent chain. Team membership/confidence is a
  provider-inferred association derived from job functions, technologies, teams, locations, and
  title similarity; it is not asserted as an actual reporting line.
- Teams do not roll subsidiaries into the parent. The request must name every explicitly admitted
  organization id; S2A starts with the exact canonical account only.

### 2.2 People

- `POST /v9/people` search mode is organization-scoped and asynchronous on v9.
- Kickoff sends `filter`, explicit non-contact `select.attributes`, `limit`, and `offset`; it returns
  `status=pending`, `request_id`, and zero credits charged.
- Polling sends `{ "request_id": "..." }` alone. Status is `pending`, `running`, `succeeded`, or
  `failed`.
- The OpenAPI marks the generic response `id` required while the async prose examples omit it.
  S2 keys provider operation identity on the required `request_id` and tolerates an absent envelope
  `id`.
- Credits are charged exactly once on the first poll returning `succeeded`. Later successful polls
  return `credits_used=0`; failed jobs cost zero.
- Search cost is one base credit plus one per paid selected attribute per returned person. Name is
  free; `person_id` and `sumble_url` are always-included provider identity.
- S2 explicitly requests LinkedIn URL, title, function, level, location, country, and current
  employer. It never requests `email`, `phone`, `person_score`, `technologies`, or `"all"`.
- `person_id` is a stable provider provenance key, not yet a platform strong identity key. The
  existing committee admission gate continues to require LinkedIn URL or verified email. Because
  S2 performs no reveal, a result without LinkedIn is retained in the provider snapshot but is
  dropped or reviewed during S2C rather than weakening admission.
- `current_employer.organization_id` must equal the exact requested organization for a candidate to
  be target-locked.

### 2.3 No-reveal boundary

S2A and the first S2 release do not select, normalize, persist as candidate data, or return email or
phone. A non-null contact value in a recorded/live response is a contract violation, not a useful
extra field. Contact reveal later requires a separate list-mode operation, identity, jurisdiction,
use-class, budget, receipt, and independent-validation contract.

## 3. Deliberately unresolved or deferred

- Sumble's `Query` schema wraps one opaque advanced-query string but the published API contract does
  not provide a complete grammar suitable for generating arbitrary expressions. S2A accepts only a
  prevalidated non-empty expression from a later committee-plan compiler; it never interpolates
  arbitrary user text.
- People list-mode `related_people` exposes manager/direct-report directions but no maximum number
  of returned related people. Because every returned relationship costs one credit, S2A does not
  call it. It remains deferred until a returned-row cap exists or a separate governance decision
  defines an acceptable bounded contract.
- Teams and People share the account's aggregate 10-request-per-second rate limit. S2B owns durable
  throttling, dispatch, polling, retry classification, and wake scheduling.
- Request fingerprints, freshness/reuse windows, immutable operation/snapshot persistence, monetary
  conversion, and exactly-once settlement are S2B responsibilities over these frozen wire models.

## 4. Provider-neutral normalization contract

The S2A normalizers return provider-local immutable records, not claims and not inferred committee
roles:

- a team record preserves team id, organization id, name/URL, breadcrumb chain, activity,
  technologies, job functions, locations, bounded job refs, and bounded related-person refs;
- a person record preserves person id, source URL, LinkedIn, name, title, function, level, location,
  country, and current-employer identity;
- every relationship carries an explicit `provider_inferred` basis;
- returned rows for another employer are rejected from the exact-account view;
- a charged/matched row without the provider identity needed to normalize it fails loudly rather
  than disappearing;
- additive unknown fields are tolerated and preserved only in the raw immutable snapshot; they do
  not silently enter the normalized contract.

S2C later maps ready snapshot records into the stable `CommitteeSource` seam. The existing M8
worker—not Sumble—owns champion, economic-buyer, technical-evaluator, blocker, and persona
classification.

## 5. S2A exit gate

S2A passes only when recorded contract tests prove:

1. no Teams or People request can select email, phone, or `"all"`;
2. one exact organization and every returned-row axis are bounded;
3. documented worst-case credits are deterministic before dispatch;
4. People pending/running/failed responses charge zero and successful polling has one settlement
   owner;
5. Teams and People additive response fields are tolerated;
6. a non-null contact reveal fails closed;
7. team breadcrumbs and person/team confidence are labeled provider-inferred, never reporting-line
   truth;
8. current-employer mismatch is rejected from the account map;
9. a charged malformed row fails loudly;
10. no network socket, database migration, provider operation, committee role inference, contact
    entity, or claim is created by this slice.

## 6. Mechanical acceptance evidence

- 27 S2A contract tests pass for exact request bodies, all row caps, credit maxima, async status
  transitions, free repeated-success polling, additive drift, no-reveal rejection, identity
  semantics, exact-employer locking, malformed charged rows, and relationship labels.
- Existing S1 Sumble resolver tests and committee/deep regressions pass with the new provider-local
  modules present.
- Ruff passes across `libs`, `subsystems`, `platform`, and `tests`.
- Mypy passes across 486 source files.
- Import-linter keeps all 24 dependency contracts.
- The full suite has one unrelated pre-existing failure:
  `tests/memory/test_memory_offline.py::test_no_production_code_outside_memory_touches_the_substrate`
  still finds the existing direct `clue_memory` import in
  `platform/api/clue_api/trial/stage0_runtime.py`.
- One full-suite DSAR test was initially denied sandbox access to localhost PostgreSQL and passed
  when rerun with localhost permission.
- No live Sumble endpoint, provider credit, database migration, durable provider operation,
  contact entity, claim, or production source binding was created.

S2A is closed mechanically. S2B is the next implementation slice: durable Teams request and People
submit/poll acquisition over immutable snapshots and exactly-once provider-credit settlement.
