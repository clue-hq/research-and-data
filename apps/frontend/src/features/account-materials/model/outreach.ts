import { isDraft, type Mailer } from '@/features/direct-mail/model/direct-mail';
export const WALKTHROUGH_CAMPAIGN='campaign-field-conversations';
export const WALKTHROUGH_NAME='Field conversations';
export const outreachTabs=['gift','note','page','review','tracking'] as const;
export type OutreachTab=typeof outreachTabs[number];
export type AccountOutreach={id:string;name:string;recipients:Mailer[];review:number;ready:number;attention:number;active:number;delivered:number};
export function accountOutreach(mailers:Mailer[],projectId?:string):AccountOutreach[] {
 const accounts=new Map<string,AccountOutreach>();
 for(const m of mailers){
  if(m.campaignId!==WALKTHROUGH_CAMPAIGN || (projectId && m.projectId!==projectId))continue;
  const a=accounts.get(m.accountId)??{id:m.accountId,name:m.recipient.company,recipients:[],review:0,ready:0,attention:0,active:0,delivered:0};
  a.recipients.push(m);if(isDraft(m)){a.review++;if(m.stage==='ready')a.ready++;if(!m.addressConfirmed||m.exception)a.attention++;}else if(m.stage==='delivered')a.delivered++;else if(m.stage!=='canceled')a.active++;
  accounts.set(a.id,a);
 }
 return [...accounts.values()];
}
export function queryOutreach(rows:AccountOutreach[],filter:{search:string;status:string;page:number}) {
 const search=filter.search.trim().toLowerCase();
 const matches=rows.filter(a=>(!search||[a.name,...a.recipients.map(m=>m.recipient.name)].join(' ').toLowerCase().includes(search)) && (filter.status==='all'||(filter.status==='review'?a.review:filter.status==='ready'?a.ready:filter.status==='attention'?a.attention:filter.status==='delivered'?a.delivered:a.active)>0));
 const pages=Math.max(1,Math.ceil(matches.length/25)),page=Math.max(1,Math.min(pages,Number.isFinite(filter.page)?filter.page:1));
 return {rows:matches.slice((page-1)*25,page*25),total:matches.length,pages,page};
}
export function outreachSelection(rows:AccountOutreach[],accountId:string,recipientId:string|null) {
 const account=rows.find(a=>a.id===accountId);
 return account?.recipients.find(m=>m.id===recipientId)??account?.recipients[0];
}
/** Explicit table handoff owns its account and clears the previous recipient context. */
export function accountReviewQuery(query:string,accountId:string){
 const next=new URLSearchParams(query);next.set('surface','gallery');next.set('materialsAccount',accountId);
 for(const key of ['recipient','review','material','catalog','libraryReview','libraryRecipient','libraryPage','libraryStatus','librarySearch','type','campaign'])next.delete(key);
 return next.toString();
}
export function earlierMailers(mailers:Mailer[]){return mailers.filter(m=>m.campaignId!==WALKTHROUGH_CAMPAIGN);}
