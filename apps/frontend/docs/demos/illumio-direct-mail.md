# Illumio / U.S. Bank local recording demo

Isolated checkout and branch: `codex/illumio-usbank-demo`. The Harvey checkout and port 5001 are unchanged. This reuses the existing Direct Mail interface, domain validation and approval snapshot. It does not connect ordering, payments, delivery, publication or live agent execution.

## Start and demonstrate

From `apps/frontend`, run `npm run dev:preview -- --port 3000`.

- Queue: `http://localhost:3000/direct-mail?demo=illumio&project=prj_f9574afe6def584da9ff7ba3cd3f35d3`
- Review: `http://localhost:3000/direct-mail/mailer-illumio-usbank-ann`
- One account and one recipient, three real product options. Recommended gift: Craighill Jack Puzzle in brass, $98; estimated total $142. Other costs are illustrative, not checkout quotes.
- Review gift, card and note; acknowledge the public office address; review itemized costs; approve.
- The top-right ellipsis exposes explicitly labeled simulation steps, the deployed research link and reset. Advance through merchant order, inbound delivery, receipt, preparation, quality check, dispatch and delivery.
- Reset restores the original draft and refunds only this demo's net local credit debit. Revisions remain monotonic. Approval freezes the selected gift, note, card artwork and cost.
- Supplied ad and a saved capture of the actual deployed landing-page design open from Campaign materials. These are previews, not newly published assets. The original designs remain accessible through their Clue links.

## Sources and limits

Observed November 2, 2026. Account and recipient IDs are in `recording-demo-context.ts` and `illumio-demo.ts`. The existing Illumio project and researched U.S. Bank contact were read through the deployed app UI; no production data was changed.

- Role: [U.S. Bank interview with Ann Barron-DiCamillo](https://www.usbank.com/about-us-bank/news-and-stories/article-library/cybersecurity-awareness-month-insights-with-new-ciso-ann-barron-dicamillo.html).
- Gift connection: [WashingtonExec’s March 14, 2014 STEM symposium report](https://washingtonexec.com/exec-profiles/open-possibilities-around-stem-google-homeland-security-leaders-encourage-students-k-12-stem-symposium). Ann described the appeal of cybersecurity as new puzzles every day. The physical puzzle is a creative response to that historical professional remark; it is not a claimed personal hobby.
- Account context: [AWS / U.S. Bank transformation announcement](https://press.aboutamazon.com/aws/2026/5/u-s-bank-expands-collaboration-with-aws-to-accelerate-progressive-technology-transformation-and-ai-driven-customer-experience-innovation).
- Public office address: [U.S. Bancorp contact page](https://ir.usbank.com/resources/contact-us/default.aspx). This does not establish the recipient's office, permission to send, or gift-policy approval. The address is unconfirmed by default.
- Merchant product variants: [Craighill Jack Puzzle](https://craighill.co/products/jack-puzzle?variant=46559121309933) ($98), [Archimedes’ Gear](https://projectgeniusinc.com/products/archimedes-gear?variant=44024825151684) ($29.99), [Museum Collection](https://projectgeniusinc.com/products/museum-collection?variant=44024685985988) ($34.99). All available in the public merchant feeds on November 2, 2026. Each option uses an actual retailer image.
- The ad is the exact user-supplied `U.S. Bank 1 1 LinkedIn ad (1).png`, copied unchanged. The landing-page image is a capture of the deployed editor canvas, with application chrome removed.
- Brand wordmark and favicon are official Illumio assets; the account logo is from U.S. Bank. Asset URLs are recorded in `public/direct-mail/illumio-demo/asset-sources.json`.

## Card artwork

The front uses an unchanged official office photograph from [Illumio’s careers page](https://www.illumio.com/company/careers), framed with the cream border and footer proportions of the Harvey postcard. The optional `frontLayout: photograph` composes the original image in the card component without raster modification. Original wordmark and brand line are rendered separately. The updated back uses the built-in imagegen tool to match the original handwriting reference with the new puzzle message; it is not an editable font or a claim of exact pen reproduction. Logo and real QR remain separate overlays. Both the inline card and enlarged dialog share Front / Message controls and the same selected side.

The message image is bound to the exact note, signature and handwriting style. Text edits invalidate the image match and use the existing editable font preview, so a stale image cannot conceal edits.

QR destination: `https://www.illumio.com/illumio-platform`. The U.S. Bank landing-page draft is not published or bound to that QR. No route or publication was changed.

## Isolation and handoff

- Browser database: `clue-direct-mail-illumio-puzzle-demo`, isolated further by port 3000's origin. This revised concept starts as a fresh draft. The previous coffee scenario’s browser database is preserved, not deleted or silently re-approved.
- Fixture seed: `data/illumio-demo.ts`; recording context: `model/recording-demo-context.ts`.
- Shared fulfillment simulation: `data/recording-simulation.ts`, injected into the repository. Harvey regression tests retain the original simulation adapter and fixtures.
- Fail-closed preview runner clears backend URLs and workspace pins and binds to localhost. Production auth/runtime paths are unchanged.
- Other product modules retain their existing fixtures; this is a Direct Mail recording scenario, not a cloned live Illumio workspace.

## Verification

32 focused domain/repository/Harvey/Illumio tests passed. Design-system build and production build passed; lint returned zero errors and 11 pre-existing warnings outside the changed files. Browser verified exact ad, saved landing-page preview, card front/back, approval totals, every simulation stage, reload persistence and reset to draft. No order, send, publication or payment occurred.

## November 2 revision: artwork generation

Saved assets (under `apps/frontend/public/direct-mail/illumio-demo/`): `illumio-hq.webp` (original photograph), `card-message-ann-puzzle.png` (generated handwriting), `jack-puzzle.jpg`, `archimedes-gear.jpg`, `museum-collection.jpg` (original retailer images).

Mode: built-in imagegen edit, using `card-message-ann.png` as the handwriting and paper reference. Prompt:

> Preserve the 3:2 landscape format, warm cream paper texture, thin dark-brown pen lettering, natural irregularities and generous spacing. Replace all writing with the message below. Keep the upper 19% clear for a separately rendered logo; greeting around 24%; first paragraph around 36–44%; second paragraph around 57–65%; signature around 79%. Leave the bottom-right area clear for the QR. No generated logo, QR, decoration, border or computer font.

Exact message:

```text
Hi Ann,

You once described cyber as a new puzzle every day.
Here's one with no incident report attached.

As U.S. Bank moves more apps to AWS, let's compare
notes on keeping a breach from moving with them.

The Illumio team
```

Revision validation: 32 focused tests, design-system build and production build passed; lint has zero errors and 11 existing unrelated warnings. Browser verified the photographic front, both enlarged side controls, exact generated message and the queue’s updated $142 total. The source Harvey worktree is unchanged.
