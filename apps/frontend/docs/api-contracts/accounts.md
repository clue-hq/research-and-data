# Accounts API contract

Status: frontend-ready proposal for backend implementation.

Owner for backend integration: Aaryan.

The frontend currently uses `fixtureAccountsRepository` and
`fixtureAccountDetailsRepository`, plus dedicated contact and account-workspace
repositories. Setting `CLUE_API_BASE_URL` activates the corresponding HTTP
repositories without changing page or component code.

## Shared response conventions

- Base path: `/api/v1`
- Content type: `application/json`
- Identifiers are opaque strings.
- Dates, when added, use ISO 8601 UTC strings.
- List pagination is cursor-based.
- Authentication is intentionally not assumed here; the chosen session layer
  should be applied consistently to every endpoint.

Error envelope:

```json
{
  "error": {
    "code": "ACCOUNT_NOT_FOUND",
    "message": "Account was not found",
    "requestId": "req_01J..."
  }
}
```

## Implemented frontend read contract

### `GET /api/v1/accounts`

Returns accounts for the Accounts table.

Query parameters:

| Parameter | Type | Notes |
| --- | --- | --- |
| `search` | string | Case-insensitive company-name search |
| `researchStatus` | enum | `not_started`, `in_progress`, `fully_enriched`, `failed` |
| `overallFit` | enum | `High`, `Medium`, `Low` |
| `projectId` | string | Return accounts associated with this project context |
| `sort` | enum | `name_asc`, `name_desc`, `project_asc`, `project_desc`, `fit_score_desc`, `fit_score_asc` |
| `cursor` | string | Opaque cursor from the previous response |
| `limit` | integer | Recommended default 50, maximum 100 |

Success response:

```json
{
  "data": [
    {
      "id": "openai",
      "name": "OpenAI",
      "logoPath": "/logos/openai.svg",
      "websiteUrl": "https://openai.com",
      "researchStatus": "fully_enriched",
      "researchIsRefreshing": true,
      "overallFit": "High",
      "fitScore": 75,
      "revenueBand": "$1 - $10M",
      "employeeBand": "100-200",
      "locationCount": 10,
      "primaryProjectId": "10m-landing-page-campaign",
      "projects": [
        {
          "id": "10m-landing-page-campaign",
          "name": "10x revenue campaign"
        },
        {
          "id": "conference-2026",
          "name": "conference 2026"
        }
      ]
    }
  ],
  "meta": {
    "total": 1,
    "nextCursor": null
  }
}
```

Current frontend validation is defined in
`src/features/accounts/model/account.ts`. Until a shared contract package is
introduced, that schema is the authoritative shape for this screen.

`projects` is a many-to-many account relationship. An account can participate
in multiple project contexts without duplicating the canonical account record.
`primaryProjectId` must reference one member of `projects` when present and is
used for stable project sorting; account name is the secondary sort key.
`projectId` filters by membership in the full `projects` array. Project is the
campaign/context boundary in Clue; Campaign is not a separate atomic entity.
Populate the Project filter catalog from `GET /api/v1/projects/sidebar`
(documented in `projects.md`) rather than inferring the complete catalog from a
paginated account response.

`logoPath` is frontend-compatible today. A future backend may instead return a
stable `logoUrl`; if that change is made, update the schema and adapters
together rather than mapping it inside table components.

### `GET /api/v1/accounts/:accountId`

Returns the record used by both the account preview drawer and the full account
page. The frontend validates this response in
`src/features/accounts/model/account-detail.ts`.

Success response:

