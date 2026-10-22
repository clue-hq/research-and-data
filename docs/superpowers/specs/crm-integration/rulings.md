# CRM integration — founder rulings

The running record of every decision Aryan (founder/CTO) has made about the CRM integration.
Newest rulings are added at the bottom of each section with their date. When a ruling replaces an
earlier one, the earlier one is struck through and points to its replacement — nothing is deleted.

Related documents:
- `docs/superpowers/specs/2026-10-18-crm-integration-v1-design.md` — the first design draft
  (read-only dev checkpoint; must be revisited for writes, see R-3.2).
- Shashank's draft `SPEC-integrations-crm-slack-email.md` (2026-10-19, shared outside the repo) —
  requirements input only, see R-1.5.

---

## 1. Scope and approach

- **R-1.1 (2026-10-17)** Integrations go through **Composio**.
- **R-1.2 (2026-10-17)** The first reason to read the CRM is the **Head of ABM's sales analysis**
  during the interview, feeding the project playbook (founder whiteboard flow: onboarding → brand
  context → interview → CRM deals → missing facts → project plan → playbook).
- **R-1.3 (2026-10-17, narrowed 2026-10-20)** CRMs: **HubSpot and Salesforce**. ~~Then Attio and
  Zoho.~~ Attio and Zoho are not of interest right now (2026-10-20).
- ~~**R-1.4 (2026-10-18)** Importing **target accounts and contacts** into projects is **not in the
  first slice**; it comes in the second wave of the integration.~~ → replaced by R-1.9.
- **R-1.9 (2026-10-20)** Importing accounts and contacts **from** the CRM is **dropped** until the
  founder brings it up again.
- **R-1.5 (2026-10-20)** Shashank's integrations draft is requirements input; it is discussed, not
  followed blindly.
- **R-1.6 (2026-10-20)** Before locking any design, the founder does a **learning pass** on CRMs:
  what they contain, and what tools they expose (CRM APIs, Composio toolkits, the CRMs' own MCP
  servers).
- **R-1.7 (2026-10-18)** Recorded sales calls ("call book") are a **separate integration** (e.g.
  Gong), not part of the CRM integration.
- **R-1.8 (2026-10-20)** **Composio only** for these integrations. HubSpot's and Salesforce's own
  MCP servers are **not** used ("no extra headache").

## 2. Release scope

- **R-2.1 (2026-10-20)** "v1" is only an **internal development checkpoint**. The **first product
  release includes CRM write actions**. Tools and actions are designed for **both read and write**
  from the start.
  - Replaces: ~~R-3.2's original form, "read-only, no write-back" (2026-10-17)~~ for the release;
    read-only still describes the dev checkpoint.

- **R-2.2 (2026-10-20)** **Incremental, spec-driven development.** Clue is young, so the
  integration is built a little at a time: **all the reads first, then writes slowly, a few at a
  time**. Features Clue itself doesn't support yet (e.g. email) are not built now but will be added
  eventually. A short **build-status log** ([`status.md`](status.md)) records what is built and what
  isn't; every major development is tracked in this docs folder.

- **R-2.3 (2026-10-20)** **Phase 1 ends with the founder's own test.** After the read features
  are built, the founder connects a CRM and tests them on the Clue platform; **write development
  (Phase 2) starts only after the founder is satisfied the reads work well.** The test runs on the
  **local dev stack** against **free developer/test CRM accounts** (a HubSpot developer test account
  and a Salesforce Developer Edition org with sample deals), so Composio's managed apps are fine for
  it.

- **R-2.4 (2026-10-20)** **The read features are deployed** once developed (after the founder's
  local test, R-2.3), before write development.

## 3. Reading the CRM and the sales analysis

- **R-3.1 (2026-10-17)** The connection is **owned by the workspace**, not by one member.
- **R-3.2 (2026-10-17)** ~~The integration is read-only; no write-back.~~ → see R-2.1.
- **R-3.3 (2026-10-18)** The analysis results are saved as a **detailed brand-context document**,
  reused by every project. Keep the derived summary, not raw deals.
- **R-3.4 (2026-10-18)** The agent does the math itself, in its **Python sandbox** (`run_python`).
- **R-3.5 (2026-10-18)** "Demo" / "qualified demo": the agent **infers** them from the customer's
  own stage names, **confirms** with the user, and **asks up front** when unsure.
