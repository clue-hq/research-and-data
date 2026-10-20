# CRM integration — first release design (HubSpot and Salesforce, read and write)

| | |
|---|---|
| Status | Draft for founder review (2026-10-20) |
| Owner | Aryan (founder/CTO) |
| Decisions | Every founder decision is in [`rulings.md`](rulings.md) and cited here as **R-x.y**. This document does not repeat the reasoning behind them. Choices made by Claude (not the founder) are listed in section 15 for review. |
| Replaces | [`../2026-10-18-crm-integration-v1-design.md`](../2026-10-18-crm-integration-v1-design.md) (read-only draft). Its read-side design carries over here; the internal read-only "v1" stays a development checkpoint (R-2.1). |
| Index of all documents | [`README.md`](README.md) |
| What is built / not built | [`status.md`](status.md) — the build-status log; this design describes the whole first release, built incrementally: **reads first, then writes, a few at a time** (R-2.2) |

---

## 1. What this is and why

Clue's Head of ABM plans ABM programmes from public research and the brand context. It cannot see
how the customer actually sells, and nothing it does is visible inside the customer's CRM, where
their sales team lives.

The first release connects a workspace's **HubSpot or Salesforce** through **Composio** (R-1.1,
R-1.8) and gives the Head of ABM two abilities:

1. **Read the CRM to understand the sales motion** (R-1.2): deal sizes, win and loss, sales cycle,
   who buys, where demos come from, the sales-led pricing (R-3.8), and the recent customers. The
   result is saved as a brand-context document every project reuses (R-3.3), and the recent
   customers are merged into the customers document that drives discovery exclusions (R-4.1 to
   R-4.5).
2. **Write Clue's work back into the CRM** (R-2.1) — target accounts in list or campaign
   membership, HubSpot's target-account and ICP-tier fields, the buying-committee contacts Clue
   found (and missing companies/accounts), and (when the admin opts in) Clue's own fields (R-6.19)
   — always under
   the user's permission (R-6.3 to R-6.5, R-6.7, R-6.8, R-6.12), never merging (R-6.13), and with a
   write log the user can query and undo through chat (R-8.5).

## 2. Goals, non-goals, anti-goals

### Goals
- A workspace connects HubSpot or Salesforce from the chat in one click plus the CRM's own consent
  screen (R-3.1, R-3.7).
- The Head of ABM reads the CRM, computes the sales metrics in its own sandbox (R-3.4), confirms
  definitions with the user (R-3.5), and writes `company/sales-motion.md`.
- Recent closed-won customers merge into `proof/customers.md` by domain (R-4.2, R-4.4), and survive
  onboarding refreshes (R-4.5).
- The Head of ABM can propose any allowed write; the user approves it in chat with **Allow once**,
  **Always allow** (one field on every record, or one kind of write), or **Fully automatic** (R-6.3,
  R-6.7).
- Every write is logged with the value it replaced, returns a structured per-record result
  (R-6.2), is safe to retry (R-7.1, R-7.2), and can be undone through chat (R-8.5).
- Clue's footprint in the CRM starts small (R-6.1, R-6.9) and grows only with an admin's opt-in.

### Non-goals (first release)
- Importing accounts or contacts **from** the CRM into Clue projects (R-1.9).
- Merging or deleting CRM records (R-6.13).
- Recorded sales calls (R-1.7), Slack, email sending (separate work).
- Writes driven by events, and **all activity writes** — notes (including research summaries),
  owner tasks, logged meetings/emails/replies, visit roll-ups — and deals (R-6.15, R-6.16, R-6.19,
  R-6.20) — parked for now.
- Change notifications (Composio triggers) and a continuously synced copy of the CRM.
- The CRMs' own MCP servers (R-1.8).
- A Settings → Integrations screen. Connecting, grants and the write log work through chat first
  (R-3.7, R-8.5).
- Suppressing opted-out people inside Clue (R-8.2).
- Deciding what our own Langfuse traces keep of CRM data (R-5.5).
- Attio, Zoho, Pipedrive, Dynamics (R-1.3).

### Anti-goals (a failure even if it works)
- **A number the data did not support.** Every metric comes from a sandbox computation or from the
  user, or is marked "not available".
