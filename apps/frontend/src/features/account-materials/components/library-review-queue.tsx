'use client';
import { Button } from '@/components/ui/button';
import { ApprovalDialog } from '@/features/direct-mail/components/mail-ui';
import { estimate, money, readiness, selectedGift } from '@/features/direct-mail/model/direct-mail';
import { ProductImage } from '@/features/direct-mail/components/product-image';
import type { ArtifactLibraryController } from '../hooks/use-artifact-library';
import { useLibraryApproval } from '../hooks/use-library-approval';
import { ApprovalBadge, MaterialBadge } from './material-badge';
import s from './account-artifact-library.module.css';

export function LibraryReviewQueue({library:b}:{library:ArtifactLibraryController}) {
 const a=useLibraryApproval(b.c,b.queue.rows);
 return <section className={s.reviewQueue} aria-label="Direct mail approvals">
  <div className={s.queueHeading}><div><h2>Direct mail <span>{b.queue.total} {b.queue.total===1?'recipient':'recipients'}</span></h2><p>Review the gift, card, linked page and total cost before approving a send.</p></div>{a.picked.length?<Button variant="primary" size="sm" disabled={b.c.pending} onClick={a.begin}>Approve {a.picked.length} reviewed</Button>:null}</div>
  <div className={s.reviewList}>{b.queue.rows.map(({mailer:m,materials,entry})=>{const gift=selectedGift(m),issues=readiness(m,b.mail!),ready=a.eligible(m);return <article key={m.id} className={s.reviewRow}>
   <input type="checkbox" className={s.reviewCheck} aria-label={`Select reviewed send to ${m.recipient.name} at ${m.recipient.company}`} checked={a.picked.some(p=>p.id===m.id)} disabled={!ready||b.c.pending} onChange={e=>a.toggle(m,e.target.checked)}/>
   <div className={s.reviewProduct}>{gift?<ProductImage src={gift.image} alt={gift.name}/>:null}</div>
   <div className={s.reviewIdentity}><h3>{m.recipient.name}</h3><p>{m.recipient.company} · {m.recipient.role}</p><span>{entry.campaignName??'Unassigned campaign'} · From {m.signature.split('\n')[0]}</span><div className={s.badgeLine}>{(['gift','note','page'] as const).filter(kind=>materials.some(r=>r.kind===kind)).map(kind=><MaterialBadge key={kind} kind={kind}/>)}</div></div>
   <div className={s.reviewDecision}><ApprovalBadge tone={ready?'positive':issues.some(i=>i.includes('address'))?'attention':'neutral'}>{ready?'Ready to approve':issues.some(i=>i.includes('address'))?'Address needed':'Needs review'}</ApprovalBadge><span>{money(estimate(m))} <small>estimated total</small></span><Button variant="outline" size="sm" onClick={()=>b.open(entry,true)}>Review send</Button></div>
  </article>;})}</div>
  {b.queue.pages>1?<footer className={s.pagination}><span>{(b.queue.page-1)*24+1}–{Math.min(b.queue.page*24,b.queue.total)} of {b.queue.total} {b.queue.total===1?'recipient':'recipients'}</span><Button variant="transparent" size="sm" disabled={b.queue.page===1} onClick={()=>b.filter('libraryPage',String(b.queue.page-1))}>Previous</Button><Button variant="transparent" size="sm" disabled={b.queue.page===b.queue.pages} onClick={()=>b.filter('libraryPage',String(b.queue.page+1))}>Next</Button></footer>:null}
  {a.confirmation?<ApprovalDialog mailers={a.confirmation} busy={b.c.pending} close={a.close} approve={()=>void a.approve()} error={a.error??b.c.error}/>:null}
 </section>;
}
