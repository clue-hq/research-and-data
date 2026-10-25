import { z } from "zod";

const Cents = z.number().int().nonnegative().max(10_000_000);
const AreaSchema = z.object({ x: z.number().min(0).max(45), y: z.number().min(0).max(45), width: z.number().min(35).max(100), height: z.number().min(30).max(100) }).refine((area) => area.x + area.width <= 100 && area.y + area.height <= 100, "The writing area must fit inside the card.");
export const CardAssetSchema = z.object({ id: z.string(), name: z.string().min(1), version: z.number().int().positive(), frontUrl: z.string().nullable(), backUrl: z.string().nullable(), paper: z.enum(["white", "cream"]), writingArea: AreaSchema, productionReady: z.boolean() });
export const StyleSchema = z.object({ id: z.string(), name: z.string(), version: z.number().int().positive(), family: z.string(), sourceUrl: z.string().nullable(), productionReady: z.boolean() });
export const GiftSchema = z.object({ id: z.string(), name: z.string(), variant: z.string(), merchant: z.string(), priceCents: Cents.nullable(), image: z.string(), rationale: z.string(), available: z.boolean(), arrival: z.string(), recommended: z.boolean() });
export const AddressSchema = z.object({ name: z.string(), company: z.string(), line1: z.string(), line2: z.string(), city: z.string(), region: z.string(), postalCode: z.string(), country: z.string() });
export const StageSchema = z.enum(["researching", "needs_review", "ready", "approved", "ordered", "inbound", "received", "quality_check", "preparing", "ready_to_ship", "shipped", "delivered", "attention", "canceled"]);
export type Stage = z.infer<typeof StageSchema>;
const InsightSchema = z.object({ title: z.string(), detail: z.string(), source: z.string(), date: z.string(), excerpt: z.string() });
const EventSchema = z.object({ id: z.string(), title: z.string(), detail: z.string(), at: z.string(), kind: z.enum(["standard", "exception"]) });
const ShipmentSchema = z.object({ carrier: z.string(), trackingNumber: z.string(), trackingUrl: z.string().nullable(), expected: z.string(), status: z.string() }).nullable();
const ApprovalSchema = z.object({ revision: z.number(), at: z.string(), gift: GiftSchema, note: z.string(), signature: z.string(), card: CardAssetSchema, style: StyleSchema, address: AddressSchema, estimatedCents: Cents, budgetCents: Cents });
export const MailerSchema = z.object({
  id: z.string(), revision: z.number().int().positive(), reviewedRevision: z.number().nullable(),
  projectId: z.string(), projectName: z.string(), campaign: z.string(), threadId: z.string(),
  accountId: z.string(), contactId: z.string(),
  recipient: z.object({ name: z.string(), role: z.string(), company: z.string(), initials: z.string() }),
  insight: InsightSchema, gifts: z.array(GiftSchema).length(3), selectedGiftId: z.string().nullable(),
  note: z.string(), signature: z.string(), cardId: z.string(), styleId: z.string(),
  address: AddressSchema, addressConfirmed: z.boolean(), budgetCents: Cents,
  inboundCents: Cents.nullable(), preparationCents: Cents.nullable(), outboundCents: Cents.nullable(), taxCents: Cents.nullable(),
  stage: StageSchema, updatedAt: z.string(), deliveryEstimate: z.string(),
  approval: ApprovalSchema.nullable(), priorApprovals: z.array(ApprovalSchema),
  inbound: ShipmentSchema, outbound: ShipmentSchema,
  events: z.array(EventSchema), photos: z.array(z.object({ id: z.string(), url: z.string(), caption: z.string(), at: z.string() })),
  exception: z.object({ title: z.string(), detail: z.string(), action: z.enum(["address", "replacement", "none"]) }).nullable(),
  proposalRequest: z.object({ kind: z.enum(["gifts", "insight"]), feedback: z.string(), requestedAt: z.string() }).nullable(),
});
export const StateSchema = z.object({ schemaVersion: z.literal(1), mailers: z.array(MailerSchema), cards: z.array(CardAssetSchema), styles: z.array(StyleSchema) });
export type DirectMailState = z.infer<typeof StateSchema>;
export type Mailer = z.infer<typeof MailerSchema>;
export type Gift = z.infer<typeof GiftSchema>;
export type CardAsset = z.infer<typeof CardAssetSchema>;
export type HandwritingStyle = z.infer<typeof StyleSchema>;
export const MailerPatchSchema = MailerSchema.pick({ selectedGiftId: true, note: true, signature: true, cardId: true, styleId: true, address: true, addressConfirmed: true, budgetCents: true }).partial().strict();
export type MailerPatch = z.infer<typeof MailerPatchSchema>;
export type ApprovalItem = { id: string; revision: number };
export type ApprovalResult = { id: string; ok: boolean; message: string };

