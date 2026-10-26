# CRM Settings → Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Settings → Integrations for one CRM per workspace (HubSpot or Salesforce) exactly as
designed, and rename Clue's "Clue tier" field to "Clue fit level".

**Architecture:** One read route returns everything the pages show (connection, research setup
state, standing permissions, overwrite mode, who may manage); small action routes connect from
Settings, disconnect, revoke a permission and set the overwrite mode. The frontend adds the
overview (boards 01/04/05) and a provider page `/settings/integrations/{hubspot|salesforce}`
(boards 02/03) with the board 06 dialogs and board 07 states, behind the existing repository seam.
Research setup is never run from the page: it links to the pending setup card's chat or opens a
new chat in the project home with a prefilled message.

**Tech Stack:** FastAPI + SQLAlchemy async + Postgres (Alembic); Next.js App Router + TypeScript +
CSS modules, Zod schemas, `@base-ui/react` Dialog; Composio REST v3.1.

**Spec:** Figma `NcLl2r0dzVDN28xAQCwvM1`, section node `2308:1590` (boards 01–07, read each board
with `get_design_context` before building it); rulings R-14.6, R-15.1–R-15.3 in
`docs/superpowers/specs/crm-integration/rulings.md`.

## Global Constraints

- Every member may view the pages and revoke standing permissions; connect / reconnect / change /
  disconnect and the overwrite setting need `workspace.manage_settings` (owners and admins).
- "Fully automatic" and "What Clue changed" are out of scope (R-15.1).
- The field label in the CRM is **"Clue fit level"**, values **High / Medium / Low**; in Clue's
  screens it is **"Fit level"** (R-14.6). HubSpot's own ICP tier field keeps tier_1/2/3.
- HubSpot account label: `Portal <portal_id>`; Salesforce: the org's `Name` (R-15.3).
- Disconnect deletes the Composio connected account (R-15.3).
- "Review request" with a pending setup card opens that card's chat; with none, and every
  "Ask Clue to …" button, opens `/projects/{projectId}?prompt=<message>` — the project where the CRM
  was connected, else the most recently active project — with the message prefilled, never sent
  (R-15.2).
- Copy is the design's, with the board 07 details line for company fit replaced by: "High, Medium,
  or Low fit, saved in the “Clue fit level” field." Never show API names or internal ids.
- Reuse the settings layout (`settings-screen.tsx`, `settings-primitives.tsx`, `settings.module.css`),
  `components/ui/button.tsx`, the `@base-ui/react` Dialog pattern of
  `components/shell/edit-project-dialog.tsx`, and the logos `public/icons/crm/{hubspot,salesforce}.svg`.
- Frontend check gate: `npm run design-system:build && npm run lint && npm run build` (stop the
  nashville stack first: it shares `.next`). Backend DB tests only on `clue_nashville_crm_test`.

## Review Focus

- A Settings connect while a chat's connect card is also open: completing either wakes every waiting
  chat once and leaves one active connection.
- Disconnect while a write card is sending: the card closes as "replaced", nothing is sent on the
  disconnected grant, and a later connect of the same portal reuses the row (R-14.5) with no grants.
- A member (not owner/admin) calling a manage route directly gets 403, and the page shows the
  member view (board 07) rather than disabled buttons.
- The research state when the setup card was declined (no pending card, registry absent): "Approval
  needed" with "Review request" opening a new chat, not a dead link.
- A project deleted or archived since the CRM was connected: the "Ask Clue" target falls back to
  the most recently active project; with no project at all the button is not shown.

---

### Task 1: "Clue tier" → "Clue fit level" (R-14.6)

**Files:**
- Modify: `platform/api/clue_api/crm/clue_fields.py` (the `clue_tier`/`Clue_Tier__c` entries of
  `CLUE_FIELDS`), `platform/api/clue_api/crm/targets.py` (`clue_tier` → `clue_fit_level`, value =
  the fit band), `platform/api/clue_api/crm/write_prepare.py` (field label table),
  `platform/agents/catalog/manual/tool_notes.yaml`, new `crm-writing/v7` (v6 with "Clue tier" →
  "Clue fit level"), version plumbing as in commit `5acc1f44c` (Head of ABM v85, manual v31,
  stage0-interview v58, recipe 45)