- **R-3.6 (2026-10-18)** The analysis window **defaults to 3 months** and adjusts by industry.
- **R-3.7 (2026-10-18)** The CRM is connected **from the chat** for now (a connect card).
- **R-3.8 (2026-10-20)** **Sales-led pricing:** the brand context knows only the seller's public
  self-serve pricing, so the Head of ABM gets the **sales-led / enterprise pricing** one of two ways:
  **(1) from the connected CRM** (real deal amounts), or **(2) by asking the user** for the details.
  (This is the "two options" on the founder's whiteboard.)

- **R-3.9 (2026-10-20)** The connect card is **shown to the founder as a preview** when built; this
  is **not a blocker**, and the card's visuals will be improved later.

- **R-3.10 (2026-10-20)** The **connect card is drawn from the `connect_crm` tool's result**, not an
  agent gate; a `crm_connect_request` table records which chats are waiting and each login attempt.
  Database for Phase 1 is therefore **two tables** (`workspace_integration_connection`,
  `crm_connect_request`) **and one constraint change** (`crm_connected` turn type); no gate change.
- **R-3.11 (2026-10-20)** Composio is called over its **REST API with plain HTTP**, not its Python SDK.

- **R-3.12 (2026-10-20)** **The agent shows its work:** it saves its final analysis script and the
  computed tables in `outputs/`, and `company/sales-motion.md` notes what each number was computed
  from, so the numbers are auditable and easy to re-run.
- **R-3.13 (2026-10-20)** The sandbox's **Python runs per turn are raised to 75 in local
  development** (`CLUE_SANDBOX_MAX_RUNS_PER_TURN=75` in the dev `.env`); the code default and
  production stay at 10 for now.
- **R-3.14 (2026-10-20)** The `crm-sales-analysis` skill (v1) and the `stage0-interview` change
  (v49) are **approved as drafted for now**, to be revised after trials if needed. With them, four
  points proposed by Claude and accepted:
  - `company/sales-motion.md` holds **no person's name or email**, only titles and roles, and no
    list of individual deals.
  - The analysis window **widens when the 3-month window holds fewer than about 15 closed deals**
    (offered to the person), and runs **6–12 months for long-cycle industries**.
  - The CRM step sits at **question 2 of the interview** (the last closed-won deals), **offered,
    not forced**; a recent `company/sales-motion.md` is used instead of re-running it.
  - A CRM customer row in `proof/customers.md` reads: How they buy `direct`, Evidence
    `closed-won deal`, Domain check and Quote empty, Source `CRM: <HubSpot|Salesforce>
    (closed-won <date>)` (see R-4.6).
- **R-3.15 (2026-10-20)** The Head of ABM **may edit any Brand-context document**, not only
  `company/` and `proof/`: everything under `company/`, `product/`, `audience/` and `proof/`
  (including ICP documents — a project keeps the exact ICP version it confirmed) **except the
  generated `product/catalog.md`**, which only `manage_products` changes. It does so **only when the
  person asks or a skill says to, never on its own initiative**, and only through
  `write_brand_document` (its file tools still cannot write `brand/`). Concurrent edits are guarded
  by a **version check at save, not a lock**: the agent names the version it read, and a document
  someone saved since is refused `document_changed` — the same rule a person's save follows.
  Replaces the "company/ and proof/ only" scope of Task 9.
- **R-3.16 (2026-10-20)** The **disclosed-skills budget stays at 5,120 bytes**; it is not raised
  for the CRM skill. Room is made by shortening the Stage-0 skill's summary in its new version
  (v49). (Claude had raised it to 5,632 without asking; reverted.)

## 4. Customers

- **R-4.1 (2026-10-18)** The customer list **is in the first slice**: built from closed-won deals
  alongside the analysis.
- **R-4.2 (2026-10-18)** CRM customers are **merged** into the website-researched
  `proof/customers.md`; duplicates are resolved **by website domain**.
- **R-4.3 (2026-10-18)** Churn is not checked; a closed-won customer is recorded as **closed-won**.
- **R-4.4 (2026-10-18)** For now, only companies closed-won **within the analysis window** go in,
  not every closed-won company ever.
- **R-4.5 (2026-10-18)** When onboarding refreshes `proof/customers.md`, it **keeps the CRM rows**
  and merges new website findings around them by domain.
- **R-4.6 (2026-10-20)** A **CRM row is recognised by `CRM:` in its Source cell**; when a website
  row and a CRM customer share a domain, the website row is kept and ` · CRM: …` is added to its
  Source (approved with R-3.14).

## 5. Data handling (Composio)

- **R-5.1 (2026-10-18)** ~~Accept Composio's default log retention for now.~~ → replaced the same
  day by R-5.2.
- **R-5.2 (2026-10-18)** Use **Composio Zero Data Retention**, with:
  - **our own OAuth app per CRM** (Composio's shared apps only during development; switch before
    the first real customer connects, because switching later forces reconnects);
  - ZDR on **before** any real customer connects;
  - Composio's own sandbox **off** in our sessions;
  - **no Composio triggers** for CRM data;
  - **opaque user ids** (the workspace id).
- **R-5.3 (2026-10-18)** Composio **tool search stays allowed** (accepting that Composio may cache
  search queries).
- **R-5.4 (2026-10-18)** Composio's **24-hour file staging** (e.g. Salesforce bulk-export CSVs) is
  acceptable.
- **R-5.5 (2026-10-18)** What our **own Langfuse traces** keep of CRM data is **deferred** until we
  build it; it does not block anything now.

## 6. Writing to the CRM

- **R-6.1 (2026-10-20)** **Our footprint in HubSpot:** start with **option A** — no new fields:
  list membership per project, notes, and HubSpot's own ABM fields (Target account, Ideal customer
  profile tier, Buying role). Then offer **option B** — Clue's own fields in a "Clue" field group —
  as an **opt-in the admin approves**.
