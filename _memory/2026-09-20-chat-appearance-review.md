# Chat appearance review documented

## Follow-up: buying committee table parity

- Founder expected buying committee formatting to match the accounts table. It still
  used 13px/18px; switched its shared CSS to canonical 14px/20px text-default tokens.
  Account preview and full account overview share BuyingCommitteeTable. Existing
  header/name emphasis and layout remain.
- Browser verified expanded committee headers and cells at 14px/20px in both account
  preview and full account detail; temporary tab closed. Playwright's button role did
  not match the native summary despite the AX label; using the observed summary worked.
- Design-system generation, lint and production build passed with the same two existing
  canvasOperations warnings. CSS-only change; no new tests. Closing state: saved locally,
  no remote publication. The separate Contacts-tab grid was outside this change.

## Correction: 14px/20px applies to accounts table

- Founder clarified the prior request meant accounts table typography, not chat.
  Restored chat to the accepted 14px/22px. AccountsTable now uses canonical
  text-default tokens (14px/20px) for regular headers/cells and medium company
  names/badges, scoped in accounts-table.module.css. Shared account readability
  styles for other controls and detail surfaces stay intact.
- Updated the current chat typography record and regenerated tokens. Live accounts
  table measured 14px/20px in headers, cells, names and badges (400/500 weight hierarchy
  retained); screenshot reviewed and Accounts kept open. The other chat tab measured
  14px/22px on composer and message body, confirming the mistaken trial was undone.
- Design-system generation, lint and production build passed; the same two existing
  canvasOperations warnings remain. Three existing accounts-table layout tests passed.
  Closing state: correction complete, saved locally without remote publication.

## Follow-up: tighter chat line height trial

- Founder requested trying 14px font with 20px line height and seeing the result.
  Changed the shared chat body-line-height source token from 22 to 20; the 14px font
  size remains. Updated the current typography record and regenerated CSS.
- Browser confirmed 14px/20px for the composer and all four loaded user/assistant
  message bodies. Screenshot reviewed and chat left open for the requested preview.
  Creating a new visible browser tab failed with a session-ownership error; recovered
  by selecting the available user tab and navigating to the requested chat preview.
- Design-system generation, lint and production build passed; the same two existing
  canvasOperations unused-function warnings remain. No new tests for this token-only
  trial. Closing state: saved locally with no remote publication; visual preference
  remains for the founder to assess. No message sent.

## Follow-up: smaller chat body type

- Founder selected 14px text with the existing 22px line height. Updated the shared
  product chat body-font-size source token from 15 to 14; composer, sent-user text,
  assistant prose and inline mentions consume it. No global typography change.
- Regenerated tokens and updated the canonical appearance register. Browser computed
  styles confirmed 14px/22px on the composer and all four loaded user/assistant message
  bodies and paragraphs; temporary background verification tab closed, no message sent.
- Design-system generation, lint and production build passed. Lint retains the same
  two unused-function warnings in canvasOperations.ts. No new tests for this token-only
  visual adjustment. Closing state: complete and saved locally, without remote publication.

## Follow-up: soften references on grey bubbles

- Founder reported attachment/tag chips looking out of place after the bubble colour
  change. Shared ChatAttachment now uses canonical bg-page + Gray Alpha 100 border,
  regular label weight, 14px file glyphs and transparent preview backing. Hover uses
  bg-subtle + Gray Alpha 200. Mention underline uses Gray Alpha 200; its preferred
  transparent inline treatment remains. Same primitives style drafts and sent refs.
- Live persisted image/document chips measured 32px height, 14px regular text,
  rgb(248,249,251) fill and rgba(0,30,75,.067) border; document preview backing is
  transparent and its glyph is 14px. Screenshot reviewed on the grey user bubble.
- Draft account mention verified at 15px with transparent background and Gray Alpha 200
  underline (rgba(0,31,72,.098)); draft cleared and send disabled, temporary tab closed.
- Token generation, lint and production build passed; only the two existing design-editor
  unused-function warnings remain. Visual-only change; no message/upload/provider call.
  Documentation updated and change saved as a local commit, without remote publication.

