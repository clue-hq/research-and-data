# Direct Mail Campaign Context Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Continue inline under the founder's existing build-and-iterate authorization; no repeated execution-method questionnaire.

**Goal:** Extend the current customer UI with campaign context, reusable notes, explicit gift budgets, linked assets and chronological tracking.

**Architecture:** Extend validated local state additively so existing drafts survive. Controllers expose repository operations; components remain transport-free. Pilot examples enter through a preview-only source, never the production repository.

**Tech Stack:** Existing Next.js, React, TypeScript, Zod, IndexedDB and Clue tokens.

**Spec:** `apps/frontend/docs/architecture/direct-mail.md`, Revision 2.

## Global constraints
- Frontend only, localhost:5000, no production mutations or remote pushes.
- Existing user drafts and immutable approvals survive schema extension.
- Search budget never reserves credits or approves a send.
- Exactly three proposals, individual review before bulk approval.
- Reuse existing research; email is a link only.
- Private pilot records are not committed.

## Review focus
- Existing IndexedDB records receive defaults without losing edits (Task 1).
- Approval retries cannot double-debit; insufficient credits refuse (Task 1).
- Locked budgets require deliberate editing; changes invalidate affected draft reviews (Task 1).
- Templates never overwrite approved notes; missing channel associations are not fabricated (Tasks 1–2).
- Tracking cannot present future outbound events as complete (Tasks 1–2).

### Task 1: Additive domain and repository
**Files:** `model/direct-mail-context.ts`, `model/direct-mail.ts`, `data/direct-mail.repository.ts`, tests beside those files.
**Interfaces:** `GiftBudgetSchema`, `NoteTemplateSchema`, `CampaignAssetSchema`, `trackingMilestones(mailer)`; repository `saveBudget`, `saveTemplate`, `topUp`; existing approval transition owns an idempotent mock ledger debit.
- [x] Write and run failing tests for legacy parse, budget/approval separation, credit idempotency, template rendering and tracking order.
- [x] Add optional/defaulted schemas, pure helpers and transactional operations; no network in presentation.
- [x] Run focused tests; include in the coherent revision commit below.

### Task 2: Customer surfaces
**Files:** Direct Mail review, tracking, library, project link, screen and CSS; new context controller/components.
**Interfaces:** Existing `DirectMailController` supplies all data and operations. Project view links canonical records; context settings expose budgets and mock credits.
- [x] Add badges, source/merchant links, feedback, templates, linked microsite/QR context and a recipient campaign table.
- [x] Add budget controls and mock credit review; change tracking to ordered milestones with preparation details and dated photos.
- [x] Exercise via browser, including persistence and missing-data states; include in the revision commit.

### Task 3: Pilot preview, handoff and verification
**Files:** preview-only pilot endpoint/loader, ignored local sample, API contract and session memory.
**Interfaces:** Validated pilot data source is isolated from synthetic defaults; importing cannot overwrite existing mailers.
- [x] Load a bounded final-sheet example with exact note, merchant link and matching image if verified. Keep raw records out of Git.
- [x] Run frontend tests, design-system build, lint and production build; inspect UI and one fresh review.
- [x] Record limitations and update handoff. Commit all three tasks as one revision after final checks; leave port5000 running.

## Completion notes
The historical sample has one recorded purchased gift, with the other two
proposal slots explicitly pending. No historical alternatives were invented.
The exact historical note is preserved and currently fails the smaller card's
fit check, so it cannot be approved without a suitable card or revised copy.
Private local samples are excluded both from Git and Next deployment tracing.
Verification and review dispositions are in the matching review and session note.
