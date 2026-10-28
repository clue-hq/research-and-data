# Direct Mail frontend handoff

## Revision 2 additions (2026-10-25)

- `giftBudgets` stores project-level preferred minimum/maximum and upper gift-price
  ceiling with revisions and a lock. `saveBudget` reserves no credits and grants
  no send authority. Editing is deliberate and invalidates draft reviews; approved
  mailers are unchanged. The separate `budgetCents` remains the all-in send cap.
- The preview wallet deducts the estimate exactly once on approval. Insufficient
  balance refuses; pre-order cancellation refunds only a recorded debit. `topUp`
  adds demo credits only. No processor or agent payment card is implemented.
  Actual preparation-cost reconciliation is not implemented; Aryan must define
  the ledger/adjustment approval contract before real billing is connected.
- `noteTemplates` are versioned saved structures. Applying expands recipient,
  company, gift and insight fields into a draft, requiring review. Existing
  approved snapshots never reference a mutable template body.
- Gift `productUrl`/`observedAt`, insight `sourceUrl`, `assets` and `qr` are optional
  validated references. The project campaign table links canonical records;
  absent channel links remain absent. Email integration belongs to its own branch.
- QR publication, physical assignment and verified routing are separate states.
  New campaigns clear physical assignment/verification. This UI does not generate
  codes, assign inventory, publish microsites or run redirect checks.
- Six chronological tracking milestones precede the carrier-leg details; package
  photos now display timestamps.
- Optional `GET /api/direct-mail/pilot` is gated by the existing development-only
  preview configuration and reads `.local/direct-mail-pilot.json` under the frontend.
  That folder is Git-ignored. A missing file returns204; production returns404;
  optional source failures leave existing IndexedDB drafts available with a notice.
  Import appends isolated `pilot-*` IDs and never overwrites edited records.
  A single local historical example preserves the final-sheet note and exact
  purchased variant with verified merchant imagery; the final Sheet contains one
  purchased gift, so two further proposals stay pending instead of being invented.
  No addresses, receipts or raw corpus were imported. Aryan receives portable
  synthetic fixtures, not the local private pilot sample.

All fields are additive; existing browser state remains valid. These are frontend
proposals, not ratified backend payloads. The original approval snapshot still
owns gift/card/note/address/cost; asset-publication and QR dispatch requirements
need backend enforcement in a later contract review.

Status: **frontend proposal, not an implemented backend contract** (2026-10-25).
Owner of the current UI: `src/features/direct-mail/`. Product decisions and the
longer-term flow are in [the design spec](../architecture/direct-mail.md).

## What works in this branch

- Workspace queue with project/campaign/status/search filters, sorting, ten-row
  pagination, visible-row selection and reviewed-only bulk approval.
- One recipient record: evidence excerpt → three gift choices → card, handwriting
  and note → address and full estimate → versioned approval.
- Reusable PNG/JPEG cards, front/message-side artwork, writing bounds and local
  font uploads. Preview fonts are bundled with their OFL licenses.
- Separate inbound and outbound tracking, quality/preparation history, package
  images, cancellation before ordering, and replacement review transitions.
- Chat and Gallery entry points reference the same canonical mailer ID.

The current adapter prepares synthetic recommendations immediately when a
campaign is created. Recommendation-change requests have explicit local sample
results; there is no running research agent, merchant order, carrier connection,
charge, robot conversion or fulfillment worker behind these controls. Dates,
prices, entities, evidence and tracking numbers are examples. Product/package
illustrations in `public/direct-mail/` are sample artwork, not merchant photos
or inspection evidence. No pilot corpus has been copied into this repository.

## The replacement seam

| Layer | Location | Responsibility |
| --- | --- | --- |
| Schemas / rules | `model/direct-mail.ts` | Parsed state, readiness and immutable approval snapshots |
| Repository contract | `data/direct-mail.repository.ts` | Typed operations; current factory is the local adapter |
| Local storage | `data/direct-mail.storage.ts` | One atomic IndexedDB workspace record |
| Recovery buffer | `data/direct-mail.drafts.ts` | Per-tab unsaved edits, with their base revision |
| Upload parsing | `data/direct-mail.uploads.ts` | Local byte validation and font loading |
| Composition | `data/direct-mail-provider.tsx` | Explicit adapter choice |
| Controllers | `hooks/` | Form state, errors, selection and commands |
| Presentation | `components/` | Existing Clue shell/tokens and shared controls |

