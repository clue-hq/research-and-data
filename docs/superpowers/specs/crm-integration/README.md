# CRM integration — document index

Every document written for the CRM integration decisions and design, newest first within each
group. Add a line here whenever a new document is written.

## Current

| Document | What it is | Status |
|---|---|---|
| [`2026-10-22-crm-write-permission-card-design.md`](2026-10-22-crm-write-permission-card-design.md) | Phase 2 permission card for Figma: states (asking, sending, done, not allowed, replaced, paused), grouping, wording, data | Current card (R-6.22) |
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
