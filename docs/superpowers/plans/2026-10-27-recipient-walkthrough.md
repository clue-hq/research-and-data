# Recipient walkthrough implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the authorized V2 walkthrough: one researched account with two recipients, connected gift/note/page/cost review, tracking and the same review across 500 accounts.
**Architecture:** Keep the native account table and shell. A shared recipient review projects canonical mailers and versioned page records through the existing local repository seam. An additive sample campaign preserves prior preview records. Explicit sample data never invokes live agents, payments or publishing.
**Tech Stack:** Existing Next/React/TypeScript, Zod, Clue tokens and controls; browser record store.
**Spec:** apps/frontend/docs/architecture/direct-mail-v2.md (audit and recipient-first direction), approved walkthrough scope in the user's 2026-10-27 request.

## Global Constraints
- Branch feat/direct-mail-infrastructure-v2; V2 localhost:5001. V1 code/data/process unchanged.
- Frontend only; no email work, no live mutations, no pushes.
- Preserve individual review plus bulk approval, exact approved versions and costs, no budget reservation.
- Preserve natural account/recipient context and original research navigation; no forbidden ?artifact= query.
- Use existing design tokens and controls. Keep controller and fixture logic out of presentation.

## Review Focus
- Existing saved drafts/approvals survive additive seeding and repeated reads.
- One account has two distinct recipients; shared ads do not inherit recipient identity.
- Changing a page invalidates review; approving a send pins its page version; subsequent reads stay consistent.
- Cohort/filter/recipient selection survives reload and account changes; 500 accounts do not render thousands of rows.
- Draft, approved, preparation, delivered and exception displays tell coherent, explicitly illustrative stories.

### Task 1: Canonical walkthrough data and approval boundaries
Files: account-materials/data/walkthrough.fixture.ts; direct-mail/model/outreach-page.ts; direct-mail/model/direct-mail.ts; direct-mail/data/direct-mail.repository.ts; model/walkthrough.test.ts.
- [ ] RED: 500 unique campaign accounts, 1000 recipients, two Snowflake people, repeated seed preserves edits; page review required and version changes invalidate readiness.
- [ ] Implement additive campaign/page records, revision-safe page edit/review methods, approval snapshots, coherent shipment/QR fixtures.
- [ ] GREEN: focused domain tests; checkpoint.

### Task 2: Shared account queue and recipient review
Files: account-materials/model/outreach.ts; hooks/use-outreach-browser.ts; components/materials-browser.tsx, outreach-review.tsx, outreach-tracking.tsx, outreach.module.css.
- [ ] Test bounded account/recipient queries, account scope and selection serialization.
- [ ] Reuse mailer editor, cost confirmation and card renderer. Implement gift/note/page/review and tracking in a single recipient context; natural hierarchy and compact controls.
- [ ] Add 25-row account paging, search/status/owner filtering and next recipient; use same view at one and 500 accounts.

### Task 3: Connect native entry points and coherent story
Files: accounts project table/preview fixtures/contacts adapter; project mail link; project gallery; preview project fixture transcript; direct-mail entry.
- [ ] Add native table campaign scope and recipient counts; preserve table state and research click.
- [ ] Use same recipient record from chat/Gallery/account/global/Direct Mail; remove nested Gallery handoff loop.
- [ ] Supply consistent fictional research/committee and post-research chat; no 404 committee links for prepared recipients.

### Task 4: Verification and handoff
- [ ] Build tokens; lint; appropriate tests; production build. Fresh whole-change review under executing-plans skill, resolve important findings.
- [ ] Browser walk: two Snowflake recipients, gift/note/page review, exact cost approval, approved tracking and in-progress evidence, 500-account queue, reload/return.
- [ ] Verify split and expanded layouts; save screenshots; leave the working walkthrough open on 5001. Verify V1 unchanged. Update canonical docs/memory and commit locally.
