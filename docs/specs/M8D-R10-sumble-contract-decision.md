# M8D R10 — Sumble wire-contract decision note

> **Status:** decided 2026-08-06 from live provider documentation; supersedes the guessed
> multi-value filter syntax that produced the live HTTP 400s.
> **Evidence:** `https://api.sumble.com/openapi.json?version=v9` fetched 2026-08-06
> (SHA-256 `cd659dd544b17562152e2d6e8ce968a97bebad2c6f68d1de14ad03c94816074d`; the S2A-pinned
> digest `8eac8f9b…` has drifted — re-pin at next contract review) and the markdown mirrors of
> `docs.sumble.com` (`/api/core-data/teams.md`, `/api/core-data/people.md`,
> `/our-data/filter-reference.md`, `/llms.txt`).

## 1. Supported API version

**v9 remains the current public contract.** `docs.sumble.com` embeds the v9 OpenAPI document
verbatim on every endpoint page and `llms.txt` indexes only v9 material. The earlier R10 ledger
hypothesis that the public docs describe "v3 endpoints and structured `job_functions: [...]`
filters" was a misreading: the structured `job_functions`/`job_levels` arrays exist only inside
the **jobs endpoint's** `select.related_people` block (`JobRelatedPeopleSelection`), not as a
filter contract, and no v3 surface exists in the current docs. **No migration is required.**
Endpoints, async People semantics, credit charging (validated up front — "you still get a
`400`/`402` up front" before any credit is charged), and the no-reveal select lists all match the
S2A implementation.

## 2. Advanced-query (`filter.query.query`) grammar

The `Query` schema documents no grammar. Every example in the live OpenAPI and docs uses exactly
one shape:

```text
<dimension> EQ '<value>' [AND <dimension> EQ '<value>']...
```

There is **no documented `IN`, `OR`, `NOT`, or parenthesized expression anywhere.** Documented
dimensions are per-endpoint:

| Endpoint | Documented query dimensions |
|---|---|
| `/v9/jobs` | technologies, technology categories, job functions, countries, hiring period |
| `/v9/people` | job functions, technologies, job levels, locations, … |
| `/v9/teams` | technologies, technology categories, job functions, hiring period — **no job level** |

This explains the live failures precisely:

- `job_function IN ('Executive', 'Operations', …)` — undocumented operator → 400;
- `job_level IN (…)` / `job_level EQ '…'` against `/v9/teams` — undocumented **dimension** for
  Teams → 400 even for a single `EQ` probe;
- `/v9/jobs` with `job_function EQ 'Software Engineer'` — documented dimension + operator →
  succeeded live (live12).

Values are taxonomy names/slugs (`filter-reference.md`; `technology EQ '<slug>'` per
`PersonAttributes.technologies`). Free-text plan values such as `'Executive'` are not guaranteed
members of the job-function taxonomy; `/v9/jobs/title-lookup` exists to normalize names.

## 3. Binding decisions

1. **Never emit undocumented grammar.** The compiler may produce only `EQ` atoms joined by `AND`,
   only on documented dimensions for the target endpoint, and only with values verified against
   the pinned taxonomy. Anything else is uncompilable and must fail closed at compile time — not
   at the provider.
2. **Committee acquisition sends no advanced query at all (initial contract).** A multi-value
   function/level selection cannot be expressed in the documented grammar (no OR/IN), and Teams
   cannot filter on job level at all. Therefore:
   - `/v9/teams`: filter = `organization_ids` only; bounded by `team_limit`,
     `related_people.max_per_team`, `job_posts.max_per_team` exactly as today.
   - `/v9/people`: filter = `organization_ids` only; `order_by_column=job_level`,
     `order_by_direction=DESC`; bounded by `people_limit`. Credit maxima are unchanged (they are
     limit-derived, not filter-derived).
   - The committee plan's `functions`/`levels`/`teams`/`personas` selectors are enforced by the
     **local post-provider admission gate** (which already matches function/level/scope from
     returned attributes) — the plan is authority for admission, not a wire filter.
3. **A future single-function `EQ` narrowing on `/v9/people` is permitted** only after a bounded
   live probe proves it, and only when the plan resolves to exactly one taxonomy-validated
   function. It is an optimization, never a correctness dependency.
4. **Failure classification.** Per the docs, requests are validated and balance-prechecked before
   charging: an HTTP 400/402/422 kickoff response is a **deterministic zero-credit rejection**,
   not an ambiguous spend. Only transport loss / timeout after dispatch remains
   `spend_outcome_unknown`. The durable ledger must retain the HTTP status and the bounded,
   sanitized provider error body (Sumble's 422 `detail` names the exact invalid member).
5. **Charging events** (unchanged, reconfirmed): Teams is synchronous and charges on response;
   People charges once on the first `succeeded` poll; kickoff and pending/running/failed polls
   charge zero.

## 4. Consequences for code

- `sumble_committee_inputs._provider_filter` (the `IN (...)` compiler) is deleted; the request
  carries `provider_filter_expression=None`. The plan selectors continue to ride the durable
  `committee_plan_ref` authority into the admission gate and (new) the account agent's context.
- `SumbleAdvancedQuery` gains a compile-time grammar guard (EQ/AND only, per-endpoint dimension
  allowlist) so no caller can regress to guessed syntax.
- `resolvers/http.get_json` / `ProviderResponseError` retain status **and** bounded sanitized
  response body; the committee/account-gap coordinators classify deterministic rejection
  separately from unknown-spend and persist typed failure evidence.