## Follow-up: sent-user background

- Founder selected `#eff0f3` for all sent-user message boxes. Added the product chat
  background token and applied it to the shared user-role message-parts rule.
- Checked all main-frontend user-message renderers: project/design and artifact split
  views mount ChatSurface → ConversationContent → ChatTranscript. The older unused
  `.userMessage` style now shares the same background token as the active user-role rule.
- Browser measured both loaded user bubbles as rgb(239, 240, 243), exactly #eff0f3;
  assistant containers stay transparent. Used a temporary background tab because the
  user had moved their original tab to Accounts; closed the review tab afterwards.
- Token generation, lint and production build passed (two pre-existing lint warnings);
  final build repeated after aligning the older user-message style. No functional tests
  added for this color-only change.

- Founder asked to record the preceding read-only visual review for later frontend work.
- Canonical record: `apps/frontend/docs/figma/projects-chat-flow.md`, section
  `Chat appearance inconsistency register (2026-09-20)`; linked from the frontend docs index.
- Open findings: CHAT-VIS-01 body typography (15/22 composer versus 14/20 transcript),
  CHAT-VIS-02 mention appearance/icon drift, CHAT-VIS-03 attachment-chip size/geometry drift.
- Baselines: Damascus `074f038e3` on `rebase-and-expand-attachment-types`, port 3027;
  dummy port-of-spain `9fc902a` on `codex/projects-home`, port 3000. Generated tokens identical.
- Record distinguishes measured browser evidence from source-only comparisons. The current
  dummy has no populated agent transcript; 15/22 throughout is the proposed direction based
  on the founder's preferred composer, not a claimed newer dummy transcript.
- Includes source pointers, preserved properties, presentation-only boundary and unchecked
  acceptance criteria. Appearance implementation remains open; no runtime code changed.
- Documentation links and whitespace checked before the local commit; no runtime tests
  required for this documentation-only update. No remote publication.

## Implementation in progress

- Founder authorized all three appearance fixes. Added product chat body tokens via source;
  shared ChatMentionVisual and ChatAttachment across composer and transcript. Kept metadata
  sizes and backend contracts unchanged. Transcript references retain order and identity.
- First frontend token/lint/build gates passed (two existing canvasOperations unused-function
  warnings). 81 focused composer/catalog/transcript/attachment/presentation tests passed.
- Command corrections: token command initially ran from repo root (missing script); reran
  from apps/frontend. tsx CLI hit sandbox IPC EPERM; node --import tsx --test passed without IPC.
- Live current-chat body paragraphs/lists now 15/22; file chips 32px, 14px medium, 20px preview.
  Draft/sent mention, responsive and interaction verification still in progress.

## Closing entry

- CHAT-VIS-01..03 implemented. Dedicated generated chat 15/22 body tokens leave global
  typography and metadata hierarchy intact. Shared mention visuals preserve logos, initials,
  typed icons and Slate selection; failed account logos fall back to the building glyph.
  Shared attachments preserve 32px height and draft-only removal/status controls; long names
  truncate within available width. Transcript refs retain their original ordering/identity.
- Live browser: persisted PDF/XLSX/PNG chips and user/agent prose verified; Inspect absent;
  312px transcript with artifact panel open has no horizontal overflow. Main chat draft cleared
  and original URL restored. Temporary fixture route rendered the real components at 390px
  and 720px, covering draft/optimistic/persisted/streaming styles, missing-logo/contact fallbacks,
  web-kind fallback without catalog, keyboard mention selection, attachment removal and
  busy/failed status presentation. Fixture route and temporary tab removed; viewport reset.
- No message submitted, provider called, or server upload made. Fresh persistence/upload retry
  was not exercised; 81 existing regression tests covered the relevant model transitions.
- Canonical visual register updated with measured closure evidence and limits; ten file links
  resolve. No new backend contract or migration. No remote publication.
- Final post-review token generation, lint and production build passed again; only the two
  pre-existing canvasOperations warnings remain. Whitespace and documentation links checked.
- Final follow-up build passed; scoped color change complete, documentation updated,
  and saved locally without remote publication.
