# CRM integration v1 — the Head of ABM reads the customer's CRM

Status: **superseded (2026-10-20)** by
`crm-integration/2026-10-20-crm-integration-first-release-design.md` — the first release includes
writes (see `crm-integration/rulings.md`, R-2.1). Kept for history; do not build from this document.
Originally: draft for founder review (2026-10-18)
Owner: founder (Aryan)
Provider: Composio (https://docs.composio.dev)

## 1. Why

The Head of ABM proposes a project's playbook from the brand context and an interview with the
user. Today that interview has no hard numbers: the brand context comes from the customer's public
website, so it knows the product and the self-serve pricing, but nothing about how the customer
actually sells — deal sizes, win rates, how long deals take, which companies buy, who sits on the
buying committee, where demos come from.

The customer's CRM holds most of that. Version 1 lets the Head of ABM connect the workspace's CRM
from chat, read the deals, work out the sales numbers and patterns, confirm them with the user, ask
for what the CRM cannot answer, and save the result as a detailed brand-context document that every
project reuses. It also merges the CRM's closed-won customers into the existing customers document,
which already drives discovery exclusions.

This is the founder's flow (whiteboard, 2026-10-17):

1. Onboarding is done and the brand context is loaded.
2. The Head of ABM learns the brand from the brand context and interviews the user about their goals.
3. It looks at the deals in the CRM. If no CRM is connected it asks the user to connect one, or to
   give the numbers by hand.
4. The website's pricing is usually the self-serve (PLG) pricing, not what an ABM deal costs, so it
   asks for the sales-led / enterprise pricing.
5. It collects the sales metrics (section 4.4).
6. It asks for the project plan (what kind of project, which accounts, campaign goals, channels).
7. It proposes the playbook the project should carry.

v1 builds steps 3–5 and the hand-off of their result to steps 6–7.

## 2. Goals, non-goals, anti-goals

### Goals
- A workspace owner or admin can connect the workspace's CRM from a card in the chat, in one click
  plus the CRM's own login screen.
- The Head of ABM reads the CRM read-only, works out the sales metrics in its Python sandbox,
  confirms definitions with the user, and asks for what the CRM does not hold.
- The result is saved as a brand-context document (`company/sales-motion.md`) that a person can read
  and edit on the Brand Context page and that every project's Head of ABM reads.
- Closed-won customers from the CRM are merged into `proof/customers.md`, de-duplicated by website
  domain.
- Supported CRMs: **HubSpot and Salesforce first, then Attio and Zoho** — through one generic
  mechanism, not one integration per CRM. All four are in v1, built in that order: each CRM is
  offered on the card once its read-only action list is reviewed, its auth config is set, and it has
  passed its own live check (section 9).
- When no CRM is connected (or the user declines), the same interview still happens: the agent asks
  for the numbers and writes the same document from the user's answers.

### Non-goals (v1)
- Writing anything back to the CRM. The integration is read-only.
- Importing target accounts or contacts into projects (second wave of the integration).
- Recorded sales calls / "call book" transcripts (a separate integration such as Gong, later).
- Keeping CRM data in sync, scheduled refreshes, or reacting to CRM changes (no Composio triggers).
- A Settings → Integrations page. Connecting happens from chat for now; Settings stays "Coming soon".
- Pipedrive, Dynamics 365, Close and other CRMs.
- Deciding what our own Langfuse traces keep of CRM data (deferred by the founder, section 7.4).

### Anti-goals (a failure even if it works)
- **A number the CRM did not support.** Every metric in the document must come from the data, from
  the user, or be marked as unknown. A plausible guess is the failure; "not available" is correct.
- **Arithmetic done in the model's head.** Averages, rates and counts are computed in the sandbox
  over the full data, never estimated from a few records the model happened to see.
- **Raw deal records kept in our database.** We keep the derived summary only.
- **A write to the customer's CRM** of any kind.
- **Losing the website-researched customers** when the CRM customers are merged in.

## 3. Decided by the founder

| Topic | Decision |
|---|---|
| First reason for the CRM | The Head of ABM's sales analysis for the interview and playbook |
| Where results live | A detailed brand-context document, reused by every project |
| Who does the math | The agent, in its Python sandbox (`run_python`) |
| "Qualified demo" / "demo" | The agent infers them from the customer's own stage names, then confirms with the user; if unsure, it asks up front |
| Analysis window | Defaults to the last 3 months; the agent adjusts it by industry (e.g. long enterprise sales cycles) |
| Where the user connects | In chat, for now |
| Who owns the connection | The workspace, not an individual member |
| CRMs | HubSpot + Salesforce first, then Attio + Zoho |
| Write-back | None |
| Customers | Closed-won companies merge into `proof/customers.md`; duplicates resolved by website domain; churn is not checked — a closed-won customer is recorded as closed-won |
| Onboarding refresh of the customers document | Keeps the CRM rows and merges new website findings around them by domain |
| Which CRM customers go into the customers document | For now, only the companies closed-won within the analysis window (3 months by default) — not every closed-won company ever |
| Account / contact import | Second wave, not v1 |
| Call recordings | A separate, later integration |
| Composio data retention | Zero Data Retention (ZDR) on, with the settings in section 7.1 |
| Composio tool search | Allowed |
| Composio's 24-hour file staging | Acceptable |

## 4. How it works

### 4.1 The pieces

1. **Composio** handles the OAuth flow, token storage and refresh, and executes CRM API calls.
2. **One workspace CRM connection** recorded in our database (section 5.1).
3. **A connect card in chat** — a new kind of agent gate (section 4.2).
4. **Two read tools** for the Head of ABM: find CRM actions, and run one (section 4.3).
5. **Results land as files** the agent's Python sandbox can read (section 4.3).
6. **One write tool** for brand-context documents (section 4.5).
7. **A new skill**, `crm-sales-analysis`, that tells the Head of ABM how to do all of this, wired
   into the interview (section 4.6).

### 4.2 Connecting the CRM from chat

**Agent side.** A new governed tool `connect_crm@1`:

- If the workspace already has an active CRM connection, it says so (which CRM, connected when, by
  whom) and does nothing else — unless the agent passes the user's explicit wish to switch CRMs, in
  which case it opens the card in its *switch* state ("Replace HubSpot with…").
- If the connection is `expired`, it opens the card in its *reconnect* state (the same CRM
  pre-selected).
- Otherwise it opens a gate of a new kind, `crm_connection`, and the agent ends its turn on it, the
  same way it ends a turn on a product-selection gate today.

**The card.** The gate renders as a card in the transcript, in the house gate-card style:

- "Connect your CRM" with one button per supported CRM (HubSpot, Salesforce; Attio and Zoho once
  enabled), plus "I don't use a CRM / I'll give the numbers myself".
- A member who lacks `workspace.manage_settings` (viewers and operators) sees the card read-only
  with "Ask a workspace owner or admin to connect the CRM", plus the "I'll give the numbers myself"
  option.

**When the person in the thread is not an admin.** The connection belongs to the workspace, so it
does not matter which thread it is made from: an owner or admin can ask their own Head of ABM to
connect the CRM, in any thread. **When a connection becomes active, every open `crm_connection` gate
in the workspace is answered**, and each waiting thread gets its own `crm_connected` derived turn,
attributed to that gate's addressee (the person whose turn opened it). So a member who was told to
"ask an admin" sees their own thread continue once the admin has connected. The gate's
addressee rule is not relaxed: nobody answers someone else's gate by hand.

**Clicking a CRM:**

1. The browser calls a new route, `POST /frontend/v1/crm/connect-link`, with the gate id and the
   chosen CRM. The route checks `workspace.manage_settings`, asks Composio for a fresh connect link
   (Composio links expire after about 10 minutes, so a link is minted per click, never stored), and
   returns it. The browser opens it in a new tab.
2. The user logs in to their CRM and approves access on the CRM's consent screen.
3. Composio redirects to our callback route, `GET /frontend/v1/crm/callback`. The route confirms
   with Composio that the connected account is ACTIVE, records the workspace connection
   (section 5.1), answers the gate, and queues a **derived turn** (`derivation = 'crm_connected'`)
   on the thread so the Head of ABM continues the analysis without the user typing anything —
   the same pattern as `discovery_finished`. The tab shows a short "Connected — you can close this
   tab" page.

**"I'll give the numbers myself"** is an ordinary gate response; the agent continues with the
manual interview (section 4.6).

**A broken connection.** If a CRM call fails because the connection is expired or revoked, the tool
says so in plain words, the connection is marked `expired`, and the agent can open the connect card
again.

### 4.3 Reading the CRM

Two new governed tools, granted to the Head of ABM only:

- **`find_crm_actions@1`** — searches the actions available for the workspace's connected CRM
  (Composio tool search, scoped to that CRM's toolkit) and returns matching action names, what they
  do, and their input schemas. Read-only actions only (see below).
- **`run_crm_action@1`** — runs one read action with arguments, for the workspace's connection.

**Results go to files, not into the conversation.** Every `run_crm_action` result is written in full
to the agent's `reads/` folder (e.g. `reads/<operation_id>.json`), whatever its size — not only
past the existing 12 KB spill threshold. The tool's reply to the model is a short summary: the file
path, how many records, the field names, whether there are more pages, and the cursor for the next
page. The agent then analyses the files with `run_python`, which can already read `reads/`.

This keeps hundreds of deals out of the model's context, makes the arithmetic happen in code, and
keeps raw CRM data out of the transcript stream, the browser, and the Langfuse span for the tool
call (which today record the tool's full output).

**Paging.** The agent pages through results with repeated `run_crm_action` calls (one file per
page) and combines them in `run_python`. Where a CRM has a bulk export (Salesforce Bulk API 2.0,
which returns CSV), the agent may use it; Composio's 24-hour file staging for it is accepted.

**Read-only is enforced in code, not left to the prompt.** Both tools refuse any action that can
create, change or delete CRM data. How the builder decides which actions are read-only is left to
the builder (section 8), but the rule is a contract: no write action is reachable through these
tools.

**Scope of what is read.** Whatever the analysis needs: deals/opportunities (amount, stage, close
date, pipeline, source), their associated companies (industry, size, region, domain) and contacts
(job title, role on the deal), and the CRM's stage/pipeline definitions. Contact data is read only
to map buying-committee roles and is not stored except as aggregated patterns in the document.

### 4.4 What the analysis covers

From the founder's list:

| Item | Source |
|---|---|
| Average deal size | Closed-won deal amounts in the window |
| Closed-won and closed-lost (counts, win rate, value) | Deal stages and close dates |
| Patterns in the window's closed-won deals | Industry, company size, region, sales-cycle length, deal size, lead source of the companies won |
| Where demos come from | Lead / original-source fields; flagged when sparse or messy |
| Buying committee | Contacts on won deals (Salesforce opportunity contact roles; HubSpot deal–contact associations), their titles mapped to the brand context's personas |
| Cost per lead, per qualified demo, per demo | **Usually not in a CRM.** The agent asks the user; if Salesforce Campaign cost fields are filled it may use them, and says so |
| Enterprise / sales-led pricing | Asked of the user. Deal amounts are shown as the real-world range alongside |

Definitions the agent must settle with the user before computing:
- **What counts as a demo and a qualified demo** — inferred from the CRM's own stages / lifecycle
  stages, confirmed with the user; asked up front when unclear.
- **What counts as closed-won and closed-lost** — the CRM's own won/lost stages, confirmed when the
  pipeline is custom.
- **The window** — 3 months by default; widened by the agent when the industry's sales cycle is
  long or there are too few deals to say anything, and the chosen window is stated in the document.

### 4.5 Writing the results

**The sales-motion document.** `company/sales-motion.md`, a brand-level document (`project_id`
NULL). It lives under the existing `company` folder so the Brand Context page shows it and the
existing edit route accepts it without frontend changes. Contents (the skill sets the exact shape):

- front matter: `kind: sales-motion`, `as_of`, the source (CRM name, or "told by the user"), the
  window, and the definitions used;
- the metrics, each with where it came from (CRM computation, the user, or "not available");
- the closed-won patterns;
- the buying-committee mapping against the brand context's personas;
- the sales-led pricing as the user gave it;
- what is missing or uncertain, and why.

**The customers document.** The agent merges the companies closed-won **within the analysis window**
(founder decision: for now the window's customers only, not every closed-won company ever — so
older customers are still covered only by the website research) into `proof/customers.md`, keeping
its existing table format (`Customer | Domains | Domain check | How
they buy | Evidence | Quote | Source`):

- a company already in the table (same website domain) keeps its row, with the CRM added as a
  source;
- a new company gets a row with "closed-won" in *How they buy* and the CRM as the *Source*;
- a CRM company with no usable domain is still listed, marked "no domain given";
- existing website-researched rows are never removed.

The merge runs in `run_python` (read the current document from `brand/knowledge/proof/customers.md`
and the CRM files, write the merged markdown).

**Onboarding refreshes keep the CRM rows (founder decision).** Onboarding's customers step (the
customers-only refresh and the customers step of a full run, `existing_customers_document` in
`arv2/onboarding_documents.py`) today rebuilds `proof/customers.md` from website research alone.
It must instead carry forward every row whose *Source* is a CRM, and merge its new website findings
around them by website domain: a company found on both keeps one row with both sources. This is a
code change in onboarding, not an agent step.

**One write tool for both.** A new governed tool `write_brand_document@1` creates or updates a
brand-level document:

- **Where it may write:** only under `company/` and `proof/`. It refuses `audience/` (the ICP and
  persona documents, which are confirmed through their own gates and pinned by projects) and
  `product/` (owned by `manage_products@1`).
- **What it takes:** a path and either the markdown body or the path of a file the agent produced in
  its sandbox (`outputs/…`). The file form exists so a long merged customers table never has to be
  re-typed through a tool call.
- **How it writes:** a new version the same way a person's edit does (new row at `version + 1`,
  older row superseded, content-addressed artifact, stamped as written by the agent and the turn).
- **Which brand:** the brand of the project the conversation belongs to.
- The new version is visible in the agent's `brand/` folder from the next turn (the brand mount is
  pinned per turn).