export const stageLabels: Record<Stage, string> = { researching: "Researching", needs_review: "Needs review", ready: "Ready to approve", approved: "Approved", ordered: "Gift ordered", inbound: "On its way to Clue", received: "Received at Clue", quality_check: "Quality inspection", preparing: "Package preparation", ready_to_ship: "Ready to ship", shipped: "Shipped", delivered: "Delivered", attention: "Needs attention", canceled: "Canceled" };
export function isDraft(mailer: Mailer) { return mailer.stage === "needs_review" || mailer.stage === "ready"; }
export function selectedGift(mailer: Mailer) { return mailer.gifts.find((gift) => gift.id === mailer.selectedGiftId) ?? null; }
export function money(cents: number | null) { return cents === null ? "Not quoted" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(cents / 100); }
export function estimate(mailer: Mailer): number | null {
  const amounts = [selectedGift(mailer)?.priceCents ?? null, mailer.inboundCents, mailer.preparationCents, mailer.outboundCents, mailer.taxCents];
  return amounts.some((amount) => amount === null) ? null : amounts.reduce<number>((total, amount) => total + (amount ?? 0), 0);
}
function hasReceivingAddress(mailer: Mailer) {
  const a = mailer.address;
  return [a.name, a.line1, a.city, a.postalCode, a.country].every((value) => value.trim());
}

/** Conservative 6×4 card layout at 600×400 preview pixels; real print fitting stays backend-owned. */
export function noteFits(note: string, signature: string, card?: CardAsset): boolean {
  if (!card || note.length > 600) return false;
  const width = 600 * card.writingArea.width / 100;
  const height = 400 * card.writingArea.height / 100;
  const columns = Math.max(1, Math.floor(width / 12));
  let lines = 0;
  for (const paragraph of `${note}\n\n${signature}`.split("\n")) {
    let used = 0;
    lines += 1;
    for (const word of paragraph.split(/\s+/)) {
      if (used && used + word.length + 1 > columns) { lines++; used = 0; }
      const length = word.length + (used ? 1 : 0);
      lines += Math.floor(Math.max(0, length - 1) / columns);
      used += length % columns || (length ? columns : 0);
    }
  }
  return lines * 29 <= height;
}

export function readiness(mailer: Mailer, state: DirectMailState): string[] {
  const issues: string[] = [];
  const gift = selectedGift(mailer);
  const card = state.cards.find((item) => item.id === mailer.cardId);
  const style = state.styles.find((item) => item.id === mailer.styleId);
  if (!gift) issues.push("Choose a gift.");
  else if (!gift.available) issues.push("Choose an available gift.");
  if (!card?.productionReady) issues.push("Choose a card approved for production.");
  if (!style?.productionReady) issues.push("Choose a handwriting style approved for production.");
  if (!mailer.note.trim()) issues.push("Write a note.");
  else if (!noteFits(mailer.note, mailer.signature, card)) issues.push("Shorten the note to fit the card’s writing area.");
  if (!mailer.signature.trim()) issues.push("Add a sender signature.");
  if (!hasReceivingAddress(mailer)) issues.push("Complete the receiving address.");
  if (!mailer.addressConfirmed) issues.push("Confirm that the recipient can receive mail at this address.");
  const total = estimate(mailer);
  if (total === null) issues.push("A complete cost estimate is needed.");
  else if (total > mailer.budgetCents) issues.push("The estimated total exceeds the spending limit.");
  if (mailer.proposalRequest) issues.push("Resolve the requested recommendation changes before approving.");
  return issues;
}

