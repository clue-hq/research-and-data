# Combined browser acceptance

Date: 2026-08-16
Branch: `platform/integration-onboarding-pilot`
Status: stopped at the first invalid downstream prerequisite; Stage-0 interview passed but ICP
synthesis is blocked by a product-scoped Client-KB version-pin mismatch

## Isolated runtime

- Fresh PostgreSQL database: `clue_combined_browser_20260816_c1`.
- Fresh durable artifact root: `/private/tmp/clue-combined-browser-20260816-c1`.
- Separate agent-workspace root:
  `/private/tmp/clue-combined-browser-agent-20260816-c1`.
- Database is at sole Alembic head `f85ca69b93ba` and remains zero-state: zero platform users,
  workspaces, and projects.
- The merged API is running on `127.0.0.1:8000` with real Clerk authentication, self-serve
  provisioning, frontend reads, chat, C7 reads/snapshots/evidence/handoff, filesystem storage, and
  pilot budget controls off. It authorizes the active `localhost:3000` Clerk origin and retains the
  earlier isolated `3077` origin for diagnostic continuity.
- The merged frontend now runs on `127.0.0.1:3000` with its authenticated same-origin BFF. The
  earlier disposable `3077` process was stopped.
- The fleet now runs with the fresh browser-provisioned workspace in both the official-site crawl
  and agent-runtime allowlists.

## Resolved browser blocker

- The in-app Browser connected successfully and its first request reached the frontend/API, but
  the first frontend process had an incorrectly overridden cross-origin project-chat URL. The
  process was restarted with the repository's required `/api/clue` same-origin value.
- On the corrected stack, the in-app Browser refused both reload and DOM inspection of the
  localhost tab under its URL safety policy. Per the Browser skill, no other browser surface,
  raw protocol, indirect navigation, or automation workaround was used.
- Resume condition: the user opens `http://localhost:3077` in the in-app Browser, then the agent
  claims that exact tab and continues the requested browser -> API -> PostgreSQL matrix.

## Local rendering diagnosis

- The user-opened in-app tab first exposed a complete `/onboarding/profile` accessibility tree,
  while the isolated database remained zero-state. The initial root request took 5.4 seconds:
  3.9 seconds in Next development compilation and about 1.5 seconds in proxy/application work.
- The same Turbopack dev process then became genuinely unresponsive: direct probes to both `/` and
  `/onboarding/profile` timed out after 15 seconds with zero response bytes even though the Node
  listener remained open. The user's screenshot correctly showed a blank navigation, not merely a
  slow rendered page.
- Restarted only the disposable frontend with Next 16 webpack. Direct route probes then passed:
  root returned its expected redirect in 2.6-2.9 seconds, and the onboarding profile returned 200
  in 1.7-2.4 seconds. API, database, and fleet state were not the cause of the blank page.
- Computer Use could not attach to the running Google Chrome application after three attempts.
  The dedicated Chrome browser-control path did reach the webpack server—the server completed root
  and profile responses—but the control operation itself remained pending for 45 seconds. This is
  evidence of a browser-control/extension-side hang after a healthy server response; it is not a
  completed visual Chrome acceptance.
- The first real profile submission was correctly rejected by the frontend CSRF boundary with
  `origin_forbidden`: the disposable frontend listened on `localhost:3077` while `clueAppOrigin()`
  retained its development default `http://localhost:3000`. The backend and provisioning route were
  never reached. Restarted the webpack frontend with exact `CLUE_APP_ORIGIN=http://localhost:3077`
  and matching Clerk authorized parties; source files were not changed.

## Acceptance still outstanding

ICP revision and approval, discovery, FI-2 selected-account launch, budget controls in both modes,
different product choices across projects, DSAR/historical target receipts, and
design-integration exclusion remain outstanding. The main path cannot progress past ICP synthesis
without repairing the product-scoped Client-KB resource pin described below.

## Clerk onboarding and fast-release evidence

- Real Clerk provisioning succeeded and created one fresh user/workspace. The setup BFF returned
  `202` and the frontend began polling durable setup truth.
- The first acceptance worker boot failed before claiming work because the isolated agent-workspace
  root had mode `0755`; the runtime correctly requires an owner-private directory. With no worker,
  the setup stayed at one durable frontier until the UI's honest stall budget exposed `Try again`
  and `Continue anyway`. This was test-stack preparation drift, not a regression in onboarding
  enqueue, polling, or release behavior.
- Changed only the isolated agent-workspace root to `0700` and restarted the worker with the exact
  fresh workspace allowlisted. It claimed the original task, bound the client entity, and enqueued
  one authoritative Scrapling crawl.