- **R-6.2 (2026-10-20)** **Write failures return a structured acknowledgement**, per record: which
  record and field, the kind of failure, the CRM's own message, and whether retrying can help — so
  the agent's next attempt can repair it.
- **R-6.3 (2026-10-20)** **Permission UX follows Claude Code / Codex.** When the agent wants to
  write, it asks in chat with three choices: **Allow once**, **Always allow** this particular write
  (this record / field / activity kind), and **fully automatic** after setup.
- **R-6.4 (2026-10-20)** **Starting defaults:** a per-batch preview for activities, record creation
  and changes to the customer's own fields; a one-time, revocable admin "yes" for writing Clue's own
  fields and list membership.
- **R-6.5 (2026-10-20, amended same day)** Clue **may overwrite a value a person set or changed**,
  but only with a **before/after preview and the user's permission**. **For now this always asks,
  whatever "Always allow" or "Fully automatic" grants exist**; letting grants skip it will be a
  setting on the future Settings → Integrations page.
- **R-6.6 (2026-10-20)** Adopted as guidance: established ABM tools (6sense, Demandbase) write
  **their own clearly labelled fields, account-level scores and stages, in scheduled batches, don't
  touch rep-owned standard fields, and create records rarely and deliberately**.
- **R-6.7 (2026-10-20)** **"Always allow" covers** either **one field on every record** (e.g.
  "always update the Clue tier on any company") or **one kind of write** (e.g. "always log notes") —
  not a single field on a single record.
- **R-6.8 (2026-10-20)** **Any workspace member** can grant "Always allow" (not only owners and
  admins).
- **R-6.9 (2026-10-20)** **Our footprint on Salesforce** (which has no built-in Target account / ICP
  tier / Buying role fields): option A is **a Campaign per Clue project** (target contacts and leads
  as campaign members, the member status carrying the ABM stage, e.g. Targeted, Engaged, Meeting)
  **plus tasks and notes**; Clue's own custom fields are the **admin opt-in**, the same as HubSpot.
- **R-6.10 (2026-10-20)** **Flood control defaults** (adjustable by us): important events (a reply,
  a meeting booked, a committee member found) are written **one by one**; low-signal activity is
  **rolled into one daily note per account**; **at most 3 Clue timeline items per account per day**,
  the rest folding into the roll-up; every Clue note **starts with "Clue:"**; tasks for reps go to the
  **account owner** with a **per-rep daily cap**.
- **R-6.11 (2026-10-20)** **Salesforce connecting user:** a **dedicated integration user is
  recommended but not required**; a personal login is allowed, with a clear note that Clue's changes
  will show that person's name. (HubSpot labels changes as coming from the Clue integration.)
