# CRM integration — Phase 1 (reads) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A workspace connects HubSpot or Salesforce from the chat, and the Head of ABM reads the CRM, analyses the sales motion in its sandbox, writes `company/sales-motion.md`, and merges recent closed-won customers into `proof/customers.md` — ending with the founder's own test on the local dev stack (R-2.3).

**Architecture:** One gateway module calls Composio's REST API v3.1 over `httpx` (repo convention: providers over HTTP, never a vendor SDK). Four governed tools give the agent connect / find / run (reads) / write-brand-document. Read results always land as files in the thread's `reads/` folder through a per-execution sink registry (the `run_python` precedent). Connecting is a card rendered from the `connect_crm` tool's own result (not an agent gate); the OAuth callback wakes each waiting thread with a derived turn (`crm_connected`, the `discovery_finished` pattern).

**Tech Stack:** Python 3.12 / FastAPI / asyncpg / Alembic (raw SQL); `httpx`; Next.js App Router + Zod on the frontend; the governed toolbelt (`clue_toolbelt`); Composio REST v3.1.

**Spec:** `docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md` (sections 4, 5, 7, 9, 10, 12) and `docs/superpowers/specs/crm-integration/rulings.md` (R-x.y cited below). Status log: `docs/superpowers/specs/crm-integration/status.md` — update it as each task lands.

## Global Constraints

- Composio only (R-1.8); REST base `https://backend.composio.dev/api/v3.1`; header `x-api-key`.
- Toolkit versions pinned on every execute: hubspot `20261020_01`, salesforce `20261018_00` (configurable; verified in Task 0).
- Composio user id is opaque: `ws_<workspace_id>` (R-5.2). No CRM token is ever stored by Clue.
- One active connection per workspace (design §15 call 1); only `workspace.manage_settings` (owners/admins) may connect (call 2); any member's agent may read (call 15).
- Reads only in this phase. Never expose `*_FROM_NL` actions; never execute an action outside the read allowlist.
- Every read result is written to `reads/<operation_id>.json`; the model receives only a summary.
- Salesforce: Clue's API calls per connection per UTC day ≤ `CLUE_CRM_SALESFORCE_API_SHARE_PCT` (default 10) % of the org's `DailyApiRequests.Max`; also stop when the org's remaining allowance is under 10% (R-7.5).
- `write_brand_document` writes only under `company/` and `proof/`, brand-level (`project_id IS NULL`), to the brand of the conversation's project.
- CRM customer rows in `proof/customers.md` carry `CRM: <HubSpot|Salesforce>` in the *Source* cell; onboarding refreshes keep every row whose Source contains `CRM:` (R-4.5).
- Env parity rule: every new key in `.env.example` with its default, in the same commit as the code that reads it.
- Alembic: random-hash id, `down_revision = "cba395a41e66"` (current head), raw `op.execute` SQL, named CHECKs, reversible; `make db-smoke` green.
- DB tests run only against the lane's throwaway DB via `CLUE_DATABASE_URL`; never `make check` or broad pytest with real keys (`--ignore-glob='*_live.py'`).
- Commits: no AI attribution; never push.
- **Skill text** (`crm-sales-analysis`, `stage0-interview` change) is presented to the founder in chat and approved **before** it is written, and stays **uncommitted until the founder's trial run** (standing rules).

## Review Focus

1. **A user clicks "Connect" twice, or after the link expired (10 min)** → a fresh link each click; a stale callback for an old attempt is ignored, never activates a second connection. (Task 5.)
2. **The callback arrives with `status=failed`, or with a `connected_account_id` that doesn't match the attempt** → no connection row is activated; the tab says it failed; the thread is not woken. (Task 5.)
3. **The connection expired/revoked at Composio between turns** → `run_crm_action` returns `crm_connection_expired` and marks the row `expired`; `connect_crm` then offers reconnect. (Tasks 4, 8.)
4. **A read result larger than the 12 KiB spill threshold *and* a tiny one** → both land in `reads/` and the model sees only the summary; the summary never inlines records. (Task 8.)
5. **A Salesforce org without API access (Professional Edition)** → the connection or first read fails with `salesforce_api_disabled` and a plain explanation, not a stack trace. (Task 8.)

---

## File Structure

| File | Responsibility |
|---|---|
| `libs/clue-config/clue_config/secrets.py`, `settings.py`, `.env.example` | new keys (Task 1) |
| `alembic/versions/<hash>_crm_integration_connection.py` | tables + derivation widening (Task 2) |
| `platform/api/clue_api/crm/composio_gateway.py` | the only module that talks to Composio (Task 3) |
| `platform/api/clue_api/crm/connections.py` | connection + connect-request persistence (Task 4) |
| `platform/api/clue_api/crm/wake.py` | `crm_connected` derived turns (Task 5) |
| `platform/api/clue_api/frontend_read/crm.py` | `/frontend/v1/crm/*` routes (Task 5) |
| `platform/api/clue_api/crm/read_actions.py` | per-CRM read allowlist + result summariser (Task 8) |
| `platform/api/clue_api/crm/read_sinks.py` | per-execution `reads/` sink registry (Task 8) |
| `platform/api/clue_api/crm/salesforce_budget.py` | Salesforce daily-share guard (Task 8) |
| `platform/api/clue_api/crm/tools.py` | `connect_crm@1`, `find_crm_actions@1`, `run_crm_action@1` (Tasks 7, 8) |
| `platform/api/clue_api/brand_knowledge_writes.py` | shared brand-document version writer, extracted from `product_management.py` (Task 9) |
| `platform/api/clue_api/brand_document_tool.py` | `write_brand_document@1` (Task 9) |
| `platform/api/clue_api/arv2/onboarding_documents.py`, `arv2/onboarding_driver.py` | carry CRM customer rows forward (Task 10) |
| `apps/frontend/src/features/projects/...`, `apps/frontend/src/app/(protected)/integrations/crm/callback/page.tsx` | connect card + callback page (Task 6) |
| agent catalog files (profile v76, recipe v36, manual v22, skills) | grants and guidance (Task 11) |