- Browser control selected `Try again`, which reloads the replay-safe start/read path. The app
  observed the same durable run and automatically navigated through `/session/establish` to Home;
  `Continue anyway` was not used.
- After worker start, the fast checkpoint froze and fast extraction completed in about 11 seconds:
  12 fast snapshots, 13 claims, eight filled company fields, one empty and one failed operation.
  Client-KB v1 and one linked product were synchronized.
- Same-frontier background work then completed about 16 seconds later under the same crawl and
  recon ids: 52 background snapshots, 27 claims, all nine company fields filled with one failed
  field operation preserved, Client-KB v2 synchronized, and the linked product received five
  filled fields with two empty and two failed operations. No second crawl was created by retry.

## Project and Stage-0 browser evidence

- Project A inherited Client-KB v2. Before product selection its turn had company knowledge and
  Stage-0 project state; after the human selected `AI Virtual Care Assistant`, the following turn
  pinned that exact product and Product-KB v1 and included product profile/product knowledge.
- Project A used governed `list_client_knowledge@2` and `inspect_client_claim@2` calls. One parallel
  inspection attempt hit PostgreSQL `DeadlockDetectedError` while inserting an execution event;
  repair/retry recovered, but the no-deadlock acceptance row failed.
- The product-selection alert used the product name, but the separate human receipt rendered
  `Requested changes: AI Virtual Care Assistant`; that label is wrong for a selection receipt.
  Normal transcript prose also leaked raw internal statement, gate, and readiness ids.
- A fresh Project B ran the actual Stage-0 interview. The human selected the project product, then
  the browser answered account scope/exclusions, primary pain and messaging, and buying-committee
  priorities. The database holds seven project-state statements (including instruction/product
  selection), two `ready` ICP-synthesis decisions, and no ICP row.
- The live turn inspector and worker agree on L3 composition. The final interview turn pinned
  Client-KB v2 and Product-KB v1 under `company-and-selected-product-v2` and included
  `client_knowledge.json`, `product_knowledge.json`, `product_profile.json`, and
  `stage0_project_state.json`. The eager onboarding knowledge was therefore available during the
  interview as intended.
- `synthesize_icps@2` fails deterministically with
  `pin_resolution_failed: cannot pin Stage-0 resource
  client_kb:<client>|<selected-product>@2: missing`. The company Client-KB is v2 while the selected
  product KB is v1. No ICP draft, ICP gate, discovery plan, or discovery candidate is created.
- Reloading Project B preserved the product receipt, full interview, ready decision, and synthesis
  failure without spawning a new turn. Durable replay passed at this stopping point.

## Accounts/FI-2 prerequisite defect

- The Accounts browser page showed Insight Health AI as its only row. That entity is the bound
  client, not a prospect. Read-only database evidence shows exactly one `account_entity`, its id is
  the `workspace_client_binding.client_entity_id`, and the workspace has zero `project_account`
  rows and zero `discovery_candidate_link` rows.
- `frontend_read/accounts_list.py` scopes `account_entity` only by workspace/merge/project
  membership and does not exclude the workspace client binding, so the client leaks into the
  prospect Accounts surface.
- The frontend `New account` control creates explicitly local, non-durable state. It cannot be used
  as a substitute for real discovery or a valid FI-2 selected-account launch.
- Stop downstream browser acceptance here. Do not treat Insight Health as its own target, seed a
  fixture, or claim discovery/FI-2 evidence until ICP synthesis is repaired and a genuine target
  account is produced by the platform.

## Confirmed-discovery retry and live Exa boundary

- Repaired the Stage-0 handoff without compiling any new knowledge: company-wide Client-KB cards
  may be present without a project binding, Recipe #1 now pins the receipt's exact company
  Client-KB v2 and selected-product Product-KB v1, and the recipe worker preserves the parent turn
  execution id in tool contexts.
- The narrower content-addressed `product_context_version` receipt now identifies Client-KB,
  selected product/product profile, Product-KB, and approved ICP only. Mutable project conversation
  state remains in every turn's L3 project context but no longer creates a different paid-run
  receipt after each message.
- Browser run `3093fcfb-921e-5668-aa18-be8024aeec72` reached the real Exa Websets submit path. The
  durable batch and provider operation both ended `failed_terminal` with `exa_http_401`, zero
  provider units charged, zero cost charged, and no candidate materialization. A separate
  read-only request with that credential returned HTTP 401 because its Exa team lacked API-plan
  entitlement, confirming a provider-auth/entitlement blocker rather than a browser, spend-gate,
  or verification-gate bug.
