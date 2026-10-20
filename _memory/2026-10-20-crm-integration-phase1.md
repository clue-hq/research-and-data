# CRM integration — Phase 1 (reads) progress, 2026-10-20

Branch `feat/crm-integration` (cut from origin/main f05373d59; upstream unset — never push).
Docs module: `docs/superpowers/specs/crm-integration/` — `README.md` (index), `rulings.md`
(every founder decision, R-x.y), `status.md` (build status), the first-release design, and
`composio-api-notes.md` (verified Composio REST v3.1 shapes). Plan:
`docs/superpowers/plans/2026-10-20-crm-integration-phase-1-reads.md`.

## Done (committed)
- Task 0: Composio spike — notes file; HubSpot developer test account + Salesforce Developer
  Edition org connected via a Composio **dev** project (managed auth configs), seeded with the same
  story (20 companies `*.test`, 66 contacts `@*.example.com`, 36 deals: 14 won / 14 lost / 8 open,
  118 SF contact roles). Spike/seed scripts live only in the session scratchpad.
- Task 1 `be7883485` config; Task 2 `896280273` + fix `f17a3f254` migration `3b800d603402`
  (project/thread ids are TEXT); Task 3 `7d8e0863b` gateway (`clue_api.crm.composio_gateway`,
  REST over httpx, composio SDK forbidden by import-linter); Task 4 `072bc6806` connection store;
  Task 5 `61d95df2f` routes `/frontend/v1/crm/{connect-link,complete,connection}` + wake.

## Facts / decisions worth knowing
- Connect card is drawn from the `connect_crm` tool result (no agent gate) + `crm_connect_request`
  table (R-3.10). Callback page is a frontend route `/integrations/crm/callback?request=<id>`
  built from `CLUE_APP_ORIGIN`.
- Composio managed apps fix their scopes (dashboard trims don't stick); Salesforce subdomain
  `login` works; expired connection = HTTP 410 slug `ActionExecute_ConnectedAccountExpired`.
- Test DB: `clue_nashville_crm_test` (localhost:55040) — swap the db name in the .env DSN.
- Pre-existing on main, not ours: import contract "agents import only the toolbelt facade +
  projections" broken by `clue_agents.compaction_config -> clue_gateway.model_windows`.
- Dev `.env`: `CLUE_SANDBOX_MAX_RUNS_PER_TURN=75` (R-3.13; example/code default stay 10).
- The founder's Composio dev API key was printed once in a tool output (failed masking);
  founder advised to rotate it.

- Task 8 (reads): `crm/read_actions.py` (allowlist + summary), `crm/read_sinks.py`
  (`CrmReadSinks`, built in `fleet_main`, passed to `build_toolbelt(crm_read_sinks=)` and
  `AgentPlatformComponents.crm_read_sinks`; `conversation_turns` registers `lease.backend` per
  execution and releases in the sandbox's `finally`), `crm/salesforce_budget.py`
  (`SalesforceBudget.take_call`; org limits cached 5 min; `count_salesforce_call(allowed=)` is an
  atomic conditional increment). `find_crm_actions@1` (READ) and `run_crm_action@1` (SPEND,
  AT_LEAST_ONCE) registered ungranted; pinned counts 154 names / 180 addresses.
  Live check 2026-10-20 on the seeded CRMs: summaries parse real shapes (HubSpot search total 36
  with `after` cursor; SOQL 36 records done). Composio's tool search is narrow ("search deals"
  returned only `HUBSPOT_SEARCH_DEALS`) — the Task 11 manual should list the key actions by name.

- Task 9: `brand_knowledge_writes.py` is now the one brand-document writer (`lock_brand`,
  `next_brand_version`, `store_document_bytes`, `retire_older_versions`,
  `render_brand_document`, `write_brand_document_version`; folder = path's first segment);
  `product_management` calls it through thin wrappers stamped `brand_product_management`
  (behaviour unchanged, its tests green). `write_brand_document@1` (`brand_document_tool.py`):
  `company|proof/<slug>.md`; kind required only for a new path, an existing path keeps its kind
  and front matter (like the Brand-context editor) plus `written_by {user_id, turn_id}`;
  identical bytes → `unchanged: true` (its replay identity); `from_file` under `outputs/` via
  `SandboxWorkspaces`. Pinned counts 155 names / 181 addresses.

## Next
Task 10, Task 11 (catalog; skill text to founder first,
uncommitted until trial), then Task 12 founder test on the local stack (gate before Phase 2),
then deploy reads (R-2.4).
