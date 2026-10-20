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

## 9. Open — not yet decided

- **What personal data Clue may write into the customer's CRM** (which person fields; verified
  work email only; no phone; no personal research details in notes; how EU people are handled) —
  asked 2026-10-20, not yet answered.
