# CRM settings contract (Settings → Integrations)

Resolved 2026-10-26 on `feat/crm-settings-integrations`. **The backend is the truth**: the routes are
`platform/api/clue_api/frontend_read/crm.py`, the read model `platform/api/clue_api/crm/settings_view.py`,
and the rulings R-14.6 and R-15.1–R-15.3 in `docs/superpowers/specs/crm-integration/rulings.md`.
Design: Figma `NcLl2r0dzVDN28xAQCwvM1`, section `2308:1590` (boards 01–07).

Frontend: schemas and the research section's words in
`src/features/integrations/model/crm-settings.ts`; the browser repository (HTTP + an explicit fixture
adapter) in `src/features/integrations/data/crm-settings.repository.ts`; the server read in
`src/features/integrations/data/crm-settings.server.ts`; fixtures in `crm-settings.fixtures.ts`.

## Transport

All routes live under `/frontend/v1/crm` on the read app (`CLUE_FRONTEND_READ_ENABLED`), with the usual
authenticated principal and workspace dependency. The Settings page reads `GET /integration` on the
server through the authenticated read seam (`fetchRead`); browser actions go through the same-origin BFF
`/api/clue/frontend/v1/crm/…` (the path the connect card's `crm.repository.ts` uses), through the shared
`fetchMutation`. Every browser request names the page's workspace in `X-Clue-Page-Workspace`
(`httpCrmSettingsRepository(pageWorkspace)`); when the selected workspace changed since the page loaded
the BFF refuses with `409 WORKSPACE_CHANGED`, which the repository throws as `CrmWorkspaceChangedError`
so the screen can say so and reload — the action did not happen. Payloads are bare camelCase objects.

Every refusal is the read API's envelope `{"error": {"code", "message", "requestId"}}` (never
`{"detail": …}`); the repository throws it as `ClueApiError {code, status, requestId}` (code
`HTTP_ERROR` when a body is not the envelope). Common codes:
`UNAUTHORIZED` (401), `PERMISSION_REQUIRED` (403, the action needs `workspace.manage_settings`),
`crm_not_connected` (409), `crm_permission_not_found` (404), `crm_not_configured` (503), and a 422
validation envelope for a bad body.

| Method and path | Who | Request | Response |
| --- | --- | --- | --- |
| GET `/crm/integration` | any member | — | the integration (below) |
| POST `/crm/connect-request` | owner/admin | `{mode: "connect"\|"reconnect"\|"switch"}` | `{requestId: uuid}` — reuses the workspace's open Settings request of the same mode; the id then drives the existing `POST /crm/connect-link` → callback → `POST /crm/complete` flow |
| POST `/crm/disconnect` | owner/admin | — | `{outcome: "disconnected"}`; 409 `crm_not_connected` when there is no active or expired connection. Revokes every standing permission, closes this connection's open write cards and deletes Clue's Composio connected account (a Composio failure is logged; the disconnect stands) |
| POST `/crm/permissions/{grantId}/revoke` | any member | — | `{outcome: "revoked"\|"already_revoked"}`; 404 `crm_permission_not_found` unless the grant belongs to this workspace's latest connection |
| PUT `/crm/overwrites` | owner/admin | `{mode: "ask"\|"follow_grants"}` | `{overwrites: mode}`; 409 `crm_not_connected` |

## `GET /crm/integration`

```json
{
  "connection": {
    "provider": "hubspot",
    "status": "active",
    "accountLabel": "Portal 111",
    "connectedByName": "Aryan",
    "connectedAt": "2026-10-25T18:52:09.106166+00:00"
  },
  "canManage": true,
  "research": {
    "state": "permission_needed",
    "failedField": null,
    "reason": "The connected HubSpot user doesn’t have permission to create fields on company records.",
    "reviewChat": null,
    "items": [
      {"key": "company_research_links", "title": "Company research links",
       "description": "A link on each company record to its research in Clue.", "status": "permission_needed"},
      {"key": "contact_profile_links", "title": "Contact profile links",
       "description": "A link on each contact record to the person’s Clue profile.", "status": "pending"},
      {"key": "contact_buying_roles", "title": "Contacts’ buying roles",
       "description": "The person’s role in the buying decision, saved on their contact record.", "status": "pending"},
      {"key": "company_fit", "title": "Company fit",
       "description": "High, Medium, or Low fit, saved in the “Clue fit level” field.", "status": "pending"}
    ]
  },
  "permissions": [
    {"grantId": "dad429b8-…", "description": "Always set Clue fit level on companies",
     "grantedByName": "Aryan", "grantedAt": "2026-10-25T18:52:09.106166+00:00"}
  ],
  "overwrites": "ask",
  "askClueProjectId": "prj_…"
}
```

- `connection` — `null` when the workspace never connected. Otherwise the latest connection, including a
  `disconnected` one (status `active|expired|disconnected`). `accountLabel` is `Portal <portal id>` on
  HubSpot and the organization's name on Salesforce (R-15.3). `connectedByName` may be `null`.
- `canManage` — the reader holds `workspace.manage_settings` (owners and admins). Members may view and
  revoke standing permissions only (plan Global Constraints).
- `research.state` — one of `approval_needed | preparing | ready | needs_attention | permission_needed |
  couldnt_finish | not_connected` (precedence in `settings_view.research_view`). `failedField` is the Clue
  label of the deleted field in `needs_attention`, else `null`. `reason` is a plain sentence in
  `permission_needed`, `couldnt_finish` and `needs_attention`, else `null`. `reviewChat`
  `{projectId, threadId}` is the unanswered setup card's chat and is set **only** in `approval_needed`
  (the frontend schema refuses it in any other state). `items` are always the four preparations, in the
  page's order, worded by the backend (Salesforce says "account record"); `status` is
  `created|pending|permission_needed|missing`.
- `permissions` — the live standing permissions of the current connection, each described imperatively
  ("Always set Clue fit level on companies", Salesforce "… on accounts"); empty when disconnected.
- `overwrites` — `ask` (default) or `follow_grants`.
- `askClueProjectId` — where "Ask Clue to …" (and "Review request" without a `reviewChat`) opens
  `/projects/{id}?prompt=<message>`, prefilled and never sent (R-15.2); `null` when the workspace has no
  open marketing project.

## Frontend decisions

- The research section's words come from `researchStateCopy(state, provider, items, failedField)`
  (board 07); the backend's `reason` is not shown verbatim (the design words each state itself).
- `needs_attention` names one field throughout: with `failedField` the title, body and the "Restore …"
  message all name it; without one the deleted item names it, as the board does.
- Fixtures are explicit only. `CLUE_CRM_SETTINGS_FIXTURE=<provider>:<state>` (server, read in
  `crm-settings.server.ts` only) serves `crmIntegrationFixture(state, provider)` to the Settings page for
  checking a state; unset, malformed or `NODE_ENV=production` means live, and a failed live read never
  falls back to it. Browser actions stay live in fixture mode. The `not_connected` fixture is worded for
  HubSpot whatever provider is asked, like the backend.
  `fixtureCrmSettingsRepository(payload)` is the in-memory browser adapter for tests and design checks.
- Fixed with this contract: `crm.repository.ts` read refusal codes from `body.detail.code`, which the read
  app never sends, so `connect_request_closed` was never recognised; it now reads the envelope
  (`crmErrorCode`, through `frontend-mutation.ts`'s `readErrorEnvelope` — the one envelope parse).
