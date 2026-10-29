'use client';
import { useMemo, useRef } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import type { AccountArtifact } from '@/features/accounts/model/account-workspace';
import type { GalleryArtifact } from '@/features/gallery/model/project-gallery';
import { useDirectMail } from '@/features/direct-mail/hooks/use-direct-mail';
import { useWorkspace } from '@/features/orchestration/hooks/use-workspace';
import { buildAccountLibrary, queryAccountLibrary, type LibraryItem } from '../model/account-library';
import { buildProjectLibrary, libraryOverview, libraryFilterPatch, queryReviewQueue } from '../model/project-library';
import { outreachTabs, type OutreachTab } from '../model/outreach';

const noFiles:AccountArtifact[]=[],noNative:GalleryArtifact[]=[];
export type LibraryScope={accountId?:string;accountName?:string;projectId?:string;projectTitle?:string;files?:AccountArtifact[];native?:GalleryArtifact[]};
export function useArtifactLibrary({accountId,projectId,files=noFiles,native=noNative}:LibraryScope) {
 const c=useDirectMail(),w=useWorkspace(),params=useSearchParams(),path=usePathname();
 const mail=c.data,workspace=w.data,projectMode=!accountId;
 const scroll=useRef<HTMLDivElement>(null),position=useRef(0);
 const rows=useMemo(()=>!mail||!workspace?[]:accountId?buildAccountLibrary(accountId,workspace,mail,files):buildProjectLibrary(projectId??workspace.project.id,workspace,mail,native),[accountId,projectId,workspace,mail,files,native]);
 const query={accountId:projectMode?params.get('materialsAccount')??'all':undefined,campaignId:params.get('campaign')??'all',contactId:params.get('libraryRecipient')??'all',kind:params.get('type')??'all',status:params.get('libraryStatus')??'all',search:params.get('librarySearch')??'',page:Number(params.get('libraryPage')??1)};
 const result=queryAccountLibrary(rows,query),queue=queryReviewQueue(rows,query),view=params.get('view')==='list'?'list':'grid';
 const standalone=queryAccountLibrary(rows.filter(r=>(!r.mailer||r.mailer.approval)&&['draft','review'].includes(r.status)&&Boolean(r.creative)),{...query,status:'all'});
 const statusCounts={all:queryAccountLibrary(rows,{...query,status:'all'}).total,review:projectMode?queue.total+standalone.total:queryAccountLibrary(rows,{...query,status:'review'}).total,approved:queryAccountLibrary(rows,{...query,status:'approved'}).total};
 const selectedId=params.get('material'),item=rows.find(r=>r.id===selectedId),review=params.get('libraryReview')==='1';
 const campaigns=Array.from(new Map(rows.filter(r=>r.campaignId).map(r=>[r.campaignId!,{value:r.campaignId!,label:r.campaignName??'Unnamed campaign'}])).values());
 const accounts=Array.from(new Map(rows.filter(r=>r.accountId).map(r=>[r.accountId,{value:r.accountId,label:r.accountName??r.mailer?.recipient.company??r.accountId}])).values()).sort((a,b)=>a.label.localeCompare(b.label));
 const recipients=Array.from(new Map(rows.filter(r=>r.contactId).map(r=>[r.contactId!,{value:r.contactId!,label:r.recipient!}])).values());
 function change(values:Record<string,string|null>,push=false) {
  const next=new URLSearchParams(window.location.search);next.delete('catalog');
  for(const [key,value]of Object.entries(values))if(value===null)next.delete(key);else next.set(key,value);
  window.history[push?'pushState':'replaceState'](null,'',`${path}${next.size?`?${next}`:''}`);
 }
 function filter(key:string,value:string){change(libraryFilterPatch(key,value));scroll.current?.scrollTo({top:0});}
 function open(row:LibraryItem,asReview=false){position.current=scroll.current?.scrollTop??0;change({material:row.id,libraryReview:asReview?'1':null,review:asReview?'gift':null},true);}
 function back(){change({material:null,libraryReview:null,review:null,recipient:null},true);requestAnimationFrame(()=>scroll.current?.scrollTo({top:position.current}));}
 function clear(){change({campaign:null,type:null,libraryStatus:null,librarySearch:null,libraryRecipient:null,materialsAccount:'all',libraryPage:null});}
 const related=item?rows.filter(r=>r.id!==item.id&&r.accountId===item.accountId&&r.projectId===item.projectId&&r.campaignId===item.campaignId&&r.campaignId!==null&&(r.contactId===item.contactId||r.contactId===null)):[];
 const tab=outreachTabs.includes(params.get('review') as OutreachTab)?params.get('review') as OutreachTab:item?.kind==='note'?'note':item?.kind==='page'?'page':'gift';
 return {overview:libraryOverview(rows,query),c,w,mail,workspace,projectMode,scroll,rows,query,result,queue,standalone,view,statusCounts,selectedId,item,review,campaigns,accounts,recipients,change,filter,open,back,clear,related,tab,path,error:c.error??w.error};
}
export type ArtifactLibraryController=ReturnType<typeof useArtifactLibrary>;
