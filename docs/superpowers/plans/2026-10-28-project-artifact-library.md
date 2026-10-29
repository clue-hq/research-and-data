# Project artifact library implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Keep a session ledger and perform one final whole-change review.

**Goal:** Replace the competing V2 Gallery catalogs with one project library and an explicit recipient-level direct-mail approval queue.

**Architecture:** Reuse the account artifact library's canonical projections, previews and recipient review. Project and account scopes are filters over canonical records, never additional editable copies. Native project designs and documents remain in the same library and open their existing editors.

**Tech Stack:** Existing Next.js, TypeScript, CSS modules, Clue semantic tokens and account badge styles.

**Spec:** This document records the user's 2026-10-28 revision request and the already discussed Project artifacts direction.

## Design and choices
- Keep the account library and Direct Mail layouts the user approved. Replace the Gallery queue/catalog switch, not the shell or design system.
- Artifacts is the chat tab; Project artifacts is its heading. All materials is the default. Needs review shows recipient sends with distinct gift/note/page type badges, readiness, itemized-cost entry and deliberate approval. Approved is a content approval filter, not delivery status.
- One search/filter bar for account, campaign, type. Preview within the chat panel; existing expand control works. Return preserves search, filters and position.
- Target accounts continues to show research/committee/owners. Remove the hard-coded campaign header; an Artifacts column opens the project library filtered to the account. Counts derive from scoped records and represent materials, not recipients.
- Alternative: retain outreach queue as Gallery's default. Rejected because it duplicates account management and hides ads/documents. Alternative: separate gift, page and file modules. Rejected because the user explicitly asks for shared navigation and the same records.
- Marketer's public library and guardrail descriptions inform the organization and explicit action approval; no claim to having inspected their private app. No Userled website visit.

## Global constraints
- V2 only, localhost 5001; V1 unchanged. No backend integration, external orders, email work or publishing.
- Existing canonical approval and version gates remain authoritative. No broad approve-all action; bulk approval only for individually reviewed current mailers, with confirmation and cost.
- Ads remain account-scoped. Unknown campaign/account metadata is unassigned, never guessed.
- Use Clue badge classes/tokens, accessible names, keyboard controls, loading/error/empty states.

## Review focus
- Multiple campaigns for the same account/contact cannot cross-link material or approval.
- Unknown/stale deep links cannot open a different record silently.
- Native files/documents stay visible alongside direct-mail materials.
- At 500 accounts only a bounded page of previews renders; filters/counts/selection stay consistent.
- Edits invalidate readiness; bulk confirmation cannot authorize a newer revision unseen.

## Tasks
- [x] 1. Model: project library projection, native file merge, account/type/campaign filtering, recipient review deduplication and scoped account summaries. Add behavioral tests for scope and pagination.
- [x] 2. UI: shared library controller and presentational cards/badges, inline canonical preview/review, paginated recipient approval queue. Preserve the existing account library layout.
- [x] 3. Integration: replace V2 ProjectGallery mount; rename tab; remove misleading account banner; real material-count entry into library; canonical native editor callbacks.
- [ ] 4. Verification: focused tests, design token build, lint, production build, browser checks for filters/back/review/cost/tracking and narrow panel. Final whole-change review and local commit.

Implementation clarification: standalone creative content approvals are now recorded in the V2 fixture repository, with a pinned version and content snapshot. They never authorize publishing or spend. At project scale, All materials shows up to four previews for every type, with paginated View all drilldown.
