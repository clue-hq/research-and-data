'use client';
import { useMemo, useRef } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { FileText, Gift, Globe, Image as ImageIcon, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DesignIcon } from '@/components/ui/design-icon';
import { SelectField } from '@/components/ui/select-field';
import type { AccountArtifact } from '@/features/accounts/model/account-workspace';
import { useDirectMail } from '@/features/direct-mail/hooks/use-direct-mail';
import { isDraft } from '@/features/direct-mail/model/direct-mail';
import { MailerReview } from '@/features/direct-mail/components/mailer-review';
import { MailerTracking } from '@/features/direct-mail/components/mailer-tracking';
import { useWorkspace } from '@/features/orchestration/hooks/use-workspace';
import { buildAccountLibrary, queryAccountLibrary, libraryKinds, libraryStatusLabels, type LibraryItem } from '../model/account-library';
import { outreachTabs, type OutreachTab } from '../model/outreach';
import { OutreachReview } from './outreach-review';
import { LibraryPreview } from './library-preview';
import s from './account-artifact-library.module.css';

const icons={page:Globe,ad:ImageIcon,gift:Gift,note:FileText,file:FileText};
const groups=Object.keys(libraryKinds) as (keyof typeof libraryKinds)[];
type Props={accountId:string;accountName:string;files:AccountArtifact[]};

