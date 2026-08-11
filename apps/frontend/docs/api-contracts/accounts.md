# Accounts API contract

Status: implemented FI-2 read contract with authenticated frontend cutover.

Owner for backend integration: Aaryan.

As of the 2026-08-11 FI-2 cutover, Accounts and Contacts have no runtime fixture
mode. Their repositories always use the live `/frontend/v1` read surface.
Server Component reads derive the Clerk provider proof on the Next server,
resolve the selected workspace through Clue's membership store, and send
`Authorization` plus `X-Clue-Workspace-Id` to FastAPI. Browser-originated API
requests use the same resolver through the same-origin `/api/clue/**` BFF.
`CLUE_ACCOUNTS_API_BASE_URL`, `CLUE_WORKSPACE_ID`, legacy `X-Workspace-Id`, and
the unauthenticated Next rewrite are no longer part of this flow.

The frontend-authored proposal below is retained as history. The “As-built
backend read API” and “Authenticated frontend cutover” sections are the current
contract where the proposal differs.

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
2. Configure authentication plus the server-only `CLUE_API_BASE_URL`; there is
   no Accounts-specific origin or workspace environment variable.
3. Keep browser calls same-origin through `/api/clue`; Server Components call
   the same authenticated backend primitive directly and never loop back
   through their own Route Handler.
4. Derive provider proof and `X-Clue-Workspace-Id` on the Next server. Never
   accept a browser-authored workspace or authorization header.
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
when it is off) and is served under `/frontend/v1`. The router's isolated
development fallback accepts `X-Workspace-Id`; an authenticated application
overrides that resolver with Lane B's principal service, which requires provider
proof plus `X-Clue-Workspace-Id`. The production frontend uses only the latter.
`GET /frontend/v1/health` remains an unscoped liveness probe.
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
  "summary": {
    "state": "available",
    "paragraphs": ["Acme is a multi-site healthcare operator."],
    "researchOutcome": "completed"
  },
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
  "coverage": {
    "researchedFieldCount": 6,
    "unresolvedFieldKeys": ["healthcare.npi"],
    "unresolvedFields": [
      {
        "fieldKey": "healthcare.npi",
        "description": "National Provider Identifier (deterministic registry id; tier-1)."
      }
    ]
  }
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
`overview` (the same typed prose state as Account `summary`),
`professionalFacts` (`{ fieldKey, value, observedAt, provider, restricted }`),
and `evidence` (`{ provider, observedAt }`, no URLs).

The error envelope is the one documented above. Codes in use:
`UNAUTHORIZED` (401, missing workspace in the isolated development resolver;
the authenticated application instead rejects missing provider proof or
`X-Clue-Workspace-Id` through its principal resolver), `INVALID_CURSOR` (400),
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
  `unresolvedFields` carries the same keys with their field-registry descriptions,
  so a new dynamic/industry-pack field can explain itself without a frontend map.
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
§9, the D-4–D-7 entry. These no longer gate anything — they are the decisions the
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

### Frontend seam as flipped (Task 6, 2026-08-08)

The Zod schemas (`src/features/accounts/model/`) and HTTP adapters
(`src/features/accounts/data/`) are now written against the wire above. Five
decisions were taken at the adapter and are recorded here rather than left
implicit.

1. **The adapters unwrap on the list side only.** `GET /accounts` and
   `GET /accounts/{id}/contacts` parse `{data, meta}`; the account detail and
   the contact profile parse the bare object. This closes the "decide at the
   adapter flip" note in the single-resource deviation above — the backend
   keeps its shapes and no wrapper is added.
2. **`addedVia` is parsed as `z.string()`, not an enum.** The backend stores the
   raw registered channel behind a CHECK constraint (`discovered` / `imported` /
   `manual` / `directive` today) *specifically* so a read does not crash on a
   channel a later migration adds, so the frontend keeps the same posture:
   sentence-cased through a generic prettifier with no lookup table to drift.
   `researchStatus`, `persona` and `freshness` — closed backend enums — are the
   only `z.enum`s on this surface, plus `not_launchable`, ratified forward.