---

### Task 0: Composio spike (real API, dev project)

**Files:**
- Create: `docs/superpowers/specs/crm-integration/composio-api-notes.md`

Needs from the founder: a Composio API key for a **development** project (in `.env` as `CLUE_COMPOSIO_API_KEY`), a HubSpot developer test account and a Salesforce Developer Edition org (R-2.3), and one Composio-managed auth config id per CRM.

- [ ] **Step 1:** With `httpx` in a scratch script (not committed), call and record the exact request/response JSON (redact ids) for: `POST /connected_accounts/link` (body `auth_config_id`, `user_id`, `callback_url`, and for Salesforce `connection_data`), `GET /connected_accounts/{id}`, `GET /tools?toolkit_slug=hubspot&query=search deals&limit=5`, `POST /tools/execute/HUBSPOT_SEARCH_DEALS` (body `arguments`, `connected_account_id`, `user_id`, `version`), `POST /tools/execute/SALESFORCE_RUN_SOQL_QUERY`, `POST /tools/execute/SALESFORCE_GET_ORG_LIMITS`.
- [ ] **Step 2:** Record: the query params Composio appends to `callback_url` (`status`, `connected_account_id` expected); whether `Tool.tags` carries `readOnlyHint`; the HTTP status and error body for an expired/revoked account and for a Professional-Edition-style `API_DISABLED_FOR_ORG`; the Salesforce `connection_data` keys (`subdomain`, `instanceEndpoint` expected).
- [ ] **Step 3:** Write the findings into `composio-api-notes.md` (one short section per endpoint: request, response fields used, errors). Later tasks code against these notes; where a note contradicts this plan, the notes win and the plan is amended.
- [ ] **Step 4:** Commit `composio-api-notes.md` (no keys, no ids).

---

### Task 1: Configuration

**Files:**
- Modify: `libs/clue-config/clue_config/secrets.py`, `libs/clue-config/clue_config/settings.py`, `.env.example`
- Test: `tests/test_crm_integration_settings.py`

**Interfaces:**
- Produces: `Secrets.composio_api_key: SecretStr | None`; `Settings.crm_integration_enabled: bool = True`; `Settings.composio_base_url: str = "https://backend.composio.dev/api/v3.1"`; `Settings.composio_hubspot_auth_config_id: str = ""`; `Settings.composio_salesforce_auth_config_id: str = ""`; `Settings.composio_hubspot_toolkit_version: str = "20261020_01"`; `Settings.composio_salesforce_toolkit_version: str = "20261018_00"`; `Settings.crm_salesforce_api_share_pct: int = Field(default=10, ge=1, le=100)`. The callback origin reuses the existing `Settings.app_origin` (`CLUE_APP_ORIGIN`).

- [ ] **Step 1: Failing test** — `test_crm_keys_have_defaults_and_are_documented`: asserts each field exists with the default above (`Settings(_env_file=None)`, `Secrets(_env_file=None).composio_api_key is None`), and `.env.example` contains `^CLUE_COMPOSIO_API_KEY=$`, `^CLUE_CRM_INTEGRATION_ENABLED=true$`, `^CLUE_COMPOSIO_BASE_URL=https://backend.composio.dev/api/v3.1$`, `^CLUE_COMPOSIO_HUBSPOT_AUTH_CONFIG_ID=$`, `^CLUE_COMPOSIO_SALESFORCE_AUTH_CONFIG_ID=$`, `^CLUE_COMPOSIO_HUBSPOT_TOOLKIT_VERSION=20261020_01$`, `^CLUE_COMPOSIO_SALESFORCE_TOOLKIT_VERSION=20261018_00$`, `^CLUE_CRM_SALESFORCE_API_SHARE_PCT=10$` (pattern of `tests/test_site_section_link_settings.py`).
- [ ] **Step 2:** `uv run pytest tests/test_crm_integration_settings.py -v` → FAIL.
- [ ] **Step 3:** Add the fields with `# Env: CLUE_...` comments; add a `# --- CRM integration (Composio) ---` section to `.env.example` after the provider-keys block. Add the same keys to the local `.env` (parity rule).
- [ ] **Step 4:** Re-run → PASS.
- [ ] **Step 5:** Commit `feat(crm): configuration for the Composio CRM integration`.

---

### Task 2: Migration — connection, connect requests, `crm_connected` derivation

**Files:**
- Create: `alembic/versions/<hash>_crm_integration_connection.py` (`uv run alembic revision -m "crm integration connection"`)
- Test: `tests/db/test_crm_integration_migration.py`