- Test: `tests/api/test_crm_clue_fields.py`, `tests/api/test_crm_targets_db.py`,
  `tests/api/test_crm_write_prepare_db.py`

**Interfaces:**
- Produces: `CLUE_FIELDS` company field `crm_name="clue_fit_level"` (HubSpot, enumeration, options
  `high`/`medium`/`low` labelled High/Medium/Low) and `"Clue_Fit_Level__c"` (Salesforce picklist
  High/Medium/Low), label `"Clue fit level"`; `CrmTarget.clue_fit_level: TargetValue | None`.

- [ ] **Step 1: Write the failing tests** — `test_clue_fit_level_is_the_fit_band_in_each_crm`
  asserting `read_crm_targets` offers `clue_fit_level` = `high` (HubSpot) / `High` (Salesforce) for
  a fit in the High band and no `clue_tier` key; `test_clue_fields_name_fit_level` asserting the
  company field's label is "Clue fit level" and options are High/Medium/Low on both CRMs.
- [ ] **Step 2: Run them** — `uv run pytest -q tests/api/test_crm_clue_fields.py
  tests/api/test_crm_targets_db.py -k fit_level` → FAIL.
- [ ] **Step 3: Implement** the rename; the value comes from `fit_band()` directly, not from
  `_TIER_BY_BAND` (which stays for HubSpot's own ICP tier).
- [ ] **Step 4: Run the whole CRM suite** (`tests/api/test_crm_*.py`, live files ignored) → PASS;
  fix every test that named `clue_tier`.
- [ ] **Step 5: Mint the agent version** (crm-writing v7, manual v31, stage0 v58, Head of ABM v85,
  recipe 45); `make manual-check` and `uv run pytest -q tests/agents` → PASS.
- [ ] **Step 6: Commit** (`feat(crm): Clue tier becomes Clue fit level (R-14.6)`).

### Task 2: Connection identity name, Settings connect requests, Composio delete

**Files:**
- Create: an Alembic migration (`alembic revision -m "crm settings connect and account name"`)
- Modify: `platform/api/clue_api/crm/connections.py`, `platform/api/clue_api/crm/composio_gateway.py`,
  `platform/api/clue_api/crm/wake.py`, `platform/api/clue_api/frontend_read/crm.py`
- Test: `tests/api/test_crm_connections_db.py`, `tests/api/test_frontend_read_crm_db.py`

**Interfaces:**
- Produces: column `workspace_integration_connection.external_account_name text NULL`;
  `crm_connect_request.project_id/thread_id/turn_id` nullable with CHECK all-null-or-all-set;
  `open_settings_connect_request(conn, *, workspace_id, requested_by_user_id, mode) -> ConnectRequest`;
  `crm_account_identity(...) -> CrmAccountIdentity(external_id: str, name: str | None) | None`
  (Salesforce name from SOQL `SELECT Name FROM Organization LIMIT 1`; HubSpot name `None`);
  `activate_from_attempt(..., external_account_name: str | None = None)` stores it;
  `ComposioGateway.delete_account(connected_account_id: str) -> None` (`DELETE
  /connected_accounts/{id}`; 404 is success).

- [ ] **Step 1: Failing tests** — `test_a_settings_connect_request_has_no_chat` (opened without
  project/thread/turn; activation fulfils it; no wake turn queued for it, while a chat request
  opened alongside is woken once); `test_salesforce_connection_keeps_the_org_name` (route test, fake
  who-am-I + Organization query → `external_account_name` stored).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the migration (reversible), the functions above, and skip chat-less
  requests in `queue_crm_connected_turns`.
- [ ] **Step 4: Run** `tests/api/test_crm_connections_db.py tests/api/test_frontend_read_crm_db.py`
  → PASS; `alembic heads` → one head; `make db-smoke` on a throwaway DB → PASS.
- [ ] **Step 5: Commit.**

### Task 3: Settings API

**Files:**
- Create: `platform/api/clue_api/crm/settings_view.py` (the read model and the research state)
- Modify: `platform/api/clue_api/frontend_read/crm.py` (routes), `platform/api/clue_api/crm/writes.py`
  (revoke-all helper)
- Test: `tests/api/test_crm_settings_db.py`

**Interfaces:**
- Consumes: Task 2's columns and functions; `live_grants`, `revoke_grant`, `_grant_phrase`
  (move to `writes.py` as `grant_phrase(provider, grant) -> str`), `clue_fields_state`.
- Produces routes (under the existing CRM router):
  - `GET /crm/integration` (any member) →
    `{ "connection": null | {provider, status: "active"|"expired"|"disconnected", accountLabel,
    connectedByName, connectedAt}, "canManage": bool, "research": {state, failedField: str|null,
    reason: str|null, reviewChat: {projectId, threadId}|null, items: [{key, title, description,
    status: "created"|"pending"|"permission_needed"|"missing"}]}, "permissions": [{grantId,
    description, grantedByName, grantedAt}], "overwrites": "ask"|"follow_grants",
    "askClueProjectId": str|null }`
    where `research.state` ∈ `approval_needed | preparing | ready | needs_attention |
    permission_needed | couldnt_finish | not_connected`.
  - `POST /crm/connect-request {mode: "connect"|"reconnect"|"switch"}` (manage) → `{requestId}`.
  - `POST /crm/disconnect` (manage) → `{outcome: "disconnected"}`: marks the row disconnected,
    revokes every live grant, closes open proposals as replaced, calls `delete_account`.
  - `POST /crm/permissions/{grantId}/revoke` (any member) → `{outcome: "revoked"|"already_revoked"}`.
  - `PUT /crm/overwrites {mode}` (manage) → `{overwrites}`; stored in the connection's `settings`
    JSONB under `"overwrites"`.
- Research state rules: registry `ready` → `ready`; registry `gone` → `needs_attention` with the
  missing field's Clue label; a `clue_fields_setup` write `queued`/`sending` → `preparing`; the
  latest setup write failed or registry `partial` → `permission_needed` when the CRM's message names
  a permission (HubSpot `MISSING_SCOPES`/HTTP 403, Salesforce `INSUFFICIENT_ACCESS`), else
  `couldnt_finish`; otherwise `approval_needed`, with `reviewChat` = the chat of an unanswered setup
  card if any. `askClueProjectId` = the project of the latest chat connect request of this
  connection's workspace if that project is active, else the most recently active project.

- [ ] **Step 1: Failing tests** — one per route and per research state, named
  `test_<route_or_state>…`, plus `test_a_member_cannot_disconnect` (403) and
  `test_disconnect_closes_cards_and_clears_grants` (fake gateway records `delete_account`).
- [ ] **Step 2: Run** `uv run pytest -q tests/api/test_crm_settings_db.py` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file plus `tests/api/test_crm_*.py` → PASS.
- [ ] **Step 5: Commit.**

### Task 4: The overwrite setting gates covering grants

**Files:**
- Modify: `platform/api/clue_api/crm/write_prepare.py` (line ~2046:
  `None if overwrites else covering_grant(...)`), the card snapshot so an overwrite covered under
  `follow_grants` is not listed
- Test: `tests/api/test_crm_write_prepare_db.py`

**Interfaces:**
- Consumes: the connection's `settings["overwrites"]` (default `"ask"`).

- [ ] **Step 1: Failing test** — `test_follow_grants_lets_a_grant_cover_an_overwrite`: with a
  field grant and `overwrites=follow_grants`, an overwrite of a person's value is covered (no card
  row); with `ask` it is listed, unticked, as today.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the CRM suite → PASS.
