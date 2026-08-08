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

## As-built backend read API (FI-2 slice 1, 2026-08-08) — ratified deviations & pending items

The proposal above is unchanged and stays the frontend's authored view. This
section records what the backend actually serves after FI-2 slice 1, so the Zod
schemas and HTTP adapters are written against the real wire. Every shape below
is copied from a passing test: `tests/integration/test_fi2_slice1_read_layer.py`
drives all four endpoints over one seeded workspace, and
`tests/api/test_frontend_read_*.py` cover each endpoint on its own.

The surface is flag-gated (`frontend_read_enabled`, default off; the routes 404
when it is off), is served under `/frontend/v1`, and requires the tenant header
`X-Workspace-Id` on every request. It is read-only: no create, update, delete,
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
        { "projectId": "prj_a", "addedVia": "discovered", "addedAt": "2026-08-01T12:00:00Z" },
        { "projectId": "prj_b", "addedVia": "imported", "addedAt": "2026-08-01T12:05:00Z" }
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
    { "projectId": null, "addedVia": null, "addedAt": null, "scores": [], "narratives": [], "insights": [] }
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
      "signals": { "count": 1 }
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

Pagination is keyset over `(createdAt, id)` descending, newest account first.
`limit` defaults to 50 and is capped at **200** (this supersedes the maximum of
100 proposed above); a value outside `1..200` is a `422`. `cursor` is opaque and
must not be parsed; a cursor the endpoint did not issue is a `400`, never a
silent restart. `projectId` filters by membership; an unknown project returns an
empty page, not a `404`, and the rows it does return still carry their full
`projects` array. `meta.nextCursor` is `null` on the last page.

### Ratified deviations from the proposal

- **`scores[]` is a list keyed by `(projectId, icpKey, icpVersion)`, on both the
  list row and the detail section** — one project can score an account under
  several ICPs and versions, so a single `fitScore` would require guessing a
  winner. No representative run is chosen.
- **`narratives[]` is plural, one per persona** — value narratives are written
  per persona, and collapsing them would drop the persona structure.
- **`researchStatus` is a per-project array, not a scalar**, with the
  backend-honest vocabulary `not_started | in_progress | needs_review |
  completed | suspended`. This supersedes the proposed
  `not_started | in_progress | fully_enriched | failed`. There is no `failed`:
  a crashed worker re-queues the job and suspends the fleet, so the honest state
  is always "halted, awaiting a human". `completed` means the job's own terminal
  outcome, not the stronger "fully enriched".
- **`titleRestricted` (row) and `restricted` (profile fact) mark withheld
  values** — a display-denied field is served absent with the marker and with no
  provenance, while a field the backend simply does not hold is absent and
  unmarked. Absence and redaction are different answers and the wire says which.
- **`provider` is the raw backend source key** (`clearbit`, `sumble`,
  `committee_inference`, ...). No source display-name surface exists yet; a
  label belongs in a future source-registry column, not in an adapter map.
- **`observedAt` is the claim's observed time, falling back to its collection
  time** — the same reference-time rule the merge uses.
- **`signals.count` counts current display-eligible statements** over a
  two-family whitelist (`contact.facet.recent_post`,
  `contact.facet.public_appearances`). A list-valued field counts as **1**;
  whether a richer unit (per item) is wanted is an open founder question.
- **Merged accounts redirect**: `GET /accounts/{id}` and the contact profile
  serve the survivor with `redirectedFrom` set to the requested id. Lists carry
  no redirect vocabulary — a merged loser simply does not appear as a row.
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
  `insights[].value`, `narratives[].value`, `registryIds`, and `hqGeo` are
  passed through verbatim from the claim, so their internal keys are the
  writer's (snake_case, e.g. the narrative's `angle_label`) and are not part of
  this layer's camelCase vocabulary.
- **The detail carries no research status.** Status is a `(account, project)`
  fact served on the list row; a detail or preview badge must read it from the
  list response until a later slice adds it.
- **No display strings anywhere.** `sizeLabel`, `locationsLabel`,
  `revenueLabel`, `websiteLabel`, `dateLabel`, `timeLabel`, and
  `previewTitle` are not served; the frontend formats from semantic values.
  `domain` replaces `websiteUrl`, and `freshness` (`fresh` | `stale`) is served
  as an enum.

### Pending founder ratification (FI-1 D-4–D-7)

These gate the adapter flip (Task 6 of the slice-1 plan); none of them changes
the backend shapes above.

1. **D-4 — absence and redaction vocabulary in the Zod schemas.** Every
   enrichment field is nullable/optional on this wire, and redaction is carried
   by `titleRestricted` / `restricted`. The current schemas reject that and must
   adopt it before any HTTP repository is enabled.
2. **D-5 — display strings leave the frontend schemas.** The `*Label` fields
   have no backend source and must be formatted client-side from the ISO
   timestamps and semantic values above.
3. **D-6 — enum adoption.** `researchStatus` takes the five-value backend
   vocabulary, `persona` and `roleOnCommittee` take the four backend personas,
   `freshness` and `addedVia` are new enums, and `overallFit` needs a ruling
   (tier badge from `scores[].fit`, or a versioned policy band) since the
   backend serves raw scores only.
4. **D-7 — drop or respec the fields with no backend data.**
   `referralFit` / `directAccessFit` / `recallFit`, `locationCount`,
   `influence`, non-LinkedIn `socials`, `avatarUrl`, `researchIsRefreshing`, and
   the `emailStatus` widening are all unserved in slice 1; each is either
   dropped from the schemas or specified as new backend work.