3. **SUPERSEDED 2026-08-11 — no Accounts-specific base URL or fixture
   switch.** Accounts and Contacts always use `/frontend/v1` through the shared
   server-only `CLUE_API_BASE_URL`. Removing `CLUE_ACCOUNTS_API_BASE_URL` means
   an unset variable can no longer silently substitute unrelated demo data.
4. **SUPERSEDED 2026-08-11 — tenancy comes from the authenticated session.**
   `CLUE_WORKSPACE_ID` and legacy `X-Workspace-Id` are removed from the
   frontend. The Next server resolves the provider session and selected Clue
   membership, then emits `Authorization` and `X-Clue-Workspace-Id`. FastAPI
   remains the final authorization authority and refuses missing, revoked, or
   cross-workspace memberships.
5. **`error.code` is carried, never switched on — and a `404` is not
   automatically an empty workspace.** A failed read raises
   `ClueApiError { code, status, requestId }` with `code` typed as a plain
   string. A `404` resolves to `null` only when the envelope names a
   record-level code — `ACCOUNT_NOT_FOUND` or `CONTACT_NOT_FOUND` — on an
   endpoint that has one. Every other `404` throws: a wrong base URL, a wrong
   prefix, or the read flag being off all produce the framework's generic
   `NOT_FOUND`, and rendering those as "this workspace has no accounts" hides a
   misconfiguration behind a plausible empty state. The list endpoint has no
   domain `404` by contract (an unknown project is an empty page), so a `404`
   there always throws. Errors are parsed leniently: a non-envelope body (a
   proxy error page) degrades to a status-only message that names the three
   things worth checking.
6. **The list is paginated, visibly.** The table renders one keyset page and a
   "Showing X loaded of Y accounts" footer with a Load-more control that appends
   through `meta.nextCursor` (a server action, so the workspace header and base
   URL never reach the browser). The authored filters and search run over the
   rows already loaded, and the footer says so when a filter is active —
   truncation is stated, not silent.
7. **Every contacts row links to its own contact route.** The row's name cell is
   the link and the route param drives which profile is fetched, so rows 2..n
   are not dead clicks. The gated preview drawer — which could only ever open
   for one hard-coded contact — was removed rather than left as an affordance
   that works on one row.
8. **SUPERSEDED 2026-08-11 — workspace tabs carry no runtime fixture data.**
   Slice 1 still serves no activity feed or artifact index, and account insights
   arrive on the Overview detail contract. `account-workspace.repository.ts`
   therefore returns an explicit empty model for every real account, with each
   tab explaining that the capability is not served yet. It neither invents a
   URL nor preserves the former OpenAI demo workspace.

### Authenticated frontend cutover (2026-08-11)

Server Component reads call the authenticated backend primitive directly; they
do not perform a loopback HTTP request to Next. Browser-originated reads and
mutations use `/api/clue/**`, whose Route Handler uses that same primitive. The
shared path proves the Clerk session, re-loads Clue membership, strips
browser-authored authorization/workspace headers, and sends only the server
bearer plus `X-Clue-Workspace-Id` to FastAPI. `next.config.ts` no longer carries
the unauthenticated `/frontend/v1` rewrite.

There is no runtime fixture mode. The former Accounts, Account detail, Contact,
and Account-workspace fixture modules were removed. Test-local payload builders
may exercise Zod and repository contracts, and browser acceptance may seed
durable Postgres rows, but neither is reachable as an application fallback.
With the Insight Health onboarding-only seed, `GET /frontend/v1/accounts`
returns `{data: [], meta: {total: 0, nextCursor: null}}` and the page renders
“No accounts exist in this workspace yet.”