```json
{
  "data": {
    "id": "openai",
    "name": "OpenAI",
    "previewTitle": "Synergy medical group",
    "logoPath": "/logos/openai-detail.svg",
    "websiteUrl": "https://openai.com",
    "websiteLabel": "www.openai.com",
    "researchStatus": "fully_enriched",
    "sizeLabel": "Large enterprise",
    "locationsLabel": "Global",
    "revenueLabel": "Private / not disclosed",
    "referralFit": "Medium",
    "directAccessFit": "High",
    "recallFit": "Medium",
    "overallFit": "High",
    "summaryParagraphs": ["Account summary paragraph"],
    "businessParagraphs": ["Business description paragraph"],
    "fitCriteria": [
      {
        "id": "enterprise-growth",
        "matched": true,
        "title": "Operates a large and rapidly growing enterprise business",
        "evidence": "Supporting account evidence"
      }
    ],
    "contacts": [
      {
        "id": "denise-dresser",
        "name": "Denise Dresser",
        "avatarUrl": "https://cdn.cluehq.ai/contacts/denise-dresser.jpg"
      }
    ],
    "insights": [
      {
        "id": "enterprise-revenue",
        "source": "link",
        "title": "OpenAI says enterprise now represents more than 40% of revenue",
        "dateLabel": "April 8, 2026",
        "url": "https://openai.com/"
      }
    ],
    "activity": [
      {
        "id": "contacts-added",
        "kind": "contacts",
        "text": "Clue added 14 new contacts",
        "timeLabel": "1 hour ago"
      }
    ]
  }
}
```

Valid `source` values are `link`, `linkedin`, and `x`. Valid `kind` values are
`contacts`, `summary`, and `created`.

Return `404` with the shared error envelope when `accountId` is unknown.

`previewTitle` exists because the source MVP frame displays a contextual drawer
title separately from the normalized account name. The backend may return the
same value for both fields when that distinction is not needed.

### `GET /api/v1/accounts/:accountId/contacts`

Returns the contact-table rows. Contact records are kept outside the account
detail response so the backend can paginate and refresh them independently.

Each record includes `id`, `name`, `title`, `persona`, `personaTone`,
`influence`, `avatarUrl`, `emailStatus`, and a `socials` array. Runtime
validation lives in `src/features/accounts/model/account-contact.ts`.

`avatarUrl` is supplied by the backend or enrichment provider and should be a
stable, cacheable CDN URL. The frontend accepts either an absolute URL or a
public fixture path, displays initials when the image fails, and does not
scrape LinkedIn in the browser.

Recommended query parameters: `search`, `persona`, `influence`, `cursor`, and
`limit`.

### `GET /api/v1/accounts/:accountId/contacts/:contactId`

Returns one complete contact profile, including account identity, recent-signal
label, LinkedIn/X links, overview paragraphs, and evidence records. Return `404`
when either identifier is unknown.

### `GET /api/v1/accounts/:accountId/workspace`

Returns the modular payload used by the Insights, Artifacts, and Activity tabs:

```json
{
  "data": {
    "accountId": "openai",
    "insights": [
      {
        "id": "cro-appointment",
        "source": "link",
        "title": "Denise Dresser appointed Chief Revenue Officer",
        "sourceLabel": "https://openai.com/index/leadership",
        "url": "https://openai.com/",
        "summary": "Evidence summary"
      }
    ],
    "artifacts": [
      {
        "id": "finance-review",
        "title": "10x revenue ad",
        "type": "presentation",
        "thumbnailPath": "/artifacts/finance-review.png",
        "lastEditedLabel": "Last edited today"
      }
    ],
    "activity": [
      {
        "id": "contacts-added",
        "kind": "contacts",
        "text": "Clue added 14 new contacts",
        "timeLabel": "1 hour ago"
      }
    ]
  }
}
```

The schema is in `src/features/accounts/model/account-workspace.ts`. The
endpoint can later be split by tab if payload size or update frequency warrants
it without changing the presentation components.

## Planned write and configuration endpoints

### `POST /api/v1/accounts/query`

Executes the multi-condition filter shell without encoding a rule tree into a
long URL. The frontend validates rule shapes in
`src/features/accounts/model/account-query.ts`.