### 4.6 The skill and the interview

A new skill, **`crm-sales-analysis` v1**, in plain language, telling the Head of ABM:

1. When to run it: in the interview, after it has learned the brand and the user's goals, before
   asking for the project plan — and whenever `company/sales-motion.md` is missing or stale.
2. Check for a connection with `connect_crm`; if none, explain why the CRM helps (the website's
   pricing is self-serve; the playbook needs the real sales motion) and open the connect card, with
   the manual option.
3. With a connection: find the deal/opportunity actions, read the pipeline definitions, infer and
   confirm the definitions (section 4.4), pull the window's deals page by page, and compute in
   `run_python`.
4. Ask the user for what the CRM cannot answer (cost per lead/demo, sales-led pricing), and for the
   numbers by hand when there is no CRM.
5. Show the user the findings in the conversation and ask whether they look right.
6. Write `company/sales-motion.md` and merge the closed-won customers into `proof/customers.md`.
7. Never write to the CRM, never state a number it did not compute or get from the user, and search
   for actions by what it wants to do, not with customer data in the search text.

The `stage0-interview` skill is updated to call for this step at the right point in the interview,
and to read `company/sales-motion.md` when proposing the playbook.

**The skill text itself is reviewed by the founder in chat before it is written or merged** (standing
rule). This spec fixes its substance, not its wording.