**Fields dropped from the frontend schemas (D-7).** `referralFit`,
`directAccessFit`, `recallFit`, `overallFit`, `locationCount`, `employeeBand`,
`influence`, `researchIsRefreshing`, `avatarUrl`, `previewTitle`, non-LinkedIn
`socials`, and every `*Label` display string are gone from the models, the
fixtures and the components. The "Overall fit" and "Locations" table columns
went with them and a "Projects" column took their place; the contacts table's
"Influence" column became "Committee role" (with its confidence) plus
"Signals". What those placeholders stood in for now renders dynamically: the
detail's registry-driven `neutralFacts` and `projectSections[].insights` are
laid out generically off `fieldKey` through a key→label prettifier, so an
industry pack's custom field appears with no schema change and no adapter
change. `logoUrl` is bound but always null, and the existing initials mark is
the rendering until `core.company_logo_url` exists.

**Verified live, 2026-08-08.** A throwaway database was migrated to head, seeded
with the canonical slice-1 workspace (the same fixture
`tests/integration/test_fi2_slice1_read_layer.py` builds: two projects, three
accounts, a governed committee, mixed statuses), and served by the real app with
`CLUE_FRONTEND_READ_ENABLED=true`; the frontend ran against it through
`next dev`. All four endpoints returned payloads the schemas parsed unchanged,
both directly and through the same-origin rewrite. The screens rendered live:
two ICP versions inside one project section, a fit-without-intent score shown as
`Intent —`, the unattributed bucket labelled as such, a withheld title rendering
`Withheld` beside a real one, `1 signal type`, and the null-heavy
membership-less row showing five honest absences. The full error matrix behaved
as specified — `ACCOUNT_NOT_FOUND` (404) resolved to the not-found page while a
wrong base URL produced a loud `500` naming the base, the mount and the flag;
`UNAUTHORIZED` (401), `INVALID_CURSOR` (400) and `VALIDATION_ERROR` (422) all
returned the documented envelope. CORS answered the exact listed dev origin and
refused an unlisted one. One live finding is recorded for whoever runs
`next dev` next: Next.js blocks cross-origin dev resources, so browse the dev
server on the SAME host string it prints (`localhost`), not `127.0.0.1`, or
server actions are refused.

**SUPERSEDED by FI-2 slice 4.** Account summary and Contact overview now have
typed live prose fields. The contact page's hard-coded "Last updated yesterday"
remains removed; no unsupported recency is inferred.

### Typed Account recovery (FI-2 slice 2, 2026-08-11)

Expected Account-list bootstrap failures are return values at the Accounts
data seam, not uncaught Server Component exceptions. The page renders one of
five recovery states from this closed frontend vocabulary; it never renders a
backend message, framework trace, exception digest, status code, or stack.

| Recovery kind | Transport evidence | User action |
| --- | --- | --- |
| `session_expired` | `401`, `AUTHENTICATION_REQUIRED`, or `SESSION_INVALID` | Sign in again. |
| `workspace_selection` | `WORKSPACE_SELECTION_REQUIRED`; during the auth-contract transition, the existing `WORKSPACE_FORBIDDEN` plus the exact safe server reason `a workspace selection is required` | Focus the authenticated workspace selector and choose a membership. |
| `forbidden` | `WORKSPACE_FORBIDDEN`, `PERMISSION_DENIED`, `IDENTITY_NOT_PROVISIONED`, `USER_DISABLED`, `MEMBERSHIP_STATE_CHANGED`, or another `403` | Open the access-denied recovery surface; never retry in place. |
| `service_unavailable` | Network refusal/timeout, `AUTHENTICATION_UNAVAILABLE`, `408`, `429`, or `5xx` | Retry the Account read. This is the only state with a retry action. |
| `contract_error` | Generic route `404`, validation/configuration status, malformed success JSON, Zod mismatch, or missing frontend/backend configuration | Contact support with the safe request reference when one exists; no reload loop. |

The open backend `error.code` set remains intact below this mapping. Unknown
expected HTTP refusals fail closed into `contract_error`; unexpected programming
exceptions still throw so engineering error boundaries and observability see a
real defect. The request id is copied into the recovery value, but the backend
message is discarded before the value reaches a component.

