import { updateOutreachPage, reviewOutreachPage, invalidatePageReview, type PagePatch } from "../model/outreach-page";
import { z } from "zod";
import { approveMailers, CardAssetSchema, isDraft, requireMailer, reviewMailer, StateSchema, StyleSchema, updateMailer, type ApprovalItem, type ApprovalResult, type CardAsset, type DirectMailState, type HandwritingStyle, type Mailer, type MailerPatch } from "../model/direct-mail";
import type { DirectMailStore } from "./direct-mail.storage";
import { demoGifts } from "./direct-mail.fixture";
import { GiftBudgetSchema, NoteTemplateSchema, type GiftBudget, type NoteTemplate } from "../model/direct-mail-context";
import { advanceHarveyDemo, resetHarveyDemo } from "./harvey-demo";
import { writePendingDraft } from "./direct-mail.drafts";

const CreateSchema = z.object({ projectId: z.string(), campaign: z.string().trim().min(1).max(100), recipientIds: z.array(z.string()).min(1), budgetCents: z.number().int().min(100).max(1_000_000), cardId: z.string(), styleId: z.string() });
export type CreateCampaign = z.infer<typeof CreateSchema>;
export interface DirectMailRepository {
  read(): Promise<DirectMailState>;
  patchPage(id:string, version:number, patch:PagePatch):Promise<DirectMailState>;
  invalidatePage(id:string, version:number):Promise<DirectMailState>;
  reviewPage(id:string, version:number):Promise<DirectMailState>;
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
  saveBudget(input: GiftBudget, expectedRevision: number): Promise<DirectMailState>;
  saveTemplate(input: NoteTemplate): Promise<DirectMailState>;
  topUp(amountCents: number): Promise<DirectMailState>;
  advanceDemo?(id: string, revision: number): Promise<DirectMailState>;
  resetDemo?(id: string, revision: number): Promise<DirectMailState>;
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

export function createDirectMailRepository(store: DirectMailStore, pilotLoader?: () => Promise<Mailer[]>, recordingDemo = false, simulation = { advance: advanceHarveyDemo, reset: resetHarveyDemo }): DirectMailRepository {
  let loaded: Promise<Mailer[]> | undefined;
  async function write(change: (state: DirectMailState) => DirectMailState) {
    const state = await store.transact((state) => { const next = StateSchema.parse(change(state)); return { state: next, result: next }; });
    notify(); return state;
  }
  return {
    ...(recordingDemo ? {
      advanceDemo: (id: string, revision: number) => write(state => simulation.advance(state, id, revision)),
      resetDemo: async (id: string, revision: number) => {
        const state = await write(state => simulation.reset(state, id, revision));
        if (typeof sessionStorage !== "undefined" && !writePendingDraft(id, null)) throw new Error("The recording was reset, but the unsaved note could not be cleared. Discard the recovered draft before continuing.");
        return state;
      },
    } : {}),
    read: async () => {
      if (!pilotLoader) return store.read();
      let examples: Mailer[];
      try { examples = await (loaded ??= pilotLoader().catch((error) => { loaded = undefined; throw error; })); }
      catch { return { ...await store.read(), pilotLoadError: "Saved drafts are available. The optional local pilot examples could not be loaded." }; }
      return store.transact((state) => {
        for (const example of examples) if (!state.mailers.some((m) => m.id === example.id)) state.mailers.push(structuredClone(example));
        return { state: StateSchema.parse(state), result: StateSchema.parse(state) };
      });
    }, subscribe,
    saveBudget: (input, expectedRevision) => write((state) => {
      const value = GiftBudgetSchema.parse(input);
      if (!state.mailers.some((m) => m.projectId === value.projectId)) throw new Error("Choose an existing project.");
      const previous = state.giftBudgets?.find((b) => b.projectId === value.projectId);
      if ((previous?.revision ?? 0) !== expectedRevision) throw new Error("The project budget changed. Reload before saving.");
      value.revision = expectedRevision + 1;
      state.giftBudgets = [...(state.giftBudgets ?? []).filter((b) => b.projectId !== value.projectId), value];
      for (const mailer of state.mailers) if (mailer.projectId === value.projectId && isDraft(mailer)) { mailer.revision++; mailer.reviewedRevision = null; mailer.stage = "needs_review"; }
      return state;
    }),
    saveTemplate: (input) => write((state) => {
      const template = NoteTemplateSchema.parse(input);
      if (state.noteTemplates?.some((t) => t.id === template.id)) throw new Error("Save a new template version instead of overwriting a saved template.");
      (state.noteTemplates ??= []).push(template); return state;
    }),
    topUp: (amount) => write((state) => {
      if (![100000, 200000].includes(amount)) throw new Error("Choose a $1,000 or $2,000 preview top-up.");
      state.creditBalanceCents = (state.creditBalanceCents ?? 200000) + amount;
      (state.creditEntries ??= []).push({ id: crypto.randomUUID(), kind: "top_up", amountCents: amount, mailerId: null, at: new Date().toISOString(), description: "Preview credit top-up" }); return state;
    }),
    patchPage: (id, version, patch) => write(state => updateOutreachPage(state,id,version,patch)),
    invalidatePage: (id, version) => write(state => invalidatePageReview(state,id,version)),
    reviewPage: (id, version) => write(state => reviewOutreachPage(state,id,version)),
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
          budgetCents: data.budgetCents, cardId: data.cardId, styleId: data.styleId, gifts: structuredClone(source.gifts), selectedGiftId: null,
          qr: source.qr ? { ...source.qr, printedUrl: null, verifiedAt: null } : undefined,
          assets: source.assets?.filter((asset) => asset.scope === "account"),
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
    cancel: (id, revision) => write((state) => {
      const mailer = requireMailer(state, id, revision);
      if (mailer.stage !== "approved") throw new Error("This mailer cannot be canceled at its current stage.");
      const at = new Date().toISOString();
      const debit = state.creditEntries?.find((entry) => entry.id === `approval-${id}-${mailer.approval?.revision}` && entry.kind === "mailer");
      if (debit) { state.creditBalanceCents = (state.creditBalanceCents ?? 200000) - debit.amountCents; (state.creditEntries ??= []).push({ id: `refund-${debit.id}`, kind: "refund", amountCents: -debit.amountCents, mailerId: id, at, description: `Canceled before ordering · ${mailer.recipient.name}` }); }
      mailer.stage = "canceled"; mailer.revision++; mailer.events.push({ id: `cancel-${revision}`, title: "Mailer canceled", detail: "Canceled before a merchant order was confirmed.", at, kind: "standard" }); return state;
    }),
    replace: (id, revision) => write((state) => {
      const mailer = requireMailer(state, id, revision);
      if (mailer.exception?.action !== "replacement") throw new Error("No replacement is requested for this mailer.");
      if (mailer.approval) mailer.priorApprovals.push(mailer.approval);
      mailer.approval = null; mailer.selectedGiftId = null; mailer.reviewedRevision = null;
      mailer.gifts = structuredClone(demoGifts).map((gift) => ({ ...gift, id: `${gift.id}-replacement-${revision}` }));
      mailer.inbound = null; mailer.outbound = null; mailer.photos = []; mailer.proposalRequest = null;
      mailer.deliveryEstimate = "7–10 business days after replacement approval";
      mailer.stage = "needs_review"; mailer.exception = null; mailer.revision++;
      mailer.events.push({ id: `replacement-${revision}`, title: "Replacement review started", detail: "The earlier approval is retained. Choose a new gift before approving this replacement.", at: new Date().toISOString(), kind: "exception" });
      return state;
    }),
  };
}
const unavailable = async (): Promise<never> => { throw new Error("Direct Mail is not connected to this workspace yet."); };
export const unavailableDirectMailRepository: DirectMailRepository = { read: unavailable, patchPage: unavailable, reviewPage: unavailable, invalidatePage: unavailable, patch: unavailable, review: unavailable, approve: unavailable, create: unavailable, addCard: unavailable, addStyle: unavailable, requestProposal: unavailable, resolveProposal: unavailable, cancel: unavailable, replace: unavailable, saveBudget: unavailable, saveTemplate: unavailable, topUp: unavailable, subscribe: () => () => {} };
