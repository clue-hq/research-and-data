'use client';
import { FileText, Gift, Globe, Image as ImageIcon, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DesignIcon } from '@/components/ui/design-icon';
import { SelectField } from '@/components/ui/select-field';
import type { AccountArtifact } from '@/features/accounts/model/account-workspace';
import { isDraft } from '@/features/direct-mail/model/direct-mail';
import { MailerReview } from '@/features/direct-mail/components/mailer-review';
import { MailerTracking } from '@/features/direct-mail/components/mailer-tracking';
import { libraryKinds, libraryStatusLabels, type LibraryItem } from '../model/account-library';
import type { GalleryArtifact } from '@/features/gallery/model/project-gallery';
import { useArtifactLibrary, type LibraryScope } from '../hooks/use-artifact-library';
import { MaterialBadge, ApprovalBadge } from './material-badge';
import { ContentApproval } from './content-approval';
import { LibraryReviewQueue } from './library-review-queue';
import { OutreachReview } from './outreach-review';
import { LibraryPreview } from './library-preview';
import s from './account-artifact-library.module.css';

const icons={page:Globe,ad:ImageIcon,gift:Gift,note:FileText,file:FileText};
const groups=Object.keys(libraryKinds) as (keyof typeof libraryKinds)[];
type Props={accountId:string;accountName:string;files:AccountArtifact[]};

