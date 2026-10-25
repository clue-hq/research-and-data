# Direct Mail Frontend Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Execution is authorized by the founder's instruction to start building the presented design.

**Goal:** A connected customer journey for reviewing personalized mailers, approving reviewed batches and following both shipment legs in the existing Clue frontend.

**Architecture:** Typed domain state and repository operations sit behind an explicit fixture adapter. Shared controllers drive the dedicated section and chat/Gallery entry points. Browser storage holds synthetic state and local uploads; no production backend contract is assumed.

**Tech Stack:** Next.js App Router, React, TypeScript, Zod, IndexedDB, existing Clue CSS tokens and shared UI controls.

**Spec:** `apps/frontend/docs/architecture/direct-mail.md` (approved to build 2026-10-25).

## Global constraints

- Customer screens only; no fulfillment administration or real spending.
- Three gift options, individual review, reviewed/ready bulk approval.
- Automatic dispatch after quality check; photos in tracking, no second routine approval.
- Existing 240px shell, semantic tokens, existing typography and shared controls.
- Local preview on 5000; no 3000-series process changes, no floating demo badge.
- Synthetic data only; do not copy the training corpus. Components never import fixtures or fetch.
- Commit locally; never push or change deployed data.

## Review focus

- An edit after review must invalidate readiness; immutable approvals remain untouched (Task 1).
- Missing address/cost, unavailable gifts and note overflow must block approval (Task 1).
- Reloads, two tabs and outdated revisions must preserve drafts/refuse stale writes (Task 2).
- Failed/oversized uploads must retain the draft and report an actionable error (Task 3).
- Narrow widths, keyboard focus and partial bulk failures must remain usable (Tasks 3–4).

### Task 1: Mailer domain and readiness

**Files:** Create `apps/frontend/src/features/direct-mail/model/direct-mail.ts`, `direct-mail.test.ts`; create `data/direct-mail.fixture.ts`.

**Interfaces:** Export `DirectMailState`, `Mailer`, `CardAsset`, `HandwritingStyle`, `MailerPatch`; `readiness(mailer,state): string[]`, `estimate(mailer): number|null`, `updateMailer(state,id,revision,patch): DirectMailState`, `reviewMailer(state,id,revision): DirectMailState`, `approveMailers(state,items): {state,results}`. Values use integer USD cents. Approved snapshots include chosen asset versions and the cost ceiling.

- [ ] Write failing tests: exactly three choices; no default selection; missing gift/address/cost and note overflow block review; a draft change invalidates review; stale revision refuses; approval is idempotent and preserves the selected snapshot; bulk outcomes remain per-item.
- [ ] Run `cd apps/frontend && npx tsx --test src/features/direct-mail/model/direct-mail.test.ts` (expect failure before implementation).
- [ ] Implement schemas, pure transitions, synthetic scenarios and readiness checks.
- [ ] Run the same command (expect all pass), then commit the coherent domain.

### Task 2: Persistent repository and controller

**Files:** Create `data/direct-mail.repository.ts`, `direct-mail.storage.ts`, `direct-mail.repository.test.ts`, `direct-mail-provider.tsx`; `hooks/use-direct-mail.ts`.

**Interfaces:** `DirectMailRepository` exposes `read`, `patch`, `review`, `approve`, `create`, `addCard`, `addStyle`, `requestProposal` and `subscribe`. The factory accepts a transactional store; browser IndexedDB and memory test stores implement that interface. Provider takes `enabled:boolean` resolved on the server. Hooks return typed data, pending/error state and callbacks.

- [ ] Write failing repository tests for persistence, concurrent stale updates, mixed bulk results, proposal requests and unavailable-mode refusal.
- [ ] Run `cd apps/frontend && npx tsx --test src/features/direct-mail/data/direct-mail.repository.test.ts` (expect failure).
- [ ] Implement atomic persistent writes, cross-view updates, explicit unavailable adapter, upload validation and local font registration.
- [ ] Run repository and domain tests (expect all pass), then commit.

### Task 3: Queue, review, assets and tracking

**Files:** Create components `direct-mail-screen.tsx`, `mailer-queue.tsx`, `mailer-review.tsx`, `mailer-tracking.tsx`, `card-library.tsx`, `mailer-preview.tsx`, `direct-mail.module.css`; route `app/(protected)/direct-mail/[[...path]]/page.tsx`.

**Interfaces:** Views consume `useDirectMail` controller results; canonical URL `/direct-mail/:id`, library `/direct-mail/library`. Queue query parameters preserve filters. Approval confirmation receives exact record revisions. Card previews use real uploaded image/font assets, writing bounds and conservative fit checks.

- [ ] Build queue with status/search/project filters, sort, pagination, visible-row selection and reviewed-only bulk confirmation.
- [ ] Build three-choice gift review, evidence references, card/handwriting/note editing, live preview, receiving address and all-in cost review with versioned approval.
- [ ] Build campaign creation from synthetic project recipients and three-option/insight request states. Preserve existing drafts until replacement results are applied.
- [ ] Build reusable card/font uploads and tracking timeline with two legs, package photos and replacement/exception actions.
- [ ] Browser-walk gift → card → review → approve, bulk exclusions and reload retention; check narrow width and keyboard behavior. Fix actual failures, then commit.

### Task 4: Shared entry points, final verification and handoff

**Files:** Modify `config/navigation.ts`, `components/shell/app-sidebar.tsx`, `sidebar-icon.tsx`, protected layout; project conversation and Gallery composition. Create `components/direct-mail-project-link.tsx`; write `docs/api-contracts/direct-mail.md` and update canonical spec/index.

**Interfaces:** Entry points receive project/thread scope and open the same canonical mailer IDs. The sidebar is enabled only with the explicit preview provider until backend integration is ratified.

- [ ] Add sidebar route and compact chat/Gallery links without overloading design-artifact records.
- [ ] Write proposed API operations, snapshots/version/error rules and exact adapter replacement instructions for Aryan.
- [ ] Run all new tests plus token tests, `npm run design-system:build`, `npm run lint`, `npm run build` (expect pass; report existing warnings).
- [ ] Verify shared state, keyboard interaction, uploads and exception scenarios in localhost:5000; save visual evidence.
- [ ] Obtain one fresh-context whole-branch review under executing-plans, resolve material findings, update memory/ledger and commit locally.
