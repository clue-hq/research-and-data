import { advanceRecordingDemo, resetRecordingDemo } from "./recording-simulation";
import { MailerSchema, StateSchema, estimate, type CardAsset, type HandwritingStyle, type DirectMailState } from "../model/direct-mail";

/** A sourced recording fixture. No backend, merchant or carrier writes are connected. */
import { HARVEY_DEMO_ID, HARVEY_PROJECT_ID, HARVEY_ACCOUNT_ID, HARVEY_PROJECT_URL, HARVEY_DELIVERED_ID, HARVEY_PINSENT_ID } from "../model/harvey-demo-context";
export { HARVEY_DEMO_ID } from "../model/harvey-demo-context";

const jasonMessage = {
  note: "Hi Jason,\n\nA small addition to your workshop. I saw that you enjoy woodworking and thought this might earn a place on the bench.\n\nCongrats on building Benesch’s innovation team. I’d love to compare notes on one legal workflow where Harvey could help, with your lawyers in control.",
  signature: "The Harvey team",
};
const hayleyMessage = {
  note: "Hi Hayley,\n\nA small desk companion for the ideas ahead. Congratulations on your knowledge and AI remit at Pinsent Masons.\n\nI’d welcome a working session on one firm-knowledge workflow, with your lawyers reviewing every answer.",
  signature: "Shank Keshri\nThe Harvey team",
};
const harveyCard: CardAsset = {
  id: "card-harvey-demo", name: "Harvey · Studio card", version: 3,
  frontUrl: "/direct-mail/harvey-demo/card-front.png", backUrl: null, paper: "cream",
  writingArea: { x: 9, y: 10, width: 82, height: 82 }, productionReady: true,
  branding: { name: "Harvey", logoUrl: "/direct-mail/harvey-demo/harvey-logo.svg", markUrl: "/direct-mail/harvey-demo/harvey-mark.png", line: "AI for legal work", qrImageUrl: "/direct-mail/harvey-demo/harvey-qr.svg", qrDestination: "https://www.harvey.ai/" },
  messageArtworks: [
    { ...jasonMessage, styleId: "style-harvey-handprint", url: "/direct-mail/harvey-demo/card-message-jason.png" },
    { ...hayleyMessage, styleId: "style-harvey-handprint", url: "/direct-mail/harvey-demo/card-message-hayley.png" },
  ],
};
// Generated artwork reproduces the supplied physical handwriting. This bundled font is
// only the text-edit fallback; matching artwork is checked against note + signature.
const harveyHandwriting: HandwritingStyle = {
  id: "style-harvey-handprint", name: "Card handwriting", version: 1,
  family: "Clue Handprint", sourceUrl: "/direct-mail/patrick-hand.ttf", productionReady: true,
};

