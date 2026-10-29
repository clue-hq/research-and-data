'use client';
import { Button } from '@/components/ui/button';
import { MailDialog } from '@/features/direct-mail/components/mail-ui';
import type { WorkspaceController } from '@/features/orchestration/hooks/use-workspace';
import type { LibraryItem } from '../model/account-library';
import s from './account-artifact-library.module.css';
import { useContentApproval } from '../hooks/use-content-approval';

export function ContentApproval({item,controller:c}:{item:LibraryItem;controller:WorkspaceController}) {
 const asset=item.creative;
 const {confirmation,begin,close,confirm}=useContentApproval(asset,c);
 if(!asset)return null;
 return <div className={s.contentApproval}>
  <p className={s.subtle}>{item.status==='approved'?`Content approved · version ${asset.version}`:'Approve the content after reviewing this preview.'} {item.kind==='ad'?'Campaign launch and media budget are approved separately.':'Publishing is a separate action.'}</p>
  {item.status!=='approved'?<Button variant="outline" size="md" disabled={c.pending} onClick={begin}>Approve content</Button>:null}
  {confirmation!==null?<MailDialog title="Approve this content?" description={`${confirmation.title} · Version ${confirmation.version}. This records content approval only.`} busy={c.pending} close={close}>
   <p className={s.subtle}>This preview saves the approval locally. It does not publish a page, launch an ad or spend a campaign budget.</p>
   {c.error?<p role="alert">{c.error}</p>:null}
   <div className={s.approvalActions}><Button variant="transparent" disabled={c.pending} onClick={close}>Back to preview</Button><Button variant="primary" disabled={c.pending} onClick={()=>void confirm()}>{c.pending?'Approving…':'Confirm content approval'}</Button></div>
  </MailDialog>:null}
 </div>;
}
