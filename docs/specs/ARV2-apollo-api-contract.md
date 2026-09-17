# ARV2 — Apollo API contract: the schema mix-up, and the corrected adapter spec

**Status:** review document for the founders, 2026-08-23. Verified against live fetches of
docs.apollo.io on 2026-08-23 (source URLs at the end). Companions:
`ARV2-deep-agent-build-runbook.md`, `ARV2-schema-impact-audit.md`.

---

## 1. Why this document exists

The repo already contains an Apollo resolver
(`subsystems/research/clue_research/resolvers/apollo/__init__.py`). It was built deliberately as a
*documented assumed contract* — its own docstring says the live request shape is "finalized against
recorded fixtures when credentials land," and the request builder is marked `# pragma: no cover`.
Credentials never landed, so the assumptions were never checked. **Checked now: the assumed
contract is wrong on six counts.** None of this is a criticism of the original code — it was
honest about being unverified — but ARV2 must not inherit it silently.

## 2. The mix-up — repo assumption vs verified reality

| # | Repo resolver assumes | Verified reality (docs.apollo.io, 2026-08) | Severity |
|---|---|---|---|
| 1 | Base URL `https://api.apollo.io/v1` | **`https://api.apollo.io/api/v1`** | Every call 404s |
| 2 | Auth as query param `api_key=…` | **Header `x-api-key`** (OAuth Bearer exists for partner apps only) | Every call 401s; keys also leak into logged URLs |
| 3 | Flat response — reads `estimated_num_employees`, `email` at top level | Org enrichment wraps everything in **`{"organization": {...}}`**; people match returns **`person` + `request_id` (+ `waterfall`)** at top level | Normalizer reads `None` for every field |
| 4 | `core.work_email` served by `/organizations/enrich` (person + org fields in one `_PROVIDER_FIELD` map on one endpoint) | Org enrichment has **no email field at all** — emails come only from `POST /people/match` (a different endpoint, different wrapper, different credit cost) | Work email is unfetchable as written |
| 5 | Funding read from `funding_total_usd` | The real fields are **`total_funding`** (number) + `total_funding_printed` (string) + `funding_events[]` (`{id,date,news_url,type,investors,amount,currency}`); `latest_funding_stage` does exist | Funding never normalizes |
| 6 | Citing URL from response key `apollo_url`; per-record `confidence` key | **Neither key exists anywhere** in the documented responses. There is no confidence score; the resolver's `_DEFAULT_CONFIDENCE=0.9` was silently the only value ever used | Provenance URL fabricated from a fallback (`https://app.apollo.io`) |

Also: only 1 of the 5 endpoints ARV2 needs was modeled at all (no people search, no people match,
no job postings, no org search).

## 3. The corrected wire contract (what the ARV2 client implements)

Base `https://api.apollo.io/api/v1`, header `x-api-key: <key>`. Keys are **endpoint-scoped by
default** — created with a picklist of allowed endpoints; "Set as master key" grants all; an
out-of-scope call returns **403 `API_INACCESSIBLE`**. Rate limits are **per team, not per key**
(headers `x-rate-limit-minute|hourly|24-hour`, `x-*-usage`, `x-*-requests-left`, `retry-after` on
429); paid-plan enrichment endpoints run at 1,000/min uncapped daily, search at 200/min /
6,000/hr / 50,000/day.

### 3.1 `GET /organizations/enrich` — 1 credit/org
Query: `domain` | `name` | `linkedin_url` | `website` (≥1). Response `{"organization": {...}}`.
Fields ARV2 consumes (names verbatim): `id`, `name`, `website_url`, `primary_domain`,
`linkedin_url`, `founded_year`, `industry`, `industries`, `secondary_industries`, `keywords`,
`estimated_num_employees`, `annual_revenue` / `annual_revenue_printed`, `total_funding` /
`total_funding_printed`, `latest_funding_round_date`, `latest_funding_stage`, `funding_events[]`,
`current_technologies[]` (`{uid,name,category}`), `technology_names`, `departmental_head_count{}`
(19 department keys — note the doc's verbatim misspelling **`media_and_commmunication`**, matched
as-is), `organization_headcount_{six,twelve,twenty_four}_month_growth`, `raw_address`,
`street_address`, `city`, `state`, `postal_code`, `country`, `retail_location_count`,
`owned_by_organization_id`, `owned_by_organization`, `ultimate_parent_organization`,
`suborganizations`, `publicly_traded_symbol`, `logo_url`, `short_description`, `seo_description`.
Bulk: `POST /organizations/bulk_enrich`, **max 10**.

### 3.2 `POST /mixed_companies/search` — 1 credit/page, 100/page, 500-page / 50k ceiling
Filters ARV2 uses for discovery: `organization_num_employees_ranges[]` (`"min,max"` strings),
`organization_locations[]` / `_not_locations[]`, `q_organization_keyword_tags[]`,
`revenue_range[min|max]`, `currently_using_any_of_technology_uids[]`,
`total_funding_range` / `latest_funding_amount_range` / `latest_funding_date_range`, job-posting
filters (`q_organization_job_titles[]`, `organization_num_jobs_range`,
`organization_job_posted_at_range`), `q_organization_domains_list[]` (≤1,000), `page`, `per_page`.
**Response returns two arrays:** `organizations[]` (net-new) **and `accounts[]`** (companies
already saved to the team) — merge both or previously-saved accounts silently vanish from
discovery. Plus `pagination{page,per_page,total_entries,total_pages}`, `partial_results_only`.

