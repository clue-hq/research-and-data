# Harvey / Benesch recording walkthrough

Open http://localhost:5001/direct-mail/mailer-harvey-benesch-jason.

This is the existing Direct Mail V2 UI with additive local recording fixtures. Harvey is the seller; Benesch is the researched target account, and Pinsent Masons supplies a separate completed-delivery example. No production records were changed. Research was read from the deployed Harvey project and the selected buyer profile; only the relevant public context is represented locally. This is not a full workspace sync.

## Recording sequence

1. Start with Benesch research / Jason Dirkx in the deployed app. Use the existing Benesch landing-page conversation if showing the design part first.
2. Switch to the local mailer. Explain the woodworking insight, open its source, and review three real products. The 6-inch Woodpeckers Precision Square is selected at $89.99.
3. Continue to Card & note. The default recipient messages use generated lettering images based on the supplied physical handwriting. Edits switch to a text preview until new artwork is generated. The card uses original Harvey brand assets, an adapted official office photograph, and a homepage QR; the composition is local demo creative, not an approved Harvey print design. See `harvey-card-artwork.md` for prompts and provenance.
4. Review the public Chicago office address. Select the acknowledgment to use it only for the simulated shipment. This does not establish recipient acceptance or permission to send a real gift.
5. Review the $133.99 illustrative total: $89.99 gift + $8 inbound + $15 card/preparation + $12 outbound + $9 estimated tax. Only the gift is a sourced retailer price. The overall demo limit is $150; the gift-price ceiling is $120.
6. Approve and confirm. The browser records a local approval snapshot and deducts demo credits. No order or payment is sent.
7. Open the header’s ⋯ recording-controls menu and use the clearly labeled simulation action to advance through order confirmation, inbound shipment, receipt at Clue, preparation, quality check, dispatch and office delivery. No fabricated tracking links or inspection photos are supplied.
8. ⋯ → Reset demo → Reset recording restores the original mailer and returns its net demo credits. It clears this tab’s pending note draft. Other mailers are preserved.

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

## Recording overview and completed example

`/direct-mail` now opens the Harvey queue by default. Existing scenarios remain in the project filter; the earlier 500-account walkthrough is at `/direct-mail?demo=walkthrough`.

- The local shell uses **Shank Keshri / Harvey workspace**, with the original Harvey logo. This is a preview identity, not a new membership or a production profile change.
- The queue shows real account logos, each recipient’s selected gift and note, separate account-level landing-page/ad previews, delivery stage and approved estimate.
- Four previews were captured from the actual deployed project: Benesch and Pinsent Masons pages and LinkedIn ads. These are read-only visual captures, not locally editable or published copies. Landing-page captures show the opening viewport; “Open original in Clue” returns to the existing design conversation for the complete page.
- `/direct-mail/mailer-harvey-pinsent-hayley` is a **simulated historical delivery**. It uses a genuine $65 Baronfig Squire Classic Pen (Emerald), a drafted approved card snapshot, and the public London office address. $129.50 illustrative estimate: $65 product + $8 inbound + $15 preparation + $35 outbound + $6.50 tax. The seeded history neither spends nor changes the current demo wallet.
- The professional context is sourced from the firm’s [appointment announcement](https://www.pinsentmasons.com/about-us/announcements/pinsent-masons-appoints-first-global-chief-knowledge-and-ai-adoption-officer); the address from its [London office page](https://www.pinsentmasons.com/locations/europe/united-kingdom/london). The suggestion does not imply a personal hobby, acceptance of a gift or a real delivery.
- The same cost-breakdown component now appears during review, approval (including summed bulk costs) and tracking. Unknown costs remain “Not quoted”.

Validation for the overview polish: 28 Direct Mail tests plus 6 preview tests; design-system build; lint with 0 errors and 11 pre-existing warnings; Next production build; browser checks for queue filtering, saved ad previews, delivery details, and local workspace identity.
