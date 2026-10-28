'use client';
import { useState } from 'react';
import type { OutreachPage, PagePatch } from '@/features/direct-mail/model/outreach-page';
import { browserPageDraftStore, type PageDraft } from '../data/page-draft';
export function usePageDraft(page?:OutreachPage){
 const [draft,setDraft]=useState<PageDraft|null>(()=>page?browserPageDraftStore().read(page.id):null);
 const [error,setError]=useState<string|null>(null);
 function replace(next:PageDraft|null){setDraft(next);if(page&&!browserPageDraftStore().write(page.id,next))setError('Page draft recovery is unavailable. Save the page before leaving this recipient.');else setError(null);}
 function edit(patch:PagePatch){if(page)replace({version:draft?.version??page.version,patch:{...draft?.patch,...patch}});}
 return {draft,error,edit,discard:()=>replace(null)};
}
