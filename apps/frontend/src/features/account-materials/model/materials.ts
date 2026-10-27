import type { CampaignArtifact, WorkspaceState } from "@/features/orchestration/model/workspace";
import { isDraft, stageLabels, type DirectMailState, type Mailer } from "@/features/direct-mail/model/direct-mail";

export const materialKinds = { gift: "Gift", note: "Card & note", page: "Landing page", ad: "LinkedIn ad" };
export type MaterialKind = keyof typeof materialKinds;
export type Material = { id:string; projectId:string; accountId:string; accountName:string; contactId:string|null; recipient:string|null; kind:MaterialKind; title:string; status:string; version:number; mailer?:Mailer; asset?:CampaignArtifact };
export type MaterialQuery = { projectId?:string; accountId?:string; contactId?:string; kind?:string; status?:string; search?:string; page?:number };
/** UI projection only: gift/note content and approval always come from the mailer repository. */
export function buildMaterials(workspace:WorkspaceState, mail:DirectMailState):Material[] {
 const mailers = new Map(mail.mailers.map(m => [m.id,m]));
 const accounts = new Map(workspace.accounts.map(a => [a.id,a]));
 const rows:Material[] = [];
 for (const m of mail.mailers) {
  for (const kind of ["gift","note"] as const) rows.push({
   id:`${kind}:${m.id}`,projectId:m.projectId,accountId:m.accountId,accountName:m.recipient.company,
   contactId:m.contactId,recipient:m.recipient.name,kind,title:kind === "gift" ? "Gift selection" : "Handwritten card",
   status:kind === "note" && m.approval ? "Approved" : isDraft(m) ? (m.stage === "ready" ? "Ready to approve" : "Needs review") : stageLabels[m.stage],
   version:m.approval?.revision ?? m.revision,mailer:m,
  });
 }
 for (const asset of workspace.artifacts) {
  if (asset.kind === "note") continue; // A note is the canonical mailer draft/approval, never copied content.
  const account=accounts.get(asset.accountId); if (!account) continue;
  const m=asset.mailerId ? mailers.get(asset.mailerId) : undefined;
  if (asset.mailerId && (!m || m.accountId !== asset.accountId)) continue;
  rows.push({id:asset.id,projectId:workspace.project.id,accountId:asset.accountId,accountName:account.name,
   contactId:m?.contactId ?? null,recipient:m?.recipient.name ?? null,kind:asset.kind,title:asset.title,
   status:asset.status === "review" ? "Needs review" : asset.status === "approved" ? "Approved" : "Draft",
   version:asset.version,asset,mailer:m});
 }
 return rows;
}
export function queryMaterials(rows:Material[], query:MaterialQuery={}) {
 const search=query.search?.trim().toLocaleLowerCase();
 const matching=rows.filter(r => (!query.projectId || r.projectId===query.projectId)
  && (!query.accountId || query.accountId==="all" || r.accountId===query.accountId)
  && (!query.contactId || query.contactId==="all" || !r.contactId || r.contactId===query.contactId)
  && (!query.kind || query.kind==="all" || r.kind===query.kind)
  && (!query.status || query.status==="all" || (query.status==="review" ? ["Needs review","Ready to approve"].includes(r.status) : query.status==="approved" ? r.status==="Approved" : r.kind==="gift" && r.mailer && !["needs_review","ready","researching","delivered","canceled"].includes(r.mailer.stage)))
  && (!search || `${r.title} ${r.accountName} ${r.recipient ?? ""}`.toLocaleLowerCase().includes(search)));
 const pages=Math.max(1,Math.ceil(matching.length/25)), page=Math.min(pages,Math.max(1,query.page ?? 1));
 return {rows:matching.slice((page-1)*25,page*25),total:matching.length,page,pages};
}
export function materialGalleryHref(projectId:string, accountId?:string, materialId?:string) {
 const query=new URLSearchParams({surface:"gallery"});
 if (accountId) query.set("materialsAccount",accountId);
 if (materialId) query.set("material",materialId);
 return `/projects/${encodeURIComponent(projectId)}/chats/thread-primary?${query}`;
}

export function materialEntry({fixedAccount,tableAccount,routeAccount,routeMaterial}:{fixedAccount?:string;tableAccount?:string;routeAccount:string|null;routeMaterial:string|null}) {
 return {accountId:fixedAccount ?? tableAccount ?? routeAccount ?? "all",materialId:tableAccount ? null : routeMaterial};
}