- **Any change to the customer's CRM the user did not permit** — by Allow once, a standing grant, or
  Fully automatic.
- **A duplicate record created by a retry.**
- **A silent failure.** Every write ends as succeeded, or failed with a reason the agent can act on.
- **Touching consent fields** (R-8.1) or **merging** records (R-6.13).
- **Burning a Salesforce customer's daily API allowance** so their other tools fail (R-7.5).
- **Flooding reps' timelines** (R-6.10).

## 3. The pieces

```
Head of ABM (chat)
  │  connect_crm ──────────────▶ connect card (gate) ─▶ CRM consent screen ─▶ callback ─▶ connection row
  │  find_crm_actions / run_crm_action ──▶ Composio ──▶ CRM            (reads; results land in reads/)
  │  run_python  ──▶ analysis in the sandbox
  │  write_brand_document ──▶ company/sales-motion.md, proof/customers.md
  │  propose_crm_changes ──▶ classify each change ──▶ covered by a grant? ──yes──▶ write executor
  │                                                      └─no──▶ permission card (gate) ─▶ answer ─┘
  │                                       write executor ──▶ write log ──▶ Composio ──▶ CRM
  │                                                 └──▶ wake the thread with per-record results
  │  crm_write_log / manage_crm_grants ──▶ "what did Clue change?", undo, list/revoke grants
```

Everything the agent does goes through governed Clue tools; the model never calls Composio
directly. Composio holds the CRM tokens and executes the calls (R-5.2).

## 4. Connecting

### 4.1 From the chat (R-3.7)

- **`connect_crm@1`** reports the existing connection, or shows a **connect card** and ends the
  turn. The card is drawn from the tool's own result (not an agent gate, R-3.10); the tool writes a
  `crm_connect_request` row recording the waiting chat, the turn that showed the card, who asked, and
  the mode.
  - Already connected: says which CRM, since when, by whom.
  - The connection is `expired`: opens the card in its *reconnect* state.
  - The user wants a different CRM: opens the card in its *switch* state. One active CRM per
    workspace (section 15, call 1).
- **The card** offers HubSpot and Salesforce, plus "I'll give the numbers myself". Clicking a CRM
  calls `POST /frontend/v1/crm/connect-link`, which mints a fresh Composio connect link (they expire
  after about 10 minutes) and opens it in a new tab.
- **The callback** (`GET /frontend/v1/crm/callback`) confirms the connection is active, stores it,
  answers **every open connect card in the workspace**, and queues a derived turn
  (`derivation = 'crm_connected'`) on each waiting thread, attributed to that card's addressee —
  the same pattern as `discovery_finished`.
- **Who can connect:** owners and admins (`workspace.manage_settings`). Others see the card
  read-only with "ask an owner or admin", plus the manual option (section 15, call 2).

### 4.2 Right after connecting

The agent's first message after `crm_connected` covers, in plain words:
1. **What Clue may now read**, and that nothing is written without permission.
2. **The starting permission** (R-6.4): "May Clue keep its own lists/campaigns and, if you turn
   them on later, its own fields up to date without asking each time?" — a one-time, revocable yes.
3. **Automations** (R-8.4): Clue writes mainly to things it owns (its lists, campaigns, notes); we
   recommend excluding Clue's changes from the customer's own automations (on Salesforce, by
   excluding the integration user).
4. **Salesforce only:**
   - The org must have API access (Enterprise, Performance, Unlimited, Developer; Professional only
     with the paid API add-on). If the connection fails for this reason, the agent says so plainly.
   - A **dedicated integration user is recommended** (five free API-only licences on Enterprise and
     above), but a personal login works; Clue's changes will then show that person's name (R-6.11).
   - The admin may need to approve Clue's connected app in their org.

### 4.3 Connection record

One row per workspace connection: workspace, CRM (`hubspot` | `salesforce`), Composio connected
account id and auth config id, the CRM account id (HubSpot portal id / Salesforce org id), status
(`active`, `expired`, `disconnected`), connected by, connected at, settings (including the
Salesforce API share, R-7.5, and whether Clue fields are on, R-6.1). The Composio user id is opaque:
derived from the workspace id (R-5.2). Clue never stores CRM tokens.

