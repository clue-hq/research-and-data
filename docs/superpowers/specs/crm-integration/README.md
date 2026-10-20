# CRM integration — document index

Every document written for the CRM integration decisions and design, newest first within each
group. Add a line here whenever a new document is written.

## Current

| Document | What it is | Status |
|---|---|---|
| [`status.md`](status.md) | Build status: what is built, in progress, not started, or parked — one line per feature | Live — updated whenever a feature changes state |
| [`rulings.md`](rulings.md) | Every founder decision, numbered (R-x.y) and dated; superseded rulings struck through | Live — updated after every decision |
| [`2026-10-20-crm-integration-first-release-design.md`](2026-10-20-crm-integration-first-release-design.md) | The first-release design: HubSpot and Salesforce, read and write, through Composio | Draft for founder review |

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
