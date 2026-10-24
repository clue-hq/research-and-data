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

## Writes (Phase 2 spike, 2026-10-22)

Checked live on the same two test CRMs at the pinned versions (hubspot `20261020_01`, salesforce
`20261018_00`) through `HttpComposioGateway.execute`. Writes were made to one seeded test record per
CRM ("Aldercare" company/account, one Aldercare contact) and each was read back and restored; every
invalid probe was read back to confirm nothing changed. No lists, campaigns, contacts or companies
were created. Slugs found with `search_tools` plus `GET /tools/{slug}?version=` for full schemas.

### What every write caller must know
- **`successful` alone does not prove a write.** Three cases seen:
  1. Salesforce `SALESFORCE_PATCH_COMPOSITE_SOBJECTS` returns `successful: true` when records
     fail — each record carries `success: false` and `errors[]` in `data.results[]`.
  2. `HUBSPOT_UPDATE_CONTACT` turned HubSpot's duplicate-email refusal into `successful: true`
     with `data.composio_execution_message = "No update performed. The property value(s) you
     provided are identical to the current values."` — **false**: the values were different and
     nothing was written. → Do not use `HUBSPOT_UPDATE_CONTACT`; use `HUBSPOT_UPDATE_CONTACTS`
     (batch) or `HUBSPOT_PARTIALLY_UPDATE_CRM_OBJECT_BY_ID`, which surface the real error.
  3. HubSpot silently ignores a write to a read-only property (`hs_object_id`): `successful: true`,
     record unchanged.
  → The write executor reads the record back after a write and compares (the before/after read
  is needed anyway for undo).
- **Salesforce does not refuse an unknown value in an unrestricted picklist.** Standard `Industry`,
  `Type`, `Rating` etc. are unrestricted in this org: `Industry = "Zz Not A Real Industry"` was
  **saved** (then restored). Only restricted picklists refuse (seen: `BillingCountryCode`). → Clue
  must check picklist values itself against the field's describe before proposing a write.
- **Error text is a JSON string, not an object.** `ExecuteResult.error` holds the CRM's raw body
  serialized as a string (Salesforce REST: a JSON list; Salesforce UI API: an object with
  `output.fieldErrors`; HubSpot: an object with `message`, `category`, `errors[].code`). Parse it
  to pick out the code; keep the raw text for the record. `data` carries `{http_error, message,
  status_code}` on these failures (same as reads).
- **Composio-side argument validation** fails before reaching the CRM: `successful: false`,
  `data = {message, status_code: 400}` (no `http_error`), error text
  `Invalid request data provided\n- Following fields are missing: {'account_id'}`.
- **Clearing a field:** HubSpot — send `""` (reads back as `""`, not `null`; treat `null` and `""`
  as the same before-value). Salesforce — `SALESFORCE_UPDATE_ACCOUNT` / `_UPDATE_CONTACT` cannot
  clear ("leave empty to keep unchanged"); `SALESFORCE_UPDATE_RECORD` with `{"Field": null}` and
  the composite tool with `null` can. → Undo of a Salesforce field that was empty needs
  `SALESFORCE_UPDATE_RECORD` or the composite tool.
- **Batch failure modes differ.** HubSpot batch update is all-or-nothing on validation: one bad
  item → whole call `successful: false` (HTTP 400), the valid item was not written (checked). The
  response schema also allows `numErrors`/`errors[]` (HTTP 207 multi-status) — not observed.
  Salesforce composite is per-record (with `all_or_none: false`) or all-or-nothing
  (`all_or_none: true`), always reported inside `data.results[]`.