```json
{
  "search": "open",
  "rules": [
    {
      "id": "account-filter-1",
      "field": "project",
      "operator": "is",
      "value": "10m-landing-page-campaign",
      "join": "and"
    },
    {
      "id": "account-filter-2",
      "field": "overallFit",
      "operator": "is",
      "value": "High",
      "join": "and"
    }
  ],
  "sort": "project_asc",
  "cursor": null,
  "limit": 50
}
```

Allowed fields are `name`, `project`, `researchStatus`, `overallFit`,
`fitScore`, `revenueBand`, `employeeBand`, and `locationCount`. Allowed
operators are `contains`, `does-not-contain`, `is`, `is-not`, `greater-than`,
and `less-than`; the backend must reject invalid field/operator combinations
with `400 INVALID_FILTER_RULE`. Project values are project IDs, not display
labels. Apply rules in authored order, then sort, then cursor pagination.
Return the same response envelope as `GET /api/v1/accounts`.

### `POST /api/v1/accounts`

Create an account.

```json
{
  "name": "Acme",
  "websiteUrl": "https://acme.example"
}
```

Returns `201` with one account object.

### `PATCH /api/v1/accounts/:accountId`

Update editable account fields. Use partial-update semantics and return the
updated account object.

### `DELETE /api/v1/accounts/:accountId`

Archive or delete an account according to the backend retention policy.
Returns `204` on success.

### `POST /api/v1/accounts/:accountId/research`

Start or refresh research. Returns `202`.

```json
{
  "data": {
    "jobId": "research_01J...",
    "accountId": "openai",
    "status": "queued"
  }
}
```

### `GET /api/v1/accounts/:accountId/research`

Return current job status so the frontend can reconcile live state.

### `GET /api/v1/accounts/table-config`

Return the current user's saved column visibility and ordering.

### `PUT /api/v1/accounts/table-config`

Persist column visibility, ordering, widths, sort configuration, and the
authored filter rules. Project IDs must remain opaque stable identifiers.

## Integration checklist

1. Implement both frontend read contracts exactly as the validated shapes
   above.
2. Configure `CLUE_API_BASE_URL` only on the Next.js server.
3. Confirm CORS/network topology if the Next server and API use different
   origins.
4. Add the chosen authentication header or server session inside
   `createHttpAccountsRepository`.
5. Replace `logoPath` only through the schema and repository boundary.
6. Add contract tests using representative success, empty, and error payloads.
7. Keep table and detail records independently fetchable so list responses do
   not grow with research paragraphs, contacts, insights, and activity.
8. Keep accounts canonical and connect them to projects many-to-many; do not
   introduce Campaign as a second project-like account entity.
9. Apply filtering before sorting and cursor pagination, with account name as
   the project-sort tie-breaker.

## As-built backend read API (FI-2 slice 1, 2026-08-08) — ratified deviations

The proposal above is unchanged and stays the frontend's authored view. This
section records what the backend actually serves after FI-2 slice 1, so the Zod
schemas and HTTP adapters are written against the real wire. Every shape below
is copied from a passing test: `tests/integration/test_fi2_slice1_read_layer.py`
drives all four endpoints over one seeded workspace, and
`tests/api/test_frontend_read_*.py` cover each endpoint on its own.

The surface is flag-gated (`frontend_read_enabled`, default off; the routes 404
when it is off), is served under `/frontend/v1`, and requires the tenant header
`X-Workspace-Id` on every data request (the one exception is
`GET /frontend/v1/health`, an unscoped liveness probe that carries no tenant).
It is read-only: no create, update, delete,
research-launch, query-POST, table-config, `search`, or `sort` endpoint exists
yet, and the only list query parameters are `projectId`, `cursor`, and `limit`.

### Endpoints and wire shapes

| Endpoint | Envelope |
| --- | --- |
| `GET /frontend/v1/accounts` | `{ data: [...], meta: { total, nextCursor } }` |
| `GET /frontend/v1/accounts/{accountId}` | the account object itself, no `data` wrapper |
| `GET /frontend/v1/accounts/{accountId}/contacts` | `{ data: [...], meta: { total } }` |
| `GET /frontend/v1/accounts/{accountId}/contacts/{contactId}` | the contact object itself, no `data` wrapper |