- **R-6.12 (2026-10-20)** **Any workspace member** can turn on **"fully automatic"**, and change
  grants. **All grants** ("Always allow" and "fully automatic") are **listed and revocable from one
  place**.
- **R-6.13 (2026-10-20)** **Clue never merges CRM records.** Contacts Clue creates in the CRM are
  **tagged as Clue's** (HubSpot: record source = the Clue integration, plus a Clue list; Salesforce:
  created by the connecting/integration user, plus the project's Clue campaign). When Clue detects a
  duplicate of an existing person, it **leaves both records alone and links them in the CRM**: on
  HubSpot a "Possible duplicate" **association label** (Professional and higher; creating the label is
  a schema change in their account), on Salesforce a **custom field** (part of the Clue-fields admin
  opt-in). **Merging stays with the customer's people, in their CRM.** Founder's reasoning: Clue does
  not import accounts or contacts from the CRM, so duplicates are primarily the CRM side's to handle.
- **R-6.14 (2026-10-20)** When that CRM link **isn't possible** (HubSpot below Professional, or a
  Salesforce org without the Clue-fields opt-in), Clue **writes nothing in the CRM** about the
  duplicate.

- **R-6.15 (2026-10-20)** **For now**, writes are proposed **only by the Head of ABM** (including in
  turns the system wakes it for).
- **R-6.16 (2026-10-20)** Clue writing on its own when events happen (a research job finishes,
  discovery adds accounts — a standing sync) is **parked**.
- **R-6.17 (2026-10-20)** On Salesforce, people Clue writes are created as **Contacts only**, never
  Leads.
- **R-6.18 (2026-10-20)** Clue **may create** a HubSpot company or Salesforce account that is missing
  from the CRM (with permission, like any other write).
- **R-6.19 (2026-10-20, corrected same day)** **First-release writes** are: target accounts added to
  Clue **lists** (HubSpot) or **campaigns** (Salesforce); HubSpot's **Target account** and **ICP
  tier** fields; **contacts** for the buying-committee members Clue found (and missing
  companies/accounts, R-6.18). **All activity writes are parked for now** — ~~notes summarising
  Clue's research~~ (founder correction: "keep them all at bay"), logged emails, meetings and meeting
  notes, replies, visit roll-ups, owner tasks.
- **R-6.20 (2026-10-20)** **Creating deals** is not in the first release.

- **R-6.21 (2026-10-22)** **The permission card groups changes, it does not list every change.**
  One line per group (the same action on the same field) with a count, a summary of the values and
  the agent's reason; opening a group lists its records, which can be unticked one by one. Changes
  that **overwrite a value a person set are never grouped** — each is listed on its own, unticked by
  default. Card spec: `2026-10-22-crm-write-permission-card-design.md`.

- **R-6.22 (2026-10-22)** **The card spec is the current card**; planning and building do not
  wait for a Figma design. "Fully automatic" lives on the settings page, not on the card; only one
  live write card per chat (a new proposal replaces an unanswered one); the asking card shows the
  CRM's logo.

- **R-6.23 (2026-10-22)** **Write actions are found the same way as reads.** The agent searches
  Composio (`find_crm_actions`) and picks the write action itself, guided by the `crm-writing`
  skill; proposing writes by a fixed list of "kinds" was considered and rejected (one generic
  mechanism, judgement in the prompt). Safety stays in code: only allowlisted write actions can run,
  and each carries data we maintain (kind of change, object and fields, plain-words label) that
  drives the permission scope, the card's groups, the before-values and the write log. In trial 1
  the search missed one named read action (F5) but the agent still finished correctly; on Salesforce
  it found everything first time.

- **R-6.24 (2026-10-22, replaces the starting default in R-6.4)** **No permission question at
  connect.** The first permission card asks instead: it already offers "Always allow" for the kinds
  of change on it (e.g. adding contacts to Clue lists), so the person decides when a real write is
  in front of them. The connect card stays as built.

- **R-6.25 (2026-10-22)** **Confirmed design calls** (design §15): writes run in a background
  executor that wakes the chat with the results (call 4); undo is a new proposal of the reverse
  changes through the same permissions (call 9); when the CRM cannot tell who set a value, Clue
  assumes a person did (call 11); Clue removes only memberships, notes and tasks it created itself,
  per its own record (call 12); standing permissions belong to the current connection and changing
  CRMs clears them (calls 1, 8); setting up Clue's own fields always needs an owner or admin, once,
  and is never covered by "Fully automatic" (call 7).