## 5. Data and configuration

### 5.1 The workspace CRM connection (new table)

One row per workspace connection: workspace id, CRM (Composio toolkit slug), Composio connected
account id, Composio auth config id, status (`active`, `expired`, `disconnected`), connected by
(membership id), connected at, updated at.

- v1 allows **one active CRM connection per workspace** (most companies run one CRM), enforced by a
  unique index over active rows. Switching CRMs goes through the card's *switch* state
  (section 4.2); the old row becomes `disconnected` and its Composio connected account is deleted.
- **Multi-brand workspaces:** deals are not filtered by brand in v1. If a workspace has more than
  one brand, the skill tells the agent to ask the user how to tell the brands' deals apart (a
  pipeline, a product field) before computing.
- The Composio user id is opaque and derived from the workspace id (e.g. `ws_<workspace_id>`) —
  never an email or a name, because Composio stores it even under ZDR.
- No token is ever stored by us; Composio holds the credentials.

### 5.2 Gate kind and derived-turn value

- New gate kind `crm_connection`: added to `GATE_KINDS`, the `agent_gate_kind` DB CHECK, and the
  frontend's supported gate kinds.
- New derivation `crm_connected`: added to the `agent_turn_submission.derivation` CHECK.

### 5.3 Configuration (env parity rule applies — every key goes into `.env.example` with its default)

