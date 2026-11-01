import { MailerSchema, StateSchema, requireMailer, type DirectMailState, type Stage } from "../model/direct-mail";

/** A sourced recording fixture. No backend, merchant or carrier writes are connected. */
import { HARVEY_DEMO_ID, HARVEY_PROJECT_ID, HARVEY_ACCOUNT_ID, HARVEY_PROJECT_URL } from "../model/harvey-demo-context";
export { HARVEY_DEMO_ID } from "../model/harvey-demo-context";

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
    note: "Hi Jason,\n\nA small addition to your workshop. I saw that you enjoy woodworking and thought this might earn a place on the bench.\n\nCongrats on building Benesch’s innovation team. I’d love to compare notes on one legal workflow where Harvey could help, with your lawyers in control.",
    signature: "The Harvey team", cardId: "card-harvey-demo", styleId: "style-warm",
    address: { name: "Jason Dirkx", company: "Benesch", line1: "71 South Wacker Drive", line2: "Suite 1600", city: "Chicago", region: "IL", postalCode: "60606", country: "United States" },
    addressConfirmed: false, budgetCents: 15000,
    inboundCents: 800, preparationCents: 1500, outboundCents: 1200, taxCents: 900,
    stage: "needs_review", updatedAt: "2026-11-01T20:00:00Z", deliveryEstimate: "Shown after merchant confirmation",
    approval: null, priorApprovals: [], inbound: null, outbound: null, events: [], photos: [], exception: null, proposalRequest: null,
    sourceLabel: "Real account research and retailer products · Ordering, costs beyond the gift price, and delivery are simulated.",
    assets: [{ id: "harvey-benesch-landing-page", kind: "microsite", title: "Benesch landing page · Existing project", url: HARVEY_PROJECT_URL, status: "review", scope: "account", source: "Open the existing design conversation in the deployed app. This demo does not publish or attach a QR code." }],
  });
}

/** Additive migration: existing recording edits and all other campaigns survive. */
export function withHarveyDemo(input: DirectMailState): DirectMailState {
  const state = structuredClone(input);
  if (!state.mailers.some(m => m.id === HARVEY_DEMO_ID)) state.mailers.unshift(createHarveyMailer());
  if (!state.cards.some(c => c.id === "card-harvey-demo")) state.cards.push({ id: "card-harvey-demo", name: "Harvey · Personal note", version: 1, frontUrl: "/direct-mail/harvey-demo/card.svg", backUrl: null, paper: "white", writingArea: { x: 9, y: 10, width: 82, height: 82 }, productionReady: true });
  if (!state.giftBudgets?.some(b => b.projectId === HARVEY_PROJECT_ID)) (state.giftBudgets ??= []).push({ projectId: HARVEY_PROJECT_ID, revision: 1, minimumCents: 7000, preferredCents: 10000, ceilingCents: 12000, locked: true });
  return StateSchema.parse(state);
}

const sequence: Stage[] = ["approved", "ordered", "inbound", "received", "preparing", "ready_to_ship", "shipped", "delivered"];

const eventText: Partial<Record<Stage, [string, string]>> = {
  ordered: ["Gift ordered", "Simulated merchant confirmation for the approved product and variant. No purchase was made."],
  inbound: ["On its way to Clue", "Simulated inbound shipment to Clue for inspection and preparation."],
  received: ["Received at Clue", "Simulated receipt at the fulfillment center; inspection begins."],
  preparing: ["Card & package preparation", "Simulated product inspection, handwritten card and repackaging."],
  ready_to_ship: ["Quality check complete", "Simulated final inspection passed. Package ready for carrier collection."],
  shipped: ["Shipped to recipient", "Simulated carrier handoff. No real shipment or tracking number exists."],
  delivered: ["Delivered to office", "Simulated delivery at the office address. Personal receipt is not confirmed."],
};

export function advanceHarveyDemo(input: DirectMailState, id: string, revision: number): DirectMailState {
  if (id !== HARVEY_DEMO_ID) throw new Error("Simulation is limited to the recording demo.");
  const state = structuredClone(input), m = requireMailer(state, id, revision);
  if (!m.approval || !sequence.includes(m.stage)) throw new Error("Complete gift, note and cost approval before simulating fulfillment.");
  const index = sequence.indexOf(m.stage), stage = sequence[index + 1];
  if (!stage) throw new Error("The demo delivery is complete. Reset to record another take.");
  const at = new Date().toISOString(), [title, detail] = eventText[stage]!;
  m.stage = stage; m.revision++; m.updatedAt = at;
  m.events.push({ id: `harvey-demo-${m.revision}`, title, detail, at, kind: "standard" });
  m.deliveryEstimate = stage === "delivered" ? "Delivered · Simulated" : "Demo timeline · No live delivery estimate";
  if (index >= 1) m.inbound = { carrier: "Merchant shipment · Simulation", trackingNumber: "DEMO-INBOUND", trackingUrl: null, expected: "Demo timeline", status: index >= 2 ? "Received at Clue" : "In transit to Clue" };
  if (index >= 5) m.outbound = { carrier: "Recipient shipment · Simulation", trackingNumber: "DEMO-OUTBOUND", trackingUrl: null, expected: "Demo timeline", status: stage === "delivered" ? "Delivered to office" : "In transit" };
  return StateSchema.parse(state);
}

export function resetHarveyDemo(input: DirectMailState, id: string, revision: number): DirectMailState {
  if (id !== HARVEY_DEMO_ID) throw new Error("Reset is limited to the recording demo.");
  const state = structuredClone(input), old = requireMailer(state, id, revision);
  // Reverse only this record's net demo debit, including any prior cancel refund.
  const net = (state.creditEntries ?? []).filter(e => e.mailerId === id).reduce((sum, e) => sum + e.amountCents, 0);
  if (net < 0) {
    state.creditBalanceCents = (state.creditBalanceCents ?? 200000) - net;
    (state.creditEntries ??= []).push({ id: `demo-reset-${revision}`, kind: "refund", amountCents: -net, mailerId: id, at: new Date().toISOString(), description: "Recording reset · Demo credits restored" });
  }
  state.mailers = state.mailers.map(m => m.id === id ? { ...createHarveyMailer(), revision: old.revision + 1 } : m);
  return StateSchema.parse(state);
}