## 7. Correctness and API budget

- **R-7.1 (2026-10-20)** **No duplicates:** every create is **find, then create** (contacts matched
  by email, companies/accounts by domain, activities by a Clue reference), and **every write is
  recorded in our own write log before it is sent**, so a retry returns the stored result instead of
  writing twice.
- **R-7.2 (2026-10-20)** **Retry rule:** temporary failures (rate limit, timeout, CRM briefly
  unavailable) are **retried automatically** with back-off; real refusals (validation, required
  field, duplicate rule, permission) **go back to the agent** to repair or ask the user; an expired
  connection pauses writes until reconnect, then they resume in order.
- **R-7.3 (2026-10-20)** **Throttle per workspace**, with the thresholds and limits **set by us**
  (configurable, not hard-coded).
- **R-7.4 (2026-10-20)** **Always use batch calls** (100 records per call on HubSpot, 200 on
  Salesforce) rather than one record at a time.
- **R-7.5 (2026-10-20)** **Salesforce gets special care with API budget:** check the org's remaining
  daily allowance before large pulls, and **cap Clue's share at 10% of the daily allowance by
  default**, adjustable by the customer's admin.
- **R-7.6 (2026-10-20)** Composio's single per-organisation rate limit (shared across all our
  customers) is **acceptable for now**, given today's customer count.

## 8. People, consent and the customer's automations

- **R-8.1 (2026-10-20)** Clue **never changes consent fields** (email opt-out, subscription status,
  do-not-call) in the customer's CRM.
- **R-8.2 (2026-10-20)** Marking opted-out / do-not-call people as suppressed inside Clue is **left
  out for now**.
- **R-8.3 (2026-10-20)** Our existing **personal-data / compliance rules apply on top** when Clue
  writes a person into the CRM.
- **R-8.4 (2026-10-20)** **Keep Clue out of the customer's automations:** Clue writes mainly to what
  it owns (its own lists, campaigns, fields, notes), so it doesn't set off their workflows, and we
  **advise the admin to exclude Clue's changes from their automations** (on Salesforce, typically by
  excluding the integration user). Warning in prompts and reading their automations were not chosen.
