import { AccountDetailSchema } from "@/features/accounts/model/account-detail";
import { AccountWorkspaceSchema } from "@/features/accounts/model/account-workspace";
import { accountFixtures } from "@/features/accounts/data/accounts.fixture";
import { createWorkspaceFixture } from "@/features/orchestration/data/workspace.fixture";
import { materialAccountRows, withMaterialsWorkspace } from "./materials.fixture";
export function materialAccountDetail(accountId:string) {
 const workspace=withMaterialsWorkspace(createWorkspaceFixture());
 const row=materialAccountRows(accountFixtures,workspace).find(a=>a.id===accountId);
 if(!row)return null;
 const plan=workspace.accounts.find(a=>a.id===accountId);
 return AccountDetailSchema.parse({...row,previewTitle:row.name,websiteLabel:row.websiteUrl?new URL(row.websiteUrl).hostname:"—",headcountLabel:row.employeeBand,revenueLabel:row.revenueBand,locationsLabel:row.locationsLabel??"—",createdAt:row.createdAt??"2026-10-26T12:00:00Z",lastModifiedAt:row.lastModifiedAt??"2026-10-26T12:00:00Z",owner:workspace.people.find(p=>p.id===plan?.ownerId)??row.owner,summaryParagraphs:plan?.researchStatus==="ready"?["Illustrative account for the local campaign walkthrough. Recipients, insights and campaign materials are sample data."]:[],fitCriteria:[],contacts:[],insights:[],activity:[],buyingCommittee:[]});
}
export function materialAccountWorkspace(accountId:string) {
 return materialAccountDetail(accountId)?AccountWorkspaceSchema.parse({accountId,insights:[],artifacts:[],activity:[]}):null;
}
