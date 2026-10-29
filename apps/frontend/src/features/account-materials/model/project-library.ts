import type { GalleryArtifact } from '@/features/gallery/model/project-gallery';
import { isDraft, type DirectMailState, type Mailer } from '@/features/direct-mail/model/direct-mail';
import type { WorkspaceState } from '@/features/orchestration/model/workspace';
import { buildAccountLibrary, filterLibrary, libraryKinds, type LibraryItem, type LibraryKind, type LibraryQuery } from './account-library';

/** Shared read projection. Library entries always reference the original editable record. */
export function buildProjectLibrary(projectId:string,workspace:WorkspaceState,mail:DirectMailState,native:GalleryArtifact[]):LibraryItem[] {
 const scopedMail={...mail,mailers:mail.mailers.filter(m=>m.projectId===projectId)};
 const scopedWorkspace={...workspace,artifacts:workspace.project.id===projectId?workspace.artifacts:[]};
 const accounts=new Set([...scopedMail.mailers.map(m=>m.accountId),...scopedWorkspace.artifacts.map(a=>a.accountId)]);
 const rows=[...accounts].flatMap(id=>buildAccountLibrary(id,scopedWorkspace,scopedMail,[]).map(row=>({...row,accountName:workspace.accounts.find(a=>a.id===id)?.name??row.mailer?.recipient.company})));
 for(const card of native) {
  if(card.project&&card.project.id!==projectId)continue;
  if(rows.some(r=>r.id===card.id))continue;
  rows.push({id:`project-native:${card.id}`,accountId:card.account?.id??'',accountName:card.account?.name,
   projectId,projectName:workspace.project.id===projectId?workspace.project.name:null,campaignId:null,campaignName:null,
   contactId:null,recipient:null,kind:card.collateralType==='microsite'?'page':card.collateralType?.endsWith('-ad')?'ad':'file',
   title:card.title,status:'saved',execution:null,version:card.document?.version??null,updatedAt:card.updatedAt,gallery:card});
 }
 return rows.sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt)||a.title.localeCompare(b.title));
}

export type RecipientReview={mailer:Mailer;materials:LibraryItem[];entry:LibraryItem};
export function queryReviewQueue(rows:LibraryItem[],query:LibraryQuery) {
 const candidates=filterLibrary(rows,{...query,status:'all'});
 const sends=new Map<string,RecipientReview>();
 const byMailer=new Map<string,LibraryItem[]>();
 for(const item of rows)if(item.mailer){const items=byMailer.get(item.mailer.id)??[];items.push(item);byMailer.set(item.mailer.id,items);}
 for(const item of candidates) {
  const m=item.mailer;if(!m||!isDraft(m)||m.approval||sends.has(m.id))continue;
  sends.set(m.id,{mailer:m,entry:item,materials:byMailer.get(m.id)??[item]});
 }
 const all=[...sends.values()];
 const pages=Math.max(1,Math.ceil(all.length/24)),page=Number.isFinite(query.page)?Math.max(1,Math.min(pages,Math.floor(query.page!))):1;
 return {rows:all.slice((page-1)*24,page*24),total:all.length,pages,page};
}

export function summarizeAccountMaterials(rows:LibraryItem[]) {
 const result=new Map<string,{total:number;kinds:Partial<Record<LibraryKind,number>>;sendsToReview:number}>();
 const reviewed=new Set<string>();
 for(const r of rows) {
  if(!r.accountId)continue;
  const a=result.get(r.accountId)??{total:0,kinds:{},sendsToReview:0};
  a.total++;a.kinds[r.kind]=(a.kinds[r.kind]??0)+1;
  if(r.mailer&&isDraft(r.mailer)&&!r.mailer.approval&&!reviewed.has(r.mailer.id)){a.sendsToReview++;reviewed.add(r.mailer.id);}
  result.set(r.accountId,a);
 }
 return result;
}

/** The overview exposes every type; high-volume pages cannot hide a single ad or brief. */
export function libraryOverview(rows:LibraryItem[],query:LibraryQuery) {
 const found=filterLibrary(rows,query);
 return (Object.keys(libraryKinds) as LibraryKind[]).map(kind=>{
  const items=found.filter(row=>row.kind===kind);
  return {kind,total:items.length,rows:items.slice(0,4)};
 }).filter(group=>group.total>0);
}

export function libraryFilterPatch(key:string,value:string):Record<string,string|null> {
 return key==='libraryPage'?{libraryPage:value}:{[key]:value,libraryPage:null};
}