- **R-8.5 (2026-10-20)** **The write log is seen through chat first** ("what did Clue change this
  week?", "undo the tier changes on Acme", with undo going through the normal permission prompt),
  and **on a screen once the Integrations page is built**. Undo covers field changes, list/campaign
  membership, and Clue's own notes and tasks; it cannot cover merges or anything the customer's
  automations already did.
- **R-8.6 (2026-10-20, final)** Clue **may add opted-out people** to lists or campaigns, even ones
  the customer's automations might email.

- **R-8.7 (2026-10-22)** **What personal data Clue may write into the customer's CRM.** First and
  last name, job title and the company/account link: yes. Work email: **only verified** (no verified
  email, no contact created — design call 6). Buying/committee role: yes. LinkedIn profile URL: yes,
  when identity-bound. **Phone numbers: no.** **Personal research details** (interests, posts,
  resonance facts) **never go into the CRM**; they stay in Clue behind its own checks. **Sensitive
  data: never.** **EU and every other person:** the same rules, and every person written must also
  pass Clue's existing identity-binding and jurisdiction/use-class check — a field Clue may not use
  for that person in outreach is never written to the CRM. Each write records the claim it came
  from in the write log, so a privacy erasure in Clue can list what was written into the customer's
  CRM (Clue never deletes it there, R-6.13).

## 9. Open — not yet decided

- *(none — the personal-data question was answered 2026-10-22, R-8.7)*

## 10. Trial 1 findings — decisions

- **R-10.1 (2026-10-21)** **F2 (an open chat misses turns it did not start) is fixed with a live
  thread stream** (approach 4): a thread-level SSE stream of turn lifecycle events read from
  `agent_turn_event_stream` by `thread_id`, single-use `agent_thread` stream tokens, keep-alive, and
  reconnect from the cursor — multi-process safe (all state in Postgres) and multi-tab. **Option
  (a):** the stream is open only while the tab is visible. The discovery 5 s timer and the CRM card's
  re-read nudge are removed. Plan: `docs/superpowers/plans/2026-10-21-chat-thread-stream.md`.
- **R-10.2 (2026-10-21)** **Intermediate progress messages during long tasks** (like Claude Code /
  Codex) are wanted; the founder will take this up separately ("mid-tasks"), not in the CRM work.
- **R-10.3 (2026-10-21)** **F4 fix:** `write_brand_document`'s inline input is renamed `body` →
  `markdown`; a build-time guard forbids tool inputs named like raw content (`body`, `content`,
  `text`, …) for every tool, with `write_project_document@1` the single listed exception; and the
  tool is tested through the real plan builder and validator. The platform's raw-content check
  itself is left unchanged.
- **R-10.4 – R-10.8 (2026-10-21)** **Moved** to the agent workspace rulings, because they govern
  every agent, not only the CRM: R-10.4 → AW-1 (machine-independent workspace), R-10.5 → AW-2 (what
  is kept and for how long), R-10.6 → AW-3 (resumed chats use the current profile), R-10.7 → AW-4
  (staleness), R-10.8 → AW-5 (order and scope). See
  `docs/superpowers/specs/agent-workspace/rulings.md`, which also holds AW-6 (the `outputs/` stopgap),
  AW-7 (F3 in its own worktree) and AW-8 (rules for this lane until F3 lands).
- **R-10.9 (2026-10-21)** **F1 dropped — works as intended.** The CRM sign-in callback is a Clue page
  and needs a browser signed in to Clue; finishing the sign-in in another browser is not supported.
- **R-10.10 (2026-10-21)** **F6 (slow turns) and F7 (underscores rendered as italics in chat)
  dropped.**
- **R-10.11 (2026-10-21)** **F5 (narrow Composio action search) deferred** — to be taken up later.
- **R-10.12 (2026-10-21)** **F11 fix — the sales motion stands on its own.** The skill no longer
  asks the agent to save its script (the sandbox does not keep `.py`); the CSV tables are still
  saved for later turns. The published document says in words how its numbers were computed
  (window, definitions, deals counted, filters, deals set aside and why), and each number's Source
  is the CRM and the day it was computed (e.g. "CRM (HubSpot), computed 21 Oct 2026"), never a file
  in the agent's workspace. Option 1 (letting the sandbox keep `.py`) was not chosen.
- **R-10.13 (2026-10-22)** **F8 (callback page background), F9 (test CRM data limits) and F10 (an
  11-minute reasoning loop) are not counted as issues or defects for now.** Nothing is done about
  them; with F5 deferred, no trial finding blocks the Phase 1 gate.
- **R-10.14 (2026-10-22)** **Changing the CRM once one is connected belongs on a settings page, not
  in the chat.** The switch test was skipped. Found during it: a switch or reconnect card was shown
  as already connected because the tool's snapshot and the connection route format the same time
  differently (`…Z` vs `…+00:00`) — fixed in `ef4e96cbc` (compared as moments), still needed for
  reconnecting an expired connection. Whether `connect_crm` should keep offering a switch from chat
  is to be decided with the settings page.

## 11. Phase 2 live check — decisions (2026-10-22)

- **R-11.1 (2026-10-22)** **A card link always says `agent_gate`.** The agent linked the write card by
  its kind (`crm_write_permission`), so the chat showed an incomplete review request. Finalization
  now refuses a link whose id is a card under any other type (design-leg links untouched), and the
  manual's gate line spells the link out (`e672ab95c`).
- **R-11.2 (2026-10-22)** **The card names records, not ids** — the prepare read also fetches the
  record's display name (`e93ad4a27`).
- **R-11.3 (2026-10-22)** **Answering the write card starts no agent turn.** Allow records the answer
  and hands the changes to the background sender; its one wake turn reports the results. Don't allow
  records the answer only; the card shows the decline and the agent sees it the next time the person
  writes. (Live: Allow started a needless turn that ran 9½ minutes, failed on a model timeout and held
  back the results report.)
- **R-11.4 (2026-10-22)** **Answering any card adds no message bubble to the chat**, for every kind of
  agent gate: only the card's state changes. The answer stays recorded (and a turn the answer starts
  still runs, for the cards that start one).