List row:

```json
{
  "data": [
    {
      "id": "0f0f4e8c-4d1a-4f0b-9f2d-2b7a1c0d5e11",
      "name": "Acme",
      "domain": "acme.test",
      "employeeCount": 1200,
      "revenueBand": "100m_500m",
      "logoUrl": null,
      "projects": [
        {
          "projectId": "prj_a",
          "name": "Project A",
          "addedVia": "discovered",
          "addedAt": "2026-08-01T12:00:00Z"
        },
        {
          "projectId": "prj_b",
          "name": "Project B",
          "addedVia": "imported",
          "addedAt": "2026-08-01T12:05:00Z"
        }
      ],
      "primaryProjectId": "prj_a",
      "scores": [
        {
          "projectId": "prj_a",
          "fit": 0.81,
          "intent": 0.4,
          "icpKey": "alpha",
          "icpVersion": 1,
          "scoredAt": "2026-08-01T12:00:00Z"
        },
        {
          "projectId": "prj_b",
          "fit": 0.55,
          "intent": null,
          "icpKey": "beta",
          "icpVersion": 3,
          "scoredAt": "2026-08-01T12:00:00Z"
        }
      ],
      "researchStatus": [
        { "projectId": "prj_a", "status": "needs_review" },
        { "projectId": "prj_b", "status": "in_progress" }
      ],
      "updatedAt": "2026-08-01T12:00:00Z"
    }
  ],
  "meta": { "total": 3, "nextCursor": null }
}
```

Account detail:

```json
{
  "id": "0f0f4e8c-4d1a-4f0b-9f2d-2b7a1c0d5e11",
  "name": "Acme",
  "domain": "acme.test",
  "aliases": ["acme"],
  "registryIds": {},
  "hqGeo": null,
  "redirectedFrom": null,
  "neutralFacts": [
    {
      "fieldKey": "core.employee_count",
      "value": 1200,
      "freshness": "fresh",
      "observedAt": "2026-08-01T12:00:00Z",
      "provider": "clearbit"
    }
  ],
  "projectSections": [
    {
      "projectId": "prj_a",
      "name": "Project A",
      "addedVia": "discovered",
      "addedAt": "2026-08-01T12:00:00Z",
      "scores": [
        { "fit": 0.81, "intent": 0.4, "icpKey": "alpha", "icpVersion": 1, "scoredAt": "2026-08-01T12:00:00Z" }
      ],
      "narratives": [
        {
          "fieldKey": "account.value_narrative",
          "value": { "persona": "economic_buyer", "argument": "...", "angle_label": "roi" },
          "observedAt": "2026-08-01T12:00:00Z",
          "provider": "narrative_synthesis"
        }
      ],
      "insights": [
        {
          "fieldKey": "fi2read.campaign_insight",
          "value": "insight for A",
          "observedAt": "2026-08-01T12:00:00Z",
          "provider": "deep_research"
        }
      ]
    },
    {
      "projectId": null,
      "name": null,
      "addedVia": null,
      "addedAt": null,
      "scores": [],
      "narratives": [],
      "insights": []
    }
  ],
  "committee": [
    {
      "contactId": "3a1c...",
      "name": "Dana Buyer",
      "persona": "economic_buyer",
      "roleOnCommittee": "economic_buyer",
      "projectIds": ["prj_a", "prj_b"]
    }
  ],
  "coverage": { "researchedFieldCount": 6, "unresolvedFieldKeys": [] }
}
```

Contacts row and profile:

```json
{
  "data": [
    {
      "id": "3a1c...",
      "name": "Dana Buyer",
      "title": "VP Finance",
      "titleRestricted": false,
      "persona": "economic_buyer",
      "roleOnCommittee": { "value": "economic_buyer", "confidence": 0.87 },
      "linkedinUrl": "https://linkedin.com/in/dana-buyer",
      "projectIds": ["prj_a", "prj_b"],
      "signals": { "typeCount": 1 }
    }
  ],
  "meta": { "total": 1 }
}
```

