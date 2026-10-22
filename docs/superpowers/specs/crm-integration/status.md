# CRM integration — build status

What is built and what isn't. Short on purpose: one line per feature. Update it whenever a feature
changes state. Design: [`2026-10-20-crm-integration-first-release-design.md`](2026-10-20-crm-integration-first-release-design.md).
Decisions: [`rulings.md`](rulings.md).

Legend: ✅ built · 🔨 in progress · ⬜ not started · ⏸ parked (waiting on a Clue feature or a founder call)

_Last updated: 2026-10-22 — Phase 2 built and live-checked on both test CRMs; findings in [`2026-10-22-phase-2-live-check-findings.md`](2026-10-22-phase-2-live-check-findings.md) (three founder questions, two fixes, minors); whole-branch review next._

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
- ✅ `write_brand_document` (Task 9; new version each write, older superseded, identical bytes publish nothing; body inline or from a sandbox `outputs/` file) — ✅ widened by R-3.15 (`1e88e9242`): any `company/`, `product/`, `audience/`, `proof/` document except the generated catalog, only when the person asks or a skill says so, and a version check at save (`based_on_version`; `document_changed`) instead of a lock
- ✅ `crm-sales-analysis` skill v1 and interview step (stage0-interview v49, section 2b) — approved (R-3.14, R-10.12), committed (`a51d1022f`, `412bac3ef`); Head of ABM v76 grants the four tools (recipe 36, manual v22)
- 🔨 `company/sales-motion.md` — the skill writes it; first real one comes from the trial
- 🔨 CRM customers merged into `proof/customers.md` (the agent's merge comes with the Task 11 skill); ✅ onboarding refresh keeps CRM rows (Task 10: rows whose Source has `CRM:` are carried, merged by domain)
- 🔨 Manual path (no CRM): same document from the user's answers — in the skill (section 11); proven at the trial

- ✅ Test CRMs ready: HubSpot developer test account + Salesforce Developer Edition org, both connected through Composio (dev project) and seeded with the same story — 20 companies (`*.test` domains), 66 contacts, 36 deals/opportunities (14 won, 14 lost, 8 open; 2 outliers), 118 Salesforce contact roles; stage history is artificial (stamped at creation)
- 🔨 **Gate: founder tests the reads on the local dev stack and signs off** (R-2.3) — trial 1 done 2026-10-21: connect + reads + analysis worked; publishing was blocked by F4 (fixed `1e88e9242`; live re-check passed 2026-10-21 — sales-motion v1 and customers v3 published); F2 fixed (live thread stream, live-checked in two tabs); F3 direction decided (AW-1–AW-8, own worktree; `outputs/` stopgap in `f799a9830`); F1/F6/F7 dropped, F5 deferred; F11 fixed; F8–F10 not counted as issues (R-10.13) — remaining: the untested paths (Salesforce in chat, by-hand path, Cancel/failed sign-in, non-admin, reconnect/switch, server-started wake, onboarding refresh keeping CRM rows), then the founder's sign-off. Phase 2 waits for this
- ✅ Connect card redesigned to the founder's Figma (three states, driven by the real connection) — committed (`5d1081c7b`)

- ⬜ **Deploy the reads** (R-2.4). Before any real customer connects on the deployed platform
  (R-5.2): our own HubSpot app and Salesforce connected app, Composio Zero Data Retention on, the
  public callback URL and Composio keys in that environment.

## Phase 2 — write foundation
- ✅ Design reviewed 2026-10-22 (R-6.21–R-6.25, R-8.7); card spec current (R-6.22); plan `docs/superpowers/plans/2026-10-22-crm-integration-phase-2-write-foundation.md` executed (subagent-driven, Tasks 1–11)
- ✅ Write allowlist (13 actions, `crm/write_actions.py`): kind of change, object and fields, forbidden fields; `HUBSPOT_UPDATE_CONTACT` left out (reports success on a refused write)
- ✅ Schema: `crm_write_proposal`, `crm_write` (the log), `crm_write_grant`, `crm_record_link`, the `crm_write_permission` gate, `crm_write` fleet kind, `crm_writes_finished` wake (`ebf28e41a6a4`, `a3b587b8fdfd`, `0e92986934d3`)
- ✅ `propose_crm_changes`: find-before-create, before-values from a read, picklist values checked, overwrite marker (R-6.5), grouping for the card, one live card per chat (a new proposal replaces an unanswered one)
- ✅ Executor on the fleet: batch calls, read-back after every write (`not_applied`), retries for temporary failures, auth errors pause, never resumes across connections, re-offers itself; `crm_writes_finished` / paused wake turns name who allowed what
- ✅ Permission card in chat (six states; any member answers; answering starts no agent turn and adds no bubble — R-11.3/R-11.4/R-11.6); progress route `GET /crm/proposals/{id}`
- ✅ Standing permissions ("Always allow" per kind of change on the card); `manage_crm_grants` (list, revoke; idempotent revoke); a new connection starts with none
- ✅ `crm_write_log` (filters, before-values, action slug for undo) and undo through chat (`reverses_write_id`; removals only of members Clue added)
- ✅ `crm-writing` skill v1 (founder-approved wording), Head of ABM v77 (recipe 37, manual v23), crm-sales-analysis v2 points to it
- ✅ Live check on both test CRMs 2026-10-22 — [`2026-10-22-phase-2-live-check-findings.md`](2026-10-22-phase-2-live-check-findings.md): propose/allow/log/undo/revoke/create/refusals/overwrite all pass; decided the same day: L6 per-change not-found (R-11.7, fixed), L8 CRM message text and L9 create id in the log (fixed), L5 lists wait for Phase 3 (R-11.8), L10 Salesforce field coverage stays (R-11.9, design A noted)
- ✅ Final review (0 Critical, 5 Important, 12 Minor) fixed and re-run live 2026-10-23 on the restarted stack (decline, replace, paused batch, real reconnect, CRM message text, per-change not-found, Cancel); L13 fixed. Deferred by the founder: Phase 1 by-hand path, live onboarding refresh, non-admin member
- ⬜ **Open frontend bugs (noted, fixing set aside):** L12 — a card in a chat started from the project page can show "belongs to a different conversation" until a reload (every card kind); L14 — a card linked by two turns renders twice. Details: [`2026-10-22-phase-2-live-check-findings.md`](2026-10-22-phase-2-live-check-findings.md) "Open frontend bugs"
- ⬜ Per-workspace throttle (R-7.3) — not built in Phase 2
- ⏸ "Fully automatic" and the "skip overwrite card" setting — Settings → Integrations page

## Phase 3 — first writes (a few at a time)
- 🔨 Plan `docs/superpowers/plans/2026-10-23-crm-integration-phase-3-first-writes.md` (branch `feat/crm-integration-phase-3`) approved 2026-10-23 with D-1–D-6 as recommended (R-12.1–R-12.6); executing subagent-driven
- ⬜ Target accounts → Clue list (HubSpot) / campaign (Salesforce) — design R-11.11: Clue creates its own list or finds the person's by name, stores the id (one list, many projects), recovers by name; allowlist list lookup + create-list / create-campaign after a live check
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
