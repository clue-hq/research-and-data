# Composio REST API — verified notes (Task 0 spike, 2026-10-20)

Checked live against a development Composio project, a HubSpot developer test account and a
Salesforce Developer Edition org, using plain `httpx` against REST **v3.1**. No keys or account ids
are recorded here. Later tasks code against these notes; where they contradict the plan, these
notes win.

## Basics
- Base URL `https://backend.composio.dev/api/v3.1`; auth header `x-api-key: <project API key>`.
- Every tool execution response (HTTP 200) has top-level keys `data`, `error`, `successful`,
  `log_id`.

## Auth configs — `GET /auth_configs/{id}`
- Fields used: `auth_scheme` (`OAUTH2`), `is_composio_managed`, `status` (`ENABLED`),
  `toolkit.slug`, `credentials.scopes`, `expected_input_fields[]`.
- **Managed apps fix their scopes.** Trimming scopes in the dashboard did not change them:
  HubSpot keeps its 33 defaults; Salesforce managed uses `full`, `refresh_token`, `openid`. Our own
  OAuth apps (before real customers, R-5.2) are where scopes are chosen.
- Salesforce `expected_input_fields`: `subdomain` (default `login`; "your real instance is detected
  after you sign in") and `suffix.one` = instance endpoint (default `/services/data/v67.0`). The
  hosted connect page asks for both; **`login` worked for a Developer Edition org**, so the connect
  card does not need to ask for a subdomain.

## Connect link — `POST /connected_accounts/link`
- Body: `auth_config_id`, `user_id`, `callback_url` (optional `connection_data` for prefilled
  connection fields).
- Response (201): `link_token`, `redirect_url` (`https://connect.composio.dev/link/lk_…`),
  `expires_at` (ISO, **10 minutes**), `connected_account_id`.
- **Links are fragile when shared:** a link opened by anything else first (e.g. a chat link
  preview) showed "invalid or expired" while still inside its 10 minutes; its account stayed
  `INITIALIZING`. Unused links end `EXPIRED` with reason "Connection expired before authorization
  was started". → Mint a fresh link per click and open it directly (the plan already does this).
- After approval the browser is sent to `callback_url`. (The query parameters Composio appends —
  expected `status` and `connected_account_id` per the docs — still to be confirmed from a real
  redirect; the backend must verify the account by id regardless.)

## Connected accounts
- `GET /connected_accounts?user_ids=<id>&limit=…` → `items[]` with `id`, `toolkit.slug`, `status`,
  `status_reason`, `created_at`.
- `GET /connected_accounts/{id}` → same fields.
- Statuses seen: `INITIALIZING`, `INITIATED`, `ACTIVE`, `EXPIRED`.

## Tools
- Search: `GET /tools?toolkit_slug=hubspot&query=<text>&limit=<n>` → `items[]` with `slug`, `name`,
  `description`, `input_parameters` (JSON Schema), `output_parameters`, `tags`, `scopes`,
  `scope_requirements`, `version`, `available_versions`, `is_deprecated`, `toolkit`.
- Filter by tag: `GET /tools?toolkit_slug=hubspot&tags=readOnlyHint&limit=300`.
- **Tags exist and mark reads:** e.g. `HUBSPOT_SEARCH_DEALS` → `['Search', 'openWorldHint',
  'readOnlyHint', 'idempotentHint']`. Counts tagged `readOnlyHint`: HubSpot 133, Salesforce 150.
  Use as a second guard beside our own read allowlist.
- One tool: `GET /tools/{slug}` (optional `?version=`).

## Execute — `POST /tools/execute/{slug}`
- Body: `arguments` (object), `connected_account_id`, `user_id`, `version`.
- **Pinned versions work**, including older ones (e.g. `HUBSPOT_SEARCH_DEALS` at `20261015_00`
  and `20261020_01`). Current on 2026-10-20: hubspot `20261020_01`, salesforce `20261018_00`. Pin
  these in configuration.
- **Tool-level failure** (e.g. bad SOQL): HTTP 200, `successful: false`, `error` = the CRM's own
  message, `data` = `{http_error, message, status_code}`. → map to `crm_action_failed` with the
  message verbatim.
- **Expired connection:** HTTP **410**, body `{"error": {"message": "Connected account … is in
  EXPIRED state", "code": 1820, "slug": "ActionExecute_ConnectedAccountExpired", "status": 410,
  "request_id": …, "suggested_fix": …}}` (no `data`/`successful`). → `ComposioError.kind =
  "connection_expired"` keyed on the `slug`.

## Calls checked
| Action | Result |
|---|---|
| `HUBSPOT_WHO_AM_I` | `data.data.account_type = DEVELOPER_TEST`, portal id, time zone |
| `HUBSPOT_LIST_GRANTED_SCOPES` | the granted scope list |
| `HUBSPOT_READ_ALL_PROPERTIES_FOR_OBJECT_TYPE` (`objectType: deals`) | works without `crm.schemas.deals.read`; **~164 KB** — results must go to files |
| `HUBSPOT_RETRIEVE_ALL_PIPELINES_FOR_SPECIFIED_OBJECT_TYPE` (`deals`) | pipelines with stages (`id`, `label`, `metadata`) |
| `HUBSPOT_SEARCH_DEALS` | `{results, total}`; paging token at `paging.next.after` when present |
| `SALESFORCE_GET_ORG_LIMITS` | per-limit `{Max, Remaining}`, incl. `DailyApiRequests` |
| `SALESFORCE_RUN_SOQL_QUERY` | `{done, records, totalSize}` (+ `nextRecordsUrl` when not done); sub-queries on `OpportunityContactRoles` and `OpportunityHistories` accepted |

## Test data
Both test CRMs start **empty** (HubSpot 0 deals; the new Salesforce Developer Edition org 0
opportunities — no sample data). Seeding is needed before the analysis can be exercised. (Seeded 2026-10-20: see `status.md`.) HubSpot rejects contact emails on the reserved `.test` domain (`INVALID_EMAIL`), so seeded contacts use `@<name>.example.com` while company domains stay `<name>.test`.
