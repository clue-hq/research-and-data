# Project workspace V2

Status: local frontend preview. Revised after the founder rejected the initial
V2 scope and visual treatment on 2026-10-25.

## Scope

This branch owns the project account view and its connection to Direct Mail.
The previous V2 Email and Analytics screens, email models/actions, scripted chat
and custom Home are removed. Home, chat, global Artifacts and sidebar use the
original Clue implementation. Email belongs to the separate email branch.

V1 stays on `feat/direct-mail-infrastructure-ui`, port 5000. V2 stays on
`feat/direct-mail-infrastructure-v2`, port 5001, in a separate worktree.

```sh
# From this worktree's apps/frontend directory
npm run dev:preview -- --port 5001
```

Open `/projects/10m-landing-page-campaign/plan`. The launcher enables isolated
fixture mode and clears live backend configuration. No purchases, messages,
model calls, publication or fulfillment actions run against live services.

## Customer experience

- Accounts: compact table of account, relationship owner, research, gift status
  and connected artifacts. Search, status/owner filters, stable sorting and
  25/50/100-row pages keep rendering bounded.
- Selection applies only to visible rows on the current page. Filter and page
  changes clear it. Bulk owner assignment checks every selected revision and
  commits atomically; it preserves the sender on already prepared items.
- An account opens one drawer with Overview, Gift, Page, Note and Ad tabs as
  available. Gift and note previews read the existing mailer and approval
  snapshot, rather than storing a second copy.
- The drawer opens the existing Direct Mail review for gift selection, the card,
  the note and itemized cost approval. Approved gifts open existing tracking.
  A recorded approval alone does not create order/shipping events.
- Project Artifacts is a searchable, paginated list. It opens the same account
  drawer. Page/ad previews contain recipient-facing fictional copy. Pages remain
  unpublished; QR assignment and public destinations are not simulated.
- Chat opens the original Clue project chat. No custom agent simulator is added.

Project = overall account motion; campaign = channel program within it. Project
owner, account owner and prepared sender stay distinct. Territory is context;
automatic territory routing is not implemented.

## Scale fixture and repository handoff

`features/orchestration/data/workspace.fixture.ts` generates 1,000 fictional
accounts at runtime: six prepared examples plus 994 research-pending accounts.
Pending accounts have no invented research, fit score, contacts or artifacts.
No private training corpus or real pilot contacts are copied into the project.

`model/account-list.ts` handles local filtering, stable sorting, pagination and
selection boundaries. Only the visible page is rendered. The full fixture is
still loaded in browser memory: this proves the frontend list behavior, not live
server pagination or production throughput.

`data/workspace.repository.ts` is the ownership/persistence seam. The preview
adapter uses atomic IndexedDB transactions and revision checks, with cross-tab
notifications. Storage version 4 migrates earlier V2 fixtures, preserving owner
assignments while removing retired email records and replacing preview copy.
The separate `clue-direct-mail-preview-v2` store retains existing gift edits and
approvals; V1 browser storage is untouched.

For live integration, review contracts with the founder first. Aryan should
replace fixture reads with scoped account projections and server pagination,
filter/sort queries and batch owner assignment. Preserve stable account,
contact, mailer and artifact IDs, authorization, revision conflicts and approved
snapshots on the server. Components must not embed transport logic.

Required services outside this frontend slice include actual research claim
references, authenticated owner identities, creative generation/versioning,
publication/QR routing, gift ordering, fulfillment events and cost settlement.

## Validation and limits

The scale-model tests cover page boundaries, search/filter/sort, page-only
selection, unchanged off-page accounts, stale-batch rejection and sender
preservation. Cross-domain tests cover account/contact/mailer joins and existing
gift-approval gates. Browser checks cover the table, local bulk assignment,
previews and original navigation.

The isolated preview is not a live workspace or deployed backend integration.
The previous V2 research report remains background material, not authorization
to build the removed email or analytics infrastructure.

Final checks: design-token generation and production build passed; lint has zero
errors and 11 inherited warnings. The full suite passed 3,672 tests with 5 skips;
an additional prepared-mailer scale test passed in the final four-test scale run.
Browser QA confirmed 25 rendered rows out of 1,000, bounded page selection,
preview-to-tracking navigation and the restored chat controls. Desktop layouts
were inspected at 1159px and 2511px; mobile-device verification was not performed.