The table is named and shaped so later integrations (Slack, email) can share it: a `provider`
column, not a CRM-only name (section 15, call 3).

## 5. Reading the CRM and the sales analysis

### 5.1 Read tools

- **`find_crm_actions@1`** — Composio tool search scoped to the connected CRM (R-5.3). Returns
  matching actions with their input schemas, each marked **read** or **write**, and for writes the
  permission category it falls in (section 6.2). Never returns forbidden actions (section 6.7).
- **`run_crm_action@1`** — runs one **read** action. The full result is **always written to the
  agent's `reads/` folder** as a file; the model gets only a summary (file path, record count, field
  names, next-page cursor). This keeps hundreds of records out of the conversation, the browser and
  the tool span, and makes the arithmetic happen in code.

### 5.2 What is read

Follow the learning-pass findings (HubSpot Part 2–3, Salesforce Part 4):

| Read | HubSpot | Salesforce |
|---|---|---|
| Setup first | all properties incl. custom, pipelines and stages, owners, granted scopes | all fields and picklists (describe), record types, org limits |
| Closed deals in the window | search deals by close date + stage history | SOQL on Opportunity with OpportunityHistory |
| Who was on the deals | deal → contact and company associations (labels if present) | OpportunityContactRole (role, primary) |
| Companies on those deals | batch read by id (domain, industry, size, country, lifecycle) | Account fields via the same SOQL |
| Contacts on those deals | batch read (job title, buying role, source) | Contact title, department, lead source |
| Open pipeline (context) | open deals | open opportunities |

- The **window** defaults to 3 months and the agent adjusts it by industry (R-3.6).
- **Salesforce API budget:** before any large pull, read the org limits; never use more than the
  configured share of the daily allowance (default 10%, R-7.5).
- Batch calls always (R-7.4).
- **Who may read:** any workspace member's Head of ABM may use the read tools once the workspace is
  connected (consistent with any member granting writes, R-6.8).

### 5.3 The analysis

The agent computes in `run_python` (R-3.4):
- average and median deal size (mean with and without outliers), closed-won and closed-lost
  counts, value and win rate, sales cycle, stage durations and where deals stall;
