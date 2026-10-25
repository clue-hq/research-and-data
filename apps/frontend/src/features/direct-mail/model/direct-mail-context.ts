import { z } from "zod";
import type { Mailer } from "./direct-mail";

export const WebUrlSchema = z.string().url().refine((value) => /^https?:\/\//i.test(value), "Use an HTTP or HTTPS link.");
const Cents = z.number().int().min(0).max(10_000_000);
export const GiftBudgetSchema = z.object({ projectId: z.string().min(1), revision: z.number().int().positive(), minimumCents: Cents, preferredCents: Cents, ceilingCents: Cents, locked: z.boolean() }).refine((b) => b.minimumCents <= b.preferredCents && b.preferredCents <= b.ceilingCents && b.ceilingCents > 0, "Keep the preferred range below the upper gift-price limit.");
export type GiftBudget = z.infer<typeof GiftBudgetSchema>;
export function dollarsToCents(value: string): number { return Math.round(Number(value) * 100); }
export const NoteTemplateSchema = z.object({ id: z.string().min(1), name: z.string().trim().min(1).max(80), body: z.string().trim().min(1).max(1200), signature: z.string().max(100), version: z.number().int().positive() });
export type NoteTemplate = z.infer<typeof NoteTemplateSchema>;
export const CampaignAssetSchema = z.object({ id: z.string(), kind: z.enum(["microsite", "linkedin-ad", "email"]), title: z.string(), url: WebUrlSchema.nullable(), status: z.enum(["draft", "review", "approved", "published", "unavailable"]), scope: z.enum(["account", "recipient"]), source: z.string().optional() });
export const QrConnectionSchema = z.object({ destinationUrl: WebUrlSchema.nullable(), destinationStatus: z.enum(["draft", "published", "unknown"]), printedUrl: WebUrlSchema.nullable(), verifiedAt: z.string().datetime().nullable() });
export const CreditEntrySchema = z.object({ id: z.string(), kind: z.enum(["top_up", "mailer", "refund"]), amountCents: z.number().int(), mailerId: z.string().nullable(), at: z.string(), description: z.string() });

export function renderNoteTemplate(body: string, mailer: Mailer): string {
  const values: Record<string, string> = { first_name: mailer.recipient.name.split(" ")[0], recipient: mailer.recipient.name, company: mailer.recipient.company, gift: mailer.gifts.find((g) => g.id === mailer.selectedGiftId)?.name ?? "your gift", insight: mailer.insight.title };
  return body.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_, key: string) => { if (!(key in values)) throw new Error(`Unsupported template field: ${key}`); return values[key]; });
}

export function noteTemplateBody(mailer: Mailer): string {
  const firstName = mailer.recipient.name.split(" ")[0];
  let body = mailer.note.replaceAll(mailer.recipient.name, "{{recipient}}").replaceAll(mailer.recipient.company, "{{company}}");
  for (const prefix of [`${firstName},`, `Hi ${firstName},`, `Hello ${firstName},`, `Dear ${firstName},`]) {
    if (body.startsWith(prefix)) { body = prefix.replace(firstName, "{{first_name}}") + body.slice(prefix.length); break; }
  }
  return body;
}

export function trackingMilestones(mailer: Mailer) {
  const phases = [
    { id: "ordered", title: "Gift ordered", detail: "The merchant confirms your selected gift and variant." },
    { id: "inbound", title: "On its way to Clue", detail: "Merchant delivery to the Clue fulfillment center." },
    { id: "received", title: "Received at Clue", detail: "The gift is checked in against your mailer." },
    { id: "preparing", title: "Inspection & preparation", detail: "Product inspection, handwritten card and repackaging." },
    { id: "shipped", title: "Shipped to recipient", detail: "The finished package is handed to the outbound carrier." },
    { id: "delivered", title: "Delivered", detail: "Carrier-confirmed delivery; personal receipt is separate." },
  ];
  const stages: Record<string, number> = { ordered: 0, inbound: 1, received: 2, quality_check: 3, preparing: 3, ready_to_ship: 3, shipped: 4, delivered: 5 };
  const current = stages[mailer.stage] ?? -1;
  return phases.map((phase, index) => ({ ...phase, state: index < current || (index === current && mailer.stage === "delivered") ? "complete" as const : index === current ? "current" as const : "pending" as const }));
}