**Interfaces:**
- Produces tables:
  - `workspace_integration_connection(connection_id uuid PK, workspace_id text NOT NULL FK workspace, provider text NOT NULL CHECK (provider IN ('hubspot','salesforce')), composio_connected_account_id text NOT NULL, composio_auth_config_id text NOT NULL, external_account_id text NULL, status text NOT NULL CHECK (status IN ('active','expired','disconnected')), connected_by_user_id text NOT NULL, connected_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), disconnected_at timestamptz NULL, api_calls_day date NULL, api_calls_count integer NOT NULL DEFAULT 0, settings jsonb NOT NULL DEFAULT '{}')` + `UNIQUE INDEX workspace_integration_connection_one_active ON (workspace_id) WHERE status = 'active'` + `UNIQUE (composio_connected_account_id)`.
  - `crm_connect_request(request_id uuid PK, workspace_id text NOT NULL FK workspace, project_id uuid NOT NULL, thread_id uuid NOT NULL, turn_id uuid NOT NULL, requested_by_user_id text NOT NULL, mode text NOT NULL CHECK (mode IN ('connect','reconnect','switch')), status text NOT NULL CHECK (status IN ('open','fulfilled','cancelled')), pending_connected_account_id text NULL, pending_provider text NULL CHECK (pending_provider IS NULL OR pending_provider IN ('hubspot','salesforce')), pending_started_by_user_id text NULL, pending_started_at timestamptz NULL, created_at timestamptz NOT NULL DEFAULT now(), fulfilled_at timestamptz NULL)` + `INDEX ON (workspace_id) WHERE status = 'open'`.
  - `agent_turn_submission_derivation_kind` CHECK widened to add `'crm_connected'` (copy the drop/re-add of `0a3a88c7e5ed`; downgrade deletes `crm_connected` submissions first, then restores the previous three values).
  - Bump a matching Python constant `DERIVATION_CRM_CONNECTED = "crm_connected"` in `platform/api/clue_api/agent_turn_submission.py` (exported in `__all__`).

- [ ] **Step 1: Failing tests** (`require_db`, `migrated_db`): `test_one_active_connection_per_workspace` (second `active` row for the same workspace raises `UniqueViolationError`; an `expired` + an `active` row coexist); `test_provider_and_status_checks` (`provider='pipedrive'` and `status='pending'` rejected); `test_derivation_accepts_crm_connected` (reads `pg_get_constraintdef` of `agent_turn_submission_derivation_kind` and asserts `'crm_connected'` is listed, as `tests/db/test_discovery_excludes_customers_migration.py` does).
- [ ] **Step 2:** Run with the lane test DB → FAIL.
- [ ] **Step 3:** Write the migration (pattern: `aaff3d831895_workspace_hostnames_and_pages_settings.py` for the tables, `0a3a88c7e5ed` for the CHECK).
- [ ] **Step 4:** Tests PASS; `uv run alembic heads` shows one head; `make db-smoke` green on a throwaway DB.
- [ ] **Step 5:** Commit `feat(crm): connection and connect-request tables; crm_connected derivation`.

---

### Task 3: Composio gateway

**Files:**
- Create: `platform/api/clue_api/crm/__init__.py`, `platform/api/clue_api/crm/composio_gateway.py`
- Modify: root `pyproject.toml` import-linter contract — add `composio` and `composio_client` to the forbidden-SDK list (we never import them; this keeps it so)
- Test: `tests/api/test_crm_composio_gateway.py` (uses `httpx.MockTransport`)

**Interfaces:**
- Produces:
  ```python
  CrmProvider = Literal["hubspot", "salesforce"]
  @dataclass(frozen=True) class ConnectLink: redirect_url: str; connected_account_id: str; expires_at: datetime | None
  @dataclass(frozen=True) class ConnectedAccount: id: str; status: str; toolkit: str
  @dataclass(frozen=True) class ToolInfo: slug: str; description: str; input_schema: Mapping[str, Any]; tags: tuple[str, ...]
  @dataclass(frozen=True) class ExecuteResult: successful: bool; data: Any; error: str | None
  class ComposioError(Exception): kind: Literal["auth","not_found","rate_limited","connection_expired","bad_request","unavailable"]; status: int | None; message: str
  class ComposioGateway(Protocol):
      async def create_link(self, *, auth_config_id: str, user_id: str, callback_url: str, connection_data: Mapping[str, str] | None = None) -> ConnectLink
      async def get_account(self, connected_account_id: str) -> ConnectedAccount
      async def search_tools(self, *, toolkit: CrmProvider, query: str, limit: int) -> list[ToolInfo]
      async def execute(self, *, slug: str, arguments: Mapping[str, Any], connected_account_id: str, user_id: str, version: str) -> ExecuteResult
  class HttpComposioGateway:  # implements ComposioGateway
      def __init__(self, *, api_key: str, base_url: str, client: httpx.AsyncClient | None = None) -> None
  def composio_user_id(workspace_id: str) -> str  # "ws_" + workspace_id
  def build_composio_gateway(*, settings: Settings, secrets: Secrets | None) -> ComposioGateway | None  # None when disabled or key blank
  ```
