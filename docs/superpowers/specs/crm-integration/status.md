# CRM integration — build status

What is built and what isn't. Short on purpose: one line per feature. Update it whenever a feature
changes state. Design: [`2026-10-20-crm-integration-first-release-design.md`](2026-10-20-crm-integration-first-release-design.md).
Decisions: [`rulings.md`](rulings.md).

Legend: ✅ built · 🔨 in progress · ⬜ not started · ⏸ parked (waiting on a Clue feature or a founder call)

_Last updated: 2026-10-21 — Trial 1 run on the local stack: connect, reads and analysis work; publishing blocked (F4); findings in [`2026-10-21-trial-1-findings.md`](2026-10-21-trial-1-findings.md), to be discussed before fixing._

## Phase 1 — reads (the internal "v1" checkpoint)
- ✅ Task 0: Composio REST spike — findings in `composio-api-notes.md`
- ✅ Configuration (Task 1, `be7883485`): Composio key, flag, auth config ids, pinned toolkit versions, Salesforce share
- ✅ Migration (Task 2): `workspace_integration_connection`, `crm_connect_request`, `crm_connected` derivation (revision `3b800d603402`; db-smoke green)
- ✅ Composio setup with development apps (dev project, managed auth configs for HubSpot and Salesforce)
- ✅ Composio REST gateway (Task 3)
- ✅ Connection store (Task 4)
- ✅ Connect-link, callback-completion and status routes; `crm_connected` wake of every waiting chat (Task 5)
- ✅ Connect card in chat and callback page (Task 6, frontend) — preview screenshot owed once `connect_crm` exists (Task 7); visuals to be polished later (R-3.9)
- ✅ `connect_crm` tool (Task 7; registered, granted in Task 11)
- ✅ `find_crm_actions` / `run_crm_action` (Task 8; reads only, every result to a `reads/` file, the model gets a summary; registered, granted in Task 11; checked live on both test CRMs)
- ✅ Salesforce API-budget check before every read (Task 8; 10% default share of the org's daily calls, stop when the org has under 10% left)
- ✅ `write_brand_document` (Task 9; new version each write, older superseded, identical bytes publish nothing; body inline or from a sandbox `outputs/` file) — 🔨 widened by R-3.15 (uncommitted with Task 11): any `company/`, `product/`, `audience/`, `proof/` document except the generated catalog, only when the person asks or a skill says so, and a version check at save (`based_on_version`; `document_changed`) instead of a lock
- 🔨 `crm-sales-analysis` skill v1 and interview step (stage0-interview v49, section 2b) — approved by the founder (R-3.14), written, **uncommitted until the trial**; Head of ABM v76 grants the four tools (recipe 36, manual v22)
- 🔨 `company/sales-motion.md` — the skill writes it; first real one comes from the trial
- 🔨 CRM customers merged into `proof/customers.md` (the agent's merge comes with the Task 11 skill); ✅ onboarding refresh keeps CRM rows (Task 10: rows whose Source has `CRM:` are carried, merged by domain)
- 🔨 Manual path (no CRM): same document from the user's answers — in the skill (section 11); proven at the trial

- ✅ Test CRMs ready: HubSpot developer test account + Salesforce Developer Edition org, both connected through Composio (dev project) and seeded with the same story — 20 companies (`*.test` domains), 66 contacts, 36 deals/opportunities (14 won, 14 lost, 8 open; 2 outliers), 118 Salesforce contact roles; stage history is artificial (stamped at creation)
- 🔨 **Gate: founder tests the reads on the local dev stack and signs off** (R-2.3) — trial 1 done 2026-10-21: connect + reads + analysis worked; `write_brand_document` refused by the plan validator (F4), so nothing published; F1–F9 open — Phase 2 waits for this
- 🔨 Connect card redesigned to the founder's Figma (three states, driven by the real connection) — built and seen in the trial, uncommitted

- ⬜ **Deploy the reads** (R-2.4). Before any real customer connects on the deployed platform
  (R-5.2): our own HubSpot app and Salesforce connected app, Composio Zero Data Retention on, the
  public callback URL and Composio keys in that environment.

## Phase 2 — write foundation
- ⬜ `propose_crm_changes`: classification, find-before-create, before-values, overwrite marker
- ⬜ Write log, idempotency keys, executor (fleet task), `crm_writes_finished` wake with per-record results
- ⬜ Retry rule (automatic for temporary failures only) and per-workspace throttle
- ⬜ Permission card (Allow once / Always allow / Fully automatic); grants; `manage_crm_grants`
- ⬜ Overwrites of a person's value always ask
- ⬜ `crm_write_log` and undo through chat
- ⬜ Forbidden actions enforced (merge, delete, consent fields, `*_FROM_NL`, GDPR erasure)

## Phase 3 — first writes (a few at a time)
- ⬜ Target accounts → Clue list (HubSpot) / campaign (Salesforce)
- ⬜ HubSpot Target account + ICP tier fields
- ⬜ Buying-committee contacts (Salesforce: Contacts only); missing companies/accounts
- ⬜ Duplicate tagging and "possible duplicate" links (nothing written when a link isn't possible)

## Phase 4 — Clue's own fields (admin opt-in)
- ⬜ HubSpot "Clue" property group and fields
- ⬜ Salesforce Clue custom fields (+ external-id field for upserts)

## Production readiness
- ⬜ Own OAuth apps (HubSpot app; Salesforce connected app) — needed for the reads deploy if real customers connect
- ⬜ Composio Zero Data Retention on, sandbox off, pinned toolkit versions — same
- ⬜ HubSpot Marketplace listing (needed before the 25th install)

## Parked
- ⏸ Writes on events / standing sync (R-6.16); writes from anything other than the Head of ABM (R-6.15, "for now")
- ⏸ All activity writes: notes (incl. research summaries), owner tasks, logged meetings/emails/replies, visit roll-ups, and their flood control (R-6.19)
- ⏸ Creating deals (R-6.20)
- ⏸ Settings → Integrations page (grants, write log, the "skip overwrite card" setting)
- ⏸ Importing accounts/contacts from the CRM (R-1.9)
- ⏸ Recorded sales calls (R-1.7), Slack, email sending
- ⏸ What our Langfuse traces keep of CRM data (R-5.5)
