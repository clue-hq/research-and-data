# Harvey / Benesch recording walkthrough

Open http://localhost:5001/direct-mail/mailer-harvey-benesch-jason.

This is the existing Direct Mail V2 UI with one additive, local recording fixture. Harvey is the seller; Benesch is the researched target account. No production records were changed. Research was read from the deployed Harvey project and the selected buyer profile; only the relevant public context is represented locally. This is not a full workspace sync.

## Recording sequence

1. Start with Benesch research / Jason Dirkx in the deployed app. Use the existing Benesch landing-page conversation if showing the design part first.
2. Switch to the local mailer. Explain the woodworking insight, open its source, and review three real products. The 6-inch Woodpeckers Precision Square is selected at $89.99.
3. Continue to Card & note. The note is editable; the physical card preview uses the existing handwriting renderer. The sender and card are demo creative, not approved Harvey brand assets.
4. Review the public Chicago office address. Select the acknowledgment to use it only for the simulated shipment. This does not establish recipient acceptance or permission to send a real gift.
5. Review the $133.99 illustrative total: $89.99 gift + $8 inbound + $15 card/preparation + $12 outbound + $9 estimated tax. Only the gift is a sourced retailer price. The overall demo limit is $150; the gift-price ceiling is $120.
6. Approve and confirm. The browser records a local approval snapshot and deducts demo credits. No order or payment is sent.
7. Use the clearly labeled simulation button to advance through order confirmation, inbound shipment, receipt at Clue, preparation, quality check, dispatch and office delivery. No fabricated tracking links or inspection photos are supplied.
8. Reset demo → Reset recording restores the original mailer and returns its net demo credits. It clears this tab’s pending note draft. Other mailers are preserved.

## Evidence and product provenance

- Live profile: https://app.cluehq.ai/accounts/aae1f2fd-6762-4245-8617-7b1045ad3a7e/contacts/fca7b692-4454-4858-9a65-1dbf88c4bd57?projectId=prj_7f66ff82c4185f7789074d4555f3105e
- Current role: https://www.beneschlaw.com/people/jason-dirkx/
- Woodworking / DIY: https://www.legaltechnologyhub.com/experts/jason-dirkx/ (older employer information; use only the hobby evidence, not its old role).
- Office address: https://www.beneschlaw.com/locations/chicago/
- Product URLs, exact variants, image sources and observation date: `public/direct-mail/harvey-demo/sources.json`.

Retail prices and availability checked November 1, 2026. The square and multi-marking square were available; the $99.99 dual-beam scribe was a preorder with November shipping, explicitly shown in its card. A real order would need refreshed quotes, availability, recipient acceptance, and gift-policy checks.

## Isolation and handoff

The V2 provider adds the fixture through its existing browser repository seam. Data persists in the existing V2 IndexedDB record; repeated reads preserve edits. Replay operations are exposed only by the enabled V2 preview repository and accept only this scenario’s ID and current revision. V1 and the unavailable/live repository do not expose them.

Approval uses the existing gift/note/address/budget checks. The existing landing page is linked to the deployed design conversation as account-level context; it is not represented as a published recipient microsite or a working QR destination.

Validation: 27 focused tests; token build; lint (0 errors, 11 existing warnings); Next production build. Browser verification covered approval through all seven simulated fulfillment transitions, reset, unsaved-note reset, filtered queue, and reload persistence.
