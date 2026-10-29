'use client';
import { useState } from 'react';
import type { DirectMailController } from '@/features/direct-mail/hooks/use-direct-mail';
import { readiness, type Mailer } from '@/features/direct-mail/model/direct-mail';
import type { RecipientReview } from '../model/project-library';

export function useLibraryApproval(c:DirectMailController,rows:RecipientReview[]) {
 const [selected,setSelected]=useState<Record<string,number>>({}),[confirmation,setConfirmation]=useState<Mailer[]|null>(null),[error,setError]=useState<string|null>(null);
 const eligible=(m:Mailer)=>Boolean(c.data&&m.stage==='ready'&&m.reviewedRevision===m.revision&&!readiness(m,c.data).length);
 // Selection belongs to the visible page and exact reviewed revision, never an unseen newer draft.
 const picked=rows.filter(r=>selected[r.mailer.id]===r.mailer.revision&&eligible(r.mailer)).map(r=>r.mailer);
 function toggle(m:Mailer,checked:boolean){setSelected(current=>{const next={...current};if(checked)next[m.id]=m.revision;else delete next[m.id];return next;});}
 async function approve(){if(!confirmation)return;const result=await c.run(()=>c.repository.approve(confirmation.map(m=>({id:m.id,revision:m.revision}))));if(result?.results.every(r=>r.ok)){setConfirmation(null);setSelected({});}else if(result)setError(result.results.filter(r=>!r.ok).map(r=>r.message).join(' '));}
 return {eligible,picked,toggle,confirmation,error,begin(){setError(null);setConfirmation(picked);},close(){setConfirmation(null);},approve};
}
