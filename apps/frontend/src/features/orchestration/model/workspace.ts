import { z } from "zod";

export const PROJECT_ID = "10m-landing-page-campaign";
export const projectHref = `/projects/${PROJECT_ID}/plan`;
export const chatHref = `/projects/${PROJECT_ID}/chats/thread-primary`;
const PersonSchema = z.object({ id: z.string(), name: z.string(), initials: z.string(), role: z.string(), territory: z.string(), email: z.string().email(), canSend: z.boolean() });
const AccountSchema = z.object({
  id: z.string(), revision: z.number().int().positive(), name: z.string(), initials: z.string(), industry: z.string(),
  ownerId: z.string(), senderId: z.string(), territory: z.string(), assignmentReason: z.string(),
  approach: z.enum(["Gift-led", "Email-led", "Opportunity support"]), fit: z.number(),
  insight: z.string(), evidence: z.string(), source: z.string(), observedAt: z.string(), rationale: z.string(),
  mailerId: z.string().nullable(), contactId: z.string(), contact: z.string(), role: z.string(), email: z.string().email(),
  committee: z.array(z.object({ name: z.string(), role: z.string(), status: z.string() })),
  campaignIds: z.array(z.string()), audienceSize: z.number().int().nonnegative(),
});
const ArtifactSchema = z.object({ id: z.string(), accountId: z.string(), kind: z.enum(["page", "ad", "email", "note"]), title: z.string(), version: z.number().int().positive(), status: z.enum(["draft", "review", "approved"]), headline: z.string(), body: z.string(), cta: z.string(), emailId: z.string().nullable(), mailerId: z.string().nullable() });
const ApprovalSchema = z.object({ revision: z.number(), senderId: z.string(), subject: z.string(), body: z.string(), trigger: z.string(), at: z.string() });
const EmailSchema = z.object({ id: z.string(), revision: z.number().int().positive(), accountId: z.string(), senderId: z.string(), subject: z.string(), body: z.string(), trigger: z.enum(["After gift delivery", "After approval"]), status: z.enum(["draft", "scheduled", "reply", "handled"]), approval: ApprovalSchema.nullable(), sequenceStopped: z.boolean(), reply: z.string().nullable() });
export const WorkspaceSchema = z.object({
  version: z.literal(2), project: z.object({ id: z.string(), name: z.string(), goal: z.string(), ownerId: z.string(), budget: z.string() }),
  people: z.array(PersonSchema), accounts: z.array(AccountSchema), artifacts: z.array(ArtifactSchema), emails: z.array(EmailSchema),
  campaigns: z.array(z.object({ id: z.string(), name: z.string(), channel: z.string(), ownerId: z.string(), purpose: z.string() })),
  messages: z.array(z.object({ id: z.string(), role: z.enum(["user", "assistant"]), text: z.string(), action: z.enum(["plan", "review", "email", "none"]) })),
  outcomes: z.array(z.object({ id: z.string(), accountId: z.string(), kind: z.enum(["human_reply", "meeting_booked", "meeting_held", "opportunity"]), detail: z.string() })),
});
export type WorkspaceState = z.infer<typeof WorkspaceSchema>;
export type AccountPlan = WorkspaceState["accounts"][number];
export type CampaignArtifact = WorkspaceState["artifacts"][number];
export type EmailDraft = WorkspaceState["emails"][number];
export type Person = WorkspaceState["people"][number];
export type EmailPatch = Partial<Pick<EmailDraft, "body" | "subject" | "senderId" | "trigger">>;

function current<T extends { id: string; revision: number }>(items: T[], id: string, revision: number): T {
  const item = items.find((entry) => entry.id === id);
  if (!item) throw new Error("This record is no longer available.");
  if (item.revision !== revision) throw new Error("This record changed in another view. Reload before saving.");
  return item;
}
export function setAccountOwner(state: WorkspaceState, id: string, revision: number, ownerId: string) {
  const next = structuredClone(state), account = current(next.accounts, id, revision);
  if (!next.people.some((p) => p.id === ownerId && p.canSend)) throw new Error("Choose an available account owner.");
  account.ownerId = ownerId; account.revision++; account.assignmentReason = "Explicit account assignment";
  return WorkspaceSchema.parse(next);
}
export function saveEmail(state: WorkspaceState, id: string, revision: number, patch: EmailPatch) {
  const next = structuredClone(state), email = current(next.emails, id, revision);
  if (email.sequenceStopped) throw new Error("This sequence stopped after a reply. Keep the existing conversation intact.");
  Object.assign(email, patch);
  if (!email.body.trim() || !email.subject.trim()) throw new Error("Add a subject and message before saving.");
  if (!next.people.some((p) => p.id === email.senderId && p.canSend)) throw new Error("Choose an authorized sender.");
  email.revision++; email.approval = null; email.status = "draft";
  return WorkspaceSchema.parse(next);
}
export function approveEmail(state: WorkspaceState, id: string, revision: number) {
  const next = structuredClone(state), email = current(next.emails, id, revision);
  if (email.sequenceStopped) throw new Error("A reply has stopped this sequence.");
  if (!email.body.trim() || !email.subject.trim()) throw new Error("Review the complete message first.");
  if (/\{\{.*?\}\}/s.test(email.body + email.subject)) throw new Error("Resolve the template fields before approving.");
  if (!next.people.some((p) => p.id === email.senderId && p.canSend)) throw new Error("Choose an authorized sender.");
  if (!next.accounts.some((a) => a.id === email.accountId)) throw new Error("The recipient is unavailable.");
  email.approval = { revision, senderId: email.senderId, subject: email.subject, body: email.body, trigger: email.trigger, at: new Date().toISOString() };
  email.status = "scheduled"; email.revision++;
  return WorkspaceSchema.parse(next);
}
export function markReplyHandled(state: WorkspaceState, id: string, revision: number) {
  const next = structuredClone(state), email = current(next.emails, id, revision);
  if (email.status !== "reply") throw new Error("This conversation has no outstanding reply.");
  email.status = "handled"; email.revision++;
  return WorkspaceSchema.parse(next);
}
export function validateWorkspaceLinks(state: WorkspaceState) {
  const problems: string[] = [];
  const accounts = new Set(state.accounts.map((a) => a.id));
  const people = new Set(state.people.map((p) => p.id));
  const campaigns = new Set(state.campaigns.map((c) => c.id));
  for (const a of state.accounts) if (!people.has(a.ownerId) || !people.has(a.senderId) || a.campaignIds.some((id) => !campaigns.has(id))) problems.push(`Invalid account context: ${a.id}`);
  for (const a of state.artifacts) if (!accounts.has(a.accountId) || (a.emailId && !state.emails.some((e) => e.id === a.emailId && e.accountId === a.accountId))) problems.push(`Invalid artifact context: ${a.id}`);
  for (const e of state.emails) if (!accounts.has(e.accountId) || !people.has(e.senderId)) problems.push(`Invalid email context: ${e.id}`);
  return problems;
}
export function workspaceMetrics(state: WorkspaceState) {
  const count = (kind: WorkspaceState["outcomes"][number]["kind"]) => new Set(state.outcomes.filter((e) => e.kind === kind).map((e) => e.accountId)).size;
  return { accounts: state.accounts.length, replies: count("human_reply"), meetingsBooked: count("meeting_booked"), meetingsHeld: count("meeting_held"), opportunities: count("opportunity") };
}
export function person(state: WorkspaceState, id: string) { return state.people.find((p) => p.id === id)!; }