export function requireMailer(state: DirectMailState, id: string, revision?: number): Mailer {
  const mailer = state.mailers.find((item) => item.id === id);
  if (!mailer) throw new Error("This mailer is no longer available.");
  if (revision !== undefined && revision !== mailer.revision) throw new Error("This mailer changed in another view. Reload it before saving.");
  return mailer;
}

export function updateMailer(state: DirectMailState, id: string, revision: number, input: MailerPatch): DirectMailState {
  const next = structuredClone(state);
  const mailer = requireMailer(next, id, revision);
  if (!isDraft(mailer)) throw new Error("An approved or in-progress mailer cannot be edited.");
  const patch = MailerPatchSchema.parse(input);
  if (patch.selectedGiftId && !mailer.gifts.some((gift) => gift.id === patch.selectedGiftId)) throw new Error("That gift is no longer an option.");
  Object.assign(mailer, patch, { revision: revision + 1, reviewedRevision: null, stage: "needs_review", updatedAt: new Date().toISOString() });
  if (patch.address && patch.addressConfirmed !== true) mailer.addressConfirmed = false;
  if (mailer.exception?.action === "address" && mailer.addressConfirmed && hasReceivingAddress(mailer)) mailer.exception = null;
  return next;
}

export function reviewMailer(state: DirectMailState, id: string, revision: number): DirectMailState {
  const next = structuredClone(state);
  const mailer = requireMailer(next, id, revision);
  if (!isDraft(mailer)) throw new Error("This mailer cannot be reviewed at its current stage.");
  const issues = readiness(mailer, state);
  if (issues.length) throw new Error(issues[0]);
  mailer.revision += 1;
  mailer.reviewedRevision = mailer.revision;
  mailer.stage = "ready";
  return next;
}

export function approveMailers(state: DirectMailState, items: ApprovalItem[]): { state: DirectMailState; results: ApprovalResult[] } {
  const next = structuredClone(state);
  const results = items.map(({ id, revision }) => {
    try {
      const mailer = requireMailer(next, id);
      if (mailer.approval?.revision === revision && mailer.stage !== "canceled") return { id, ok: true, message: "Already approved" };
      requireMailer(next, id, revision);
      if (mailer.stage !== "ready" || mailer.reviewedRevision !== revision) throw new Error("Review this mailer before approving it.");
      const issues = readiness(mailer, next);
      if (issues.length) throw new Error(issues[0]);
      const at = new Date().toISOString();
      mailer.approval = { revision, at, gift: structuredClone(selectedGift(mailer)!), note: mailer.note, signature: mailer.signature,
        card: structuredClone(next.cards.find((card) => card.id === mailer.cardId)!),
        style: structuredClone(next.styles.find((style) => style.id === mailer.styleId)!),
        address: structuredClone(mailer.address), estimatedCents: estimate(mailer)!, budgetCents: mailer.budgetCents };
      mailer.stage = "approved";
      mailer.revision += 1;
      mailer.updatedAt = at;
      mailer.events.push({ id: `approval-${revision}`, title: "Mailer approved", detail: "Gift, note, card and spending limit confirmed. Awaiting merchant order confirmation.", at, kind: "standard" });
      return { id, ok: true, message: "Approved" };
    } catch (error) { return { id, ok: false, message: error instanceof Error ? error.message : "Approval failed. Try again." }; }
  });
  return { state: next, results };
}