- [ ] **Step 5: Commit.**

### Task 5: Frontend data layer

**Files:**
- Create: `apps/frontend/src/features/integrations/model/crm-settings.ts` (Zod schemas mirroring
  Task 3, plus `researchStateCopy(state, provider)` returning the board 07 title/body/buttons),
  `apps/frontend/src/features/integrations/data/crm-settings.repository.ts` (HTTP + fixture adapters,
  following `crm.repository.ts`), `…/model/crm-settings.test.ts`
- Modify: `apps/frontend/docs/api-contracts/` (add the CRM settings contract)

- [ ] **Step 1: Failing test** (node:test) — schemas parse a fixture of each research state;
  `researchStateCopy` returns the design's strings for HubSpot and Salesforce.
- [ ] **Step 2: Run** `npx tsx --test src/features/integrations/model/crm-settings.test.ts` → FAIL.
- [ ] **Step 3: Implement. Step 4: Run → PASS. Step 5: Commit.**

### Task 6: Integrations overview and connect dialogs (boards 01, 04, 05, 06 connect/finish/reconnect/change)

**Files:**
- Create: `apps/frontend/src/features/settings/components/integrations-settings.tsx`,
  `apps/frontend/src/features/integrations/components/crm-connect-dialogs.tsx`
- Modify: `settings-screen.tsx` (drop `integrations` from the coming-soon list), the settings page
  route to load the Task 5 data, `use-crm-connect.ts` (reuse its pop-up + callback for a Settings
  request)

