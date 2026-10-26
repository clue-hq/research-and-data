# Connected account experience V2

Status: working local frontend preview, not a backend integration or deployment.

## Run and compare

V1 remains on `feat/direct-mail-infrastructure-ui`, in the original
`direct-mail-infrastructure-ui/clue-main-pull-oct24` worktree, on port 5000.
V2 is `feat/direct-mail-infrastructure-v2`, in the separate
`direct-mail-v2/clue-main-pull-oct24` worktree, on port 5001.

From V2's `apps/frontend` directory:

```sh
npm run dev:preview -- --port 5001
```

The existing preview launcher clears backend configuration, restricts its origin
to loopback, and enables explicit fixture mode. No new environment flag was added.
V2 has separate dependencies, browser origin and IndexedDB names. There are no
production orders, emails, publishes, CRM writes or model calls in this flow.
No private corpus, credentials or pilot contact records are copied into V2.

## Walkthrough

1. `/projects/10m-landing-page-campaign/chats/thread-primary` opens the prepared
   conversational brief. The chips and composer return clearly identified local
   example responses; they do not run a live agent.
2. **Account plan** connects six fictional accounts. Four have mailers; Meridian
   and Atlas Cloud start with email. Open an account for evidence, buying team,
   ownership, selected approach and all related creative.
3. **Northstar / Avery** starts with three gifts, card and note selection, a
   confirmed sample address, and a $98 itemized estimate. Review and approve to
   enter tracking. Approval does not manufacture order or carrier events.
4. **Fieldwork / Priya** demonstrates a receiving-address hold. **Harbor / Casey**
   shows fulfillment preparation. **Linden / Riley** shows carrier delivery and
   a separate human reply. Shipment status and personal receipt remain distinct.
5. **Artifacts** and project **Gallery** display the same records. Pages, ads,
   emails and notes link back to the account. Email and note previews read their
   owning records. A page preview is not published; no public URL or QR assignment
   is invented. Ads are creative previews with sample audience eligibility.
6. **Email** lets a user edit recipient copy, choose a sender and trigger, review
   the rendered message, and save a local approval. Edits invalidate approval.
   A human reply stops the sequence; marking it handled does not resume sending.
7. **Results / Analytics** reads recorded distinct-account outcomes and approved
   gift estimates. It does not infer a meeting from delivery or revenue from a gift.

## Object ownership

Project = the overall account motion; campaign = a channel program inside it.
The account plan exists independently of any mailer. Maya is the project and
campaign owner in these examples. Alex and Jamie own account relationships;
the sender on each outgoing item is explicit and can differ from account owner.
Territory is assignment context, not an implemented automatic routing engine.
Reassigning an account preserves existing approved sender/content snapshots.

`features/orchestration/model/workspace.ts` defines the Zod records and immutable
revision-checked email/ownership operations. `data/workspace.fixture.ts` owns
fictional people, accounts, channel programs, assets, email and outcomes.
`data/workspace.repository.ts` is the presentation-facing seam; components never
fetch backend payloads. `hooks/use-workspace.ts` handles subscription, pending
and error state. IndexedDB transactions prevent stale multi-tab writes.

The existing Direct Mail domain remains responsible for gift changes, review,
cost approval, card assets and tracking. `data/mail.fixture.ts` composes a V2 seed
joined by canonical account/contact/mailer IDs. `createBrowserRecordStore` is
the shared atomic fixture persistence helper. V2 stores are
`clue-orchestration-preview-v2` and `clue-direct-mail-preview-v2`.

## Backend handoff for Aryan

Replace the repository adapters and seed composition at the protected-layout
boundary after an explicit contract review. Keep revision conflicts and approved
snapshots enforceable on the server; IndexedDB is only a preview adapter.
The models are frontend proposals, not assertions about backend schema.

Required live services include account-plan projections, actual evidence/claim
references, authorized owner/sender identities, recipient email approvals and
provider events, creative version/publication records, QR routing, gift ordering,
fulfillment events, cost settlement and CRM/calendar outcome events. Link these
through shared IDs; avoid copying record bodies between surfaces.

Email infrastructure remains a separate implementation effort. This version
demonstrates the shared customer journey and does not replace that branch's
mailbox integration. The original live-mode project and artifact routes retain
their existing behavior when explicit preview mode is off.

## Deliberate limits

- One prepared project and six fictional accounts; other existing app routes keep
  their original fixture behavior.
- Page/ad previews are inspectable concepts. Full editing, publication, media
  budgets and campaign activation are not implemented in this slice.
- No automatic territory assignment, live agent reasoning, mailbox sending,
  reply composition, payment processing or fulfillment simulation.
- A search budget sets a preferred gift range and ceiling without reserving funds.
  Final gift approval uses the existing demo-credit estimate mechanism.

Reference: [approved product research](../research/abm-orchestration.md).

## Verification

The completed slice passed token generation, the production build, 3,675 tests
(with 5 inherited skips), and lint (zero errors, 11 inherited warnings). A fresh
review found stale email-dialog revisions and hardcoded reply ownership; both
were reproduced in failing tests and fixed. Canonical artifact revisions also
have regression coverage. Browser QA covered the connected customer journey at
1159×899; no mobile-device verification is claimed.

The current browser retains QA example edits: Avery is approved and awaiting
merchant confirmation, Drew's edited message has a local approval, and Northstar
is assigned to Jamie while Alex remains its prepared sender. New browser storage
starts from the original six-account fixture.
