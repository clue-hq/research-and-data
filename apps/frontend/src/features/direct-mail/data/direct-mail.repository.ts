import { z } from "zod";
import { approveMailers, CardAssetSchema, isDraft, requireMailer, reviewMailer, StateSchema, StyleSchema, updateMailer, type ApprovalItem, type ApprovalResult, type CardAsset, type DirectMailState, type HandwritingStyle, type MailerPatch } from "../model/direct-mail";
import type { DirectMailStore } from "./direct-mail.storage";
import { demoGifts } from "./direct-mail.fixture";

const CreateSchema = z.object({ projectId: z.string(), campaign: z.string().trim().min(1).max(100), recipientIds: z.array(z.string()).min(1), budgetCents: z.number().int().min(100).max(1_000_000), cardId: z.string(), styleId: z.string() });
export type CreateCampaign = z.infer<typeof CreateSchema>;
export interface DirectMailRepository {
  read(): Promise<DirectMailState>;
  patch(id: string, revision: number, patch: MailerPatch): Promise<DirectMailState>;
  review(id: string, revision: number): Promise<DirectMailState>;
  approve(items: ApprovalItem[]): Promise<{ state: DirectMailState; results: ApprovalResult[] }>;
  create(input: CreateCampaign): Promise<DirectMailState>;
  addCard(card: CardAsset): Promise<DirectMailState>;
  addStyle(style: HandwritingStyle): Promise<DirectMailState>;
  requestProposal(id: string, revision: number, kind: "gifts" | "insight", feedback: string): Promise<DirectMailState>;
  resolveProposal(id: string, revision: number, apply: boolean): Promise<DirectMailState>;
  cancel(id: string, revision: number): Promise<DirectMailState>;
  replace(id: string, revision: number): Promise<DirectMailState>;
  subscribe(listener: () => void): () => void;
}
const EVENT = "clue-direct-mail-change";
function notify() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(EVENT));
  if (typeof BroadcastChannel !== "undefined") { const channel = new BroadcastChannel(EVENT); channel.postMessage("changed"); channel.close(); }
}
function subscribe(listener: () => void) {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(EVENT, listener);
  const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(EVENT);
  if (channel) channel.onmessage = listener;
  return () => { window.removeEventListener(EVENT, listener); channel?.close(); };
}