- **R-11.5 (2026-10-22)** **The card shows option labels, not internal values** ("Tier 1", not
  "tier_1"), from the field definitions Clue already reads to check picklist values.
- **R-11.6 (2026-10-22)** **How R-11.3 is built: a submission can need no reply.** A card answer stays
  a turn submission (the answer's receipt and double-click anchor), with a new column saying whether
  the agent replies; the CRM card's answers say no. The dispatcher and busy checks skip such
  submissions; the route tells the browser "recorded, no turn". The sender's results message says
  who allowed what and which standing permission was granted; a decline reaches the agent as one
  context line on its next turn ("since your last turn, the write card from … was declined by …").
  Set aside: holding the answer turn until the writes finish (blocks the chat, worse when paused);
  recording the answer with no submission (changes the gate-answer contract every card relies on);
  faking a finished run.
- **R-11.7 (2026-10-22)** **A missing record refuses only its own change.** When the read before the
  card finds that a record does not exist (HubSpot 404), that change is refused as
  `crm_record_not_found` and the rest of the batch goes on the card; the agent tells the person
  which record was missing. (Live check L6: the whole proposal was refused.)
- ~~**R-11.8 (2026-10-22)** **List lookup and creation wait for Phase 3.** Clue can add contacts to a
  HubSpot list but cannot look lists up or create one (live check L5); the list-lookup read and the
  create-list write (and the Salesforce campaign equivalents) arrive with the target-accounts
  feature in Phase 3.~~ *(replaced by R-11.11)*
- **R-11.9 (2026-10-22)** **Salesforce field coverage stays at Composio's named arguments for now.**
  `SALESFORCE_UPDATE_ACCOUNT` / `_UPDATE_CONTACT` accept only the fields Composio names (plus
  `custom_fields`), so a standard field outside that list (live check L10: `Rating`) cannot be
  proposed, although the composite patch that actually sends every Salesforce update could set it.
  Nothing in Phases 3–4 needs such a field. **Noted for later (design A):** accept any field by its
  Salesforce API name on the existing action, checked at proposal time against the org's field
  definitions (exists, updateable, not forbidden; label and picklist labels from the same read),
  sent through the composite patch as today — about a day with its live test. Not chosen:
  allowlisting `SALESFORCE_UPDATE_RECORD` as a second action.
- **R-11.10 (2026-10-23)** **A reconnect does not resume a paused batch — and the card says so.**
  Every reconnect creates a new connection, and Clue never resumes changes across connections, so
  changes left unsent when a connection lapses are closed and proposed again. The paused card says
  that plainly instead of "sending carries on once it is reconnected" (final review I-1, option a).
  Resuming on a same-portal / same-org reconnect (stamping the org id at activation, carrying the
  queued changes and the record of members Clue added) is not chosen for now. This replaces the
  "resume in order" part of R-7.2.
- **R-11.11 (2026-10-23, replaces R-11.8)** **Clue keeps the ids of its CRM lists and campaigns
  itself (Phase 3).** A CRM assigns a list's or campaign's id when it is created; Clue cannot choose
  it, so Clue stores it. (1) **Clue's own list:** the first time a project writes, the agent proposes
  "Create the list 'Clue: <project name>'" (HubSpot: a *manual* list; Salesforce: a campaign) on the
  normal card; the returned id is stored as a CRM record of Clue's, marked created by Clue. (2) **A
  list the person already has:** the person names it; the agent finds it by exact name and Clue
  stores its id, marked not created by Clue (Clue never removes members it did not add; a
  rule-based HubSpot list cannot take members and is refused). (3) **A list belongs to many
  projects:** the stored list is one row, and a separate link records every project that uses it.
  (4) **Recovery:** if the stored id stops working (HubSpot "List does not exist with ID …"), Clue
  looks the list up by its exact name, and proposes creating it again only if it is truly gone.
  Needs Clue's allowlists widened — reads `HUBSPOT_GET_CRM_LIST_BY_NAME`, `HUBSPOT_SEARCH_CRM_LISTS`;
  writes `HUBSPOT_CREATE_LIST`, `SALESFORCE_CREATE_CAMPAIGN` — each verified live on both test CRMs
  first. (Live check L5: the agent could not find a list because these actions were never on Clue's
  allowlist; the HubSpot grant itself already allows lists.)