The profile is that row plus `accountId`, `accountName`, `redirectedFrom`,
`professionalFacts` (`{ fieldKey, value, observedAt, provider, restricted }`),
and `evidence` (`{ provider, observedAt }`, no URLs).

The error envelope is the one documented above. Codes in use:
`UNAUTHORIZED` (401, missing `X-Workspace-Id`), `INVALID_CURSOR` (400),
`ACCOUNT_NOT_FOUND` (404), `CONTACT_NOT_FOUND` (404), `VALIDATION_ERROR` (422,
malformed identifier or out-of-range `limit`), `INTERNAL_ERROR` (500). Every
response also carries an `X-Request-Id` header matching `error.requestId`.

**`error.code` is an OPEN set — do not close the Zod enum.** Those six are the
codes this surface raises deliberately, but the framework layer beneath it also
emits generic ones: `NOT_FOUND` (an unknown route under the `/frontend/v1`
prefix — a path typo, not a missing account) and `BAD_REQUEST`. Parse `code` as
a string, branch on the known values, and fall back to the message for anything
else; a closed `z.enum([...])` turns a new backend code into a client-side
parse crash instead of a displayable error.

Pagination is keyset over `(createdAt, id)` descending, newest account first.
`limit` defaults to 50 and is capped at **200** (this supersedes the maximum of
100 proposed above); a value outside `1..200` is a `422`. `cursor` is opaque and
must not be parsed; a cursor the endpoint did not issue is a `400`, never a
silent restart. `projectId` filters by membership; an unknown project returns an
empty page, not a `404`, and the rows it does return still carry their full
`projects` array. `meta.nextCursor` is `null` on the last page.

### Ratified deviations from the proposal

- **`projects[]` is `{ projectId, name, addedVia, addedAt }` — the proposed
  `{ id, name }` widened, not narrowed** (ratified 2026-08-08; was the Task-6
  blocker). `projectId` replaces `id`, `name` is the project record's own name
  resolved by a read-layer join, and `addedVia` / `addedAt` are new: they carry
  how and when the project acquired the account, which the proposal had no slot
  for. The accounts table can therefore search and sort on `project.name`
  (`src/features/accounts/model/account-query.ts`, lines 80-91) with no second
  endpoint and no client-side catalog join. The same `name` is on the detail's
  `projectSections[]`, resolved by the **same** batched read, so the table and
  the detail cannot disagree about a project's name.
  `name` is `string | null`: it is `null` for the unattributed section
  (`projectId: null` — there is no project to name) and for any section whose
  project id this workspace holds no `project` row for. That second case is
  reachable only on the detail, whose section ids can come from run lineage
  (which carries no foreign key to `project`); a membership row's project always
  resolves. Never render the id as a fallback name — an unnamed section is the
  honest rendering. Name resolution is workspace-scoped, so a foreign project id
  resolves to `null` rather than leaking another tenant's label. Cost: one
  batched statement per response, not one per membership.
- **`employeeBand: "100-200"` becomes `employeeCount: 1200`, an integer.** The
  backend holds a headcount claim, not a band; banding is a display decision the
  frontend owns.
- **`revenueBand` keeps its name but changes value space.** It now carries the
  backend claim vocabulary (for example `100m_500m`), not the proposed
  `"$1 - $10M"` display string, and it is **not** a guaranteed closed enum — the
  value is whatever the field's writer produced. Same key with a different
  vocabulary is exactly the mismatch a Zod `z.string()` will accept and a label
  map will silently mis-render, so treat it as an opaque token and render through
  a lookup with a fallback.
- **`scores[]` is a list keyed by `(projectId, icpKey, icpVersion)`, on both the
  list row and the detail section** — one project can score an account under
  several ICPs and versions, so a single `fitScore` would require guessing a
  winner. No representative run is chosen.
