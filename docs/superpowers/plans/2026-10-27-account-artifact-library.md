# Account artifact library implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, with one fresh review at the end.

**Goal:** Account Artifacts opens every artifact for that account, across campaigns, with useful previews and a deliberate path into recipient review.
**Architecture:** A read-only projection joins canonical mailers/pages, campaign creative and native account files. Presentation filters that projection; approval and edits continue through the existing repository and outreach components.
**Tech stack:** Next.js, TypeScript, existing Clue tokens, SelectField and Button.
**Spec:** User requests in this conversation: all Snowflake artifacts, campaign drill-down, bigger previews, no earlier/walkthrough split. Local recording reviewed offline for campaign/account separation.

## Global constraints
- V2 only on localhost:5001; preserve V1, existing drafts and approvals.
- Frontend fixtures only; no email build, external visits, uploads, publish or push.
- Account is permanent; campaign is a channel program within a project. Unknown campaign stays unassigned.
- Gallery is a scoped view of artifacts, not another copy of them. Approval is distinct from delivery/publication.
- Use existing design tokens, preview components and repository seams.

## Review focus
- An account and contact in two campaigns must not mix recipient sets.
- Existing saved drafts/approval snapshots must remain intact.
- Native files without campaign metadata must remain discoverable.
- Deep links and browser Back must retain filters and selection.
- Empty, unavailable and narrow views must remain usable.

## Task 1: Canonical library and account UI
- [ ] Write failing domain tests for cross-campaign scope, all source types, canonical page identity, approved versus delivery status, filters and legacy fixture preservation.
- [ ] Add model `account-library.ts` with `buildAccountLibrary` and `queryAccountLibrary`, plus explicit additive fixture context for older sample campaigns.
- [ ] Replace the V2 AccountArtifactsScreen mount with `AccountArtifactLibrary`. Default to grouped preview cards, add grid/list, campaign/type/recipient/status/search filters and 24-item pagination. Keep native files in the same result set.
- [ ] Add shared preview rendering and contextual detail. Reuse OutreachReview for canonical recipient sets and MailerReview/Tracking for older records. Preserve URL filters when returning. No automatic review on entering account.
- [ ] Run relevant model tests, token build, lint and production build; verify browser library, filters, preview, review and history at desktop/narrow widths.
- [ ] Update handoff and local memory. Commit locally. Obtain one fresh review, address material findings and show the verified local page.
