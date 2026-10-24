# CRM integration — document index

Every document written for the CRM integration decisions and design, newest first within each
group. Add a line here whenever a new document is written.

## Current

| Document | What it is | Status |
|---|---|---|
| [`2026-10-25-phase-4-live-check-findings.md`](2026-10-25-phase-4-live-check-findings.md) | Phase 4 live check on both test CRMs: setup, Clue field writes, a deleted field set up again, a possible-duplicate link; findings L4-1–L4-7 | Record — L4-1–L4-6 fixed and re-checked live |
| [`../../plans/2026-10-24-crm-integration-phase-4-clue-fields.md`](../../plans/2026-10-24-crm-integration-phase-4-clue-fields.md) | Phase 4 (Clue's own fields) plan: registry, owner/admin setup card, setup run (HubSpot group/properties/label; Salesforce fields, permission set R-13.1, external id), writing Clue fields, duplicate links, skill v5, live check; decisions D-1–D-6 (ruled R-13.2–R-13.7) | Approved 2026-10-24; built and live-checked 2026-10-25 |
| [`2026-10-23-phase-3-live-check-findings.md`](2026-10-23-phase-3-live-check-findings.md) | Phase 3 live check on both test CRMs: what passed (lists, targets, tiers, committee, missing accounts, campaign, removal), findings L-1–L-11 and what was decided on them (R-12.11–R-12.14) | Record — step 4 and the Tasks 10–11 re-run still to add |
| [`2026-10-22-crm-write-permission-card-design.md`](2026-10-22-crm-write-permission-card-design.md) | Phase 2 permission card for Figma: states (asking, sending, done, not allowed, replaced, paused), grouping, wording, data | Current card (R-6.22) |
| [`../../plans/2026-10-23-crm-integration-phase-3-first-writes.md`](../../plans/2026-10-23-crm-integration-phase-3-first-writes.md) | Phase 3 (first writes) implementation plan: 9 tasks — verify list/campaign shapes, list registry (R-11.11), create-list / company lists, `read_crm_targets` (R-8.7 reduced view), R-8.7 checked in prepare, record links, find/link a list, skill v2 + v78, live check; decisions D-1–D-6 for the founder | Approved 2026-10-23 (R-12.1–R-12.6); executing |
| [`2026-10-22-phase-2-live-check-findings.md`](2026-10-22-phase-2-live-check-findings.md) | Phase 2 live check on both test CRMs: what passed, what was fixed mid-run (R-11.1–R-11.6), open founder questions L5/L6/L10, fixes L8/L9, minors, what was not exercised | Record — questions and fixes feed the whole-branch review |
| [`status.md`](status.md) | Build status: what is built, in progress, not started, or parked — one line per feature | Live — updated whenever a feature changes state |
| [`composio-api-notes.md`](composio-api-notes.md) | Verified Composio REST v3.1 shapes, errors and versions from the Task 0 spike | Live — amend when Composio behaviour changes |
| [`2026-10-21-trial-1-findings.md`](2026-10-21-trial-1-findings.md) | First end-to-end trial of the reads on the local stack: what happened, findings F1–F11, what was not exercised | Record — F2 and F4 fixed; F3 moved to agent-workspace |
| [`../agent-workspace/README.md`](../agent-workspace/README.md) | F3 moved to its own folder: workspace footprint findings and rulings AW-1… (was R-10.4–R-10.8) | Live |
| [`../../plans/2026-10-22-crm-integration-phase-2-write-foundation.md`](../../plans/2026-10-22-crm-integration-phase-2-write-foundation.md) | Phase 2 (write foundation) implementation plan: 11 tasks, ending with a live check on both test CRMs | Draft for founder review |
| [`../../plans/2026-10-21-chat-thread-stream.md`](../../plans/2026-10-21-chat-thread-stream.md) | Plan for F2: the live thread stream (R-10.1) | Done 2026-10-21 (F2 fixed) |
| [`rulings.md`](rulings.md) | Every founder decision, numbered (R-x.y) and dated; superseded rulings struck through | Live — updated after every decision |
| [`2026-10-20-crm-integration-first-release-design.md`](2026-10-20-crm-integration-first-release-design.md) | The first-release design: HubSpot and Salesforce, read and write, through Composio | Reviewed for Phase 2 (2026-10-22) |
| [`../../plans/2026-10-20-crm-integration-phase-1-reads.md`](../../plans/2026-10-20-crm-integration-phase-1-reads.md) | Phase 1 (reads) implementation plan: 13 tasks, ending with the founder's local test | Draft for founder review |

## Superseded

| Document | What it was | Replaced by |
|---|---|---|
| [`../2026-10-18-crm-integration-v1-design.md`](../2026-10-18-crm-integration-v1-design.md) | Read-only first draft (sales analysis, customers merge) | The first-release design (2026-10-20) |

## Inputs (not written here)

| Document | Where | Note |
|---|---|---|
| Shashank's integrations draft, `SPEC-integrations-crm-slack-email.md` (2026-10-19) | Shared by the founder outside the repo (`~/Downloads`) | Requirements input only (R-1.5) |
| Founder's whiteboard of the onboarding → interview → CRM → playbook flow (2026-10-17) | Image shared in conversation | Source of R-1.2 and R-3.8 |

## Research done in conversation (no separate file)

The learning pass of 2026-10-17 to 2026-10-20 was delivered in chat, not as files: Composio's
model, auth, retention and pricing; the common CRM data model; HubSpot's objects, fields and quirks;
HubSpot's API and Composio toolkit; Salesforce's objects, SOQL, toolkit and quirks; the write side of
both CRMs and how 6sense and Demandbase write back. Its conclusions that matter are captured in
`rulings.md` and the first-release design.

## Outside the repo

| Document | Where |
|---|---|
| Claude's memory summary of these decisions | `~/.claude/projects/-Users-aryankeshri-conductor-repos-research-and-data/memory/crm-integration-composio-v1-scope.md` (points back to `rulings.md`, which is authoritative) |