- The live browser correctly showed `0-0 of 0` Accounts, and the project Gallery opened with `No
  artifacts yet`. Neither downstream surface passes acceptance until a valid Exa credential is
  installed and the exact run is retried.
- The same run exposed an additional contract failure: the assistant told the user that five
  accounts were starting, but `project_run_discovery_configuration` persisted the policy default
  `requested_account_count=10`, generic approved-ICP firmographics, and no exclusions. The existing
  Stage-0 discovery-start tool cannot consume the already-recorded five-account criteria override.
  Do not describe this run as honoring the requested discovery scope.
- Focused verification passed: Recipe #1 cutover/resume tests, Stage-0 confirmed-run v2/v3 tests,
  an executor regression proving parent-execution propagation, Ruff, formatting, and mypy.
- The user then replaced `CLUE_EXA_API_KEY`. A direct Websets GET sent with team id
  `cmsasct2d00ncl104qjqw0jo9` returned HTTP 200 and listed an existing completed Clue Webset. The
  acceptance fleet was restarted with the refreshed environment. Exa's public Websets contract
  binds access to the API key; the production client continues to authenticate with `x-api-key`.

## Browser retry with repaired Exa access

- A fresh authenticated browser turn retried the existing five-account discovery after the fleet
  loaded the working Exa key. The turn again received the exact project card, Client-KB v2,
  selected product/profile, Product-KB v1, and approved ICP context. Budget and verification gates
  remained absent.
- `start_confirmed_project_run@3` failed before provider I/O with `ExecutionConflict: execution id
  was replayed with a different recipe, scope, or parameters`. The durable run still owns Recipe #1
  execution `44ef6fe3-b2bf-52a5-8ae8-6bad3eb367c1`, whose immutable parent execution is the older
  chat turn `75d39ff1-884e-590a-bb76-b855418848f5`; the browser retry originates from a different
  chat execution. `DbExecutionStarter` includes `parent_execution_id` in exact replay identity,
  while `Recipe1ProjectExecutionRouter` passes the current chat execution on every attach.
- The failed retry created no new discovery batch or provider operation. The old 401 batch remains
  the only batch, candidate links remain zero, and the project has zero project accounts. Browser
  `/accounts` truthfully rendered `No accounts exist in this workspace yet` and `0-0 of 0`.
- The previously recorded scope defect also remains: the durable run asks for 10 generic ICP-derived
  accounts with no exclusions, despite the assistant describing a five-account Washington/Oregon
  scope. Account-discovery browser acceptance must remain failed until replay retains the original
  Recipe #1 parent and an explicit confirmed discovery-scope override reaches the run receipt.

## Confirmed-discovery retry repair

- Replaced the stale acceptance frontend, API and fleet processes while preserving the named
  database, project, approved ICP, failed 401 run and provider receipts.
- Recipe #1 exact replay now retains the immutable parent already stored on its deterministic
  execution id, so a later chat turn cannot redefine execution ownership. A real PostgreSQL
  regression proves a retry from a different parent returns the same execution and preserves the
  original parent.
- An explicit bounded human discovery scope may now be confirmed even when the approved ICP also
  admits a complete policy default. `start_confirmed_project_run@3` prefers the newest exact
  approved scope for the active ICP and falls back to deterministic derivation only when no such
  gate exists.
- Minted `stage0-interview@v20` and `head-of-abm@v33` so new turns instruct the agent to honor an
  explicit human count/criteria/exclusion request before starting. Historical v19/v32 bytes remain
  unchanged.
- Focused unit/catalog/registry/trial/privacy tests passed (56 cases); the Recipe #1 PostgreSQL
  replay regression passed; Ruff, formatting and mypy passed on the changed runtime surfaces.
- Live browser -> Exa -> database acceptance remains pending the corrected stack restart.
- Fresh corrected processes then started successfully: frontend on `localhost:3000`, projections
  API on `127.0.0.1:8000`, and a new fleet worker, all against the preserved database/artifact
  pair. API and fleet logged the same filesystem root; Exa acquisition/lifecycle are enabled while
  budget controls and verification remain disabled.
- The initial `/accounts` support screen was deployment configuration, not an Account payload
  incompatibility: the API returned 404 for both frontend-read endpoints while
  `CLUE_FRONTEND_READ_ENABLED` was false. Restarting only the API with that flag enabled made
  `/frontend/v1/accounts` and `/frontend/v1/accounts/bulk-capabilities` return 200 and restored the
  truthful empty table.
