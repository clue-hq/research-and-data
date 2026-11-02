# Illumio / U.S. Bank local recording demo

Isolated checkout and branch: `codex/illumio-usbank-demo`. The Harvey checkout and port 5001 are unchanged. This reuses the existing Direct Mail interface, domain validation and approval snapshot. It does not connect ordering, payments, delivery, publication or live agent execution.

## Start and demonstrate

From `apps/frontend`, run `npm run dev:preview -- --port 3000`.

- Queue: `http://localhost:3000/direct-mail?demo=illumio&project=prj_f9574afe6def584da9ff7ba3cd3f35d3`
- Review: `http://localhost:3000/direct-mail/mailer-illumio-usbank-ann`
- One account and one recipient, three real product options. Recommended gift: White 10 oz Ember Mug 2, $89.99; estimated total $133.99. Other costs are illustrative, not checkout quotes.
- Review gift, card and note; acknowledge the public office address; review itemized costs; approve.
- The top-right ellipsis exposes explicitly labeled simulation steps, the deployed research link and reset. Advance through merchant order, inbound delivery, receipt, preparation, quality check, dispatch and delivery.
- Reset restores the original draft and refunds only this demo's net local credit debit. Revisions remain monotonic. Approval freezes the selected gift, note, card artwork and cost.
- Supplied ad and a saved capture of the actual deployed landing-page design open from Campaign materials. These are previews, not newly published assets. The original designs remain accessible through their Clue links.

## Sources and limits

Observed November 2, 2026. Account and recipient IDs are in `recording-demo-context.ts` and `illumio-demo.ts`. The existing Illumio project and researched U.S. Bank contact were read through the deployed app UI; no production data was changed.

- Role: [U.S. Bank interview with Ann Barron-DiCamillo](https://www.usbank.com/about-us-bank/news-and-stories/article-library/cybersecurity-awareness-month-insights-with-new-ciso-ann-barron-dicamillo.html).
- Coffee preference: [American University public faculty profile](https://www.american.edu/kogod/faculty/barrondi.cfm). This is an older profile, used for its stated preference, not her current job title.
- Account context: [AWS / U.S. Bank transformation announcement](https://press.aboutamazon.com/aws/2026/5/u-s-bank-expands-collaboration-with-aws-to-accelerate-progressive-technology-transformation-and-ai-driven-customer-experience-innovation).
- Public office address: [U.S. Bancorp contact page](https://ir.usbank.com/resources/contact-us/default.aspx). This does not establish the recipient's office, permission to send, or gift-policy approval. The address is unconfirmed by default.
- Merchant product variants: Ember Mug 2 `30843977859157` ($89.99), Ember Cup Copper `42039411867833` ($77.97), Fellow Monty White Latte `18635552358515` ($29.95). Price/availability checked against the public merchant product feeds; each option links to its real variant.
- The ad is the exact user-supplied `U.S. Bank 1 1 LinkedIn ad (1).png`, copied unchanged. The landing-page image is a capture of the deployed editor canvas, with application chrome removed.
- Brand wordmark and favicon are official Illumio assets; the account logo is from U.S. Bank. Asset URLs are recorded in `public/direct-mail/illumio-demo/asset-sources.json`.

## Card artwork

The front is generated cream-paper artwork with orange geometric containment forms. Original Illumio wordmark and brand line are rendered separately. The back is a generated handwritten image inspired by the supplied physical handwritten card; it is not an editable handwriting font or a claim of exact pen reproduction. Logo and real QR are separate overlays.

The message image is bound to the exact note, signature and handwriting style. Text edits invalidate the image match and use the existing editable font preview, so a stale image cannot conceal edits.

QR destination: `https://www.illumio.com/illumio-platform`. The U.S. Bank landing-page draft is not published or bound to that QR. No route or publication was changed.

## Isolation and handoff

- Browser database: `clue-direct-mail-illumio-demo`, isolated further by port 3000's origin.
- Fixture seed: `data/illumio-demo.ts`; recording context: `model/recording-demo-context.ts`.
- Shared fulfillment simulation: `data/recording-simulation.ts`, injected into the repository. Harvey regression tests retain the original simulation adapter and fixtures.
- Fail-closed preview runner clears backend URLs and workspace pins and binds to localhost. Production auth/runtime paths are unchanged.
- Other product modules retain their existing fixtures; this is a Direct Mail recording scenario, not a cloned live Illumio workspace.

## Verification

32 focused domain/repository/Harvey/Illumio tests passed. Design-system build and production build passed; lint returned zero errors and 11 pre-existing warnings outside the changed files. Browser verified exact ad, saved landing-page preview, card front/back, approval totals, every simulation stage, reload persistence and reset to draft. No order, send, publication or payment occurred.