- `CLUE_COMPOSIO_API_KEY` — secret (project API key of the environment's Composio project).
- `CLUE_CRM_INTEGRATION_ENABLED` — the feature flag, default on (built features stay on); the CRM
  tools (`connect_crm`, `find_crm_actions`, `run_crm_action`) and routes are composed only when it
  is on and the API key is set (the same pattern as `arv2_discovery_enabled` + the Exa key).
  **The manual path does not depend on Composio:** `write_brand_document@1`, the skill and the
  manual interview are always composed, and the skill tells the agent to go straight to the manual
  interview when `connect_crm` is not available.
- One Composio auth config id per enabled CRM (e.g. `CLUE_COMPOSIO_AUTH_CONFIG_HUBSPOT`,
  `..._SALESFORCE`, `..._ATTIO`, `..._ZOHO`); a CRM with no auth config is not offered on the card.
- The public base URL for the OAuth callback, if not already available from existing settings.

The legacy `CLUE_CRM_API_KEY` and the unwired `resolvers/crm/` connector are left alone.

## 6. Agent catalog changes

Following the existing pattern for a new tool + skill (see `manage_products@1`):

- New tools `connect_crm@1`, `find_crm_actions@1`, `run_crm_action@1`, `write_brand_document@1`,
  registered in `build_toolbelt`, granted to `AgentRole.HEAD_OF_ABM` in the tool-authority map,
  each with a `tool_notes.yaml` entry and a chat-card label in `chat-tool-presentation.ts`.
- New skill `crm-sales-analysis/v1`; new `stage0-interview` version.
- New Head of ABM profile version (v73 at time of writing), new recipe0-stage0 revision, manual
  re-mint — the usual bump set.

## 7. Data handling

### 7.1 Composio settings (founder decision)

- **Zero Data Retention on** in every Composio project that real customer data passes through,
  turned on **before the first real customer connects** (ZDR applies only to new calls).
- **Our own OAuth app per CRM** (our name on the consent screen) before the first real customer
  connects. Composio's managed apps are acceptable during development only. Reason: ZDR does not
  cover managed apps outside Enterprise, HubSpot shows an "unverified app" warning on Composio's app,
  managed apps share quota with all Composio customers, and switching apps later forces every
  connected customer to reconnect.
- **Composio's own sandbox (Workbench) off** in our sessions; analysis runs in our `run_python`.
- **No Composio triggers** for CRM data.
- **Tool search allowed** (founder decision; Composio may cache search queries — the skill keeps
  customer data out of search text).
- **24-hour file staging accepted.**
- **Opaque user ids** (section 5.1).
- Development and testing use a demo / developer CRM account, not a real customer's data, because
  Composio's managed apps are not covered by ZDR.

### 7.2 What still exists with ZDR on

Composio keeps per-call metadata (ids, tool name, timing, status), audit logs and its telemetry
(which can include CRM error messages). There is no API to delete Composio logs; an erasure request
goes to Composio support under its DPA (§3.1). Its DPA includes the EU Standard Contractual Clauses
for US hosting. Shorter retention, EU hosting and self-hosting are Enterprise-only and out of scope.

### 7.3 What we keep

- `reads/` files with raw CRM results live in the thread's sandbox workspace like any other spilled
  tool result.
- Our database keeps the connection row and the two documents — not raw deals.

### 7.4 Deferred by the founder

What our own Langfuse traces and our model provider see. With results going to files (section 4.3)
the tool span carries only the summary, but `run_python` output and anything the agent quotes back
into the conversation are traced as usual. Decide before broad rollout.

## 8. Left to the builder

- How read-only actions are identified (a reviewed allowlist per CRM, Composio action metadata, or
  both), as long as no write action is reachable.
- Whether the tools use Composio sessions or direct execution, and pinning toolkit versions.
- How `run_crm_action` always writes its result to `reads/` (extending the spill mechanism or a
  dedicated writer).
- The exact card copy and layout, within the existing gate-card style.
- The callback page, and how the callback finds the gate and thread (e.g. state carried through
  Composio's `callback_url`).
- Rate limiting per workspace against Composio's single per-organization limit.

## 9. Verification

Business-logic scenario tests through the real routes, database and tools (not only unit tests),
plus a live check on the dev stack against each CRM's developer / demo account — HubSpot first, then
Salesforce, Attio and Zoho as each is enabled:

1. With no connection, the agent opens the connect card; a non-admin sees the read-only version.
2. Connecting through the card records the connection, answers the gate, and the derived turn
   continues the analysis without user input.
3. The agent pulls deals page by page into `reads/`, computes the metrics in `run_python`, confirms
   definitions with the user, asks for cost per lead/demo and pricing.
4. `company/sales-motion.md` appears on the Brand Context page and is editable.
5. `proof/customers.md` gains the CRM's closed-won customers, keeps every website-researched row,
   and has no duplicate domains.
6. A write action is refused by both CRM tools.
7. An expired connection produces a plain-language message and a new connect card.
8. "I'll give the numbers myself" produces the same document, sourced to the user — also on a
   deployment with no Composio key.
9. A member without admin rights is told to ask an admin; once an admin connects from their own
   thread, the member's thread continues on its own.
10. `write_brand_document` refuses `audience/` and `product/` paths.
11. Re-running onboarding's customers step keeps every CRM row and adds the new website findings
    without duplicate domains.

## 10. Calls made by Claude, not the founder (check these)

1. One active CRM connection per workspace; switching goes through the card.
2. A connection made in any thread answers every open connect card in the workspace and wakes each
   waiting thread.
3. `write_brand_document` may write only under `company/` and `proof/`, and accepts a sandbox file
   instead of a body.
4. The sales-motion document lives at `company/sales-motion.md` (so the Brand Context page shows it
   with no frontend change).
5. The manual interview and the write tool work without Composio; only the CRM tools need it.
6. All four CRMs are in v1, enabled one by one after each passes its review and live check.
7. Every CRM result goes to a `reads/` file; the model sees only a summary.
8. Multi-brand workspaces: no brand filtering; the agent asks the user how to separate the deals.

## 11. Still open

- The founder's whiteboard says the pricing question "would give two options". This spec assumes
  the two options are *connect your CRM* or *give the details yourself*; confirm.