For Aryan:

1. Review this proposal against the real research, claim, project, asset and
   fulfillment surfaces with the founder. Record the resolved gaps here before
   implementing a live integration.
2. Implement an HTTP repository satisfying `DirectMailRepository`. Keep fixture
   generation, IndexedDB and sample-result controls out of that adapter. Parse
   responses at this seam and return typed domain values; components do not fetch.
3. Replace sample entity IDs with resolved account/contact/project/thread IDs.
   The local campaign form's people catalog is derived from sample records; the
   live adapter needs a real project-recipient query, including projects with no
   mailers yet. Campaign identity also needs a backend ID, not just a display name.
4. Move canonical readiness, approval, price/cap checks and asset eligibility to
   the server. Browser checks are customer feedback, never spending authority.
5. Select the HTTP adapter using authenticated workspace capability at the
   protected-layout composition seam. Currently `isFrontendPreviewMode()` is the
   only enablement source. Outside explicit local preview the unavailable adapter
   refuses commands and the sidebar item is hidden; it never falls back to samples.
6. Supply scoped subscriptions/polling through `subscribe`. On workspace change,
   discard the old controller/store and scope recovery buffers by workspace and
   user. The current local provider is intentionally one isolated demo workspace.

Do not wire the current `resolveProposal` sample operation to an ordering or
research endpoint. Split live request, completion and explicit apply-result
commands after the contract review. No timer advances shipments in this UI.

## Proposed operations to reconcile

Names below describe capabilities; endpoint paths are intentionally not asserted.

| Operation | Input | Result / required behavior |
| --- | --- | --- |
| List mailers | Workspace, filters, cursor | Scoped summaries, counts and next cursor |
| Read mailer | Mailer ID | Current version, proposal, approval, events, photos |
| Create campaign mailers | Project/campaign IDs, contact IDs, defaults | Deduplicated recipient records, per-recipient outcomes |
| Patch draft | Mailer ID, expected revision, patch | New version; invalidates review |
| Mark reviewed | Mailer ID, expected revision | Readiness check; reviewed version |
| Approve batch | Explicit ID/revision pairs + idempotency key | Per-mailer success/refusal and snapshots |
| Request recommendations | Mailer ID/revision, gift or insight feedback | Research job/reference; preserves current draft |
| Apply recommendations | Result/version ID + expected mailer revision | Explicitly replaces options; preserves authored note |
| Register card / handwriting | Uploaded asset refs, layout, metadata | Versioned asset, production eligibility |
| Cancel | Mailer ID/revision | Allowed capabilities checked atomically |
| Review replacement | Exception/proposal ID, mailer revision | Prior approval retained; new approval required |

The initial full-state `read()` interface is convenient for a local preview.
The live adapter should expose paginated list/detail and independent asset reads
before large customer workspaces are enabled; do not download every package photo
and full record just to render a queue.

## Version and approval rules

Amounts are integer USD cents. Unknown line items are `null`, never zero. A
complete estimate includes gift, inbound shipping, card/preparation, outbound
shipping and tax. All line items must be quoted and the total must fit the
recipient's approved ceiling.

Every customer edit increments `revision` and clears `reviewedRevision`.
Approval requires an available selected gift, a fitting nonempty note and
signature, eligible card/font, complete confirmed receiving address, no pending
recommendation change and an acceptable total. Bulk operations contain explicit
versions; never interpret visible-page selection as all search results.

An approval captures the exact gift/variant/price, note/signature, card/font
versions, receiving address, estimate and spending ceiling. Later library edits
cannot alter that snapshot. Retry is idempotent for an already-approved revision.
Use optimistic concurrency server-side; return a conflict instead of overwriting
an edit from another tab. Partial batch failure must identify each refused record.

