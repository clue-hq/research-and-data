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

- Task 10: `onboarding_documents.crm_customer_rows` parses CRM rows (Source contains `CRM:`,
  columns found by header name, `\|` unescaped); `existing_customers_document(carried_rows=)`
  merges one row per domain (shared domain → web row + ` · CRM: …` on its Source; others
  appended; sorted by name). Driver gets an injected `CurrentDocumentReader`
  (`fleet_main._current_brand_document` = `brand_knowledge_writes.current_brand_version` +
  `product_management.read_brand_document`); a failed read fails the customers step rather than
  dropping rows. CRM rows the agent writes MUST put `CRM: <HubSpot|Salesforce> …` in Source.

- Task 11 (UNCOMMITTED until the founder's trial, R-3.14): head-of-abm v76 (four tools granted,
  `crm-sales-analysis@v1`, `stage0-interview@v49` with section 2b, `manual-*@v22`), recipe
  `recipe0-stage0-v36.json` (CONVERSATION_RECIPE_VERSION 36), pins (connect_crm/write_brand_document
  from the presenting turn; find_crm_actions/run_crm_action from the execution — find_crm_actions
  gained `pin_requirements=("project",)` because the recipe audit requires a pin), tool notes for
  the four tools, CRM tools withheld on the Stage-0 trial surface, skills-block budget 5120 -> 5632
  (one resource joined). Manual v22 hand-written chapters = v21 with paths repointed, plus one
  sentence in gates-authority and workspace (and stage0 v49 §10) naming write_brand_document as
  the one exception to "brand/ is read only". Kept uncommitted as ONE unit: committing the wiring
  without the profile/skill files would leave HEAD unable to resolve head-of-abm@v76.

- 2026-10-20 later: R-3.15 — write_brand_document now takes any company/product/audience/proof
  document except product/catalog.md (and any front matter `generated: true`), only when asked or a
  skill says so; optimistic `based_on_version` check (refuse `document_changed`; identical bytes
  still return unchanged first, so replays pass). Agent's brand/ mount is fixed per turn, so a
  `document_changed` is retried NEXT turn. R-3.16 — skills-block budget kept at 5120: stage0 v49
  summary shortened (block now 5070 bytes). Both uncommitted with Task 11.

- 2026-10-21 trial 1 (local stack, Conduit AI workspace, HubSpot test account): card (Figma
  redesign, uncommitted) works in all 3 states; connect + reads + analysis correct; publishing
  BLOCKED — `clue_execution/graph.py::_RAW_BODY_KEYS` rejects any plan binding named `body` (even
  null), so `write_brand_document` is uncallable by the agent (fix = rename the field + a test through
  plan validation). Other findings F1–F9 in
  `docs/superpowers/specs/crm-integration/2026-10-21-trial-1-findings.md`; founder wants to discuss
  before fixing. Uncommitted: the card + `rereadThread()` (F2) + `connectedByName` on the route.

- 2026-10-21: F4 fixed (`1e88e9242`): input `markdown`; `tests/api/test_tool_input_names.py`
  guards every tool's input names against `_RAW_BODY_KEYS` (exception `write_project_document@1`)
  and runs write_brand_document through `_plan_graph_and_parameters` + `validate_graph`. F2 plan:
  `docs/superpowers/plans/2026-10-21-chat-thread-stream.md` (R-10.1). Skill/profile/manual hashes
  refreshed (uncommitted with Task 11).

- 2026-10-21: F2 built and live-checked (plan `docs/superpowers/plans/2026-10-21-chat-thread-stream.md`,
  commits b3c4882b7, a17124c52, f3dda2920 + review fixes 7a14ca5ad, 99a7530a1). Thread SSE route
  `…/threads/{id}/stream_token|events`, `agent_thread` stream-token subject (migration 8c3e73eb83b2),
  lifecycle partial index (c87ba03cfc4e), hello carries the start cursor, frontend `chat-sse.ts`
  (shared reader, `reconnectDelay`, thread stream retries forever), controller opens it while
  visible; discovery 5 s timer replaced (30 s thread-list safety re-read while held). The CRM card
  nudge is removed from the working tree; card files stay uncommitted with the redesign. Stack DB
  `clue_nashville_pm` at c87ba03cfc4e. `make db-smoke` cannot run on clue_nashville_crm_test (an old
  M8D R2 downgrade guard trips on leftover fleet tasks). New finding F10: an 11-minute reasoning
  loop on a test turn (stopped by hand). Owed: the server-started wake turn live, together with the
  F4 publish re-check, with the founder watching.

- 2026-10-21: F4 live re-check PASSED in the trial chat — sales-motion v1 + customers v3 published
  (7 min, $1.09, 0 tool errors); outputs/ kept after the turn (AW-6 stopgap f799a9830 live after a
  worker restart). New F11: CRM skill asks for outputs/sales-analysis.py but the sandbox deletes .py.
  F3 now lives in docs/superpowers/specs/agent-workspace/ (AW-1..AW-8), built in the dushanbe lane.

## Next
- **OWED (founder asked to note, 2026-10-21): the F2 live test of a server-started wake turn.** Not
  run yet. Options put to the founder: (A) real reconnect through the card (HubSpot sign-in in the
  in-app browser, not Arc — F1), (B) a one-off script calling `queue_crm_connected_turns` for the
  trial chat `thr_5a44dd39b5df5ee0ae0c0b7a8759c1fe` (recommended, combined with the F4 publish
  re-check, founder watching — "continue where we left off" will make the agent rebuild and publish
  company/sales-motion.md + proof/customers.md, ~8 min), or a fresh chat with nothing pending.
  Watch: the wake turn appears in both open tabs within ~2 s, and its turn.accepted has
  `"source": "worker"`. Nothing is running on the stack (checked 2026-10-21 after F2).
Task 12: founder trial on the local stack (gate before Phase 2); then commit Task 11 as one unit (or revise the skill), then deploy reads (R-2.4).

- 2026-10-22: Phase 2 (write foundation) built and live-checked — continued in
  `_memory/2026-10-22-crm-integration-phase2.md`. The owed F2 server-started wake test above was
  seen live during it (the `crm_writes_finished` wake turn appeared in the open tab without reload).
