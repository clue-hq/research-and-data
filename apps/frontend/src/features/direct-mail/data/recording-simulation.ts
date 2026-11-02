import { StateSchema, requireMailer, type DirectMailState, type Mailer, type Stage } from "../model/direct-mail";

/** Fixture-only fulfillment shared by isolated recording contexts. Never calls a merchant or carrier. */
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

export const advanceRecordingDemo = (demoId: string) => (input: DirectMailState, id: string, revision: number): DirectMailState => {
  if (id !== demoId) throw new Error("Simulation is limited to the recording demo.");
  const state = structuredClone(input), m = requireMailer(state, id, revision);
  if (!m.approval || !sequence.includes(m.stage)) throw new Error("Complete gift, note and cost approval before simulating fulfillment.");
  const index = sequence.indexOf(m.stage), stage = sequence[index + 1];
  if (!stage) throw new Error("The demo delivery is complete. Reset to record another take.");
  const at = new Date().toISOString(), [title, detail] = eventText[stage]!;
  m.stage = stage; m.revision++; m.updatedAt = at;
  m.events.push({ id: `${demoId}-${m.revision}`, title, detail, at, kind: "standard" });
  m.deliveryEstimate = stage === "delivered" ? "Delivered · Simulated" : "Demo timeline · No live delivery estimate";
  if (index >= 1) m.inbound = { carrier: "Merchant shipment · Simulation", trackingNumber: "DEMO-INBOUND", trackingUrl: null, expected: "Demo timeline", status: index >= 2 ? "Received at Clue" : "In transit to Clue" };
  if (index >= 5) m.outbound = { carrier: "Recipient shipment · Simulation", trackingNumber: "DEMO-OUTBOUND", trackingUrl: null, expected: "Demo timeline", status: stage === "delivered" ? "Delivered to office" : "In transit" };
  return StateSchema.parse(state);
}

export const resetRecordingDemo = (demoId: string, createMailer: () => Mailer) => (input: DirectMailState, id: string, revision: number): DirectMailState => {
  if (id !== demoId) throw new Error("Reset is limited to the recording demo.");
  const state = structuredClone(input), old = requireMailer(state, id, revision);
  // Reverse only this record's net demo debit, including any prior cancel refund.
  const net = (state.creditEntries ?? []).filter(e => e.mailerId === id).reduce((sum, e) => sum + e.amountCents, 0);
  if (net < 0) {
    state.creditBalanceCents = (state.creditBalanceCents ?? 200000) - net;
    (state.creditEntries ??= []).push({ id: `demo-reset-${revision}`, kind: "refund", amountCents: -net, mailerId: id, at: new Date().toISOString(), description: "Recording reset · Demo credits restored" });
  }
  state.mailers = state.mailers.map(m => m.id === id ? { ...createMailer(), revision: old.revision + 1 } : m);
  return StateSchema.parse(state);
}

