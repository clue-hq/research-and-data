import { z } from 'zod';
import { PagePatchSchema } from '@/features/direct-mail/model/outreach-page';
const DraftSchema=z.object({version:z.number().int().positive(),patch:PagePatchSchema});
export type PageDraft=z.infer<typeof DraftSchema>;
type Storage=Pick<globalThis.Storage,'getItem'|'setItem'|'removeItem'>;
/** A per-tab recovery buffer; persisted edits still require the expected page version. */
export function pageDraftStore(storage?:Storage){
 const key=(id:string)=>`clue-outreach-page-draft:${id}`;
 return {read(id:string):PageDraft|null {try{const raw=storage?.getItem(key(id));return raw?DraftSchema.parse(JSON.parse(raw)):null;}catch{return null;}},write(id:string,draft:PageDraft|null){try{if(!storage)return false;if(draft)storage.setItem(key(id),JSON.stringify(draft));else storage.removeItem(key(id));return true;}catch{return false;}}};
}
export function browserPageDraftStore(){try{return pageDraftStore(typeof window==='undefined'?undefined:window.sessionStorage);}catch{return pageDraftStore();}}
