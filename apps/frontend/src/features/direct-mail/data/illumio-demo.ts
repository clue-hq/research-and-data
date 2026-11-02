import { MailerSchema, StateSchema, type CardAsset, type HandwritingStyle } from "../model/direct-mail";
import { DEMO_ID, DEMO_PROJECT_ID, DEMO_ACCOUNT_ID, DEMO_PROJECT_URL } from "../model/recording-demo-context";
import { advanceRecordingDemo, resetRecordingDemo } from "./recording-simulation";

const media = "/direct-mail/illumio-demo";
export const annMessage = {
  note: "Hi Ann,\n\nYou once described cyber as a new puzzle every day. Here’s one with no incident report attached.\n\nAs U.S. Bank moves more apps to AWS, let’s compare notes on keeping a breach from moving with them.",
  signature: "The Illumio team",
};
const handwriting: HandwritingStyle = { id: "style-illumio-handprint", name: "Card handwriting", version: 1, family: "Clue Handprint", sourceUrl: "/direct-mail/patrick-hand.ttf", productionReady: true };
const card: CardAsset = {
  id: "card-illumio-demo", name: "Illumio · A new puzzle", version: 3,
  frontUrl: `${media}/card-front-office-v3.png`, backUrl: null, paper: "cream",
  writingArea: { x: 7, y: 18, width: 84, height: 67 }, productionReady: true,
  branding: { name: "Illumio", logoUrl: `${media}/illumio-logo.svg`, markUrl: `${media}/illumio-mark.png`, line: "Stop breaches from spreading.", qrImageUrl: `${media}/illumio-qr.svg`, qrDestination: "https://www.illumio.com/illumio-platform" },
  messageArtworks: [{ ...annMessage, styleId: handwriting.id, url: `${media}/card-message-ann-puzzle.png` }],
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
      title: "A new puzzle every day",
      detail: "At a K–12 STEM symposium in 2014, Ann described the appeal of cybersecurity as working on new puzzles every day. This brass mechanical puzzle is a creative response to that public remark, not evidence of a private hobby. The business conversation remains U.S. Bank’s AWS migration and consistent breach containment across cloud and data-center applications.",
      source: "WashingtonExec · K–12 STEM symposium, 2014", sourceUrl: "https://washingtonexec.com/exec-profiles/open-possibilities-around-stem-google-homeland-security-leaders-encourage-students-k-12-stem-symposium", date: "2026-11-02",
      excerpt: "The most exciting thing for cybersecurity professionals in our field is getting to work on new puzzles every day.",
    },
    gifts: [
      { id: "craighill-jack-brass", name: "Craighill Jack Puzzle", variant: "Solid brass · Six interlocking pieces", merchant: "Craighill", priceCents: 9800, image: `${media}/jack-puzzle.jpg`, rationale: "A crafted brass puzzle inspired by Ann’s own description of cyber work: a new puzzle every day. Six precision-machined pieces make a memorable desk object, with a personal note connecting the idea to her words.", available: true, arrival: "In stock · Delivery date at checkout", recommended: true, productUrl: "https://craighill.co/products/jack-puzzle?variant=46559121309933", observedAt: "2026-11-02" },
      { id: "archimedes-gear", name: "Archimedes’ Gear", variant: "Interlocking magnetic pin puzzle", merchant: "Project Genius", priceCents: 2999, image: `${media}/archimedes-gear.jpg`, rationale: "A compact mechanical challenge at a lower price. Its hidden magnetic mechanism offers another way to bring Ann’s public puzzle-solving remark into the gift.", available: true, arrival: "In stock · Delivery date at checkout", recommended: false, productUrl: "https://projectgeniusinc.com/products/archimedes-gear?variant=44024825151684", observedAt: "2026-11-02" },
      { id: "museum-puzzles", name: "Museum Collection", variant: "30 wood and metal puzzles", merchant: "Project Genius", priceCents: 3499, image: `${media}/museum-collection.jpg`, rationale: "A collection that can be shared with the team, with several different challenges in one box. Choose it for a shared break rather than an individual desk piece.", available: true, arrival: "In stock · Delivery date at checkout", recommended: false, productUrl: "https://projectgeniusinc.com/products/museum-collection?variant=44024685985988", observedAt: "2026-11-02" },
    ],
    selectedGiftId: "craighill-jack-brass", ...annMessage, cardId: card.id, styleId: handwriting.id,
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

/** Refresh only the previous built-in front; keep edits and frozen approvals intact. */
export function parseIllumioDemo(value: unknown) {
  const state = StateSchema.parse(value);
  const previous = state.cards.find(c => c.id === card.id);
  if (previous?.version === 2 && previous.frontUrl === `${media}/illumio-hq.webp`) {
    previous.frontUrl = card.frontUrl;
    previous.version = card.version;
    delete previous.frontLayout;
    for (const mailer of state.mailers) {
      if (mailer.cardId === card.id && !mailer.approval && ["needs_review", "ready"].includes(mailer.stage)) {
        mailer.revision += 1;
        mailer.reviewedRevision = null;
        mailer.stage = "needs_review";
      }
    }
  }
  return state;
}

export const illumioSimulation = {
  advance: advanceRecordingDemo(DEMO_ID),
  reset: resetRecordingDemo(DEMO_ID, createIllumioMailer),
};