export function createHarveyMailer() {
  return MailerSchema.parse({
    id: HARVEY_DEMO_ID, revision: 1, reviewedRevision: null,
    projectId: HARVEY_PROJECT_ID, projectName: "Harvey new logo acquisition",
    campaignId: "harvey-benesch-introduction", campaign: "Benesch · A builder’s introduction",
    threadId: "thr_2134514622d05eddb8d34bf58bc680dc",
    accountId: HARVEY_ACCOUNT_ID, contactId: "fca7b692-4454-4858-9a65-1dbf88c4bd57",
    recipient: { name: "Jason Dirkx", role: "Chief Innovation Officer", company: "Benesch", initials: "JD" },
    insight: {
      title: "A builder at work. A woodworker outside it.",
      detail: "The existing account research identifies Jason as Benesch’s new innovation leader and a potential champion for Harvey. His public Legaltech Hub biography mentions woodworking and DIY. A useful workshop tool gives the introduction a personal reason; the business conversation stays focused on one lawyer-reviewed workflow for his new team.",
      source: "Legaltech Hub · Jason Dirkx", sourceUrl: "https://www.legaltechnologyhub.com/experts/jason-dirkx/",
      date: "2026-11-01", excerpt: "Jason likes to spend time with his family and develop his woodworking and DIY skills.",
    },
    gifts: [
      { id: "woodpeckers-641", name: "Woodpeckers Precision Square", variant: "6 inch · Aluminum · Includes Rack-It", merchant: "Woodpeckers", priceCents: 8999, image: "/direct-mail/harvey-demo/precision-square.jpg", rationale: "A practical tool for his woodworking: checking corners, setting up tools and laying out the next project. A personal gift that does not assume a particular project or skill level.", available: true, arrival: "In stock · Delivery date at checkout", recommended: true, productUrl: "https://woodpeck.com/products/precision-woodworking-squares-aluminum?variant=43541846687803", observedAt: "2026-11-01" },
      { id: "woodpeckers-no94", name: "N°94 Dual Beam Scribe", variant: "Inch · Made to order", merchant: "Woodpeckers", priceCents: 9999, image: "/direct-mail/harvey-demo/dual-beam-scribe.jpg", rationale: "A more specialized option for laying out joinery. Two independent gauges help repeat precise marks. Choose this if a longer wait works for the campaign.", available: true, arrival: "Preorder · Merchant estimates November shipping", recommended: false, productUrl: "https://woodpeck.com/products/n-94-dual-beam-scribe?variant=44484751720507", observedAt: "2026-11-01" },
      { id: "woodpeckers-3d", name: "3D Multi-Marking Square", variant: "Inch · Machined aluminum", merchant: "Woodpeckers", priceCents: 6999, image: "/direct-mail/harvey-demo/multi-marking-square.jpg", rationale: "A smaller workshop companion for carrying layout lines around an edge and marking angles. Relevant to the same woodworking interest at a lower price.", available: true, arrival: "Merchant availability confirmed at checkout", recommended: false, productUrl: "https://woodpeck.com/products/3d-multi-marking-square?variant=43543744217147", observedAt: "2026-11-01" },
    ],
    selectedGiftId: "woodpeckers-641",
    ...jasonMessage, cardId: harveyCard.id, styleId: harveyHandwriting.id,
    address: { name: "Jason Dirkx", company: "Benesch", line1: "71 South Wacker Drive", line2: "Suite 1600", city: "Chicago", region: "IL", postalCode: "60606", country: "United States" },
    addressConfirmed: false, budgetCents: 15000,
    inboundCents: 800, preparationCents: 1500, outboundCents: 1200, taxCents: 900,
    stage: "needs_review", updatedAt: "2026-11-01T20:00:00Z", deliveryEstimate: "Shown after merchant confirmation",
    approval: null, priorApprovals: [], inbound: null, outbound: null, events: [], photos: [], exception: null, proposalRequest: null,
    sourceLabel: "Real account research and retailer products · Ordering, costs beyond the gift price, and delivery are simulated.",
    assets: [{ id: "harvey-benesch-landing-page", kind: "microsite", title: "Benesch landing page · Existing project", url: HARVEY_PROJECT_URL, status: "review", scope: "account", source: "Open the existing design conversation in the deployed app. This demo does not publish the page or connect it to the card’s homepage QR code." }],
  });
}

/** Additive migration: existing recording edits and all other campaigns survive. */
export function withHarveyDemo(input: DirectMailState): DirectMailState {
  const state = structuredClone(input);
  if (!state.mailers.some(m => m.id === HARVEY_DEMO_ID)) state.mailers.unshift(createHarveyMailer());
  const oldCard = state.cards.find(c => c.id === harveyCard.id);
  const replacePlaceholder = oldCard && oldCard.version < harveyCard.version && ["/direct-mail/harvey-demo/card.svg", harveyCard.frontUrl].includes(oldCard.frontUrl);
  if (!oldCard) state.cards.push(structuredClone(harveyCard));
  else if (replacePlaceholder) Object.assign(oldCard, structuredClone(harveyCard));
  if (!state.styles.some(s => s.id === harveyHandwriting.id)) state.styles.push(structuredClone(harveyHandwriting));
  // Explicit visual reset of the two local recording fixtures, including their simulated
  // approval previews. Never apply this to real approval history or other mailers.
  // Preserve text edits, selected products, prices, credits and fulfillment progress.
  for (const mailer of state.mailers.filter(m => [HARVEY_DEMO_ID, HARVEY_DELIVERED_ID].includes(m.id))) {
    if (replacePlaceholder && mailer.cardId === harveyCard.id && mailer.styleId === "style-warm") mailer.styleId = harveyHandwriting.id;
    const approval = mailer.approval;
    if (approval?.card.id === harveyCard.id && approval.card.version < harveyCard.version && ["/direct-mail/harvey-demo/card.svg", harveyCard.frontUrl].includes(approval.card.frontUrl)) {
      approval.card = structuredClone(harveyCard);
      if (["style-warm", harveyHandwriting.id].includes(approval.style.id)) approval.style = structuredClone(harveyHandwriting);
    }
  }
  if (!state.giftBudgets?.some(b => b.projectId === HARVEY_PROJECT_ID)) (state.giftBudgets ??= []).push({ projectId: HARVEY_PROJECT_ID, revision: 1, minimumCents: 7000, preferredCents: 10000, ceilingCents: 12000, locked: true });
  if (!state.mailers.some(m => m.id === HARVEY_DELIVERED_ID)) state.mailers.push(createDeliveredHarveyMailer(state));
  return StateSchema.parse(state);
}

export const advanceHarveyDemo = advanceRecordingDemo(HARVEY_DEMO_ID);
export const resetHarveyDemo = resetRecordingDemo(HARVEY_DEMO_ID, createHarveyMailer);