- **The two score surfaces are not symmetric: the list is attributed-only, the
  detail is not.** A list row's `scores[]` comes from a read that inner-joins
  run lineage to a project, so a score whose run maps to no project cannot
  appear there at all. The detail partitions the same claims into sections, so
  such a score lands in the `projectId: null` unattributed section. Consequence:
  the detail can show a score the list row does not, and the difference is
  always exactly the unattributed section. Reconcile list↔detail on attributed
  sections only; never compute a row-level "score count" from the detail.
- **`narratives[]` is plural, one per persona** — value narratives are written
  per persona, and collapsing them would drop the persona structure.
- **`researchStatus` is a per-project array, not a scalar**, with the
  backend-honest vocabulary `not_started | in_progress | needs_review |
  completed | suspended`. This supersedes the proposed
  `not_started | in_progress | fully_enriched | failed`. There is no `failed`:
  a crashed worker re-queues the job and suspends the fleet, so the honest state
  is always "halted, awaiting a human". `completed` means the job's own terminal
  outcome, not the stronger "fully enriched". An entry may name a project the
  account has **no** membership row for (research was launched for a project that
  no longer targets it); that is reported rather than hidden, so do not assume
  `researchStatus[].projectId` is always a member of `projects[]`. The committee
  and contacts union does **not** match that honesty: it iterates memberships
  only, so a non-member project that researched the account is visible in
  `researchStatus[]` / `projectSections[]` while its committee members surface
  nowhere — deliberate (the alternative attributes one project's committee to an
  account it does not target) and an anomaly state that should not occur.
- **`titleRestricted` (row) and `restricted` (profile fact) mark withheld
  values** — a display-denied field is served absent with the marker and with no
  provenance, while a field the backend simply does not hold is absent and
  unmarked. Absence and redaction are different answers and the wire says which.
- **`provider` is the raw backend source key** (`clearbit`, `sumble`,
  `committee_inference`, ...). No source display-name surface exists yet; a
  label belongs in a future source-registry column, not in an adapter map.
- **`observedAt` is the claim's observed time, falling back to its collection
  time** — the same reference-time rule the merge uses.
- **`signals` is `{ typeCount }`, not `{ count }` — it counts signal TYPES**
  (ratified 2026-08-08; the per-field unit was kept and the wire field renamed to
  say so). `typeCount` is how many of a two-family whitelist
  (`contact.facet.recent_post`, `contact.facet.public_appearances`) currently
  hold a display-eligible statement, so it is bounded by that whitelist's size
  and a list-valued field with five items still counts **1**. Label it as signal
  types ("2 signal types"), never as a count of items or posts.
- **Merged accounts redirect on the detail only.** `GET /accounts/{id}` follows a
  merged loser to its survivor and sets `redirectedFrom` to the requested account
  id. Account lists carry no redirect vocabulary at all — a merged loser simply
  does not appear as a row, and the `meta.total` does not count it.
- **The contact endpoints follow a merged account silently.** Both accept a
  merged-loser account id and serve the survivor's committee, but the contacts
  list has no marker of any kind, and the profile's `redirectedFrom` tracks a
  merged **contact** only: request a survivor contact under a merged account id
  and it is `null` while `accountId` is the survivor's. So a client that wants to
  correct a stale account link must compare `accountId` with the id it asked for.
- **`logoUrl` is always `null`** for now (it replaces `logoPath`); no logo
  pipeline exists, and the field is present so it can start returning values
  without a schema change.
- **`committee` and the contacts list are empty on live data today.** The
  governed committee reads the M8D research references, whose production writer
  is behind the R1 quarantine until the R11 DEEP-phase bridge lands. An empty
  committee is a `200` with an empty list, not a `404`. The seam itself is
  proven by fixtures, so no adapter change is needed when R11 lands.
- **Single-resource reads are not wrapped in `data`.** The account detail and
  the contact profile return the object itself; only the two lists use
  `{ data, meta }`. Either the adapters unwrap on the list side only, or the
  backend adds a wrapper — decide at the adapter flip.
