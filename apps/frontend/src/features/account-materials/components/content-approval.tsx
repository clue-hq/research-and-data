'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { MailDialog } from '@/features/direct-mail/components/mail-ui';
import type { WorkspaceController } from '@/features/orchestration/hooks/use-workspace';
import type { LibraryItem } from '../model/account-library';
import s from './account-artifact-library.module.css';

export function ContentApproval({item,controller:c}:{item:LibraryItem;controller:WorkspaceController}) {
 const [version,setVersion]=useState<number|null>(null);
 const asset=item.creative;
 if(!asset)return null;
 return <div className={s.contentApproval}>
  <p className={s.subtle}>{item.status==='approved'?`Content approved · version ${asset.version}`:'Approve the content after reviewing this preview.'} {item.kind==='ad'?'Campaign launch and media budget are approved separately.':'Publishing is a separate action.'}</p>
  {item.status!=='approved'?<Button variant="outline" size="md" disabled={c.pending} onClick={()=>setVersion(asset.version)}>Approve content</Button>:null}
  {version!==null?<MailDialog title="Approve this content?" description={`${item.title} · Version ${version}. This records content approval only.`} busy={c.pending} close={()=>setVersion(null)}>
   <p className={s.subtle}>This preview saves the approval locally. It does not publish a page, launch an ad or spend a campaign budget.</p>
   {c.error?<p role="alert">{c.error}</p>:null}
   <div className={s.approvalActions}><Button variant="transparent" disabled={c.pending} onClick={()=>setVersion(null)}>Back to preview</Button><Button variant="primary" disabled={c.pending} onClick={async()=>{if(c.repository&&await c.run(()=>c.repository!.approveContent(asset.id,version)))setVersion(null);}}>{c.pending?'Approving…':'Confirm content approval'}</Button></div>
  </MailDialog>:null}
 </div>;
}