- The corrected browser journey reused the existing Stage-0 cards and opened only discovery-scope
  gate `6657b89d-cbec-52d6-b19f-8345a6cf657b`; no budget or verification gate appeared. The human
  confirmation created project run `40b37240-4adf-524c-973d-8b6985adcac9` with the exact five-
  account Washington/Oregon configuration and reused product-context receipt
  `1c4e3ab9-4ee1-4ea8-a8a9-2187262d9106`.
- Real provider proof: fleet logged `POST https://api.exa.ai/websets/v0/websets` -> `201 Created` at
  2026-08-16 10:54:24 IST, persisted provider operation
  `webset_01m04gee1e0mhqv8d32fs5w87c`, and received 200 responses while polling it. Exa completed
  five results; the platform reconciled 70 provider units / 31.430 cents, persisted five item
  snapshots, five candidate links and five `project_account` rows. The real browser then rendered
  `Showing 1-5 of 5` with those five accounts on `/accounts`.
- Downstream completion is not yet correct: D4 materialization reached `seal_pending`, but Recipe #1
  had already terminally blocked its scoring node with `unexpected_project_phase` while discovery
  was waiting on Exa. The external wake reoffered the graph, but that immutable blocked node cannot
  retry, so the batch remains unsealed even though account discovery and UI materialization
  succeeded. Treat this as the next workflow-handoff defect, not an Exa/authentication failure.

## Discovered-account profiling browser acceptance

- Continued from the real five-account Exa Websets result in the same workspace/project. The
  browser `/accounts` table rendered all five project accounts with truthful per-account research
  status; Rebound Orthopedics & Neurosurgery changed to `Completed` while the other four remained
  `Not started`.
- The selected-account composer must retain its structured Slate mention. Browser automation that
  used `fill()` after selection replaced the mention with plain text and the agent correctly
  refused to infer an account id. The accepted path was: open the `@` picker, use keyboard
  navigation to select Rebound, retain the visible `Account context: Rebound Orthopedics &
  Neurosurgery` chip, then append the instruction with `type()`.
- The accepted v5 turn composed the unchanged Stage-0 cards: project conversation, Client-KB v2,
  Stage-0 project state, selected product profile and Product-KB v1. It minted directive
  `research-directive:982be2dc-daee-5336-b7e7-b186263c5b51:v5`, run
  `b513fbab-f7cc-545b-a2cb-0752dabb792e`, and job
  `35d863a5-70bb-5c20-85ae-90e9e3ea3ba0`. The durable authorization admits exactly Rebound, the
  three requested account fields, and `exa_deep`; committee sources, contact work, verification and
  interactive budget authority are empty/disabled.
- The first real provider attempt for this account proved external I/O: the fleet logged
  `POST https://api.exa.ai/search` -> `200 OK`. External operation
  `4481add9-c760-4337-929e-a4901d9f7863` is `ready`, provider request
  `80f80d420d14bf06761553f793484fd0`, snapshot
  `7c68b584-d3db-4a68-971c-816be9c125c5`, with 2.600 cents provider-reported and settled cost.
  All three resulting claims carry that exact operation/snapshot lineage.
- That first result transaction exposed two genuine off-mode defects: a database CHECK still
  required `spent_cents <= budget_cap_cents` even when budget enforcement was disabled, and an
  account-only run was later classified `needs_review` solely because no committee had been
  requested. The fixes make budget-off spend record-only while retaining writer-side enforcement
  in ON mode, and derive committee coverage from whether committee sources were selected.
  Migration `44dc4ba7ca63` updates the run/job nonnegative checks and is reversible.
- The v5 retry correctly reused the three already-fresh Exa claims instead of paying twice. Its
  coverage receipt marks `account.strategic_moves`, `account.operational_pain`, and
  `account.resonance.public_frustrations` completed with `existing_claim_fresh`, no unresolved
  fields, no review flags and committee `complete` because committee work was out of scope. Run and
  job are terminal; job outcome is `completed`.
- Browser detail proof passed: the Rebound preview renders the three Exa-deep researched fields,
  the generated account summary, source/date labels, and `16 fields hold a value for this account`.
  The Accounts table marks the row `Completed`.
- One UI gap remains: the task part embedded in the original chat message is intentionally a
  turn-close snapshot and still renders `Queued 0 of 1 account settled` after reload even though
  the database and Accounts read model say `Completed`. The project Gallery is currently
  artifact-only and renders `No artifacts yet`; discovered accounts live on `/accounts`, not in a
  project Gallery tab.
- Verification: focused regression suites passed (all selected unit cases plus 43 database
  integration cases); repo Ruff format/check, mypy across 691 source files, and all 25 dependency
  contracts passed. `alembic heads` reports only `44dc4ba7ca63`. A separate named database completed
  clean upgrade -> downgrade base -> upgrade head.