export function createDirectMailRepository(store: DirectMailStore): DirectMailRepository {
  async function write(change: (state: DirectMailState) => DirectMailState) {
    const state = await store.transact((state) => { const next = StateSchema.parse(change(state)); return { state: next, result: next }; });
    notify(); return state;
  }
  return {
    read: () => store.read(), subscribe,
    patch: (id, revision, patch) => write((state) => updateMailer(state, id, revision, patch)),
    review: (id, revision) => write((state) => reviewMailer(state, id, revision)),
    async approve(items) { const result = await store.transact((state) => { const result = approveMailers(state, items); return { state: result.state, result }; }); notify(); return result; },
    create: (input) => write((state) => {
      const data = CreateSchema.parse(input);
      if (!state.cards.some((card) => card.id === data.cardId) || !state.styles.some((style) => style.id === data.styleId)) throw new Error("Choose an available card and handwriting style.");
      for (const contactId of new Set(data.recipientIds)) {
        if (state.mailers.some((m) => m.projectId === data.projectId && m.campaign.toLowerCase() === data.campaign.toLowerCase() && m.contactId === contactId)) continue;
        const source = state.mailers.find((m) => m.projectId === data.projectId && m.contactId === contactId);
        if (!source) throw new Error("Choose recipients belonging to this project.");
        state.mailers.push({ ...structuredClone(source), id: `mailer-${crypto.randomUUID()}`, revision: 1, reviewedRevision: null, campaign: data.campaign,
          budgetCents: data.budgetCents, cardId: data.cardId, styleId: data.styleId, gifts: structuredClone(demoGifts), selectedGiftId: null,
          stage: "needs_review", addressConfirmed: false, approval: null, priorApprovals: [], inbound: null, outbound: null, events: [], photos: [], exception: null, proposalRequest: null, updatedAt: new Date().toISOString() });
      }
      return state;
    }),
    addCard: (input) => write((state) => {
      const card = CardAssetSchema.parse(input);
      const previous = state.cards.find((item) => item.id === card.id);
      card.version = previous ? previous.version + 1 : 1;
      // Uploaded/modified production readiness cannot be asserted by a browser.
      card.productionReady = false;
      state.cards = [...state.cards.filter((item) => item.id !== card.id), card];
      for (const mailer of state.mailers) if (isDraft(mailer) && mailer.cardId === card.id) { mailer.revision++; mailer.reviewedRevision = null; mailer.stage = "needs_review"; }
      return state;
    }),
    addStyle: (input) => write((state) => { const style = StyleSchema.parse({ ...input, productionReady: false }); if (state.styles.some((item) => item.id === style.id)) throw new Error("This handwriting style already exists."); state.styles.push(style); return state; }),
    requestProposal: (id, revision, kind, feedback) => write((state) => {
      const mailer = requireMailer(state, id, revision);
      if (!isDraft(mailer)) throw new Error("Only drafts can request new recommendations.");
      mailer.proposalRequest = { kind, feedback: feedback.trim().slice(0, 1000), requestedAt: new Date().toISOString() };
      mailer.revision++; mailer.reviewedRevision = null; mailer.stage = "needs_review"; return state;
    }),
    resolveProposal: (id, revision, apply) => write((state) => {
      const mailer = requireMailer(state, id, revision);
      if (!isDraft(mailer) || !mailer.proposalRequest) throw new Error("No recommendation request is pending.");
      if (apply) {
        if (mailer.proposalRequest.kind === "insight") mailer.insight = { ...mailer.insight, title: "Making space for thoughtful planning", detail: "The team is setting aside focused time to turn customer observations into practical next steps.", excerpt: "Alternate synthetic insight: the next planning session will focus on fewer, more considered account campaigns." };
        mailer.gifts = structuredClone(demoGifts).map((gift, index) => ({ ...gift, id: `${gift.id}-${revision}`, name: ["Pocket planning journal", "Morning coffee ritual set", "Everyday travel cup"][index], variant: ["A6 · Charcoal · Dot grid", "Ceramic · White · 2 pieces", "12 oz · Cream"][index], priceCents: [2400, 4200, 3400][index] }));
        mailer.selectedGiftId = null;
      }
      mailer.proposalRequest = null; mailer.revision++; mailer.reviewedRevision = null; mailer.stage = "needs_review"; return state;
    }),
    cancel: (id, revision) => write((state) => { const mailer = requireMailer(state, id, revision); if (mailer.stage !== "approved") throw new Error("This mailer cannot be canceled at its current stage."); mailer.stage = "canceled"; mailer.revision++; mailer.events.push({ id: `cancel-${revision}`, title: "Mailer canceled", detail: "Canceled before a merchant order was confirmed.", at: new Date().toISOString(), kind: "standard" }); return state; }),
    replace: (id, revision) => write((state) => { const mailer = requireMailer(state, id, revision); if (mailer.exception?.action !== "replacement") throw new Error("No replacement is requested for this mailer."); if (mailer.approval) mailer.priorApprovals.push(mailer.approval); mailer.approval = null; mailer.selectedGiftId = null; mailer.reviewedRevision = null; mailer.stage = "needs_review"; mailer.exception = null; mailer.revision++; return state; }),
  };
}
const unavailable = async (): Promise<never> => { throw new Error("Direct Mail is not connected to this workspace yet."); };
export const unavailableDirectMailRepository: DirectMailRepository = { read: unavailable, patch: unavailable, review: unavailable, approve: unavailable, create: unavailable, addCard: unavailable, addStyle: unavailable, requestProposal: unavailable, resolveProposal: unavailable, cancel: unavailable, replace: unavailable, subscribe: () => () => {} };
