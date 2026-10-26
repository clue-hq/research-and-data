# Connected account experience V2 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Track progress in _memory/2026-10-25-direct-mail-v2.md.

**Goal:** Build the approved shared account-plan experience as an isolated frontend V2 on localhost:5001, retaining V1 on localhost:5000.

**Architecture:** Existing Clue shell and tokens; one typed orchestration fixture repository links account plans, people, campaigns, creative versions and email state. Gift execution continues through the existing Direct Mail repository. Preview gates prevent fixture interfaces from being presented as live integrations.

**Tech Stack:** Existing Next.js App Router, TypeScript, Zod, React, CSS modules and Base UI; no new packages.

**Spec:** apps/frontend/docs/research/abm-orchestration.md. The founder approved building this version separately on 2026-10-25.

## Global constraints

- V1 worktree and port 5000 remain untouched; V2 is feat/direct-mail-infrastructure-v2 in the separate managed worktree.
- Frontend only. No real model calls, purchases, sends, publishing, CRM changes or payments.
- Existing tokens, compact typography, tables and contextual review. No floating demo badge.
- Project is the overall motion; campaign is a channel program. Accounts exist independently of mailers.
- Separate project/campaign owner, account owner and sender; render actual selected sender identity.
- Gift range/ceiling reserves no credits; final cost approval remains explicit. Reuse current gift approval/revision guards.
- Email approval binds rendered recipient copy and sender. Changes invalidate approval; real replies stop scheduled follow-ups. No actual email backend integration.
- Use one fixture data source per object with Zod parsing and repository operations; never embed mock record arrays in components.
- Keep raw corpus and secrets out of V2. Local commits only.

## Review focus

1. Account with no gift remains present and usable in plan, email and artifacts.
2. Changing sender/content after approval clears only the affected approval; stale edits cannot overwrite newer state.
3. Missing address, unavailable gift and ineligible ad audience produce actionable holds instead of false success.
4. Artifact links resolve to one canonical version across plan, chat and library; preview never implies publication.
5. Tracking, carrier delivery, human reply and meeting outcomes remain separate; UI does not manufacture progress.

### Task 1: Shared domain, fixtures and repository

**Files:** Create features/orchestration/model/workspace.ts and workspace.test.ts; data/workspace.fixture.ts, workspace.repository.ts, workspace-provider.tsx; hooks/use-workspace.ts. Extend DirectMailStore with injected fixture factory for V2 composition, retaining default behavior.

**Interfaces:** WorkspaceState holds people, account plans, campaigns, artifacts, emails and activity. WorkspaceRepository exposes read, updateAccountOwner, saveEmail, approveEmail, markReplyHandled and addChatMessage with revision checks, subscriptions and atomic IndexedDB persistence. createV2MailFixture() supplies linked fictional mailers with existing domain validation.

- [x] Write tests for non-gift account presence, referential integrity, owner/sender separation, stale approval refusal, email change invalidation, reply stops, missing-recipient errors and account metrics.
- [x] Run targeted tests and observe missing behavior; implement immutable domain transitions and validated atomic fixture adapter.
- [x] Run focused tests and commit the coherent data layer.

### Task 2: Connected product surfaces

**Files:** Create features/orchestration/components/{workspace-screen,project-plan,account-detail,project-conversation,artifact-library,email-workspace,results-view,workspace-ui}.tsx and workspace.module.css.

**Interfaces:** Components consume the shared hook and the existing DirectMailController. Account selection uses URL query state; artifact/email links use stable IDs. Existing MailerReview/MailerTracking remain the gift detail/approval surface.

- [x] Build project overview with approach/owner/status/next-step rows, useful summaries and gift-free accounts.
- [x] Add account detail with evidence, buying group, sender, channel plan and connected assets; assignment changes update shared state.
- [x] Add conversational brief/review path with honest scripted fixture responses and actionable links.
- [x] Add linked artifact previews (page/ad/email/note), email review/scheduling/inbox and results from shared records; do not imply real publish/send.
- [x] Verify filters, empty states, keyboard dialogs and back navigation in browser; inspect the desktop responsive table. Mobile-device QA remains unperformed.

### Task 3: Preview routing, handoff and validation

**Files:** Modify preview-gated app routes, navigation, protected provider composition and Direct Mail context links. Add architecture/direct-mail-v2.md and update docs index and session ledger.

- [x] Wire project/home/chat/Gallery, workspace Artifacts, Email and Analytics to V2 only in explicit preview mode; connected-mode routes retain existing behavior.
- [x] Start V2 with npm run dev:preview -- --port 5001, leaving V1 server alone.
- [x] Walk project chat → account plan → gift/note review → cost approval → tracking; also email-only account, sender change, asset preview, reply and analytics.
- [x] Run design-system build, full tests, lint and production build. Fix new failures, document inherited ones.
- [x] Request one fresh whole-branch review; resolve material findings, verify both localhost URLs, commit locally and show V2.

Execution choice: continue inline under the founder's build instruction. The approved research and this plan cover the customer frontend; backend contract reconciliation remains a later step.