- [ ] **Step 1:** Read boards `2308:1591`, `2308:1594`, `2308:1595` and the board 06 dialogs with
  `get_design_context`; build from them, reusing the listed shared components.
- [ ] **Step 2:** Render tests (node:test over the view-model) for the three card states.
- [ ] **Step 3:** In the browser (nashville stack): not connected → Connect → choose → finish
  dialog → connected card with **Manage**; expired → **Reconnect**. Screenshots compared to the
  boards.
- [ ] **Step 4: Commit.**

### Task 7: Provider page, its dialogs and states (boards 02, 03, 06 disconnect/overwrite/revoke, 07)

**Files:**
- Create: `apps/frontend/src/features/settings/components/crm-integration-page.tsx` and one file per
  section (`crm-connection-section.tsx`, `crm-research-section.tsx`,
  `crm-permissions-section.tsx`, `crm-overwrites-section.tsx`)
- Modify: the settings route to serve `/settings/integrations/{hubspot|salesforce}` (redirect to
  `/settings/integrations` when that CRM is not the connected one)

- [ ] **Step 1:** Read boards `2308:1592`, `2308:1593` and every board 07 state; build each section
  for both providers (Salesforce: "organization", "account records", the access line).
- [ ] **Step 2:** Research actions: "Review request" → `reviewChat` link, else and for every "Ask
  Clue to …" → `/projects/{askClueProjectId}?prompt=` with the message for the state (approval:
  "Set up Clue's fields in {CRM}."; needs attention: "Restore Clue's {field} field in {CRM}.";
  retry: "Finish setting up Clue's fields in {CRM}."). View details toggles the read-only list.
- [ ] **Step 3:** Member view (board 07) when `canManage` is false.
- [ ] **Step 4:** Browser check of every state against the boards (states forced with the fixture
  adapter where the live data cannot produce them).
- [ ] **Step 5: Commit.**

### Task 8: Project home accepts `?prompt=`

**Files:**
- Modify: `apps/frontend/src/app/(protected)/projects/[projectId]/page.tsx` (read `prompt`), the
  project home controller (initial prompt state)
- Test: the controller's test file

- [ ] **Step 1: Failing test** — the home composer starts with the `prompt` query text and nothing
  is sent until the person submits.
- [ ] **Step 2: Run → FAIL. Step 3: Implement. Step 4: Run → PASS. Step 5: Commit.**

### Task 9: Live check and docs

- [ ] **Step 1:** Migrate the nashville DB in place; restart by double fork.
- [ ] **Step 2:** On both test CRMs: overview states, Manage, revoke a permission, switch
  overwrites (dialog), disconnect + connect again from Settings (same portal keeps the row),
  "Review request" / "Ask Clue" open the right chat with the prefilled message, member view with a
  member login.
- [ ] **Step 3:** Findings doc, `status.md`, `README.md`, `_memory/`; frontend gate green.
- [ ] **Step 4: Commit.**