Changing the product/variant or exceeding the authorized ceiling requires a new
review. Dispatch after an ordinary quality check does not authorize substitution.
The local replacement operation retains the prior approval and clears current
shipment/photo projections before opening fresh choices.

## Tracking and assets

Inbound means merchant → Clue; outbound means Clue → recipient. A shipping label
is not carrier acceptance. Carrier delivery is not personal receipt. The server
owns milestones, expected dates, exceptions, cancellation capability and signed
photo URLs. Expose the source timestamp on each event/photo; never fabricate a
progress percentage or advance a stage from elapsed time alone.

Uploaded cards/fonts are immediately previewable but `productionReady: false`.
Browser decoding proves neither print quality nor robot compatibility. Production
needs image dimensions/DPI, handwriting conversion, supported glyphs, real text
fit and eligible asset versions. The current conservative fit estimate uses a
600×400 logical card with advance metrics extracted from the bundled fonts, preserved whitespace and a safety margin. Regenerate the metrics with `python3 scripts/generate-mailer-font-metrics.py` when those fonts change. This is not a printer or robot instruction format.

Assets are local data URLs in IndexedDB for this phase. Real assets need upload
authorization, durable object storage, signed references and lifecycle handling
at the repository seam. PNG/JPEG cards are limited to 3 MB; fonts to 2 MB. PDF
ingestion and conversion are outside this first UI slice.

## Local run and verification

From `apps/frontend`, install the existing lockfile dependencies, then run
`npm run dev:preview`. The launcher binds loopback port **5000** and overrides
backend origins/authentication only for the isolated preview process. Do not
point it at live APIs to make fixture controls work. Open `/direct-mail`.

The source gate is `npm run design-system:build && npm run lint && npm run build`.
Run `npm test` for the full frontend suite. Focused domain/repository/upload tests
are under `src/features/direct-mail/`; token validation is in
`src/design-system-tokens.test.ts`. A raw `tsc --noEmit` also includes existing
design-editor test type errors that the repository's build configuration excludes.

Browser checks: gift/card/address approval, reload retention, mixed batch
exclusions, uploaded image persistence, actual handwriting rendering, narrow
layout, project entry points and stale-version refusal. Local state persists for
this browser origin and is not part of Git; Aryan gets fresh synthetic examples
when opening the preview on his machine.

## Next backend-backed slices

Researching/no-suitable-insight/incomplete-result screens should consume real job
and proposal records instead of inventing background progress. Other later slices
include actual vendor availability, receiving-route verification, payment/budget
enforcement, print/robot validation, carrier exceptions/returns and production
uploads. These are integration work; the customer UI does not claim they ship
with this branch.


## V2 recipient-page proposal (2026-10-27, local adapter only)

No new backend endpoint is introduced or assumed. The local repository adds `patchPage(id, expectedVersion, patch)`, `reviewPage(id, expectedVersion)` and `invalidatePage(id, expectedVersion)` for the focused outreach walkthrough.

- `Mailer.campaignId` and `Mailer.pageId` are optional additions, preserving prior fixtures.
- `DirectMailState.pages` contains typed `OutreachPage` records scoped by project/account/contact/mailer, with `version`, `reviewedVersion`, copy and publication state. Current editable content has one owner.
- Page edits increment their version and invalidate the mailer's review. Beginning an edit invalidates shared readiness immediately. The per-tab recovery buffer is never treated as canonical approved content.
- Send approval requires the current referenced page version to be reviewed and copies that exact page into the immutable approval snapshot. Approved current-page edits are rejected; a future revision/reapproval flow needs its own contract review.
- Approval does not publish a page, assign a printed URL, place an order, or synthesize carrier events. Seeded published/verified markers are explicitly illustrative; `.example` destinations are not navigable live routes.
- Keep expected-version conflicts and atomic send/credit behavior when replacing the fixture adapter. Real server pagination, campaign/recipient identifiers, permissions and publication/fulfillment events must be reconciled with the backend before enabling this in a live workspace.