- patterns in the window's wins (industry, size, region, cycle, source);
- the buying committee on won deals (titles and roles mapped to the brand context's personas);
- where demos come from;
- the sales-led pricing from real deal amounts (R-3.8).

Definitions first: "demo", "qualified demo", "won", "lost" are inferred from the customer's own stage
names, confirmed with the user, and asked up front when unsure (R-3.5). What the CRM cannot answer
(cost per lead or demo; pricing when there is no CRM) is asked of the user (R-3.8).

Sample-size wording follows the learning pass: under 5 deals "not enough to say", 5–14 "early sign",
15–29 "reasonable read", 30+ "solid" — as **skill guidance**, not code.

### 5.4 Writing the results (brand context)

- **`company/sales-motion.md`** — the sales-motion document: definitions used, window, metrics each
  with its source (CRM computation, the user, or "not available"), win patterns, committee mapping,
  sales-led pricing, gaps. Brand-level, under `company/` so the Brand Context page shows and edits it
  without frontend changes.
- **`proof/customers.md`** — companies closed-won in the window are merged in, keeping the existing
  table format; one row per website domain; website-researched rows are never removed; a CRM company
  with no usable domain is listed as "no domain given" (R-4.2 to R-4.4).
- **`write_brand_document@1`** writes both: only under `company/` and `proof/`, takes the markdown
  body or a sandbox file path, writes a new version like a person's edit, to the brand of the
  project the conversation belongs to.
- **Rows from earlier windows stay.** Re-running the analysis next quarter adds the new window's
  customers; it does not remove rows a previous window added (they are still customers, and the
  document drives discovery exclusions). Each CRM row notes its close date.
- **Several brands in one workspace.** Deals are not filtered by brand automatically; if the
  workspace has more than one brand, the agent asks the user how to tell their deals apart (a
  pipeline, a product field) before computing, and writes to the brand of the current project.
- **Onboarding refreshes keep CRM rows** (R-4.5): the onboarding customers step carries forward every
  row whose source is a CRM and merges new website findings around them by domain.
- **No CRM:** the same document is written from the user's answers.

## 6. Writing to the CRM

### 6.1 The flow

1. The agent calls **`propose_crm_changes@1`** with a batch of changes. Each change names a write
   action (from the allowlist), the target CRM record (or "new"), the arguments, and a one-line
   reason.
2. Clue **prepares** the batch:
   - **classifies** each change into a permission scope (6.2);
   - **finds before creating** (R-7.1): contacts by email, companies/accounts by domain, activities by
     their Clue reference; a "create" that finds an existing record becomes an update or a link;
   - **reads the current values** of every field it will change, for the before/after preview;
   - **marks overwrites**: a field whose current value was set by a person (per the CRM's field
     history) is flagged as overwriting a person's value (R-6.5). **When the CRM cannot tell who set
     it** (e.g. Salesforce fields without history tracking), Clue **assumes a person did**.
3. Changes **covered by a grant** (6.3) go straight to the executor.
4. Changes **not covered** go on one **permission card** (a new gate kind, `crm_write_permission`),
   and the agent ends its turn on it.
5. The **write executor** (a fleet task) records each change in the write log **before** sending
   it, sends it through Composio in batches, records the CRM's answer, and then **wakes the thread**
   (`derivation = 'crm_writes_finished'`) with the per-record results (6.5).

### 6.2 Permission scopes

Every write action in the allowlist carries a **kind**; field updates also carry **object + field**.

| Kind | Examples | "Always allow" scope (R-6.7) |
|---|---|---|
| `field_update` | set Target account, ICP tier, Buying role, a Clue field | **one field on every record** (e.g. "the Clue tier on any company") |
| `list_membership` | add accounts/contacts to a Clue list or campaign | the kind |
| `create_contact`, `create_company` | add a committee member Clue found (Salesforce: as a **Contact**, R-6.17); add a target company/account missing from the CRM (R-6.18) | the kind |
| *(parked, R-6.19/R-6.20)* `activity_note`, `activity_task`, `activity_meeting`, `activity_email_log`, `create_deal` | notes (incl. research summaries); owner tasks; logged meetings, emails, replies; deals | — not in the first release |
| `link_duplicate` | label two records as possible duplicates (R-6.13) | the kind |
| `clue_fields_setup` | create the "Clue" field group and fields (option B) | never standing; **admin only**, once (R-6.1) |

### 6.3 Grants (R-6.3, R-6.4, R-6.7, R-6.8, R-6.12)

- A grant is one of: **Always allow** a field (object + field), **Always allow** a kind, or **Fully
  automatic** (everything except `clue_fields_setup`).
- **Overwriting a value a person set always shows the card, whatever the grants say** (R-6.5 as
  amended): grants cover filling empty fields and Clue's own items. Letting grants skip that card
  becomes a setting on the future Settings → Integrations page.
- **Any workspace member** can grant and revoke (R-6.8, R-6.12).
- **Starting default** (R-6.4): at connect, the user is asked once to allow Clue's own fields and its
  own list/campaign membership; everything else starts as ask-each-time.
- **One place to list and revoke** (R-6.12): through chat (`manage_crm_grants@1`: "what can Clue do
  without asking?", "stop auto-logging notes"), and on the Integrations screen once it exists.
- Grants are per workspace and per connection; switching CRMs clears them.

### 6.4 The permission card

- Shows every change in the batch as a row: record, what changes, **before → after**, the reason,
  and a marker on rows that **overwrite a person's value** (R-6.5).
- The user can untick rows.
- Answers: **Allow once** · **Always allow** — offered per scope present in the batch, e.g.
  "Always allow: notes" and "Always allow: Clue tier on companies" as separate ticks · **Fully
  automatic** · **Don't allow**.
- Any member can answer (R-6.8). The answer arrives as an ordinary gate response; the approved rows
  go to the executor. If any record changed in the CRM between preview and execution, that row is
  not written and comes back to the agent as a conflict.

### 6.5 Results: the structured acknowledgement (R-6.2)

Every change ends with one result:

| Field | Meaning |
|---|---|
| `record` | the CRM record (and field) |
| `status` | `succeeded` · `failed` · `skipped` (deselected, or a conflict) |
| `failure_kind` | `validation_rule` · `required_field` · `duplicate_rule` · `permission` · `not_found` · `rate_limited` · `connection_expired` · `conflict` · `other` |
| `crm_message` | the CRM's own message, verbatim, and the rule or field it names |
| `retryable` | whether retrying the same request could succeed |
| `crm_id` | the record id the write created or touched |

The agent repairs `failed` rows (changes the request, or asks the user — e.g. "Salesforce requires
Industry when Type is Customer; what should I set?") and proposes again.

### 6.6 Retries and duplicates (R-7.1, R-7.2)

- Every change has an **idempotency key**; the log row is written **before** sending. A retry whose
  log row already says `succeeded` returns the stored result and sends nothing.
- **Temporary failures** (rate limit, timeout, CRM briefly down) are retried automatically with
  back-off, a few times. **Refusals** (validation, required field, duplicate rule, permission) are
  never retried as-is; they go back to the agent. **Expired connection:** writes pause and resume in
  order after reconnect.
- **Find before create** (6.1 step 2). On Salesforce, once Clue fields are on, upsert by Clue's own
  external-id field.
- Contacts Clue writes are matched by **email**. A contact without a verified email is not created
  in the CRM (section 15, call 6).

### 6.7 What Clue never writes

Enforced in code (the allowlist), not left to the prompt:
- **Merges and deletes** of any kind (R-6.13).
- **Consent fields**: email opt-out, subscription status, do-not-call, GDPR legal-basis fields
  (R-8.1).
- Composio actions that run an LLM inside Composio (`*_FROM_NL`).
- Composio's GDPR erasure actions.

**Exception — removing what Clue itself created.** Clue may remove a list or campaign member it
added, and delete (archive) a note or task it created, **only** when `crm_record_link` shows Clue
created it. This is what makes undo of membership, notes and tasks possible (R-8.5). Nothing else is
ever removed or deleted.

Clue **may** add opted-out people to lists and campaigns (R-8.6), and changes to the customer's own
fields (owner, stage, lifecycle, amount…) are allowed **only through the permission card or a grant**
(R-6.5).

### 6.8 Footprint in the CRM

**Option A — the start** (R-6.1, R-6.9):

| | HubSpot | Salesforce |
|---|---|---|
| Target accounts | HubSpot's **Target account** and **Ideal customer profile tier** company fields | — (no built-in field) |
| Committee roles | HubSpot's **Buying role** contact field | — |
| Project membership | a **Clue list** per project ("Clue: <project>") | a **Campaign** per project; target contacts and leads as members; member status carries the ABM stage (Targeted, Engaged, Meeting…) |
| Findings | — (notes and tasks parked, R-6.19) | — (notes and tasks parked) |

HubSpot's ABM fields belong to the customer, so writing them goes through the normal permission
rules (they are `field_update` changes on the customer's fields).

**Option B — Clue's own fields, opt-in** (R-6.1):
- An owner or admin turns it on (a `clue_fields_setup` change, approved once).
- HubSpot: a "Clue" property group on companies and contacts. Needs the schema-write scope on Clue's
  own HubSpot app.
- Salesforce: custom fields created through Salesforce's setup API; the connecting user needs admin
  permission in Salesforce.
- Starting field set (section 15, call 5): company — Clue tier, Clue ABM stage, Clue research link,
  Clue committee status; contact — Clue committee role, Clue contact link; plus Clue's external-id
  field on Salesforce for safe upserts.

### 6.9 Flood control (R-6.10)

Enforced by the executor; thresholds configurable by us:
- **Important events written one by one**: a reply, a meeting booked, a committee member found.
- **Everything else rolls into one daily note per account** ("Clue, 14 Oct: …"), updated in place
  — unless a person has edited that note, in which case Clue starts a new note rather than
  overwrite their edit.
- **At most 3 Clue timeline items per account per day**; the rest fold into that day's roll-up.
- **Every Clue note starts with "Clue:"**.
- **Tasks go to the account owner**, with a per-rep daily cap.

**All of 6.9 is parked with the activity writes (R-6.19):** the first release writes no notes,
tasks or other timeline items. It is kept here so the design is ready when they are built.

### 6.10 Duplicates (R-6.13, R-6.14)

- **Tagging Clue's records.** HubSpot stamps app-created records with a record source of the Clue
  integration, and Clue adds them to a "Clue: created contacts" list. Salesforce shows them as
  created by the connecting user, and they sit in the project's Clue campaign. Clue also keeps its
  own map of which CRM records it created (7.2).
- **When Clue detects a duplicate** of an existing person, it leaves both records alone and links
  them in the CRM: HubSpot "Possible duplicate" association label (Professional and above; creating
  the label definition is a schema change in their account, approved like `clue_fields_setup`);
  Salesforce a custom field under option B.
- **When that link isn't possible**, Clue writes nothing in the CRM.
- Merging stays with the customer's people.

### 6.11 Throttling and API budget (R-7.3 to R-7.6)

- **Per-workspace throttle** in front of Composio, with limits set in configuration by us.
- **Salesforce:** check remaining daily allowance before large reads and before executing large
  write batches; stop at the configured share (default 10%, admin-adjustable per connection through
  the agent).
- **Batch calls** always (HubSpot 100 per call, Salesforce 200).
- HubSpot's own limit is 110 requests per 10 seconds per account; the throttle stays under it.
- Composio's single organisation-wide limit is accepted for now (R-7.6).

### 6.12 The write log and undo (R-7.1, R-8.5)

- One log row per change: workspace, connection, proposal, turn, actor, kind, object, record, field,
  **before value**, value sent, idempotency key, the grant or gate that permitted it, status,
  `failure_kind`, CRM message, CRM id, timestamps.
- **Through chat** (`crm_write_log@1`): "what did Clue change this week?", "what failed on Acme?".
- **Undo through chat**: the agent proposes the reverse changes (before-values from the log) through
  `propose_crm_changes`, so undo goes through the same permission rules. Undo covers field changes,
  list/campaign membership, and Clue's own notes and tasks; not anything the customer's automations
  did as a result.
- A screen later, with the Integrations page (R-8.5).

## 7. Data model

Alembic conventions apply (random-hash ids, reversible, named CHECKs, one head).

### 7.1 New tables
- **`workspace_integration_connection`** — section 4.3.
- **`crm_write_proposal`** — a batch from `propose_crm_changes`: workspace, connection, turn,
  thread, status (`prepared`, `awaiting_permission`, `queued`, `executing`, `finished`), gate id.
- **`crm_write`** — the write log, one row per change (6.12).
- **`crm_write_grant`** — workspace, connection, scope (`field` + object + field | `kind` + kind |
  `fully_automatic`), granted by, granted at, revoked by, revoked at.
- **`crm_record_link`** — Clue's map between its entities and CRM records: workspace, connection,
  Clue entity id, CRM object, CRM id, `created_by_clue`, linked at; used for find-before-create,
  tagging, duplicates and undo.
- **Daily roll-up and cap counters** for flood control: per account per day (and per rep for tasks).

### 7.2 Changed
- **`crm_connect_request`** (Phase 1, R-3.10) — one row per card: workspace, project, thread, turn,
  requested by, mode (`connect` | `reconnect` | `switch`), status (`open` | `fulfilled` |
  `cancelled`), and the pending login attempt (Composio account id, provider, who clicked, when).
- `agent_gate` kinds: add `crm_write_permission` (code, DB CHECK, frontend) — Phase 2.
- `agent_turn_submission.derivation`: add `crm_connected` and `crm_writes_finished`.
- Fleet task kind: add `crm_write` (the executor).
- Onboarding's customers document writer: carry CRM rows forward (5.4).

## 8. Agent changes

### 8.1 Tools (all governed, Head of ABM only)

| Tool | Purpose |
|---|---|
| `connect_crm@1` | report the connection or open the connect card |
| `find_crm_actions@1` | search the connected CRM's allowed actions (read and write) |
| `run_crm_action@1` | run one read action; result to `reads/` |
| `write_brand_document@1` | write `company/` and `proof/` documents |
| `propose_crm_changes@1` | propose a batch of writes (6.1) |
| `crm_write_log@1` | read the write log |
| `manage_crm_grants@1` | list and revoke grants |

`write_brand_document`, the skill guidance and the manual path work even when Composio is not
configured; the CRM tools are composed only when the feature flag is on and the Composio key is set.

### 8.2 Skills (substance; wording reviewed by the founder before writing, standing rule)

- **`crm-sales-analysis`** — when to run it in the interview, connecting, reading setup first,
  definitions, the window, computing in the sandbox, sample-size wording, asking for what the CRM
  lacks, writing the two documents, the manual path.
- **`crm-writing`** — what Clue writes and why (option A, then B), proposing writes as one batch per
  decision with a reason per change, reading the permission card's answer, repairing failed rows,
  flood-control habits, never touching consent fields, undo through the log, and searching actions
  by intent rather than with customer data in the search text.
- **`stage0-interview`** — new version that calls for the CRM step at the right point and reads
  `company/sales-motion.md` when proposing the playbook.

### 8.3 Catalog bump
New Head of ABM profile version, recipe revision, manual re-mint, tool notes and chat-card labels —
the usual set.

## 9. Composio setup (R-5.2 to R-5.4)

- **Our own OAuth app per CRM** before the first real customer connects (Composio's managed apps in
  development only).
  - HubSpot: own app; scopes for reading and writing companies, contacts, deals, owners, lists,
    line items, and activities, plus schema write for option B. **New HubSpot apps are limited to 25
    installs until listed on the HubSpot Marketplace**, and a listing needs at least 3 installs:
    plan the listing before customer 25.
  - Salesforce: own connected app; scopes `api` and `refresh_token` only; My Domain subdomain at
    connect; 5 refresh tokens per user per app.
- **Zero Data Retention on** before any real customer connects; Composio's sandbox off in sessions;
  no Composio triggers for CRM data; opaque user ids; tool search allowed; 24-hour file staging
  accepted.
- **Pinned toolkit versions**, so actions don't change under the agent.
- Development and testing use developer / demo CRM accounts, not real customer data.

## 10. Configuration (env parity rule: every key in `.env.example` with its default)

- `CLUE_COMPOSIO_API_KEY` (secret).
- `CLUE_CRM_INTEGRATION_ENABLED` (default on; tools compose only with the key set).
- One Composio auth config id per CRM; a CRM with no auth config is not offered on the card.
- Throttle limits per workspace; Salesforce default API share (10%); flood-control thresholds
  (3 per account per day, per-rep task cap); retry counts and back-off; Composio toolkit versions.
- The public base URL for the OAuth callback, if not already available.

## 11. Data handling

- Raw CRM results live only in the thread's `reads/` files; our database keeps the connection, the
  two documents, the write log (before and sent values) and the record links — not raw deals.
- Composio keeps metadata, audit logs and telemetry even with ZDR; there is no log-delete API;
  erasure is a support request under its DPA. Its DPA includes the EU Standard Contractual Clauses.
- The write log holds personal values when a write touched a person (e.g. a contact's title); it is
  covered by our existing personal-data rules (R-8.3) and DSAR handling.
- Langfuse: deferred (R-5.5).

## 12. Build order (incremental, R-2.2)

The live record of what is built is [`status.md`](status.md). Order:

1. **Phase 1 — reads** (the internal "v1" checkpoint, R-2.1): connection layer and connect card,
   Composio with development apps, read tools and `reads/` files, `write_brand_document`, the
   `crm-sales-analysis` skill, the customers merge and the onboarding change.
   **Gate (R-2.3):** the founder connects a CRM and tests the reads on the local dev stack; Phase 2
   starts only after their sign-off. **Then the reads are deployed (R-2.4)** — and if real customers
   can connect there, the production-readiness items (own OAuth apps, ZDR) move ahead of that deploy
   (R-5.2).
2. **Phase 2 — the write foundation**: proposals, classification, find-before-create, before-values,
   the write log, the executor with results and wake, retries, throttling, the Salesforce budget
   check, the permission card and grants, undo through chat.
3. **Phase 3 — first writes, a few at a time**: target accounts into Clue lists (HubSpot) and
   campaigns (Salesforce); HubSpot's Target account and ICP tier fields; committee contacts (and
   missing companies/accounts); duplicate tagging and links.
4. **Phase 4 — Clue's own fields (option B)**, HubSpot then Salesforce.
5. **Production readiness**: own OAuth apps, ZDR, the HubSpot listing plan.
6. **Parked** (R-6.16, R-6.19, R-6.20): event-driven writes, all activity writes (notes incl.
   research summaries, owner tasks, logged meetings/emails/replies, visit roll-ups) with their flood
   control, deals, the Settings → Integrations page.

## 13. Verification

Business-logic scenario tests through real routes, database, tools and the executor, plus live
checks against HubSpot and Salesforce developer accounts:

1. Connect from chat; a non-admin sees the read-only card; an admin connecting elsewhere wakes every
   waiting thread.
2. Salesforce org without API access fails with a plain explanation.
3. The analysis pulls deals into `reads/`, computes in the sandbox, confirms definitions, writes
   `company/sales-motion.md`; the customers merge adds the window's customers with no duplicate
   domains; an onboarding refresh keeps them.
4. A proposed batch with no grant opens the permission card with before/after rows; Allow once
   writes and wakes with results; Always allow for a field writes the next batch's changes to that
   field without asking; Fully automatic writes everything except Clue fields setup.
5. A change overwriting a person's value is marked on the card.
6. A validation-rule failure returns `failure_kind = validation_rule` with the CRM's message; a rate
   limit retries automatically; a retried change whose first attempt succeeded is not sent again.
7. Creating a contact whose email already exists becomes an update; creating a company whose domain
   exists becomes a link.
8. Merge, delete, consent-field and `*_FROM_NL` actions are refused.
9. *(Parked with activity writes)* The fourth timeline item for an account on one day folds into
   the daily roll-up.
10. "Undo the tier changes on Acme" restores the logged before-values through a new permission card.
11. Revoking a grant through chat makes the next matching change ask again.
12. Salesforce stops a large pull at the configured share of the daily allowance.

## 14. Risks

- **Salesforce variety**: validation rules, duplicate rules, record types and required fields will
  reject writes in ways tests on a clean developer org won't show. The structured results (6.5) are
  the safety net; a design-partner walk on a real org is the test.
- **Customer automations** still fire on writes to their own fields and records (R-8.4 keeps Clue
  mostly on its own objects, but approved changes to their fields will trigger them).
- **HubSpot's 25-install cap** before a marketplace listing.
- **Composio dependency**: tokens cannot be exported; owning the OAuth apps limits the pain of a
  switch but every customer would still reconnect.
- **Personal data in the write log** (section 11).

## 15. Calls made by Claude, not the founder (check these)

1. One active CRM connection per workspace; switching clears grants.
2. Only owners and admins can **connect** a CRM (any member can grant write permissions, R-6.8).
3. The connection table is provider-generic (`workspace_integration_connection`) so Slack and email
   can share it later.
4. Writes run in a background executor that wakes the thread with results, rather than inside the
   agent's turn.
5. The starting set of Clue fields under option B (6.8).
6. A contact without a verified email is not created in the CRM (matching is by email, R-7.1).
7. "Fully automatic" covers every write kind except setting up Clue's own fields, which always needs
   an owner or admin once.
8. Grants are per connection and cleared when the CRM is switched.
9. Undo is a new proposal of reverse changes, so it goes through the same permission rules.
10. The read tools stay generic (search + run any allowed read action) rather than a fixed tool per
    report.
11. When the CRM cannot tell who set a value, Clue assumes a person did (so the overwrite marker
    shows).
12. Clue may remove or archive only list/campaign memberships, notes and tasks that it created
    itself (per `crm_record_link`); nothing else is ever removed. A daily roll-up note a person has
    edited is not overwritten; Clue starts a new one.
13. CRM customer rows from earlier analysis windows stay in `proof/customers.md`.
14. In multi-brand workspaces the agent asks how to separate the brands' deals and writes to the
    current project's brand.
15. Any workspace member's agent may read the CRM once it is connected.
16. *(approved by the founder 2026-10-20, R-3.10 / R-3.11)* The connect card is a tool-result card
    with a `crm_connect_request` table, not a gate; Composio is called over REST with `httpx`.
