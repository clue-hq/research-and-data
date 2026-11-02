import { MailerSchema, StateSchema, type CardAsset, type HandwritingStyle } from "../model/direct-mail";
import { DEMO_ID, DEMO_PROJECT_ID, DEMO_ACCOUNT_ID, DEMO_PROJECT_URL } from "../model/recording-demo-context";
import { advanceRecordingDemo, resetRecordingDemo } from "./recording-simulation";

const media = "/direct-mail/illumio-demo";
export const annMessage = {
  note: "Hi Ann,\n\nFor your next latte, kept warm a little longer.\n\nAs U.S. Bank moves more apps to AWS, we would welcome a conversation about keeping a breach from moving with them.",
  signature: "The Illumio team",
};
const handwriting: HandwritingStyle = { id: "style-illumio-handprint", name: "Card handwriting", version: 1, family: "Clue Handprint", sourceUrl: "/direct-mail/patrick-hand.ttf", productionReady: true };
const card: CardAsset = {
  id: "card-illumio-demo", name: "Illumio · Breach containment", version: 1,
  frontUrl: `${media}/card-front.png`, backUrl: null, paper: "cream",
  writingArea: { x: 7, y: 18, width: 84, height: 67 }, productionReady: true,
  branding: { name: "Illumio", logoUrl: `${media}/illumio-logo.svg`, markUrl: `${media}/illumio-mark.png`, line: "Stop breaches from spreading.", qrImageUrl: `${media}/illumio-qr.svg`, qrDestination: "https://www.illumio.com/illumio-platform" },
  messageArtworks: [{ ...annMessage, styleId: handwriting.id, url: `${media}/card-message-ann.png` }],
};

/** Publicly sourced research and retail products; approval and fulfillment remain local. */
export function createIllumioMailer() {
  return MailerSchema.parse({
    id: DEMO_ID, revision: 1, reviewedRevision: null,
    projectId: DEMO_PROJECT_ID, projectName: "Illumio platform marketing",
    campaignId: "illumio-usbank-introduction", campaign: "U.S. Bank · A personal introduction",
    threadId: "thr_a84254ae478e5e38b63b743c31fd89fb",
    accountId: DEMO_ACCOUNT_ID, contactId: "4f99acfb-d6ef-4909-a9c0-2fcf5f3106be",
    recipient: { name: "Ann Barron-DiCamillo", role: "EVP & Global Chief Information Security Officer", company: "U.S. Bank", initials: "AB" },
    insight: {
      title: "A latte, and a conversation about containing the next breach",
      detail: "Ann’s public American University profile mentions her preference for a latte. The completed U.S. Bank research identifies her as the global CISO. The business conversation follows U.S. Bank’s AWS migration: keep containment consistent as applications move, with core systems still in the data center. The coffee preference informs the gift, not the account’s buying intent.",
      source: "American University · Ann Barron-DiCamillo", sourceUrl: "https://www.american.edu/kogod/faculty/barrondi.cfm", date: "2026-11-02",
      excerpt: "Favorite Spot on Campus: Wherever I can get an Latte!!",
    },
    gifts: [
      { id: "ember-mug-white", name: "Ember Mug 2", variant: "White · 10 oz · Charging coaster included", merchant: "Ember", priceCents: 8999, image: `${media}/ember-mug.jpg`, rationale: "Keeps her next latte at a chosen temperature. A useful everyday gift grounded in her publicly stated coffee preference, with room in the budget for the personal card and preparation.", available: true, arrival: "In stock · Delivery date at checkout", recommended: true, productUrl: "https://ember.com/products/ember-mug-2?variant=30843977859157", observedAt: "2026-11-02" },
      { id: "ember-cup-copper", name: "Ember Cup", variant: "Copper Edition · 6 oz", merchant: "Ember", priceCents: 7797, image: `${media}/ember-cup.jpg`, rationale: "A smaller temperature-controlled cup for espresso-based drinks. Choose this for a compact desk companion; its 6 oz capacity is smaller than the recommended mug.", available: true, arrival: "In stock · Delivery date at checkout", recommended: false, productUrl: "https://ember.com/products/ember-cup?variant=42039411867833", observedAt: "2026-11-02" },
      { id: "fellow-monty-white", name: "Fellow Monty Milk Art Cup", variant: "Matte White · Latte · 11 oz", merchant: "Fellow", priceCents: 2995, image: `${media}/fellow-monty.png`, rationale: "A double-wall ceramic latte cup at a lower price. A simple alternative with no battery, charging or app, while staying relevant to the same public coffee preference.", available: true, arrival: "In stock · Delivery date at checkout", recommended: false, productUrl: "https://fellowproducts.com/products/monty-milk-art-cups?variant=18635552358515", observedAt: "2026-11-02" },
    ],
    selectedGiftId: "ember-mug-white", ...annMessage, cardId: card.id, styleId: handwriting.id,
    address: { name: "Ann Barron-DiCamillo", company: "U.S. Bank", line1: "800 Nicollet Mall", line2: "", city: "Minneapolis", region: "MN", postalCode: "55402", country: "United States" },
    addressConfirmed: false, budgetCents: 15000, inboundCents: 800, preparationCents: 1500, outboundCents: 1200, taxCents: 900,
    stage: "needs_review", updatedAt: "2026-11-02T08:00:00Z", deliveryEstimate: "Shown after merchant confirmation",
    approval: null, priorApprovals: [], inbound: null, outbound: null, events: [], photos: [], exception: null, proposalRequest: null,
    sourceLabel: "Real account research and retailer products · Ordering, costs beyond the gift price, and delivery are simulated.",
    assets: [{ id: "illumio-usbank-landing-page", kind: "microsite", title: "U.S. Bank · Existing landing page", url: DEMO_PROJECT_URL, status: "review", scope: "account", source: "Saved design preview from the deployed project. The card’s QR opens the public Illumio Platform page; the draft account page has not been published or routed to this QR." }],
  });
}

export function createIllumioDemo() {
  return StateSchema.parse({ schemaVersion: 1, cards: [card], styles: [handwriting], mailers: [createIllumioMailer()], creditBalanceCents: 200000, creditEntries: [],
    giftBudgets: [{ projectId: DEMO_PROJECT_ID, revision: 1, minimumCents: 2500, preferredCents: 10000, ceilingCents: 12000, locked: true }],
  });
}

export const illumioSimulation = {
  advance: advanceRecordingDemo(DEMO_ID),
  reset: resetRecordingDemo(DEMO_ID, createIllumioMailer),
};