- **Fact `value` payloads are opaque backend JSON.** `neutralFacts[].value`,
  `insights[].value`, `narratives[].value`, `professionalFacts[].value`, plus
  `registryIds` and `hqGeo`, are passed through verbatim from the claim, so their
  internal keys are the writer's (snake_case, e.g. the narrative's `angle_label`)
  and are not part of this layer's camelCase vocabulary. Type them as unknown
  JSON per `fieldKey`, not as a camelCase object.
- **A project section's `projectId` and membership fields are independently
  nullable.** `projectId: null` is the unattributed bucket (claims whose run maps
  to no project — manual ingestion and the documented lineage exemptions), always
  served last and only when it has content. `addedVia` / `addedAt` are also
  `null` for a project that produced research on the account **without** a
  membership row; that state should not occur, so it is reported rather than
  hidden. A project with a membership and no work still gets an empty section,
  because "targeted, nothing produced yet" is a real state. `name` is nullable on
  the same axis — see the `projects[]` entry above.
- **`coverage.researchedFieldCount` reads stronger than it is.** It counts the
  distinct fields holding at least one live, non-rejected claim for the account
  — from **any** writer, research or not: a stage-0 interview answer, a manual
  or CRM import, and a scoring write all increment it. It is "how many fields do
  we hold a value for", not "how many fields research completed", and it is not
  a percentage of anything (there is no denominator — the field registry is open
  by registration). Do not render it as research progress or drive a completion
  meter from it; the honest research-side companion is `unresolvedFieldKeys`,
  which names fields research *asked for* and could not answer.
- **`updatedAt` is the `account_entity` row's update time, not research or claim
  recency.** It moves when the entity record itself changes (identity
  resolution, a merge, an alias or registry-id write) and does **not** move when
  a new claim, score, or narrative lands on the account. A "last updated" or
  "last researched" badge that wants research recency must not use it — read the
  relevant `observedAt` (facts, narratives, insights) or `scoredAt` instead.
  `updatedAt` is a correct cache/sort key for the entity row, nothing more.
- **The detail carries no research status.** Status is a `(account, project)`
  fact served on the list row; a detail or preview badge must read it from the
  list response until a later slice adds it.
- **No display strings anywhere.** `sizeLabel`, `locationsLabel`,
  `revenueLabel`, `websiteLabel`, `dateLabel`, `timeLabel`, and
  `previewTitle` are not served; the frontend formats from semantic values.
  `domain` replaces `websiteUrl`. `freshness` is an enum that emits exactly
  `fresh` and `stale`: it reports the merge's own two states (a past-TTL winner
  is labelled, never dropped), and the backend's third disposition, `expired`,
  is a retention age-out that can never win a merge and so never reaches this
  wire.

### Ratified 2026-08-08 (FI-1 D-4–D-7, plus the operational rulings)

Founder-ratified; the record is `docs/specs/FI-accounts-contacts-contract-gap-review.md`
§9 (top entry). These no longer gate anything — they are the decisions the
adapter flip (Task 6 of the slice-1 plan) implements. Most are frontend schema
decisions over the shapes above; where one implies further backend work, that is
called out rather than assumed.

