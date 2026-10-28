'use client';
import { useMemo } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { useDirectMail } from '@/features/direct-mail/hooks/use-direct-mail';
import { useWorkspace } from '@/features/orchestration/hooks/use-workspace';
import { accountOutreach, queryOutreach, outreachSelection, outreachTabs, type OutreachTab } from '../model/outreach';
export function useOutreachBrowser(projectId?:string,fixedAccount?:string,initialAccount?:string,initialRecipient?:string) {
 const c=useDirectMail(),w=useWorkspace(),params=useSearchParams(),path=usePathname();
 const rows=useMemo(()=>accountOutreach(c.data?.mailers??[],projectId),[c.data,projectId]);
 const accountId=fixedAccount??params.get('materialsAccount')??initialAccount??'all';
 const account=rows.find(a=>a.id===accountId),recipient=outreachSelection(rows,accountId,params.get('recipient')??initialRecipient??null);
 const tab=outreachTabs.includes(params.get('review') as OutreachTab)?params.get('review') as OutreachTab:recipient?.approval?'tracking':'gift';
 const search=params.get('q')??'',status=params.get('status')??'all';
 function change(values:Record<string,string|null>){const next=new URLSearchParams(window.location.search);for(const [key,value] of Object.entries(values)){if(value===null)next.delete(key);else next.set(key,value);}window.history.replaceState(null,"",`${path}?${next}`);}
 const result=queryOutreach(rows,{search,status,page:Number(params.get('p')??1)});
 return {c,w,rows,result,account,recipient,tab,search,status,files:params.get('catalog')==='files',legacy:params.get('catalog')==='earlier',change,
 open:(id:string)=>change({materialsAccount:id,recipient:null,review:null,catalog:null}),
 back:()=>change({materialsAccount:'all',recipient:null,review:null}),
 select:(id:string)=>change({recipient:id,review:null}),
 setTab:(value:OutreachTab)=>change({review:value}),
 };
}
