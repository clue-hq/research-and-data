import type { DirectMailState, Mailer } from "@/features/direct-mail/model/direct-mail";
import type { AccountPlan, CampaignArtifact, WorkspaceState } from "./workspace";
export type AccountStatus = "review" | "address" | "active" | "delivered" | "ready" | "research" | "canceled";
export type AccountRow = { account:AccountPlan; mailer?:Mailer; artifacts:CampaignArtifact[]; status:AccountStatus };
export type AccountQuery = { search?:string; ownerId?:string; status?:string; sort?:"priority"|"name"|"fit"; page?:number; pageSize?:number };
const priority:Record<AccountStatus,number> = { review:0,address:1,active:2,delivered:3,ready:4,research:5,canceled:6 };
export const statusLabels:Record<AccountStatus,string> = { review:"Needs review",address:"Address needed",active:"In progress",delivered:"Delivered",ready:"Research ready",research:"Not started",canceled:"Canceled" };
export function accountRows(data:WorkspaceState,mail:DirectMailState|null):AccountRow[] {
  const mailers = new Map(mail?.mailers.map((m) => [m.id,m]));
  const assets = new Map<string,CampaignArtifact[]>();
  for (const asset of data.artifacts) assets.set(asset.accountId,[...(assets.get(asset.accountId) ?? []),asset]);
  return data.accounts.map((account) => {
    const mailer = account.mailerId ? mailers.get(account.mailerId) : undefined;
    const status:AccountStatus = mailer?.stage === "canceled" ? "canceled" : mailer?.stage === "delivered" ? "delivered" : mailer?.approval ? "active" : mailer ? !mailer.addressConfirmed ? "address" : "review" : account.researchStatus === "ready" ? "ready" : "research";
    return {account,mailer,artifacts:assets.get(account.id) ?? [],status};
  });
}
export function queryAccounts(rows:AccountRow[],query:AccountQuery = {}) {
  const search = (query.search ?? "").trim().toLowerCase();
  const filtered = rows.filter(({account:a,status}) => (!search || `${a.name} ${a.contact} ${a.industry}`.toLowerCase().includes(search)) && (!query.ownerId || query.ownerId === "all" || a.ownerId === query.ownerId) && (!query.status || query.status === "all" || (query.status === "review" ? status === "review" || status === "address" : status === query.status)));
  filtered.sort((a,b) => {
    const score = query.sort === "name" ? a.account.name.localeCompare(b.account.name) : query.sort === "fit" ? (b.account.fit ?? -1) - (a.account.fit ?? -1) : priority[a.status] - priority[b.status];
    return score || a.account.name.localeCompare(b.account.name) || a.account.id.localeCompare(b.account.id);
  });
  const pageSize = [25,50,100].includes(query.pageSize ?? 25) ? query.pageSize ?? 25 : 25;
  const pages = Math.max(1,Math.ceil(filtered.length/pageSize));
  const page = Math.max(1,Math.min(pages,Math.floor(query.page || 1)));
  return { items:filtered.slice((page-1)*pageSize,page*pageSize),total:filtered.length,pages,page,pageSize };
}
export function selectedVisibleIds(selected:string[],rows:AccountRow[]) {
  const visible = new Set(rows.map((r) => r.account.id));
  return selected.filter((id) => visible.has(id));
}