The protected session bootstrap uses the same distinction for failures that
occur before an Account page can render: provider/session service outages get a
retryable protected-service state, and frontend/backend configuration or wire
schema failures get a non-retryable support state. Authentication expiry and
membership refusal continue through the established sign-in and access-denied
routes. An absent, stale, or ambiguous workspace cookie routes to the explicit
workspace chooser; the frontend no longer silently selects the first membership.

### Linked Contact integrity and accessibility (FI-2 slice 3, 2026-08-12)

Account detail, the Contacts list and Contact detail now consume one governed
committee composition seam. That seam owns project membership, latest-run/product
scope, canonical Contact survival, strongly-bound role/persona eligibility and
workspace display policy once. The resulting invariant is structural: every
`committee[].contactId` and every Contacts-row `id` is addressable through
`GET /frontend/v1/accounts/{accountId}/contacts/{contactId}` under the same
workspace and policy. A member that does not clear that rule is omitted from
every linked surface together; the frontend does not author a broken link or
invent a non-navigable profile.

Addressability does not require a display name, title, LinkedIn identity,
signals, or completed deep research. An eligible Contact may therefore serve
`name: null`, unknown professional fields and zero signal types while retaining
a valid profile. A policy-withheld title remains `null` with
`titleRestricted: true`. A stale merged-Contact URL serves the canonical
survivor and sets `redirectedFrom` to the requested loser id.

The visible fallback for `name: null` is “Unnamed contact”; the opaque id is
never rendered as a name. Contact avatars beside a visible name are decorative
and absent from the accessibility tree. Contacts-grid rows are named
`Contact <name>` and their profile links are separately named
`Open <name> profile`, so the avatar, row and link no longer concatenate the
same person name. Selection behavior is unchanged and remains owned by its
separate bulk-actions slice.

### Live prose and user-facing vocabulary (FI-2 slice 4, 2026-08-12)

Account detail serves `summary`; Contact detail serves `overview`. Both are a
discriminated union derived from the current Lane-E synthesis claim:

| `state` | `paragraphs` | `researchOutcome` | Meaning |
| --- | --- | --- | --- |
| `available` | one or more strings | `completed` or `needs_review` | Current synthesis is displayable. |
| `not_composed` | `[]` | `null` | No live synthesis claim exists. |
| `restricted` | `[]` | `null` | A synthesis record exists but cannot be served. |

`account.summary` is excluded from `neutralFacts`, and `contact.overview` is
excluded from `professionalFacts`; prose is never rendered as a generic fact.
The UI selects the summary/overview copy from this state alone. In particular,
it does not infer “research incomplete” from project status while displaying a
completed synthesis.

The backend keeps semantic values unchanged (`1b_plus`, `product_led`,
`c_level`, `economic_buyer`, `champion`, `technical_evaluator`, `blocker`). The
frontend owns stable labels (`$1B+`, `Product-led`, `C-level`, `Economic buyer`,
`Champion`, `Technical evaluator`, `Blocker`) and applies them at render time,
so filters and model data retain the machine values. Unknown ordinary prose is
not sentence-cased. Dynamic research gaps use
`coverage.unresolvedFields[].description` from the effective field registry;
the key-to-label prettifier remains only a fallback heading.

Authenticated browser acceptance used the durable Insight Health workspace and
followed the live Accounts row into Northstar's preview, its Contacts table, and
all served Contact shapes. The Account summary and Dana Buyer overview rendered
their completed prose without contradictory incomplete-research copy; Chris
Blocker and the unnamed Contact rendered the not-composed state honestly. Named,
withheld, unnamed and stale-merged Contact URLs all survived a direct reload.
Every browser request resolved through the authenticated session-to-principal
chain and `/frontend/v1` with `200`, and the same-origin BFF Account-detail
request returned `200`. Browser rendering used the stable labels above while
API/model contract coverage retained the raw semantic values.