/** Historical simulation: materialized once, without debiting the active demo wallet. */
export function createDeliveredHarveyMailer(state: DirectMailState) {
  const base = createHarveyMailer();
  const gifts = [
    { id: "squire-emerald", color: "Emerald", variant: "44180182270035" },
    { id: "squire-slate", color: "Blue Slate", variant: "909578338329" },
    { id: "squire-black", color: "Blackout", variant: "18056190689363" },
  ].map((item, index) => ({ id: item.id, name: "Baronfig Squire Classic Pen", variant: `${item.color} · Rollerball`, merchant: "Baronfig", priceCents: 6500, image: `/direct-mail/harvey-demo/${item.id}.jpg`, rationale: "A considered desk tool for working sessions and capturing ideas. This is a professional-context suggestion, not a claim about a personal interest.", available: true, arrival: "Merchant availability confirmed before ordering", recommended: index === 0, productUrl: `https://baronfig.com/products/squire?variant=${item.variant}`, observedAt: "2026-11-01" }));
  const m = MailerSchema.parse({ ...base, id: HARVEY_DELIVERED_ID, revision: 9, reviewedRevision: null,
    campaignId: "harvey-pinsent-introduction", campaign: "Pinsent Masons · Knowledge into practice",
    accountId: HARVEY_PINSENT_ID, contactId: "demo-pinsent-hayley-harris",
    recipient: { name: "Hayley Harris", role: "Global Chief Knowledge & AI Adoption Officer", company: "Pinsent Masons", initials: "HH" },
    insight: { title: "Turning firm knowledge into everyday practice", detail: "Pinsent Masons appointed Hayley to lead its knowledge strategy and the selection and deployment of legal generative AI. The gift opens a working-session conversation about one knowledge workflow, alongside the firm’s existing tools. No personal hobby is inferred.", source: "Pinsent Masons · Appointment announcement", sourceUrl: "https://www.pinsentmasons.com/about-us/announcements/pinsent-masons-appoints-first-global-chief-knowledge-and-ai-adoption-officer", date: "2026-06-22", excerpt: "Hayley will be responsible for delivering the firm’s knowledge strategy and the selection and deployment of legal generative AI tools." },
    gifts, selectedGiftId: "squire-emerald",
    ...hayleyMessage,
    address: { name: "Hayley Harris", company: "Pinsent Masons", line1: "30 Crown Place", line2: "Earl Street", city: "London", region: "", postalCode: "EC2A 4ES", country: "United Kingdom" },
    addressConfirmed: true, inboundCents: 800, preparationCents: 1500, outboundCents: 3500, taxCents: 650, budgetCents: 15000,
    stage: "delivered", updatedAt: "2026-10-30T14:24:00Z", deliveryEstimate: "Delivered 30 Oct · Office reception",
    inbound: { carrier: "Merchant delivery · Demo", trackingNumber: "DEMO-PM-INBOUND", trackingUrl: null, expected: "27 Oct 2026", status: "Received at Clue · 27 Oct" },
    outbound: { carrier: "International delivery · Demo", trackingNumber: "DEMO-PM-OUTBOUND", trackingUrl: null, expected: "30 Oct 2026", status: "Delivered to office reception · 30 Oct" },
    events: [
      ["Approved for sending", "Gift, handwritten note and $129.50 estimate approved in this example.", "2026-10-23T16:00:00Z"],
      ["Gift ordered", "Selected Emerald Squire Classic Pen ordered to Clue in the simulated sequence.", "2026-10-23T16:20:00Z"],
      ["On its way to Clue", "Merchant shipment entered the inbound delivery stage.", "2026-10-24T12:00:00Z"],
      ["Received at Clue", "Example inspection: correct item and variant, no damage recorded.", "2026-10-27T15:00:00Z"],
      ["Card & package preparation", "Approved note prepared; gift and card placed together in the presentation box.", "2026-10-28T10:00:00Z"],
      ["Quality check complete", "Example check: product, card text, recipient and label match the approved mailer.", "2026-10-28T12:00:00Z"],
      ["Shipped to recipient", "Prepared package entered international delivery in the simulated sequence.", "2026-10-28T16:00:00Z"],
      ["Delivered to office", "Simulated delivery to office reception. No real shipment or personal receipt is asserted.", "2026-10-30T14:24:00Z"],
    ].map(([title, detail, at], i) => ({ id: `demo-pm-${i}`, title, detail, at, kind: "standard" })),
    photos: [], assets: [], sourceLabel: "Sourced account and real retailer product. This delivery and approval history are simulated; no physical package was sent.",
  });
  m.approval = { revision: 2, at: "2026-10-23T16:00:00Z", gift: structuredClone(gifts[0]), note: m.note, signature: m.signature, card: structuredClone(state.cards.find(c => c.id === m.cardId)!), style: structuredClone(state.styles.find(c => c.id === m.styleId)!), address: structuredClone(m.address), estimatedCents: estimate(m)!, budgetCents: m.budgetCents };
  return MailerSchema.parse(m);
}
