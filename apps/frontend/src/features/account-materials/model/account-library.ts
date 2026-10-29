import type { AccountArtifact } from '@/features/accounts/model/account-workspace';
import { selectedGift, stageLabels, type DirectMailState, type Mailer } from '@/features/direct-mail/model/direct-mail';
import type { OutreachPage } from '@/features/direct-mail/model/outreach-page';
import type { CampaignArtifact, WorkspaceState } from '@/features/orchestration/model/workspace';
import type { GalleryArtifact } from '@/features/gallery/model/project-gallery';

export const libraryKinds = {page:'Landing pages',ad:'Ads',gift:'Gifts',note:'Cards & notes',file:'Files & documents'};
export type LibraryKind = keyof typeof libraryKinds;
export type LibraryItem = {
 id:string; accountId:string; projectId:string|null; projectName:string|null;
 campaignId:string|null; campaignName:string|null; contactId:string|null; recipient:string|null;
 kind:LibraryKind; title:string; status:'review'|'reviewed'|'approved'|'draft'|'saved'; execution:string|null;
 version:number|null; updatedAt:string; accountName?:string; gallery?:GalleryArtifact; mailer?:Mailer; page?:OutreachPage; creative?:CampaignArtifact; file?:AccountArtifact;
};
export const libraryStatusLabels = {review:'Needs review',reviewed:'Reviewed',approved:'Approved',draft:'Draft',saved:'Saved'};

/** Read model only. Every preview points back to its canonical record; no editing state lives here. */
export function buildAccountLibrary(accountId:string,workspace:WorkspaceState,mail:DirectMailState,files:AccountArtifact[]):LibraryItem[] {
 const rows:LibraryItem[]=[];
 const campaign=(id?:string)=>({campaignId:id??null,campaignName:workspace.campaigns.find(c=>c.id===id)?.name??null});
 const mailers=new Map(mail.mailers.filter(m=>m.accountId===accountId).map(m=>[m.id,m]));
 for(const m of mailers.values()) {
  const base={accountId,projectId:m.projectId,projectName:m.projectName,...campaign(m.campaignId),contactId:m.contactId,recipient:m.recipient.name,version:m.approval?.revision??m.revision,updatedAt:m.updatedAt,mailer:m};
  const status=m.approval?'approved':m.stage==='researching'?'draft':'review';
  rows.push({...base,id:`gift:${m.id}`,kind:'gift',title:(m.approval?.gift??selectedGift(m))?.name??'Gift selection',status,execution:m.approval?(m.stage==='shipped'?'In transit':m.stage==='approved'?'Awaiting purchase':stageLabels[m.stage]):null});
  rows.push({...base,id:`note:${m.id}`,kind:'note',title:`${m.recipient.name.split(' ')[0]} · Handwritten card`,status,execution:null});
  const p=m.approval?.page??mail.pages?.find(p=>p.id===m.pageId);
  // Broken/foreign links never become a seemingly valid account preview.
  if(p&&p.mailerId===m.id&&p.accountId===m.accountId&&p.contactId===m.contactId&&p.projectId===m.projectId)rows.push({...base,id:p.id,kind:'page',title:p.title,page:p,version:p.version,status:m.approval?'approved':p.reviewedVersion===p.version?'reviewed':'review',execution:p.publication==='published'?'Published · sample':'Not published'});
 }
 for(const a of workspace.artifacts) {
  if(a.accountId!==accountId||a.kind==='note')continue;
  const m=a.mailerId?mailers.get(a.mailerId):undefined;
  if(a.mailerId&&!m)continue;
  if(rows.some(r=>r.id===a.id))continue;
  rows.push({id:a.id,accountId,projectId:workspace.project.id,projectName:workspace.project.name,...campaign(a.campaignId??m?.campaignId),contactId:m?.contactId??null,recipient:m?.recipient.name??null,kind:a.kind,title:a.title,status:a.contentApproval&&a.contentApproval.version!==a.version?'review':a.status,execution:a.kind==='page'?'Not published':'Not launched',version:a.version,updatedAt:m?.updatedAt??'',creative:a,mailer:m});
 }
 for(const f of files) {
  if(f.accountId&&f.accountId!==accountId)continue;
  rows.push({id:`native:${f.id}`,accountId,projectId:null,projectName:f.projectName??null,campaignId:null,campaignName:null,contactId:null,recipient:null,kind:['site','web'].includes(f.type)?'page':f.type==='ad'?'ad':'file',title:f.title,status:'saved',execution:null,version:null,updatedAt:f.updatedAt??'',file:f});
 }
 return rows.sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt)||a.title.localeCompare(b.title));
}
export type LibraryQuery={accountId?:string;campaignId?:string;contactId?:string;kind?:string;status?:string;search?:string;page?:number};
export function filterLibrary(rows:LibraryItem[],query:LibraryQuery={}) {
 const search=query.search?.trim().toLocaleLowerCase();
 return rows.filter(r=>(!query.accountId||query.accountId==='all'||r.accountId===query.accountId)
  &&(!query.campaignId||query.campaignId==='all'||(query.campaignId==='unassigned'?!r.campaignId:r.campaignId===query.campaignId))
  &&(!query.contactId||query.contactId==='all'||!r.contactId||r.contactId===query.contactId)
  &&(!query.kind||query.kind==='all'||r.kind===query.kind)
  &&(!query.status||query.status==='all'||r.status===query.status)
  &&(!search||[r.title,r.recipient,r.accountName,r.campaignName,r.projectName].join(' ').toLocaleLowerCase().includes(search)));
}
export function queryAccountLibrary(rows:LibraryItem[],query:LibraryQuery={}) {
 const found=filterLibrary(rows,query);
 const pages=Math.max(1,Math.ceil(found.length/24)),page=Number.isFinite(query.page)?Math.min(pages,Math.max(1,Math.floor(query.page!))):1;
 return {rows:found.slice((page-1)*24,page*24),total:found.length,page,pages};
}