- HTTP → `ComposioError.kind`: 401/403 `auth`; 404 `not_found`; 429 `rate_limited`; HTTP 410 with `error.slug == "ActionExecute_ConnectedAccountExpired"` `connection_expired`; other 4xx `bad_request`; 5xx/timeouts `unavailable`. Never retried here (R-7.2's automatic retry lands with the Phase 2 executor).

- [ ] **Step 1: Failing tests** — `test_create_link_posts_v31_body` (asserts path `/connected_accounts/link`, header `x-api-key`, JSON body keys, parses `redirect_url`/`connected_account_id`/`expires_at`); `test_execute_always_sends_pinned_version`; `test_error_mapping` (parametrised 401→auth, 404→not_found, 429→rate_limited, expired body→connection_expired, 500→unavailable); `test_build_returns_none_without_key_or_when_disabled`; `test_composio_user_id_is_opaque` (`composio_user_id("abc") == "ws_abc"`).
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implement with one shared `httpx.AsyncClient` (timeout 60 s). Request/response field names exactly as in `composio-api-notes.md`.
- [ ] **Step 4:** PASS; `uv run pytest tests/test_dependency_contracts.py -q` PASS.
- [ ] **Step 5:** Commit `feat(crm): Composio REST gateway`.

---

### Task 4: Connection store

**Files:**
- Create: `platform/api/clue_api/crm/connections.py`
- Test: `tests/api/test_crm_connections_db.py`

**Interfaces:**
- Consumes: Task 2 tables.
- Produces:
  ```python
  @dataclass(frozen=True) class CrmConnection: connection_id: UUID; workspace_id: str; provider: CrmProvider; composio_connected_account_id: str; status: str; connected_by_user_id: str; connected_at: datetime
  @dataclass(frozen=True) class ConnectRequest: request_id: UUID; workspace_id: str; project_id: UUID; thread_id: UUID; turn_id: UUID; requested_by_user_id: str; mode: str; status: str
  async def latest_connection(conn, *, workspace_id: str) -> CrmConnection | None          # active first, else most recent
  async def open_connect_request(conn, *, workspace_id, project_id, thread_id, turn_id, requested_by_user_id, mode) -> ConnectRequest  # idempotent per turn_id
  async def start_attempt(conn, *, request_id: UUID, workspace_id: str, provider: CrmProvider, connected_account_id: str, started_by_user_id: str) -> None  # overwrites the pending_* fields (newest click wins)
  async def activate_from_attempt(conn, *, request_id: UUID, workspace_id: str, connected_account_id: str, auth_config_id: str) -> tuple[CrmConnection, list[ConnectRequest]] | None
      # None unless the request's pending_connected_account_id == connected_account_id.
      # Marks any other active row 'disconnected' (switch), inserts the new active row,
      # marks EVERY open request in the workspace 'fulfilled' and returns them (to wake).
  async def mark_expired(conn, *, connection_id: UUID) -> None
  async def count_salesforce_call(conn, *, connection_id: UUID, today: date) -> int        # resets on a new day; returns the new count
  ```

- [ ] **Step 1: Failing tests** — `test_activate_requires_matching_pending_account` (mismatch → None, nothing written); `test_activate_fulfils_every_open_request_in_workspace` (two threads' open requests both returned and `fulfilled`); `test_switch_disconnects_previous_active`; `test_newest_click_wins` (two `start_attempt`s; activation with the first id → None); `test_salesforce_counter_resets_daily`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement (one transaction per call; `SELECT … FOR UPDATE` on the request row in `activate_from_attempt`). **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(crm): connection store`.

---

### Task 5: Connect routes and the `crm_connected` wake

**Files:**
- Create: `platform/api/clue_api/crm/wake.py`, `platform/api/clue_api/frontend_read/crm.py`
- Modify: `platform/api/clue_api/frontend_read/app.py` (call `register_crm_routes` in `build_frontend_read_router`, pass `settings`, `secrets`, `conn_factory`, an artifact store for the wake)
- Test: `tests/api/test_frontend_read_crm_db.py`

**Interfaces:**
- Consumes: Tasks 3, 4; `persist_user_turn`, `insert_submission`, `record_wake_turn`, `dispatch_next_thread_turn` exactly as `discovery_wake.DbDiscoveryWake.queue` uses them.
- Produces:
  - `async def queue_crm_connected_turns(conn, artifacts, *, requests: Sequence[ConnectRequest], provider: CrmProvider) -> list[UUID]` — one derived submission per request: key `crm-connected:{request_id}`, `derivation=DERIVATION_CRM_CONNECTED`, `derived_from_turn_id=request.turn_id`, `submitted_by_user_id=request.requested_by_user_id`, message `"The workspace's {HubSpot|Salesforce} is now connected. Continue where we left off."`; then `dispatch_next_thread_turn` per thread.
  - `POST /frontend/v1/crm/connect-link` body `{request_id: UUID, provider: "hubspot"|"salesforce"}` (Composio's hosted page asks Salesforce users for the subdomain; `login` works — see `composio-api-notes.md`) → `{redirect_url, expires_at}`. Requires `workspace.manage_settings` (`principal_for` + `lock_manager`). Refuses `crm_not_configured` (no gateway or no auth config for the provider), `connect_request_closed`. Builds `callback_url = f"{settings.app_origin}/integrations/crm/callback?request={request_id}"`, calls `create_link` with `user_id=composio_user_id(ws)`, then `start_attempt`.
  - `POST /frontend/v1/crm/complete` body `{request_id, status, connected_account_id}` → `{outcome: "connected"|"failed"|"stale", provider?}`. Same permission. On `status != "success"` → `failed`. Else `get_account` must be `ACTIVE` and match the attempt, then `activate_from_attempt` + `queue_crm_connected_turns` in one transaction. Mismatch/no pending → `stale`.
  - `GET /frontend/v1/crm/connection` → `{provider, status, connected_at, connected_by}` or `{status: "none"}` (any member).

- [ ] **Step 1: Failing tests** (fake gateway, lane DB): `test_connect_link_requires_manage_settings` (operator → 403); `test_connect_link_records_attempt_and_callback_url`; `test_complete_success_activates_and_wakes_every_waiting_thread` (two open requests in two threads → two derived submissions with `derivation='crm_connected'` and the right `submitted_by_user_id`); `test_complete_failed_status_writes_nothing`; `test_complete_mismatched_account_is_stale`; `test_double_complete_is_idempotent` (second call → `stale`, no second wake).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(crm): connect-link and callback routes; crm_connected wake`.

---

### Task 6: Frontend — connect card and callback page

**Files:**
- Modify: `apps/frontend/src/features/projects/model/chat-tool-presentation.ts` (label `connect_crm` → "Connect your CRM"; `find_crm_actions` → "Look up CRM actions"; `run_crm_action` → "Read from your CRM"; `write_brand_document` → "Update brand context")
- Create: `apps/frontend/src/features/projects/components/crm-connect-card.tsx`, `apps/frontend/src/features/integrations/data/crm.repository.ts` (+ Zod schemas), `apps/frontend/src/app/(protected)/integrations/crm/callback/page.tsx`
- Modify: the tool-part renderer that dispatches on tool name (`components/chat-message-part.tsx`) to render `CrmConnectCard` for a finished `connect_crm` part whose output has `card` set.
- Test: the frontend gate `npm run design-system:build && npm run lint && npm run build` (stack down), plus a unit test beside the repository if the folder has them.

**Interfaces:**
- Consumes: `connect_crm` output (Task 7): `{state: "connected"|"card", mode, request_id, providers: ["hubspot","salesforce"], can_connect: bool, connection?: {...}}`; routes from Task 5 through `fetchRead`-style helpers in `features/accounts/data/frontend-api.ts`.
- Behaviour: the card shows one button per offered CRM plus "I'll give the numbers myself" which sends that sentence as a normal chat message. A member without `can_connect` sees "Ask a workspace owner or admin to connect the CRM." Clicking a CRM calls `connect-link` and opens `redirect_url` in a new tab. The callback page reads `request`, `status`, `connected_account_id` from the URL, calls `complete`, and shows "Connected — you can close this tab" / "That didn't work — close this tab and try again from the chat."
- **Visual review (R-3.9):** the card and callback page reuse existing chat-card and empty-state components and tokens. Show the founder a preview (screenshot in the in-app browser) as soon as the card renders — **not a blocker**; visual polish of the card is a planned follow-up.

- [ ] **Step 1:** Add Zod schemas + repository functions `requestConnectLink`, `completeConnection`, `getConnection`.
- [ ] **Step 2:** Build `CrmConnectCard` and the callback page.
- [ ] **Step 3:** Wire the renderer and labels.
- [ ] **Step 4:** Frontend gate green.
- [ ] **Step 5:** Commit `feat(crm): connect card and OAuth callback page`.

---

### Task 7: `connect_crm@1`

**Files:**
- Create: `platform/api/clue_api/crm/tools.py` (this task adds `ConnectCrmTool` and `build_crm_tools`)
- Modify: `platform/api/clue_api/toolbelt_wiring.py` (`build_toolbelt`: `for tool in build_crm_tools(settings=settings, secrets=secrets, conn_factory=conn_factory): registry.register(tool, make_default=True)`, next to `build_web_search_tools`, line ~3163)
- Test: `tests/api/test_crm_tools_db.py`

**Interfaces:**
- Consumes: Task 4; `turn_binding.TRUSTED_TURN_FIELD`, `parse_turn_action_ref`, `load_turn_identity`, `principal role lookup for can_connect` (the membership's role via `clue_auth.policy`).
- Produces: `ConnectCrmTool` — `name="connect_crm"`, `version="1"`, `effect_class=WRITE` (it writes a connect request), `ReplaySafety(policy=DOMAIN_IDEMPOTENT)` keyed on the turn, `pin_requirements=("project",)`. Input `ConnectCrmInput{ switch: bool = False, source_turn_ref (TRUSTED_TURN_FIELD) }`. Output `ConnectCrmOutput{ state: Literal["connected","card"], mode: Literal["connect","reconnect","switch"] | None, request_id: UUID | None, providers: list[CrmProvider], can_connect: bool, connection: CrmConnectionView | None }`. `CrmConnectionView{ provider: CrmProvider, status: str, connected_at: datetime, connected_by_user_id: str }` (no Composio ids reach the model). Refusal codes: `crm_not_configured`.
  - Active connection and not `switch` → `state="connected"` with the connection view; no request written.
  - Otherwise → `open_connect_request(mode=…)` (`reconnect` when the latest is `expired`) and `state="card"`. `providers` lists only CRMs that have an auth config id.
- `build_crm_tools(*, settings, secrets, conn_factory, read_sinks=None) -> tuple[Tool, ...]` always returns all three CRM tools (registered unconditionally; refusals in `preconditions` when not configured — the C6 audit's one-registry-shape rule).

- [ ] **Step 1: Failing tests** — `test_connected_workspace_reports_without_card`; `test_unconnected_opens_one_request_per_turn` (replay → same `request_id`); `test_expired_connection_opens_reconnect`; `test_switch_opens_switch_card`; `test_member_without_manage_settings_gets_can_connect_false`; `test_not_configured_refuses`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(crm): connect_crm tool`.

---

### Task 8: Reads — sink registry, `find_crm_actions@1`, `run_crm_action@1`, Salesforce budget

**Files:**
- Create: `platform/api/clue_api/crm/read_sinks.py`, `platform/api/clue_api/crm/read_actions.py`, `platform/api/clue_api/crm/salesforce_budget.py`
- Modify: `platform/api/clue_api/crm/tools.py` (add the two tools), `platform/api/clue_api/conversation_turns.py` (~456-470: register `lease.backend` in `CrmReadSinks` by `execution_id` where the sandbox registry is registered; release in the same `finally`)
- Test: `tests/api/test_crm_read_actions.py`, `tests/api/test_crm_tools_db.py` (extend)

**Interfaces:**
- Produces:
  ```python
  class CrmReadSinks:   # read_sinks.py — mirrors SandboxWorkspaces' register/release/lookup
      def register(self, execution_id: ExecutionId, sink: SpillSink) -> None
      def release(self, execution_id: ExecutionId) -> None
      def sink_for(self, execution_id: ExecutionId) -> SpillSink | None
  READ_ACTIONS: Mapping[CrmProvider, frozenset[str]]   # read_actions.py — the reviewed allowlist
  def is_readable(provider: CrmProvider, slug: str) -> bool   # in allowlist and not slug.endswith("_FROM_NL")
  def summarize(provider: CrmProvider, slug: str, data: Any) -> ResultSummary
  @dataclass(frozen=True) class ResultSummary: record_count: int | None; fields: list[str]; next_cursor: str | None; done: bool
  async def check_salesforce_budget(conn, gateway, *, connection: CrmConnection, share_pct: int, today: date) -> None  # raises CrmBudgetExhausted
  ```
- `READ_ACTIONS` (from the learning pass; amend from Task 0 notes):
  - hubspot: `HUBSPOT_SEARCH_DEALS`, `HUBSPOT_LIST_DEALS`, `HUBSPOT_GET_DEALS`, `HUBSPOT_READ_CRM_OBJECT_BY_ID`, `HUBSPOT_LIST_COMPANIES`, `HUBSPOT_SEARCH_COMPANIES`, `HUBSPOT_BATCH_READ_COMPANIES_BY_PROPERTIES`, `HUBSPOT_LIST_CONTACTS`, `HUBSPOT_SEARCH_CONTACTS_BY_CRITERIA`, `HUBSPOT_READ_CONTACTS`, `HUBSPOT_READ_ASSOCIATIONS_BATCH`, `HUBSPOT_LIST_ASSOCIATION_TYPES`, `HUBSPOT_READ_ALL_PROPERTIES_FOR_OBJECT_TYPE`, `HUBSPOT_RETRIEVE_ALL_PIPELINES_FOR_SPECIFIED_OBJECT_TYPE`, `HUBSPOT_RETRIEVE_PIPELINE_STAGES`, `HUBSPOT_RETRIEVE_OWNERS`, `HUBSPOT_LIST_GRANTED_SCOPES`, `HUBSPOT_WHO_AM_I`, `HUBSPOT_RETRIEVE_LINE_ITEMS`, `HUBSPOT_LIST_PRODUCTS`, `HUBSPOT_READ_APAGE_OF_OBJECTS_BY_TYPE`, `HUBSPOT_SEARCH_CRM_OBJECTS_BY_CRITERIA`.
  - salesforce: `SALESFORCE_RUN_SOQL_QUERY`, `SALESFORCE_QUERY_MORE`, `SALESFORCE_GET_ALL_FIELDS_FOR_OBJECT`, `SALESFORCE_GET_PICKLIST_VALUES_BY_RECORD_TYPE`, `SALESFORCE_GET_S_OBJECT_RECORD`, `SALESFORCE_LIST_ACCOUNTS`, `SALESFORCE_LIST_CONTACTS`, `SALESFORCE_LIST_OPPORTUNITIES`, `SALESFORCE_GET_REPORT`, `SALESFORCE_GET_ORG_LIMITS`.
- **`find_crm_actions@1`** — input `{query: str (1-200 chars), limit: int = 10 (1-25)}`; output `{provider, actions: [{slug, description, input_schema}]}`; uses `search_tools(toolkit=<connected provider>)` and keeps only `is_readable` slugs. Refusals: `crm_not_configured`, `crm_not_connected`.
- **`run_crm_action@1`** — input `{slug: str, arguments: dict}` (`safe_display_fields=("slug",)`; arguments are not journalled for display); `effect_class=SPEND`, `ReplaySafety(policy=AT_LEAST_ONCE, operation_id_required=True)`. Flow: `is_readable` else refuse `crm_action_not_allowed`; active connection else `crm_not_connected`; Salesforce → `check_salesforce_budget` (org limits via `SALESFORCE_GET_ORG_LIMITS`, cached 5 min per connection; refuse `salesforce_api_share_exhausted` when `api_calls_count ≥ share_pct% × DailyApiRequests.Max` or when `Remaining < 10% × Max`) and `count_salesforce_call`; `execute(version=<pinned>)`; `ComposioError.kind == "connection_expired"` → `mark_expired` + refuse `crm_connection_expired`; a Salesforce `API_DISABLED_FOR_ORG` error → refuse `salesforce_api_disabled`; `successful=False` → refuse `crm_action_failed` with Composio's error text. On success: `sink_for(ctx.execution_id).write_spill(operation_id, canonical_json(data))` (refuse `crm_reads_unavailable` when no sink) and return `{path, record_count, fields, next_cursor, done}` — never the records.

- [ ] **Step 1: Failing tests** — `test_from_nl_and_unlisted_slugs_are_refused`; `test_summarize_hubspot_search_page` (fixture with `results` + `paging.next.after` → count, fields, cursor, `done=False`); `test_summarize_salesforce_soql` (`records`, `done`, `nextRecordsUrl`); `test_run_writes_reads_file_even_when_small` (fake sink records the bytes; output has `path` and no records); `test_expired_connection_marks_row_and_refuses`; `test_salesforce_share_exhausted_refuses` (count at 10% of Max); `test_salesforce_org_low_remaining_refuses`; `test_find_filters_to_read_allowlist`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement; register/release `CrmReadSinks` in `conversation_turns.py`. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(crm): read tools with reads/ files and the Salesforce budget guard`.

---

### Task 9: `write_brand_document@1`

**Files:**
- Create: `platform/api/clue_api/brand_knowledge_writes.py` (extract `_store`, `_next_version`, `_retire_path`, `_write_doc` from `product_management.py` as public `store_document_bytes`, `next_brand_version`, `retire_older_versions`, `write_brand_document_version`)
- Modify: `platform/api/clue_api/product_management.py` (use the extracted functions — behaviour unchanged)
- Create: `platform/api/clue_api/brand_document_tool.py`
- Modify: `platform/api/clue_api/toolbelt_wiring.py` (register `WriteBrandDocumentTool`)
- Test: `tests/api/test_brand_document_tool_db.py`; existing product-management tests must stay green.

**Interfaces:**
- Produces:
  ```python
  async def write_brand_document_version(conn, storage, *, workspace_id: str, brand_id: UUID, path: str, kind: str, front: dict, body: str, source_key: str) -> UUID
  class WriteBrandDocumentTool  # name="write_brand_document", version="1", effect_class=WRITE, pin_requirements=("project",)
  WriteBrandDocumentInput{ path: str, kind: str, body: str | None = None, from_file: str | None = None, source_turn_ref (TRUSTED_TURN_FIELD) }   # exactly one of body/from_file
  WriteBrandDocumentOutput{ document_id: UUID, path: str, version: int }
  ```
- Rules: `path` must match `^(company|proof)/[a-z0-9][a-z0-9-]*\.md$` else refuse `path_not_allowed`; `from_file` must be under `outputs/` and is read from `SandboxWorkspaces.mounts_for(ctx.execution_id).read_write["outputs"]` (refuse `file_not_found` / `sandbox_unavailable`); brand from the turn's project (`load_turn_identity` → `get_project().brand_id`, as `product_management_tools._scope`); front matter `written_by: {user_id, turn_id}`; `source_key="brand_document_agent_write"`.

- [ ] **Step 1: Failing tests** — `test_writes_new_version_and_supersedes_previous` (`company/sales-motion.md` v1 then v2; v1 `superseded`); `test_audience_and_product_paths_refused`; `test_from_file_reads_sandbox_output`; `test_exactly_one_of_body_or_file`.
- [ ] **Step 2:** FAIL. **Step 3:** Extract + implement. **Step 4:** PASS, and `uv run pytest tests/api -k product_management -q` still green.
- [ ] **Step 5:** Commit `feat(crm): write_brand_document tool; shared brand document writer`.

---

### Task 10: Onboarding keeps CRM customer rows

**Files:**
- Modify: `platform/api/clue_api/arv2/onboarding_documents.py` (`existing_customers_document(..., carried_rows: Sequence[CustomerRow] = ())` and a parser `crm_customer_rows(markdown: str) -> list[CustomerRow]`)
- Modify: `platform/api/clue_api/arv2/onboarding_driver.py` (`_customers.finish`: read the brand's current servable `proof/customers.md`, `crm_customer_rows(...)`, pass as `carried_rows`)
- Test: `tests/arv2/test_onboarding_customers_carry_crm_rows.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class CustomerRow: customer: str; domains: tuple[str, ...]; domain_check: str; how_they_buy: str; evidence: str; quote: str; source: str`.
- Merge rule (one row per domain): CRM rows are rows whose *Source* contains `CRM:`. A carried row whose domains don't appear in the new web rows is appended unchanged. When a domain appears in both, the web row is kept and ` · <the CRM row's CRM: … part>` is appended to its Source (so the next refresh still recognises it). Rows stay sorted by customer name.

- [ ] **Step 1: Failing tests** — `test_parser_reads_only_crm_rows`; `test_refresh_keeps_crm_only_customers`; `test_shared_domain_keeps_one_row_with_both_sources`; `test_no_existing_document_behaves_as_today`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(crm): onboarding customer refresh keeps CRM rows`.

---

### Task 11: Agent catalog — grants and guidance

**Files:**
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`C6_AGENT_TOOL_AUTHORITY`: `connect_crm`, `find_crm_actions`, `run_crm_action`, `write_brand_document` → `(AgentRole.HEAD_OF_ABM,)`; `C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM] = "v76"`)
- Create: `platform/agents/catalog/profiles/head-of-abm/v76/profile.yaml` (copy v75; add the four tools with schema shas from each `Tool.descriptor`; add skill `crm-sales-analysis` v1; bump `stage0-interview` to v49)
- Create: `platform/agents/catalog/skills/crm-sales-analysis/v1/SKILL.md`, `platform/agents/catalog/skills/stage0-interview/v49/SKILL.md`
- Create: `platform/execution/recipes/recipe0-stage0-v36.json` (the four addresses in the four places v34→v35 touched); modify `recipe_wiring.py` (`SYSTEM_RECIPE_FILENAMES`), `conversation_turns.py` (`CONVERSATION_RECIPE_VERSION = 36`), `recipe_contracts.py` (`RECIPE_0_TOOL_ADDRESSES`), `stage0_recipe.py` (pins: the three turn-ref tools in the presenting-turn project-pin set; `find_crm_actions`/`run_crm_action` in the execution-project-pin set)
- Modify: `platform/agents/catalog/manual/tool_notes.yaml` (four entries, every refusal code from Tasks 7–9); `platform/agents/clue_agents/manual/build.py` (`MANUAL_VERSION = "v22"`, `PROFILE_VERSION = "v76"`); `make manual`
- Test: `tests/agents/test_tool_authority_audit.py`, `tests/api/test_agent_registry_wiring.py`, `tests/api/test_recipe_contracts.py`, `tests/agents/test_manual_drift.py`

**Skill substance** (wording drafted, shown to the founder in chat, approved before writing — R-3.x rulings):
- `crm-sales-analysis`: when in the interview (after brand + goals, before the project plan, or when `company/sales-motion.md` is missing/stale); `connect_crm` first, manual path when not offered or declined; read setup first (properties/fields, pipelines and stages); infer → confirm → ask for demo / qualified demo / won / lost (R-3.5); window 3 months adjusted by industry (R-3.6); pull page by page with `run_crm_action`, compute only in `run_python` from `reads/` files (R-3.4); sample-size wording; ask for what the CRM lacks — cost per lead/demo, sales-led pricing (R-3.8); show findings and ask if they look right; write `company/sales-motion.md`; merge the window's closed-won companies into `proof/customers.md` with `CRM: <provider>` in Source, one row per domain, never removing rows (R-4.2–R-4.4); search actions by intent, never with customer data in the query (R-5.3); multi-brand: ask how to separate deals.
- `stage0-interview` v49: one paragraph pointing at the CRM step and at reading `company/sales-motion.md` when proposing the playbook.

- [ ] **Step 1:** Present the two skills' wording to the founder; wait for approval.
- [ ] **Step 2:** Write skills, profile, recipe, pins, notes; `make manual`.
- [ ] **Step 3:** Run the four test files above → PASS.
- [ ] **Step 4:** Commit only the non-skill code changes (`agent_registry_wiring.py`, recipe wiring/contracts/pins, tool notes, manual build) once green; **leave the skill and profile files uncommitted until the founder's trial** (standing rule), and say so in `status.md`.

---

### Task 12: Founder test on the local dev stack (gate R-2.3)

**Files:**
- Modify: `docs/superpowers/specs/crm-integration/status.md`

- [ ] **Step 1:** Seed the test CRMs (HubSpot developer test account, Salesforce Developer Edition org) with ~3 months of closed-won and closed-lost deals with amounts, stage history, linked companies (with domains) and contacts (with titles), and one custom field. Hand the founder the exact setup steps and env vars (`CLUE_COMPOSIO_API_KEY`, the two auth config ids, `CLUE_APP_ORIGIN`).
- [ ] **Step 2:** Start the lane stack via its runbook (`DEV_STACK.md` / the lane script); `alembic upgrade head` first.
- [ ] **Step 3:** The founder walks: connect HubSpot from chat → the agent resumes by itself → reads setup and deals → confirms definitions → computes in the sandbox → writes `company/sales-motion.md` (visible on Brand Context) → merges customers. Repeat for Salesforce (including the subdomain prompt). Also: a member without admin rights sees the read-only card; "I'll give the numbers myself" path.
- [ ] **Step 4:** Record outcome and any fixes in `status.md` (✅ per Phase 1 line, the gate line, cost of the run) and a `_memory/` note; Phase 2 starts only on the founder's sign-off.

---

## Notes for the reviewer of this plan

- **Deviation from the design (needs founder OK):** the connect card is rendered from the `connect_crm` tool result plus a `crm_connect_request` table, **not** a new agent-gate kind. Reasons: no gate tool is granted in the current Head of ABM (all `open_*_gate` authorities are `()`), a gate answer must come from a human turn (DB trigger), and the card needs no decision recorded — it only starts OAuth. Consequence for the database (approved list was "one table + two constraint changes"): **two tables** (`workspace_integration_connection`, `crm_connect_request`) **+ one constraint change** (`crm_connected` derivation); no `agent_gate` change. Design §4.1, §7 and §15 to be amended when approved.
- Composio over REST v3.1 with `httpx` rather than the `composio` SDK: the SDK is synchronous only, pins a pre-release client and pulls `openai`; the repo's provider convention is direct HTTP.