### HubSpot (toolkit `20261020_01`)
| Intent | Slug (verified) | Key arguments | Batch / limit | Response (`data`) |
|---|---|---|---|---|
| (a) update company fields | `HUBSPOT_UPDATE_COMPANY` ✔ | `companyId`, `properties{name: str}` | `HUBSPOT_UPDATE_COMPANIES` ✔ `inputs[{id, properties}]`; **100** (verified: 101 → refused) | single: the company object `{id, properties, updatedAt, url, …}`; batch: `{status: "COMPLETE", results[], startedAt, completedAt}` |
| (b) update contact fields | `HUBSPOT_UPDATE_CONTACTS` ✔ (batch, use for one too) or `HUBSPOT_PARTIALLY_UPDATE_CRM_OBJECT_BY_ID` ✔ (`objectType: contacts`) | `inputs[{id, properties}]` / `objectType, objectId, properties` | 100 (same HubSpot batch API; not separately probed) | as companies. **Avoid `HUBSPOT_UPDATE_CONTACT`** (masks errors, above) |
| (c) add to / remove from a list | `HUBSPOT_UPDATE_LIST_MEMBERSHIPS` (schema; only a refusal probed — the portal has no lists) | `list_id`, `operation: add\|remove`, `record_ids[]` | one call, many ids (no stated max) | `{recordsIdsAdded[], recordIdsRemoved[], recordIdsMissing[]}` (schema). Manual/snapshot lists only. Find lists: `HUBSPOT_SEARCH_CRM_LISTS`; a record's lists: `HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS`; make one: `HUBSPOT_CREATE_LIST` (`name`, `object_type_id` e.g. `0-1`, `processing_type`) |
| (d) create contact | `HUBSPOT_CREATE_CONTACT` (schema only) | flat named properties (`email`, `firstname`, …) + `custom_properties{}`, `associations[]` | `HUBSPOT_CREATE_CONTACTS` `inputs[]` (100 by HubSpot's limit; not probed); `HUBSPOT_UPSERT_CONTACTS` `inputs[{id, idProperty, properties}]`, **1–100** in schema | `{id, properties, createdAt, …}`; batch `{status, results[], numErrors, errors[]}` (schema) |
| (e) create company | `HUBSPOT_CREATE_COMPANY` (schema only) | flat named properties (`name`, `domain`, `industry` enum, …) + `custom_properties{}` | `HUBSPOT_CREATE_COMPANIES` `inputs[{properties}]` (not probed) | `{id, properties, createdAt, …}` (schema) |
| (f) read current values | `HUBSPOT_READ_CRM_OBJECT_BY_ID` ✔ | `objectType`, `objectId`, `properties[]` (also `propertiesWithHistory[]`) | batch reads: `HUBSPOT_BATCH_READ_COMPANIES_BY_PROPERTIES`, `HUBSPOT_READ_CONTACT` (single) | `{id, properties{…}, updatedAt}`; unset properties come back `null` |

**Batch reads used by the write path (final review I-3, 2026-10-23).** The checks before the card,
before sending and after sending read HubSpot **companies** with
`HUBSPOT_BATCH_READ_COMPANIES_BY_PROPERTIES` (already on the read allowlist), 100 ids a call:
`inputs[{id}]` (required; at most 100 per the tool's description), `properties[]`, optional
`idProperty` (default `hs_object_id`), `propertiesWithHistory[]`, `archived` — from Composio's own
tool schema as `find_crm_actions` listed it on 2026-10-22 (schema only). The answer is read as
HubSpot's batch read, `{status, results[{id, properties{…}}]}`, **not verified live**: a record the
answer leaves out, and every record of a call that is refused or answered in another shape, is read
again on its own with `HUBSPOT_READ_CRM_OBJECT_BY_ID` (which tells a missing record, 404, from a
failed read), so a wrong guess costs calls, never a wrong value. Contacts stay one read per record:
`HUBSPOT_READ_CONTACTS` is allowlisted but its argument shape is recorded nowhere. List memberships
stay one `HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS` per contact: no allowlisted read takes many records.
First live use owed (Phase 3's first company write).

HubSpot errors seen (verbatim, `ExecuteResult.error`; long lists cut with `…`):
- **Invalid picklist (enum) value** — `{"status":"error","message":"Property values were not valid: [{\"isValid\":false,\"message\":\"ZZ_NOT_A_REAL_INDUSTRY was not one of the allowed options: [ACCOUNTING, … MOBILE_GAMES]\", …}]", …,"errors":[{…,"code":"INVALID_OPTION","context":{"propertyName":["industry"]}}],"category":"VALIDATION_ERROR"}` (≈9 KB: it lists every option — truncate before showing).
- **Unknown property** — `…"errors":[{"message":"Property \"zz_no_such_property\" does not exist","code":"PROPERTY_DOESNT_EXIST",…}],"category":"VALIDATION_ERROR"}`.
- **Duplicate (unique value)** — `{"status":"error","message":"Cannot set PropertyValueCoordinates{portalId=…, objectTypeId=ObjectTypeId{legacyObjectType=CONTACT}, propertyName=email, value=…} on <id>. <other id> already has that value.","correlationId":"…","category":"VALIDATION_ERROR"}` (via the batch and generic tools; masked by `HUBSPOT_UPDATE_CONTACT`).
- **Batch too large** — `{"status":"error","message":"The maximum number of inputs supported in a batch is 100. Please reduce the number of items and try again",…,"category":"VALIDATION_ERROR"}`.
- **Not found** (list) — HTTP 404 inside: `{"status":"error","message":"List does not exist with ID 999999999.",…,"category":"OBJECT_NOT_FOUND","subCategory":"ListError.LIST_ID_DOES_NOT_EXIST"}`.
- **Missing required argument** (Composio) — `Invalid request data provided\n- Following fields are missing: {'properties'}`.
- **Required CRM field:** not observable — HubSpot companies/contacts have no required properties
  for update.
- **Validation rule / permission refusal:** not observed. HubSpot has no validation rules of the
  Salesforce kind on this portal, and the token holds every write scope we need
  (`crm.objects.companies.write`, `crm.objects.contacts.write`, `crm.lists.write`). Expect
  `"category":"MISSING_SCOPES"` / HTTP 403 from the HubSpot docs, unverified.

### Salesforce (toolkit `20261018_00`)
| Intent | Slug (verified) | Key arguments | Batch / limit | Response (`data`) |
|---|---|---|---|---|
| (a) update account fields | `SALESFORCE_UPDATE_ACCOUNT` ✔ (named snake_case args, cannot clear) or `SALESFORCE_UPDATE_RECORD` ✔ (UI API, any object) | `account_id` + `description`, `industry`, … , `custom_fields{}` / `record_id`, `fields{ApiName: value\|null}`, optional `if_unmodified_since`, `allow_save_on_duplicate` (default false) | `SALESFORCE_PATCH_COMPOSITE_SOBJECTS` ✔ with `external_id_field_name: "Id"` (upsert on Id = update), `sobject_name`, `records[{attributes:{type}, Id, …}]`, `all_or_none`; **200** (verified: 201 → refused by Composio) | `UPDATE_ACCOUNT`: `{}` (204); `UPDATE_RECORD`: the full UI-API record `{apiName, fields{F:{value, displayValue}}, eTag, …}` (large); composite: `{results:[{id, success, created, errors[]}]}` |
| (b) update contact fields | `SALESFORCE_UPDATE_CONTACT` ✔ or `SALESFORCE_UPDATE_RECORD` | `contact_id` + `title`, `email`, … , `custom_fields{}` | composite as above (`sobject_name: Contact`) | `{}` (204) |
| (c) add to / remove from a campaign | `SALESFORCE_ADD_CONTACT_TO_CAMPAIGN` (refusal probed only — the org has no campaigns); `SALESFORCE_REMOVE_FROM_CAMPAIGN` (schema only) | add: `campaign_id`, `contact_id`, optional `status` (must match a configured member status); remove: `campaign_id` + `member_id` (contact/lead id) or `campaign_member_id` | one member per call; many via `SALESFORCE_POST_COMPOSITE_SOBJECTS` with `CampaignMember` records (200) | add: `{id, success, errors[]}`; remove: `{message}` (schema). Add **fails if already a member** (tool description) — check membership by SOQL first. Leads: `SALESFORCE_ADD_LEAD_TO_CAMPAIGN`. Make one: `SALESFORCE_CREATE_CAMPAIGN`. **Verified live 2026-10-23 — see § Phase 3 shapes** (remove answers `{}`, not `{message}`) |
| (d) create contact | `SALESFORCE_CREATE_CONTACT` (schema only) | `last_name` (required), `first_name`, `email`, `account_id`, … , `custom_fields{}` | `SALESFORCE_POST_COMPOSITE_SOBJECTS` `records[{attributes:{type:"Contact"}, …}]`, `all_or_none`; 200 | `{id, success, errors[]}` (schema) |
| (e) create account | `SALESFORCE_CREATE_ACCOUNT` (schema only) | `name` (required), `website`, `industry`, … , `custom_fields{}` | composite create, 200 | schema says `{id, success, errors[]}`; the tool's description says `data.response_data.id` — **unverified which**, check on first create |
| (f) read current values | `SALESFORCE_RUN_SOQL_QUERY` ✔ (exact fields), `SALESFORCE_GET_ACCOUNT` ✔ (all fields), `SALESFORCE_GET_CONTACT_BY_ID` ✔ (`fields` comma list) | `query` / `account_id` / `id, fields` | `SALESFORCE_GET_COMPOSITE_SOBJECTS` `sobject_name, ids[] (≤2000), fields[]` | SOQL `{records[], totalSize, done}`; GET returns the flat record |

Deprecated in this version (do not allow): `SALESFORCE_UPDATE_ACCOUNT_OBJECT_BY_ID`,
`SALESFORCE_UPDATE_CONTACT_BY_ID`.

Salesforce errors seen (verbatim `ExecuteResult.error`):
- **Restricted picklist** (UI API, `UPDATE_RECORD`) — `{"enhancedErrorType":"RecordError","message":"An error occurred while trying to update the record. Please try again.","output":{"errors":[],"fieldErrors":{"BillingAddress":[{"constituentField":"BillingCountryCode","duplicateRecordError":null,"errorCode":"INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST","field":"BillingAddress","fieldLabel":"Billing Country Code","message":"Billing Country Code: bad value for restricted picklist field: ZZ"}]}}}`.
- **Bad country** (REST, `UPDATE_ACCOUNT`) — `[{"message":"There's a problem with this country, even though it may appear correct. Please select a country/territory from the list of valid countries.: Billing Country","errorCode":"FIELD_INTEGRITY_EXCEPTION","fields":["BillingCountry"]}]`.
- **Unrestricted picklist** — no error: the value is saved (see above).
- **Required field** (UI API) — `{"enhancedErrorType":"RecordError",…,"fieldErrors":{"Name":[{…,"errorCode":"REQUIRED_FIELD_MISSING","field":"Name","fieldLabel":"Account Name","message":"Required fields are missing: [Name]"}]}}}`; via composite, `successful: true` with `results[0] = {"success": false, "errors": [{"fields": ["Name"], "message": "Required fields are missing: [Name]", "statusCode": "REQUIRED_FIELD_MISSING"}]}`.
- **Read-only field** — `…"errorCode":"INVALID_FIELD_FOR_INSERT_UPDATE","field":"CreatedDate",…,"message":"Unable to create/update fields: CreatedDate. Please check the security settings of this field and verify that it is read/write for your profile or permission set."`.
- **Inaccessible / non-existent referenced record** (the nearest permission-style refusal seen) — `[{"message":"insufficient access rights on cross-reference id: 701000000000000","errorCode":"INSUFFICIENT_ACCESS_ON_CROSS_REFERENCE_ENTITY","fields":[]}]` (adding a contact to a campaign id that does not exist).
- **Batch too large** (Composio) — `Invalid request data provided\n- List should have at most 200 items after validation, not 201 on parameter \`records\``.
- **Missing required argument** (Composio) — `Invalid request data provided\n- Following fields are missing: {'account_id'}`.
- **Duplicate rule: not observed.** The org's standard Account/Contact/Lead duplicate rules are
  active, but renaming one account to another's name **and** website on update was **saved**
  (restored at once) — the standard rules do not block edits here, and triggering one on create
  would have meant creating a record. Expect `errorCode: DUPLICATES_DETECTED` (REST) or a
  non-null `duplicateRecordError` (UI API) on create; `allow_save_on_duplicate` on
  `UPDATE_RECORD` overrides.
- **Validation rule: not observed** — the Developer Edition org has none; expect
  `FIELD_CUSTOM_VALIDATION_EXCEPTION` with the rule's own message.
- **Permission (profile / field-level security) refusal: not observed** — the connected user is
  the org admin. Expect `INSUFFICIENT_ACCESS_OR_READONLY` / `INVALID_FIELD_FOR_INSERT_UPDATE` (the
  read-only text above already names "security settings of this field").

## Phase 3 shapes (Task 1 spike, 2026-10-23)

Checked live through `HttpComposioGateway.execute` at the pinned versions (hubspot `20261020_01`,
salesforce `20261018_00`) with `scripts/crm_phase3_spike.py` (re-runnable; `hubspot` or
`salesforce` to run one half). **Both CRMs are verified end to end** (Salesforce after the
founder made the test user a Marketing User; see below).

### HubSpot ABM properties (`HUBSPOT_READ_ALL_PROPERTIES_FOR_OBJECT_TYPE` ✔)
Answer `data = {results: [property…]}` (companies 244 properties, contacts 404). Option values are
the wire values to write; labels are display only. All three are HubSpot-defined
(`readOnlyDefinition: true`) but writable (`readOnlyValue: false`).

| Object | Property | Type / fieldType | Options (value → label) |
|---|---|---|---|
| company | `hs_ideal_customer_profile` ("Ideal Customer Profile Tier") | `enumeration` / `radio` (single) | `tier_1` → Tier 1, `tier_2` → Tier 2, `tier_3` → Tier 3 |
| company | `hs_is_target_account` ("Target Account") | `bool` / `booleancheckbox` | `true` → True, `false` → False |
| contact | `hs_buying_role` ("Buying Role") | `enumeration` / **`checkbox` = multi-select** | `BLOCKER` → Blocker, `BUDGET_HOLDER` → Budget Holder, `CHAMPION` → Champion, `DECISION_MAKER` → Decision Maker, `END_USER` → End User, `EXECUTIVE_SPONSOR` → Executive Sponsor, `INFLUENCER` → Influencer, `LEGAL_AND_COMPLIANCE` → Legal & Compliance, `OTHER` → Other |

- `hs_ideal_customer_profile` and `hs_is_target_account` are company properties (group
  `targetaccountsinformation`); `hs_buying_role` is a contact property (group `deal_information`).
- `hs_buying_role` is multi-select: HubSpot stores several values `;`-separated (e.g.
  `CHAMPION;INFLUENCER`). A write replaces the whole value, so adding Clue's role must keep the
  roles already there (read, union, write) — not probed by a write in this spike.
- **R-12.6 confirmed** with these exact values: champion → `CHAMPION`, economic buyer →
  `BUDGET_HOLDER`, technical evaluator → `INFLUENCER`, blocker → `BLOCKER`, user → `END_USER`.
  (`DECISION_MAKER` and `EXECUTIVE_SPONSOR` exist too but are not used by R-12.6.)
- R-12.1 tiers write as `tier_1` / `tier_2` / `tier_3` (lower case), not "Tier 1".

### HubSpot lists (company list = object type `0-2`)
| Action | Slug | Arguments | Answer (`data`) |
|---|---|---|---|
| find lists | `HUBSPOT_SEARCH_CRM_LISTS` ✔ | `objectTypeId: "0-2"`, `count` (1–500), `offset`, optional `query`, `processingTypes[]`, `listIds[]` | `{lists: [], total: 0, offset: 0, hasMore: false}` on the empty portal |
| find one by name | `HUBSPOT_GET_CRM_LIST_BY_NAME` ✔ | `object_type_id`, `list_name` (matched case-insensitively), optional `include_filters` | `{list: {listId, name, objectTypeId, processingType, processingStatus, listVersion, size, createdAt, updatedAt, …}}`; missing → `successful: false`, 404 (below) |
| create | `HUBSPOT_CREATE_LIST` ✔ | `name` (portal-wide unique), `object_type_id: "0-2"`, `processing_type: "MANUAL"` | `{list: {listId: "17", name, objectTypeId: "0-2", processingType: "MANUAL", processingStatus: "COMPLETE", listVersion: 1, listPermissions, membershipSettings, createdAt, …}}` (no `size` on create) |
| add / remove | `HUBSPOT_UPDATE_LIST_MEMBERSHIPS` ✔ | `list_id` (string), `operation: "add"\|"remove"`, `record_ids[]` (company ids) | add: `{recordsIdsAdded: [id]}` (sic, "records"); remove: `{recordIdsRemoved: [id]}`; **adding an existing member: `successful: true`, `data = {}`** (no error, no id listed) |
| a record's lists | `HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS` ✔ | `object_type_id: "0-2"`, `record_id` | `{results: [{listId, listVersion, isPublicList, firstAddedTimestamp, lastAddedTimestamp}]}`; `{results: []}` after removal |

- **Company lists work with the planned actions** (R-12.3 holds); no other action needed.
- `processingType` values: `MANUAL` (seen live on the created list), `SNAPSHOT`, `DYNAMIC` (the
  tool's enum; a dynamic list was not created). Membership changes are allowed only on `MANUAL` /
  `SNAPSHOT` lists (tool description), so Clue must check `processingType == "MANUAL"` before
  reusing a list it finds by name.
- Note the field-name inconsistency: `listId` / `objectTypeId` on answers, snake_case
  `list_id` / `object_type_id` in most arguments, but `objectTypeId` in `SEARCH_CRM_LISTS`.

HubSpot list errors seen (verbatim `ExecuteResult.error`; `data` = `{http_error, message, status_code: 404}`):
- **List id does not exist** (add to `999999999`) — `{"status":"error","message":"List does not exist with ID 999999999.","correlationId":"…","context":{"listId":["999999999"]},"category":"OBJECT_NOT_FOUND","subCategory":"ListError.LIST_ID_DOES_NOT_EXIST"}`.
- **List name does not exist** (`GET_CRM_LIST_BY_NAME`) — `{"status":"error","message":"List does not exist with name Clue: spike and object type ID 0-2.","correlationId":"…","context":{"listName":["Clue: spike"],"objectTypeId":["0-2"]},"category":"OBJECT_NOT_FOUND","subCategory":"ListError.LIST_NAME_DOES_NOT_EXIST"}` — the normal "not made yet" answer, not a failure.

### Salesforce campaigns (verified 2026-10-23, after the founder made the test user a Marketing User)
First run: `SALESFORCE_CREATE_CAMPAIGN` was **refused** because the connected user (a System
Administrator, `User.UserPermissionsMarketingUser = false`) was not a Marketing User:
`successful: false`, `data.status_code: 400`, error
`[{"message":"entity type cannot be inserted: Campaign","errorCode":"CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY","fields":[]}]`.
Clue shows that refusal as "Your Salesforce user needs the Marketing User permission to create
campaigns." (`failure_kind` `permission`, the answer kept). A customer's connected user must have
"Marketing User" ticked to create campaigns. Re-run (`scripts/crm_phase3_spike.py salesforce`)
after the founder ticked it:

| Action | Slug | Arguments | Answer (`data`) |
|---|---|---|---|
| create | `SALESFORCE_CREATE_CAMPAIGN` ✔ | `name` (also optional `type`, `status`, `is_active`, dates, `parent_id`, `description`, cost fields, `custom_fields{}` — Clue sends `name`, `is_active: true` and `status: "In Progress"` (R-12.9; the active create itself is not yet probed live). An org without "In Progress" in Campaign.Status refuses with `INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST` on `Status`, shown as "Salesforce has no campaign status \"In Progress\"; ask your Salesforce admin to add it.") | `{"errors": [], "id": "701jV00000Hd83xQAB", "success": true}` — the id is under `id`; the new campaign's `Status` is "Planned". **Created active (R-12.9), verified live 2026-10-23:** `{"name", "is_active": true, "status": "In Progress"}` → read back `IsActive` true, `Status` "In Progress" |
| find | `SALESFORCE_RUN_SOQL_QUERY` ✔ | `SELECT Id, Name, IsActive, Status FROM Campaign WHERE Name = '…'` | the usual `{records, totalSize, done}`; Clue looks up by `Name`, then by `Id` once it has one (names may repeat) |
| member statuses | `SALESFORCE_RUN_SOQL_QUERY` ✔ | `SELECT Label, IsDefault, HasResponded, SortOrder FROM CampaignMemberStatus WHERE CampaignId = '…' ORDER BY SortOrder` | a new campaign has "Sent" (`IsDefault` true, `HasResponded` false) and "Responded" (`IsDefault` false, `HasResponded` true) |
| add | `SALESFORCE_ADD_CONTACT_TO_CAMPAIGN` ✔ | `campaign_id`, `contact_id` (optional `status`; omitted → the default "Sent") | `{"errors": [], "id": "00vjV000003bbV7QAI", "success": true}` (the CampaignMember id) |
| add again | `SALESFORCE_ADD_CONTACT_TO_CAMPAIGN` ✔ | the same contact | `successful: false`, HTTP 400, error `[{"message":"Already a campaign member.","errorCode":"DUPLICATE_VALUE","fields":[]}]` — Clue's SOQL membership check before sending avoids it |
| remove | `SALESFORCE_REMOVE_FROM_CAMPAIGN` ✔ | `campaign_id`, **`member_id` = the contact's id** (verified; not the CampaignMember id) | `{}`; the campaign then has 0 members (the CampaignMember row is deleted) |

- Other campaign slugs present at this version (not probed): `SALESFORCE_GET_CAMPAIGN`,
  `SALESFORCE_LIST_CAMPAIGNS`, `SALESFORCE_SEARCH_CAMPAIGNS`, `SALESFORCE_UPDATE_CAMPAIGN`,
  `SALESFORCE_ADD_LEAD_TO_CAMPAIGN`, `SALESFORCE_DELETE_CAMPAIGN` (never allowlist).

### Left in the test CRMs
- HubSpot (Conduit test portal): manual company list **"Clue: spike"** (list id `17`), empty —
  Aldercare was added and removed again. Clue never deletes (R-6.13); delete by hand if wanted.
- Salesforce (Garner test org): empty campaign **"Clue: spike"** (`701jV00000Hd83xQAB`) — one
  contact was added and removed again. Clue never deletes; delete by hand if wanted.

## Phase 4 shapes (spike, 2026-10-24)

Script: `scripts/crm_phase4_spike.py` (test CRMs only; everything named "spike"; nothing deleted).

**HubSpot (Composio managed app, Conduit AI test portal) — schema writes work.**
- `HUBSPOT_CREATE_AND_RETURN_A_NEW_PROPERTY_GROUP` (`objectType`, `name`, `label`; scope
  `crm.schemas.{objectType}.write`) → created `clue_spike` on companies. Again → refused 409
  `groupsErrorCode: GROUP_EXISTS` (setup can be re-run; treat as "already there").
- `HUBSPOT_CREATE_PROPERTY_FOR_SPECIFIED_OBJECT_TYPE` (`objectType`, `name`, `label`, `type`,
  `fieldType`, `groupName`, `options[]` of `{label, value, displayOrder, hidden}`) → enumeration
  property `clue_spike_stage`; `modificationMetadata`: archivable, not read-only. Written with
  `HUBSPOT_UPDATE_COMPANY` and read back with `HUBSPOT_READ_CRM_OBJECT_BY_ID` immediately.
- `HUBSPOT_CREATE_ASSOCIATION_LABEL` (`from_object_type`, `to_object_type`, `name`, `label`) →
  contacts↔contacts `USER_DEFINED` label, answer `results[].typeId` (1 here).
  `HUBSPOT_CREATE_OBJECT_ASSOCIATION` (`objectType`, `objectId`, `toObjectType`, `toObjectId`,
  `labels[{associationCategory: USER_DEFINED, associationTypeId}]`) linked two contacts with it.

**Salesforce (Garner Health Developer Edition) — fields are created but invisible until field-level
access is granted.**
- `SALESFORCE_CREATE_CUSTOM_FIELD` (Tooling API; `object_api_name`, `field_api_name`, `field_type`,
  `label`, `picklist_values[{full_name, label, default}]`, `length`, `external_id`, `unique`) created
  `Account.Clue_Spike_Stage__c` (picklist) and `Contact.Clue_Spike_Ext_Id__c` (text, external id,
  unique). Until field-level security grants access, every read/write says `INVALID_FIELD` "No such
  column" and the external-id upsert says `NOT_FOUND` "Provided external ID field does not exist or
  is not accessible". After granting Visible/Editable (done by hand in Setup for the spike), the
  update, SOQL read and `SALESFORCE_UPSERT_SOBJECT_BY_EXTERNAL_ID` (`sobject`, `field_name`,
  `field_value`, `fields`, `update_only`) all work.
- **Trap:** creating a field that exists answers the call `successful: true` with inner
  `success: false`, `errors[{message: "There is already a field named … on …"}]` and
  `already_exists: false` — `check_existing` does not detect it. Read the inner `success`.
- Granting access through Clue means creating a `PermissionSet`, `FieldPermissions` rows and a
  `PermissionSetAssignment` (generic `SALESFORCE_CREATE_S_OBJECT_RECORD`). Not tried in the spike
  (a security change in the org); Phase 4 does it inside the admin's one-time setup approval
  (R-13.1).