### 3.3 `POST /mixed_people/api_search` — 0 credits (the current people-search endpoint)
The legacy `mixed_people/search` reference page 404s; `api_search` is the documented variant.
Filters: `person_titles[]`, `include_similar_titles`, `person_seniorities[]`
(enum: `owner, founder, c_suite, partner, vp, head, director, manager, senior, entry, intern`),
`person_locations[]`, `organization_ids[]`, `q_organization_domains_list[]`,
`contact_email_status[]` (`verified, unverified, likely to engage, unavailable`), technology and
job-posting filters, `q_keywords`. **The response is deliberately degraded:** `people[]` items
carry `id`, `first_name`, **`last_name_obfuscated`**, `title`, `has_email` / `has_direct_phone`
("Yes" | "Maybe: …") and an organization stub — **no emails, no full last names**. It is a
shortlist, not truth: round-trip the `id`s through `people/match` / `bulk_match` for real records.
*(Adapter rule: `api_search` output is never written to the claim store — it only feeds the
agent's candidate list.)*

### 3.4 `POST /people/match` (+ `bulk_match`, max 10) — 1 credit demographics/email, +8 if a mobile returns
Params: `id` | `linkedin_url` | `name`+`domain` | `email` | `hashed_email`, plus
`reveal_personal_emails` (not honored for GDPR-region persons) and `reveal_phone_number`
(**requires an HTTPS `webhook_url`**). Response: top-level `person` + `request_id` (signed 64-bit,
can be negative) + optional `waterfall`. Person fields: `email`, `email_status`, `title`,
`seniority`, `headline`, `departments[]`, `subdepartments[]`, `functions[]`, `linkedin_url`,
`photo_url`, `city/state/country`, `organization{}` embedded, `employment_history[]`
(`{organization_name, title, start_date, end_date, current, …}` — the career-history skeleton),
and a `contact{}` sub-object where synchronous `phone_numbers[]` live when already known.
**Phones otherwise arrive only via the webhook** (or poll `GET /webhook_result/{request_id}`;
results retained 30 days; note the async payload uses `_cd`-suffixed field names —
`type_cd`, `status_cd`, `confidence_cd` — different from the sync shape). `bulk_match` returns
`credits_consumed` as a **decimal**.

### 3.5 `GET /organizations/{id}/job_postings` — 1 credit/page, 10k display cap
Wrapper `organization_job_postings[]`; items exactly
`{id, title, url, city, state, country, posted_at, last_seen_at}`. This is the hiring-velocity
signal (replacing `sumble_jobs`).

## 4. Adapter design implications for ARV2

1. **Five operations, one client** (`platform/api/clue_api/arv2/apollo_client.py`): org_enrich,
   org_search, people_search, people_match, job_postings — each persisted through the existing
   `external_research` snapshot family before any value is surfaced to the agent (raw response =
   the artifact; evidence and replay come free).
2. **Provenance URLs:** since no `apollo_url` exists, the claim's `source_url` is the best real
   locator per record: `linkedin_url` when present, else `website_url`, else the constructed
   `https://app.apollo.io/#/organizations/{id}` app link — recorded as an Apollo *record*
   reference, with the field value carrying Apollo as `source_key` (tier 1, method `api` per the
   stamping matrix). No fabricated confidence: Apollo claims carry the adapter's fixed
   source-level confidence, documented as such.
3. **The existing `resolvers/apollo` module is left untouched** (old lane, unwired, its tests
   frozen). The ARV2 client is new code; if the old resolver is ever revived it must be corrected
   to this contract first.
4. **Webhook receiver** (`POST /arv2/apollo/phone-results` route) is Day-3 scope; until then
   `reveal_phone_number` stays false and enrichment is email-only. The poll fallback
   (`/webhook_result/{request_id}`) covers a missed delivery within the 30-day window.
5. **Rate-limit discipline:** limits are per *team* — the client reads the `x-*-requests-left`
   headers and backs off on `retry-after`; fleet concurrency multiplies against one shared budget.
6. **Error handling:** Apollo's error body shape is explicitly undocumented ("varies by
   endpoint") — the client parses both `error` and `message` keys defensively and treats 403 as
   *key-scope misconfiguration* (a loud, actionable refusal naming the endpoint scope to grant),
   never a retry.
7. **GDPR behavior is a feature:** withheld personal emails for EU persons arrive as an honest
   miss; the adapter records `unavailable`, not an error.

## 5. Verification protocol before first claim write (Day-2 gate)

Per the repo's own locked decision #3 (live SDK boundaries verified against recorded fixtures):
with the purchased key, record one real fixture per operation (org enrich on
`digestivehealthcare.net`, org search on the GI-practice ICP filters, people search + match on one
known member, job postings on any org), commit sanitized fixtures, and pin the normalizers
against them in `tests/arv2/test_apollo_contract.py`. Only then does `apollo_*` output become
eligible for `write_claims`. Anything the docs left [UNVERIFIED] — the exact 422/429 body, the
`personal_emails[]` reveal shape, plan-tier credit pools — is resolved from those fixtures and
recorded back into this document.

**Sources fetched (2026-08-23):** docs.apollo.io/reference/{organization-enrichment,
bulk-organization-enrichment, organization-search, people-api-search, people-enrichment,
bulk-people-enrichment, organization-jobs-postings, poll-webhook-result, search-for-contacts,
rate-limits, status-codes} and docs.apollo.io/docs/{api-pricing, create-api-key}.