export function AccountArtifactLibrary(props:Props) { return <ArtifactLibrary {...props}/>; }
export function ProjectArtifactLibrary(props:LibraryScope & {onOpenNative:(artifact:GalleryArtifact)=>void;documentsLoading?:boolean;documentsError?:string|null;onRetryDocuments?:()=>void}) { return <ArtifactLibrary {...props}/>; }
function ArtifactLibrary(props:LibraryScope & {onOpenNative?:(artifact:GalleryArtifact)=>void;documentsLoading?:boolean;documentsError?:string|null;onRetryDocuments?:()=>void}) {
 const b=useArtifactLibrary(props);
 const {c,mail,workspace,scroll,rows,query,view,statusCounts,selectedId,item,review,campaigns,recipients,change,filter,open,back,clear,related,tab,path,error,projectMode}=b;
 const accountName=item?.accountName??item?.mailer?.recipient.company??props.accountName??'this account';
 const reviewMode=projectMode&&query.status==='review';
 const result=reviewMode?b.standalone:b.result;
 const overviewMode=projectMode&&!reviewMode&&view==='grid'&&query.kind==='all';
 const selectedCampaign=campaigns.find(c=>c.value===query.campaignId);
 function renderCard(row:LibraryItem) {
  const Icon=icons[row.kind];
  return <button className={s.card} key={row.id} onClick={()=>open(row)} aria-label={`Preview ${row.title} · ${row.recipient??(row.accountId?'Account-wide':'Project-wide')} · ${row.campaignName??'Unassigned'}`}>
   <div className={s.thumbnail} aria-hidden="true"><LibraryPreview item={row} mail={mail!} workspace={workspace!} compact/></div>
   <div className={s.cardBody}><div className={s.cardTitle}><Icon size={15} strokeWidth={1.5}/><strong>{row.title}</strong></div><p>{projectMode ? `${row.accountName??'Project'} · ` : ''}{row.recipient??(row.accountId?'Account-wide':'Shared document')}</p><p>{row.campaignName??'No campaign assigned'}</p><div className={s.cardFooter}><MaterialBadge kind={row.kind}/><ApprovalBadge tone={row.status==='approved'?'positive':'neutral'}>{libraryStatusLabels[row.status]}</ApprovalBadge></div>{row.execution?<p className={s.execution}>{row.kind==='gift'?'Delivery':row.kind==='page'?'Publication':'Activation'} · {row.execution}</p>:null}</div>
  </button>;
 }
 return <section className={s.surface} aria-label={projectMode?'Project artifact library':`${accountName} artifact library`}>
 {error?<div className={s.error} role="alert">{error}<Button variant="transparent" size="sm" onClick={()=>{void c.reload();void b.w.reload();}}>Retry</Button></div>:null}
 {!mail||!workspace?<p className={s.empty} role="status">{error?'Artifacts could not be loaded.':'Loading artifacts…'}</p>:<>
 <div ref={scroll} className={s.scroll} hidden={Boolean(selectedId)}>
  <div className={s.canvas}>
   <header className={s.heading}><div><h1>{projectMode?'Project artifacts':'Artifacts'}</h1><p>{projectMode?`${props.projectTitle??workspace.project.name} · Materials across campaigns and chats.`: `Everything created for ${accountName}, across campaigns.`}</p></div><span className={s.subtle}>{rows.length} materials · {campaigns.length} campaigns</span></header>
   <nav className={s.tabs} aria-label="Artifact approval status">{([['all','All materials'],['review','Needs review'],['approved','Approved']] as const).map(([id,label])=><button key={id} aria-current={query.status===id?'page':undefined} onClick={()=>filter('libraryStatus',id)}>{label}<span>{statusCounts[id]}</span></button>)}</nav>
   <div className={s.toolbar}><label className={s.search}><Search size={14}/><input aria-label={projectMode?'Search project artifacts':'Search account artifacts'} placeholder={projectMode?"Search materials or accounts":"Search materials"} value={query.search} onChange={e=>filter('librarySearch',e.target.value)}/></label>
    <div className={s.campaignFilter}><SelectField ariaLabel="Artifact campaign" value={query.campaignId} options={[{value:'all',label:'All campaigns'},...campaigns,...(rows.some(r=>!r.campaignId)?[{value:'unassigned',label:'Unassigned'}]:[])]} onValueChange={v=>filter('campaign',v)}/></div>
    <div className={s.typeFilter}><SelectField ariaLabel="Artifact type" value={query.kind} options={[{value:'all',label:'All types'},...groups.map(value=>({value,label:libraryKinds[value]}))]} onValueChange={v=>filter('type',v)}/></div>
    {projectMode?<div className={s.accountFilter}><SelectField ariaLabel="Artifact account" value={query.accountId??'all'} options={[{value:'all',label:'All accounts'},...b.accounts]} onValueChange={v=>filter('materialsAccount',v)}/></div>:<div className={s.recipientFilter}><SelectField ariaLabel="Artifact recipient" value={query.contactId} options={[{value:'all',label:'All recipients'},...recipients]} onValueChange={v=>filter('libraryRecipient',v)}/></div>}
    <div className={s.views} aria-label="Library view" role="group">{(['grid','list']as const).map(mode=><button key={mode} aria-label={`${mode==='grid'?'Grid':'List'} view`} aria-pressed={view===mode} onClick={()=>change({view:mode})}><DesignIcon name={mode==='grid'?'projects/gallery':'projects/list'} size={15}/></button>)}</div>
   </div>
   {selectedCampaign?<div className={s.campaignContext}><div><strong>{selectedCampaign.label}</strong><span>{workspace.campaigns.find(c=>c.id===selectedCampaign.value)?.purpose}</span></div><span>{workspace.project.name}</span></div>:null}
   <div className={s.results} aria-live="polite"><span>{reviewMode?`${b.queue.total} ${b.queue.total===1?'send':'sends'} to review${result.total?` · ${result.total} other materials`:""}`:result.total===rows.length?`${result.total} materials`:`${result.total} of ${rows.length} materials`}</span>{query.contactId!=='all'?<span>Includes shared account materials</span>:null}</div>
   {props.documentsError?<div className={s.error} role="alert">Project files could not be loaded. <Button variant="transparent" size="sm" onClick={props.onRetryDocuments}>Retry files</Button></div>:props.documentsLoading?<p role="status" className={s.subtle}>Loading project files…</p>:null}
   {reviewMode&&b.queue.total>0?<LibraryReviewQueue library={b}/>:null}
   {!result.total&&(!reviewMode||!b.queue.total)?<div className={s.empty}><FileText size={24} strokeWidth={1.25}/><h2>{rows.length?'No matching materials':'No artifacts yet'}</h2><p>{rows.length?'Try another campaign, recipient or type.':`Work generated for ${projectMode?'this project':accountName} will appear here.`}</p>{rows.length?<Button variant="outline" size="sm" onClick={clear}>Clear filters</Button>:null}</div>:!result.total?null:overviewMode?b.overview.map(group=><section key={group.kind} className={s.group}><div className={s.groupHeading}><h2>{libraryKinds[group.kind]} <span>{group.total}</span></h2>{group.total>group.rows.length?<Button size="sm" variant="transparent" onClick={()=>filter('type',group.kind)}>View all {group.total}</Button>:null}</div><div className={s.grid}>{group.rows.map(renderCard)}</div></section>):view==='grid'?groups.map(kind=>{const items=result.rows.filter(r=>r.kind===kind);return items.length?<section key={kind} className={s.group}><h2>{libraryKinds[kind]} <span>{items.length}</span></h2><div className={s.grid}>{items.map(renderCard)}</div></section>:null;}):<div className={s.tableWrap}><table className={s.table}><thead><tr><th>Material</th>{projectMode?<th>Account</th>:null}<th>Campaign</th><th>Recipient</th><th>Approval</th><th>Delivery / publication</th></tr></thead><tbody>{result.rows.map(row=><tr key={row.id}><td><button aria-label={`Preview ${row.title} · ${row.recipient??(row.accountId?'Account-wide':'Project-wide')} · ${row.campaignName??"Unassigned"}`} onClick={()=>open(row)}><span className={s.rowPreview} aria-hidden="true"><LibraryPreview item={row} mail={mail} workspace={workspace} compact/></span><span>{row.title}<small>{libraryKinds[row.kind]}</small></span></button></td>{projectMode?<td>{row.accountName??'Project-wide'}</td>:null}<td>{row.campaignName??'Unassigned'}</td><td>{row.recipient??(row.accountId?'Account-wide':'Project-wide')}</td><td><ApprovalBadge tone={row.status==='approved'?'positive':'neutral'}>{libraryStatusLabels[row.status]}</ApprovalBadge></td><td>{row.execution??'—'}</td></tr>)}</tbody></table></div>}
   {!overviewMode&&result.pages>1?<footer className={s.pagination}><span>{result.page} / {result.pages}</span><Button variant="transparent" size="sm" disabled={result.page===1} onClick={()=>change({libraryPage:String(result.page-1)})}>Previous</Button><Button variant="transparent" size="sm" disabled={result.page===result.pages} onClick={()=>change({libraryPage:String(result.page+1)})}>Next</Button></footer>:null}
  </div>
 </div>
 {selectedId?<div className={s.detailScroll}>
  <header className={s.detailHeader}><Button variant="transparent" size="sm" onClick={back}>{reviewMode?'Needs review':'All materials'}</Button>{item?<><span className={s.divider}/><span>{item.campaignName??'Unassigned'}<span className={s.subtle}> · {item.recipient??(item.accountId?accountName:'Project-wide')}</span></span></>:null}</header>
  {!item?<div className={s.empty}><h2>Material unavailable</h2><p>This material is not available in this {projectMode?'project':'account'} library.</p><Button variant="outline" size="sm" onClick={back}>Back to materials</Button></div>:review&&item.mailer?<>
   <div className={s.reviewHeading}><div><h1>{item.recipient}</h1><p>{item.campaignName} · {accountName}</p></div><Button variant="outline" size="sm" onClick={()=>change({libraryReview:null,review:null},true)}>Back to preview</Button></div>
   {item.mailer.pageId?<OutreachReview key={item.mailer.id} saved={item.mailer} controller={c} tab={tab} onTab={t=>change({review:t})}/>:isDraft(item.mailer)?<MailerReview key={item.mailer.id} saved={item.mailer} controller={c} initialStep={item.kind==='note'?1:0} queueHref={path} onBack={()=>change({libraryReview:null})} onOpenPage={related.some(r=>r.kind==='page')?()=>{const p=related.find(r=>r.kind==='page');if(p)open(p);}:undefined}/>:<MailerTracking controller={c} mailer={item.mailer}/>}
  </>:<div className={s.detailCanvas}>
   <div className={s.previewColumn}><div className={s.previewHeading}><h1>{item.title}</h1><span>{item.version?`Version ${item.version}`:''}</span></div><div className={s.largePreview}><LibraryPreview item={item} mail={mail} workspace={workspace}/></div></div>
   <aside className={s.context}><h2>About this material</h2><dl><dt>Campaign</dt><dd>{item.campaignName?<button onClick={()=>{change({material:null,libraryReview:null,campaign:item.campaignId,libraryPage:null},true);}}>{item.campaignName}</button>:'Unassigned'}</dd><dt>Project</dt><dd>{item.projectName??'Not assigned'}</dd><dt>Prepared for</dt><dd>{item.recipient??(item.accountId?`${accountName} buying committee`:'Project-wide')}</dd><dt>Approval</dt><dd>{libraryStatusLabels[item.status]}</dd>{item.execution?<><dt>{item.kind==='gift'?'Delivery':item.kind==='page'?'Publication':'Activation'}</dt><dd>{item.execution}</dd></>:null}{item.mailer?<><dt>From</dt><dd>{(item.mailer.approval?.signature??item.mailer.signature).split('\n')[0]}</dd></>:null}</dl>
    {item.gallery&&props.onOpenNative?<Button variant="primary" size="md" onClick={()=>props.onOpenNative?.(item.gallery!)}>{item.gallery.document?'Open document':'Open in editor'}</Button>:null}
    {item.creative?<ContentApproval key={item.id} item={item} controller={b.w}/>:null}
    {item.mailer?<Button variant="primary" size="md" onClick={()=>change({libraryReview:'1',review:item.mailer?.approval?'tracking':item.kind==='page'?'page':item.kind==='note'?'note':'gift'},true)}>{item.mailer.approval?'View approved outreach':'Review recipient outreach'}</Button>:null}
    {related.length?<div className={s.related}><h2>In this campaign</h2>{related.map(r=>{const Icon=icons[r.kind];return <button key={r.id} onClick={()=>open(r)}><Icon size={16} strokeWidth={1.5}/><span>{r.title}<small>{r.recipient??'Shared with the account'}</small></span></button>;})}</div>:null}
   </aside>
  </div>}
 </div>:null}
 </>}
 </section>;
}
