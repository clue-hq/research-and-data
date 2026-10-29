import { z } from "zod";

export const PROJECT_ID = "10m-landing-page-campaign";
export const projectHref = `/projects/${PROJECT_ID}/plan`;
export const chatHref = `/projects/${PROJECT_ID}/chats/thread-primary`;
const PersonSchema = z.object({ id:z.string(), name:z.string(), initials:z.string(), role:z.string(), territory:z.string(), canOwn:z.boolean() });
const AccountSchema = z.object({
  id:z.string(), revision:z.number().int().positive(), name:z.string(), initials:z.string(), industry:z.string(),
  ownerId:z.string(), senderId:z.string(), territory:z.string(), assignmentReason:z.string(),
  approach:z.enum(["Gift-led","Content-led","Opportunity support"]), fit:z.number().nullable(), researchStatus:z.enum(["ready","pending"]),
  insight:z.string(), evidence:z.string(), source:z.string(), observedAt:z.string(), rationale:z.string(),
  mailerId:z.string().nullable(), contactId:z.string(), contact:z.string(), role:z.string(),
  committee:z.array(z.object({ name:z.string(), role:z.string(), status:z.string() })),
  campaignIds:z.array(z.string()), audienceSize:z.number().int().nonnegative(),
});
const ArtifactSchema = z.object({
  campaignId:z.string().optional(),
  id:z.string(), accountId:z.string(), kind:z.enum(["page","ad","note"]), title:z.string(),
  version:z.number().int().positive(), status:z.enum(["draft","review","approved"]),
  headline:z.string(), body:z.string(), cta:z.string(), mailerId:z.string().nullable(),
  contentApproval:z.object({version:z.number().int().positive(),approvedAt:z.string(),headline:z.string(),body:z.string(),cta:z.string(),sectionTitle:z.string(),sectionBody:z.string()}).optional(),
  sectionTitle:z.string().default(""), sectionBody:z.string().default(""),
});
export const WorkspaceSchema = z.object({
  version:z.literal(4), project:z.object({ id:z.string(), name:z.string(), goal:z.string(), ownerId:z.string(), budget:z.string() }),
  people:z.array(PersonSchema), accounts:z.array(AccountSchema), artifacts:z.array(ArtifactSchema),
  campaigns:z.array(z.object({ id:z.string(), name:z.string(), channel:z.string(), ownerId:z.string(), purpose:z.string() })),
});
export type WorkspaceState = z.infer<typeof WorkspaceSchema>;
export type AccountPlan = WorkspaceState["accounts"][number];
export type CampaignArtifact = WorkspaceState["artifacts"][number];
export type Person = WorkspaceState["people"][number];
export type AccountRevision = Pick<AccountPlan,"id" | "revision">;

export function assignAccountOwners(state:WorkspaceState, items:AccountRevision[], ownerId:string) {
  if (!state.people.some((p) => p.id === ownerId && p.canOwn)) throw new Error("Choose an available account owner.");
  if (!items.length || items.length > 100) throw new Error("Select between 1 and 100 accounts.");
  const next = structuredClone(state), seen = new Set<string>();
  for (const item of items) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    const account = next.accounts.find((a) => a.id === item.id);
    if (!account) throw new Error("This account is no longer available.");
    if (account.revision !== item.revision) throw new Error("An account changed in another view. Reload before assigning it.");
    account.ownerId = ownerId;
    account.revision++;
    account.assignmentReason = "Assigned in project";
  }
  return WorkspaceSchema.parse(next);
}
export function setAccountOwner(state:WorkspaceState,id:string,revision:number,ownerId:string) {
  return assignAccountOwners(state,[{id,revision}],ownerId);
}
export function person(state:WorkspaceState,id:string) { return state.people.find((p) => p.id === id)!; }
export function validateWorkspaceLinks(state:WorkspaceState) {
  const people = new Set(state.people.map((p) => p.id)), accounts = new Set(state.accounts.map((a) => a.id));
  const campaigns = new Set(state.campaigns.map((c) => c.id));
  const problems:string[] = [];
  for (const a of state.accounts) if (!people.has(a.ownerId) || !people.has(a.senderId) || a.campaignIds.some((id) => !campaigns.has(id))) problems.push(`Invalid account context: ${a.id}`);
  for (const a of state.artifacts) if (!accounts.has(a.accountId)) problems.push(`Invalid artifact context: ${a.id}`);
  return problems;
}

/** Content acceptance is version-bound and never authorizes channel spend or publishing. */
export function approveArtifactContent(state:WorkspaceState,id:string,version:number,now=new Date().toISOString()) {
 const next=structuredClone(state),asset=next.artifacts.find(a=>a.id===id);
 if(!asset)throw new Error('This material is no longer available.');
 if(asset.version!==version)throw new Error('This material changed. Review the latest version before approving.');
 if(asset.kind==='note')throw new Error('Review this card with its recipient’s complete send.');
 if(!asset.headline.trim()||!asset.body.trim()||!asset.cta.trim())throw new Error('Complete the content before approving it.');
 asset.status='approved';
 asset.contentApproval={version,approvedAt:now,headline:asset.headline,body:asset.body,cta:asset.cta,sectionTitle:asset.sectionTitle,sectionBody:asset.sectionBody};
 return WorkspaceSchema.parse(next);
}

export function contentApprovalRequest(asset:CampaignArtifact) {
 return {id:asset.id,version:asset.version,title:asset.title};
}
