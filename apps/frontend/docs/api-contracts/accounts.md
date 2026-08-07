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