1. **D-4 RATIFIED — nullable/optional everywhere the backend can be correctly
   empty, plus the honest availability/redaction vocabulary** (mirroring the
   backend's `ResearchItemState`), so the UI can tell **"not researched"** from
   **"researched, not found"** from "withheld by policy". No fabricated
   placeholders anywhere. Slice 1 ships a deliberately narrower form —
   nullability everywhere plus a boolean `restricted` / `titleRestricted` for the
   policy-withheld case — because this read layer serves the merge's current
   value and holds no per-field research-attempt state on the contact path; the
   account-level approximation is `coverage.unresolvedFieldKeys`, which names
   fields research asked for and could not answer. Adopt the full vocabulary in
   the schemas, and expect the backend to widen the wire when the per-field state
   exists. Nullability alone is required before any HTTP repository is enabled —
   the current schemas crash on it.
2. **D-5 RATIFIED — display strings leave the wire; the frontend owns all display
   formatting.** The backend sends semantic values. `timeLabel`, `dateLabel`,
   `editedLabel`, `sizeLabel`, `revenueLabel`, and `locationsLabel` become ISO
   timestamps and semantic values that the frontend formats; `personaTone` stays
   frontend-side.
3. **D-6 RATIFIED — the frontend adopts the backend vocabularies as-built,
   including `not_launchable` NOW.** `researchStatus` widens to the honest
   backend set; slice 1 serves `not_started | in_progress | needs_review |
   completed | suspended` and does **not** yet serve `not_launchable`, which
   depends on the launch surface owned by Lane D (FI-1 D-9) — it is ratified into
   the vocabulary ahead of Lane D so the schema is not widened twice. `persona`
   and `roleOnCommittee` adopt the four backend personas. `emailStatus` widens
   (`available | lookup | pending | unavailable` at least), which is moot on this
   surface because slice 1 serves no email data at all (G3). **`overallFit` is
   NOT invented** — the backend serves raw `scores[].fit`, and no tier badge,
   band cut, or adapter constant is introduced on this slice. `activity.kind`
   widens to the backend event kinds with a projection-layer label map (no
   activity endpoint exists in slice 1). `freshness` and `addedVia` are new enums
   this slice introduces.
4. **D-7 RATIFIED — the fixture-only fields are DROPPED for MVP, because they
   were placeholders for industry-pack custom fields.** That is the founder's
   clarification and it changes what "dropped" means: the hardcoded fixture
   fields — `referralFit` / `directAccessFit` / `recallFit`, `locationCount`,
   `xUrl` requiredness, non-LinkedIn `socials`, `influence`,
   `researchIsRefreshing`, `avatarUrl` (G1: no avatar pipeline, and the browser
   does not scrape) — are removed from the schemas outright, **not** preserved,
   respecced, or reproduced as constants. What they were standing in for is
   already served: when an account's industry carries an associated pack, that
   pack's custom fields arrive **dynamically** through the detail's
   registry-driven `neutralFacts` / `projectSections[].insights`, which are split
   by the field registry's declared species and enumerate nothing. So the
   frontend renders pack custom fields generically off `fieldKey` — a new pack
   field appears with no schema change and no adapter change — instead of binding
   named slots. Two notes carried over unchanged: the backend already serves an
   `intent` score the frontend does not use, and slice 1 does serve
   `roleOnCommittee.confidence` (the real signal behind `influence`).
   `logoPath` stays specified as backend work, not dropped: the cheapest real fix
   is a `core.company_logo_url` field plus a materializer, which is what
   `logoUrl: null` is waiting for.
5. **`signals` is a count of signal TYPES — the per-field unit is kept, the wire
   field is renamed `typeCount`.** See the `signals` entry in the ratified
   deviations above: a list-valued facet contributes 1, and the chip must be
   labelled as signal types, never as items.
6. **CORS posture: a same-origin proxy in production, an exact `localhost` origin
   in development, wildcard never.** Production serves the frontend and this API
   same-origin — the frontend proxies `/frontend/v1` rather than calling it
   cross-origin — so no cross-origin credentialed request is made at all (the
   proxy route is the adapter flip's to build); development allows the exact
   localhost origin, listed explicitly. `"*"` is refused structurally — the app
   raises at startup rather than allowing it, because Starlette echoes the origin
   when a wildcard is combined with credentials, which under trusted-header
   tenancy is a real cross-tenant exposure. A phase-2 cross-origin POST surface
   needs a deliberate widening decision, not a config tweak.
7. **`projects[].name` is served by the read layer** (the plan-owner addendum to
   the same ruling) — see the `projects[]` entry in the ratified deviations
   above. The former Task-6 blocker is closed.
