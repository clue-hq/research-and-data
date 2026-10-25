import { approveMailers, reviewMailer, StateSchema, type Gift, type Mailer, type Stage } from "../model/direct-mail";

/** Synthetic scenarios, not customer records, current retail offers or live research. */
export const demoGifts: Gift[] = [
  { id: "field-notebook", name: "Linen field notebook", variant: "A5 · Forest · Ruled", merchant: "Paper & Field", priceCents: 3200, image: "/direct-mail/notebook.svg", rationale: "A place to capture ideas from the field team’s next workshop.", available: true, arrival: "3–5 business days", recommended: true },
  { id: "coffee-set", name: "Pour-over coffee set", variant: "Ceramic · Sand · 2 pieces", merchant: "Everyday Objects", priceCents: 4800, image: "/direct-mail/coffee.svg", rationale: "A considered addition to the team’s weekly morning planning ritual.", available: true, arrival: "4–6 business days", recommended: false },
  { id: "travel-cup", name: "Insulated travel cup", variant: "12 oz · Slate", merchant: "Carry Supply", priceCents: 3800, image: "/direct-mail/cup.svg", rationale: "Useful between customer visits and time on the road.", available: true, arrival: "2–4 business days", recommended: false },
];

const people = [
  ["avery", "Avery Stone", "Northstar Systems", "VP of Marketing"],
  ["jordan", "Jordan Lee", "Harbor Labs", "Head of Growth"],
  ["priya", "Priya Shah", "Fieldwork", "Director of Marketing"],
  ["sam", "Sam Rivera", "Northstar Systems", "Head of Revenue"],
  ["morgan", "Morgan Ellis", "Linden Technologies", "VP of Growth"],
  ["casey", "Casey Chen", "Harbor Labs", "Marketing Lead"],
  ["taylor", "Taylor Brooks", "Fieldwork", "Director of Partnerships"],
  ["riley", "Riley Parker", "Linden Technologies", "Head of Marketing"],
] as const;

export function createDemoMailer(index: number): Mailer {
  const [key, name, company, role] = people[index % people.length];
  return {
    id: `mailer-${key}`, revision: 1, reviewedRevision: null,
    projectId: "10m-landing-page-campaign", projectName: "10x revenue campaign", campaign: "Fall account outreach", threadId: "thread-primary",
    recipient: { name, company, role, initials: name.split(" ").map((word) => word[0]).join("") },
    insight: { title: "Bringing the field team closer to customers", detail: `${name.split(" ")[0]} is bringing the field and marketing teams together for a customer-led planning workshop. The gift should be useful in that work, with a short note about turning observations into action.`, source: "Sample account research brief", date: "2026-10-20", excerpt: "The team is running small, in-person workshops to bring customer observations into next quarter’s campaign planning. This is synthetic research for the frontend example." },
    gifts: structuredClone(demoGifts), selectedGiftId: null,
    note: `Hi ${name.split(" ")[0]},\n\nA place for the ideas that come out of your next field-team workshop. Here’s to turning good conversations into something useful.`,
    signature: "Alex · Clue", cardId: "card-studio", styleId: "style-warm",
    address: { name, company, line1: "100 Example Avenue", line2: "Suite 200", city: "San Francisco", region: "CA", postalCode: "94107", country: "United States" },
    addressConfirmed: false, budgetCents: 10000, inboundCents: 800, preparationCents: 1500, outboundCents: 1200, taxCents: 500,
    stage: "needs_review", updatedAt: "2026-10-25T09:00:00Z", deliveryEstimate: "7–10 business days after approval",
    approval: null, priorApprovals: [], inbound: null, outbound: null, photos: [], events: [], exception: null, proposalRequest: null,
  };
}

export function createDirectMailFixture() {
  let state = StateSchema.parse({ schemaVersion: 1,
    cards: [
      { id: "card-studio", name: "Clue note", version: 1, frontUrl: "/direct-mail/card-clue.svg", backUrl: null, paper: "cream", writingArea: { x: 9, y: 12, width: 82, height: 78 }, productionReady: true },
      { id: "card-simple", name: "A simple thank you", version: 1, frontUrl: "/direct-mail/card-thanks.svg", backUrl: null, paper: "white", writingArea: { x: 10, y: 12, width: 80, height: 78 }, productionReady: true },
    ],
    styles: [
      { id: "style-warm", name: "Alex", version: 1, family: "Clue Handwritten", sourceUrl: "/direct-mail/caveat.ttf", productionReady: true },
      { id: "style-print", name: "Jamie", version: 1, family: "Clue Handprint", sourceUrl: "/direct-mail/patrick-hand.ttf", productionReady: true },
    ], mailers: people.map((_, index) => createDemoMailer(index)),
  });
  state.mailers[2].address.line1 = "";
  state.mailers[2].exception = { title: "Receiving address needed", detail: "Confirm an address where Priya can receive the package.", action: "address" };
  for (let index = 3; index < state.mailers.length; index++) {
    const mailer = state.mailers[index];
    mailer.selectedGiftId = demoGifts[index % 3].id;
    mailer.addressConfirmed = true;
    state = reviewMailer(state, mailer.id, mailer.revision);
    if (index === 3) continue;
    state = approveMailers(state, [{ id: mailer.id, revision: state.mailers[index].revision }]).state;
    const current = state.mailers[index];
    const stages: Stage[] = ["inbound", "quality_check", "shipped", "delivered"];
    current.stage = stages[index - 4];
    current.deliveryEstimate = index === 7 ? "Delivered Oct 24" : "Oct 28–30";
    current.inbound = { carrier: "Merchant delivery", trackingNumber: "DEMO-IN-1042", trackingUrl: null, expected: "Oct 23", status: index === 4 ? "In transit to Clue" : "Received at Clue" };
    current.events = [
      { id: "approved", title: "Mailer approved", detail: "Gift, card, note and spending limit confirmed.", at: "2026-10-20T16:00:00Z", kind: "standard" },
      { id: "ordered", title: "Gift ordered", detail: "Merchant confirmed the selected item and variant.", at: "2026-10-21T09:00:00Z", kind: "standard" },
      { id: "inbound", title: "On its way to Clue", detail: "The merchant shipment is heading to the Clue fulfillment center.", at: "2026-10-22T14:00:00Z", kind: "standard" },
    ];
    if (index > 4) current.events.push({ id: "received", title: "Received at Clue", detail: "Package received. Product and condition inspection is underway.", at: "2026-10-23T10:00:00Z", kind: "standard" });
    if (index > 5) {
      current.events.push({ id: "prepared", title: "Quality check complete", detail: "Gift inspected, handwritten card added and package prepared.", at: "2026-10-23T15:00:00Z", kind: "standard" });
      current.events.push({ id: "shipped", title: "Shipped to recipient", detail: "Package handed to the outbound carrier.", at: "2026-10-23T18:00:00Z", kind: "standard" });
      current.outbound = { carrier: "UPS", trackingNumber: "DEMO-OUT-2084", trackingUrl: null, expected: "Oct 28", status: index === 7 ? "Delivered" : "In transit" };
      current.photos = [{ id: "package", url: "/direct-mail/package.svg", caption: "Prepared package · sample image", at: "2026-10-23T15:00:00Z" }];
    }
    if (index === 7) current.events.push({ id: "delivered", title: "Delivered", detail: "Carrier confirmed delivery at the receiving address. Personal receipt is not yet confirmed.", at: "2026-10-24T13:00:00Z", kind: "standard" });
  }
  return StateSchema.parse(state);
}
