# Harvey direct-mail demo implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Continue the deployed Harvey account-research story in the existing local Direct Mail V2 review and simulated fulfillment flow.

**Architecture:** Add one evidence-backed local fixture through the repository seed/migration seam. Keep the existing review, immutable approval and tracking components. Add explicitly labeled simulation controls limited to this fixture, with no network mutations.

**Tech Stack:** Next.js, React, TypeScript, Zod, IndexedDB, node:test.

**Spec:** User's November 1 clarification in this chat: read the already-researched account in the deployed app, select a real gift around $100, use its real photograph, and show the order flow only on localhost.

## Global constraints

- Keep V1, deployed application and backend unchanged; no sends, orders, publication, or payments.
- Retain real research provenance, exact retailer variants, observed prices, and photo attribution. Shipping/tax/preparation remain demo estimates.
- Public office address is not verified personal receipt or gifting permission. Require explicit demo-address acknowledgment.
- Preserve existing drafts. Reset only this recording scenario and its demo ledger entries.

## Review focus

- Reload must preserve edits and not duplicate the seed.
- Stale tabs must not advance or reset a newer revision.
- Fulfillment cannot advance before approval, or outside the dedicated demo record.
- Reset must refund only this scenario's net demo debits; repeated resets must not mint credit.
- Real product photography must never appear as an inspection photograph.

## Task 1: Seed and replay one researched mailer

**Files:** `apps/frontend/src/features/direct-mail/data/harvey-demo.ts`, `harvey-demo.test.ts`, `direct-mail.repository.ts`, `direct-mail-provider.tsx`; `public/direct-mail/harvey-demo/`.

**Interfaces:** `withHarveyDemo(state)`, `advanceHarveyDemo(state,id,revision)`, `resetHarveyDemo(state,id,revision)`; repository optional demo operations.

- [x] Write behavioral tests for additive migration, approval prerequisites, revision conflicts, sequential fulfillment, safe reset, and merchant sources.
- [x] Run tests; implement fixture and replay transitions; run tests again.
- [x] Add repository operations and apply seed only in V2.

## Task 2: Present and verify the existing flow

**Files:** Direct Mail screen/review/tracking and a small `harvey-demo-controls.tsx` component.

- [x] Display source context, persistent simulation label, replay/reset controls and live-research links. Preserve actual account ID but link it to the deployed app rather than a nonexistent local research record.
- [x] Exercise gift selection, note, address acknowledgment, cost approval and replay through delivery in the browser. Reset to the opening shot.
- [x] Run focused tests, design-system build, lint and build. Record evidence and limitations; make a scoped local commit.
