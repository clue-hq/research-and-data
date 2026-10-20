# CRM integration — build status

What is built and what isn't. Short on purpose: one line per feature. Update it whenever a feature
changes state. Design: [`2026-10-20-crm-integration-first-release-design.md`](2026-10-20-crm-integration-first-release-design.md).
Decisions: [`rulings.md`](rulings.md).

Legend: ✅ built · 🔨 in progress · ⬜ not started · ⏸ parked (waiting on a Clue feature or a founder call)

_Last updated: 2026-10-20 — Task 0 (Composio spike) done; both test CRMs connected but empty (seeding pending founder OK)._

## Phase 1 — reads (the internal "v1" checkpoint)
- ✅ Task 0: Composio REST spike — findings in `composio-api-notes.md`
- ⬜ Connection table (provider-generic) and Composio setup with development apps
- ⬜ Connect card in chat, connect-link and callback routes, `crm_connected` wake
- ⬜ `find_crm_actions` / `run_crm_action` (reads; results to `reads/` files)
- ⬜ Salesforce API-budget check before large pulls (10% default share)
- ⬜ `write_brand_document` (`company/`, `proof/` only)
- ⬜ `crm-sales-analysis` skill (substance reviewed by founder first) and interview step
- ⬜ `company/sales-motion.md`
- ⬜ CRM customers merged into `proof/customers.md`; onboarding refresh keeps CRM rows
- ⬜ Manual path (no CRM): same document from the user's answers

- 🔨 Test CRMs ready (both created and connected; seeding pending): HubSpot developer test account + Salesforce Developer Edition org, seeded with sample deals, companies and contacts
- ⬜ **Gate: founder tests the reads on the local dev stack and signs off** (R-2.3) — Phase 2 waits for this

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