export function AccountArtifactLibrary({accountId,accountName,files}:Props) {
 const c=useDirectMail(),w=useWorkspace(),params=useSearchParams(),path=usePathname();
 const mail=c.data,workspace=w.data;
 const scroll=useRef<HTMLDivElement>(null),position=useRef(0);
 const rows=useMemo(()=>mail&&workspace?buildAccountLibrary(accountId,workspace,mail,files):[],[accountId,workspace,mail,files]);
 const query={campaignId:params.get('campaign')??'all',contactId:params.get('libraryRecipient')??'all',kind:params.get('type')??'all',status:params.get('libraryStatus')??'all',search:params.get('librarySearch')??'',page:Number(params.get('libraryPage')??1)};
 const result=queryAccountLibrary(rows,query),view=params.get('view')==='list'?'list':'grid';
 const statusCounts=Object.fromEntries(['all','review','approved'].map(status=>[status,queryAccountLibrary(rows,{...query,status}).total]));
 const selectedId=params.get('material'),item=rows.find(r=>r.id===selectedId),review=params.get('libraryReview')==='1';
 const campaigns=Array.from(new Map(rows.filter(r=>r.campaignId).map(r=>[r.campaignId!,{value:r.campaignId!,label:r.campaignName??'Unnamed campaign'}])).values());
 const recipients=Array.from(new Map(rows.filter(r=>r.contactId).map(r=>[r.contactId!,{value:r.contactId!,label:r.recipient!}])).values());
 function change(values:Record<string,string|null>,push=false) {
  const next=new URLSearchParams(window.location.search);
  // Retire the split catalogs, while preserving project/return context and library filters.
  next.delete('catalog');
  for(const [key,value]of Object.entries(values))if(value===null)next.delete(key);else next.set(key,value);
  window.history[push?'pushState':'replaceState'](null,'',`${path}${next.size?`?${next}`:''}`);
 }
 function filter(key:string,value:string){change({[key]:value,libraryPage:null});scroll.current?.scrollTo({top:0});}
 function open(row:LibraryItem){position.current=scroll.current?.scrollTop??0;change({material:row.id,libraryReview:null,review:null},true);}
 function back(){change({material:null,libraryReview:null,review:null},true);requestAnimationFrame(()=>scroll.current?.scrollTo({top:position.current}));}
 const error=c.error??w.error;
 const related=item?rows.filter(r=>r.id!==item.id&&r.projectId===item.projectId&&r.campaignId===item.campaignId&&r.campaignId!==null&&(r.contactId===item.contactId||r.contactId===null)):[];
 const tab=outreachTabs.includes(params.get('review') as OutreachTab)?params.get('review') as OutreachTab:item?.kind==='note'?'note':item?.kind==='page'?'page':'gift';
 const selectedCampaign=campaigns.find(c=>c.value===query.campaignId);
 function renderCard(row:LibraryItem) {
  const Icon=icons[row.kind];
  return <button className={s.card} key={row.id} onClick={()=>open(row)} aria-label={`Preview ${row.title} · ${row.recipient??'Account-wide'} · ${row.campaignName??'Unassigned'}`}>
   <div className={s.thumbnail} aria-hidden="true"><LibraryPreview item={row} mail={mail!} workspace={workspace!} compact/></div>
   <div className={s.cardBody}><div className={s.cardTitle}><Icon size={15} strokeWidth={1.5}/><strong>{row.title}</strong></div><p>{row.recipient??'Account-wide'}<span aria-hidden="true"> · </span>{row.campaignName??'No campaign assigned'}</p><div className={s.cardFooter}><span data-status={row.status}>{libraryStatusLabels[row.status]}</span><span>{row.execution??(row.version?`Version ${row.version}`:'')}</span></div></div>
  </button>;
 }
 return <section className={s.surface} aria-label={`${accountName} artifact library`}>
 {error?<div className={s.error} role="alert">{error}<Button variant="transparent" size="sm" onClick={()=>{void c.reload();void w.reload();}}>Retry</Button></div>:null}
 {!mail||!workspace?<p className={s.empty} role="status">{error?'Artifacts could not be loaded.':'Loading artifacts…'}</p>:<>
 <div ref={scroll} className={s.scroll} hidden={Boolean(selectedId)}>
  <div className={s.canvas}>
   <header className={s.heading}><div><h1>Artifacts</h1><p>Everything created for {accountName}, across campaigns.</p></div><span className={s.subtle}>{rows.length} materials · {campaigns.length} campaigns</span></header>
   <nav className={s.tabs} aria-label="Artifact approval status">{[['all','All materials'],['review','Needs review'],['approved','Approved']].map(([id,label])=><button key={id} aria-current={query.status===id?'page':undefined} onClick={()=>filter('libraryStatus',id)}>{label}<span>{statusCounts[id]}</span></button>)}</nav>
   <div className={s.toolbar}><label className={s.search}><Search size={14}/><input aria-label="Search account artifacts" placeholder="Search materials" value={query.search} onChange={e=>filter('librarySearch',e.target.value)}/></label>
    <div className={s.campaignFilter}><SelectField ariaLabel="Artifact campaign" value={query.campaignId} options={[{value:'all',label:'All campaigns'},...campaigns,...(rows.some(r=>!r.campaignId)?[{value:'unassigned',label:'Unassigned'}]:[])]} onValueChange={v=>filter('campaign',v)}/></div>
    <div className={s.typeFilter}><SelectField ariaLabel="Artifact type" value={query.kind} options={[{value:'all',label:'All types'},...groups.map(value=>({value,label:libraryKinds[value]}))]} onValueChange={v=>filter('type',v)}/></div>
    <div className={s.recipientFilter}><SelectField ariaLabel="Artifact recipient" value={query.contactId} options={[{value:'all',label:'All recipients'},...recipients]} onValueChange={v=>filter('libraryRecipient',v)}/></div>
    <div className={s.views} aria-label="Library view" role="group">{(['grid','list']as const).map(mode=><button key={mode} aria-label={`${mode==='grid'?'Grid':'List'} view`} aria-pressed={view===mode} onClick={()=>change({view:mode})}><DesignIcon name={mode==='grid'?'projects/gallery':'projects/list'} size={15}/></button>)}</div>
   </div>
   {selectedCampaign?<div className={s.campaignContext}><div><strong>{selectedCampaign.label}</strong><span>{workspace.campaigns.find(c=>c.id===selectedCampaign.value)?.purpose}</span></div><span>{workspace.project.name}</span></div>:null}
   <div className={s.results} aria-live="polite"><span>{result.total===rows.length?`${result.total} materials`:`${result.total} of ${rows.length} materials`}</span>{query.contactId!=='all'?<span>Includes shared account materials</span>:null}</div>
   {!result.total?<div className={s.empty}><FileText size={24} strokeWidth={1.25}/><h2>{rows.length?'No matching materials':'No artifacts yet'}</h2><p>{rows.length?'Try another campaign, recipient or type.':`Work generated for ${accountName} will appear here.`}</p>{rows.length?<Button variant="outline" size="sm" onClick={()=>change({campaign:null,type:null,libraryStatus:null,librarySearch:null,libraryRecipient:null,libraryPage:null})}>Clear filters</Button>:null}</div>:view==='grid'?groups.map(kind=>{const items=result.rows.filter(r=>r.kind===kind);return items.length?<section key={kind} className={s.group}><h2>{libraryKinds[kind]} <span>{items.length}</span></h2><div className={s.grid}>{items.map(renderCard)}</div></section>:null;}):<div className={s.tableWrap}><table className={s.table}><thead><tr><th>Material</th><th>Campaign</th><th>Recipient</th><th>Approval</th><th>Delivery / publication</th></tr></thead><tbody>{result.rows.map(row=><tr key={row.id}><td><button aria-label={`Preview ${row.title} · ${row.recipient??"Account-wide"} · ${row.campaignName??"Unassigned"}`} onClick={()=>open(row)}><span className={s.rowPreview} aria-hidden="true"><LibraryPreview item={row} mail={mail} workspace={workspace} compact/></span><span>{row.title}<small>{libraryKinds[row.kind]}</small></span></button></td><td>{row.campaignName??'Unassigned'}</td><td>{row.recipient??'Account-wide'}</td><td>{libraryStatusLabels[row.status]}</td><td>{row.execution??'—'}</td></tr>)}</tbody></table></div>}
   {result.pages>1?<footer className={s.pagination}><span>{result.page} / {result.pages}</span><Button variant="transparent" size="sm" disabled={result.page===1} onClick={()=>change({libraryPage:String(result.page-1)})}>Previous</Button><Button variant="transparent" size="sm" disabled={result.page===result.pages} onClick={()=>change({libraryPage:String(result.page+1)})}>Next</Button></footer>:null}
  </div>
 </div>
 {selectedId?<div className={s.detailScroll}>
  <header className={s.detailHeader}><Button variant="transparent" size="sm" onClick={back}>All materials</Button>{item?<><span className={s.divider}/><span>{item.campaignName??'Unassigned'}<span className={s.subtle}> · {item.recipient??accountName}</span></span></>:null}</header>
  {!item?<div className={s.empty}><h2>Material unavailable</h2><p>This material is not available in {accountName}’s library.</p><Button variant="outline" size="sm" onClick={back}>Back to materials</Button></div>:review&&item.mailer?<>
   <div className={s.reviewHeading}><div><h1>{item.recipient}</h1><p>{item.campaignName} · {accountName}</p></div><Button variant="outline" size="sm" onClick={()=>change({libraryReview:null,review:null},true)}>Back to preview</Button></div>
   {item.mailer.pageId?<OutreachReview key={item.mailer.id} saved={item.mailer} controller={c} tab={tab} onTab={t=>change({review:t})}/>:isDraft(item.mailer)?<MailerReview key={item.mailer.id} saved={item.mailer} controller={c} initialStep={item.kind==='note'?1:0} queueHref={path} onBack={()=>change({libraryReview:null})} onOpenPage={()=>{const p=related.find(r=>r.kind==='page');if(p)open(p);}}/>:<MailerTracking controller={c} mailer={item.mailer}/>}
  </>:<div className={s.detailCanvas}>
   <div className={s.previewColumn}><div className={s.previewHeading}><h1>{item.title}</h1><span>{item.version?`Version ${item.version}`:''}</span></div><div className={s.largePreview}><LibraryPreview item={item} mail={mail} workspace={workspace}/></div></div>
   <aside className={s.context}><h2>About this material</h2><dl><dt>Campaign</dt><dd>{item.campaignName?<button onClick={()=>{change({material:null,libraryReview:null,campaign:item.campaignId,libraryPage:null},true);}}>{item.campaignName}</button>:'Unassigned'}</dd><dt>Project</dt><dd>{item.projectName??'Not assigned'}</dd><dt>Prepared for</dt><dd>{item.recipient??`${accountName} buying committee`}</dd><dt>Approval</dt><dd>{libraryStatusLabels[item.status]}</dd>{item.execution?<><dt>{item.kind==='gift'?'Delivery':item.kind==='page'?'Publication':'Activation'}</dt><dd>{item.execution}</dd></>:null}{item.mailer?<><dt>From</dt><dd>{(item.mailer.approval?.signature??item.mailer.signature).split('\n')[0]}</dd></>:null}</dl>
    {item.mailer?<Button variant="primary" size="md" onClick={()=>change({libraryReview:'1',review:item.mailer?.approval?'tracking':item.kind==='page'?'page':item.kind==='note'?'note':'gift'},true)}>{item.mailer.approval?'View approved outreach':'Review recipient outreach'}</Button>:null}
    {related.length?<div className={s.related}><h2>In this campaign</h2>{related.map(r=>{const Icon=icons[r.kind];return <button key={r.id} onClick={()=>open(r)}><Icon size={16} strokeWidth={1.5}/><span>{r.title}<small>{r.recipient??'Shared with the account'}</small></span></button>;})}</div>:null}
   </aside>
  </div>}
 </div>:null}
 </>}
 </section>;
}
