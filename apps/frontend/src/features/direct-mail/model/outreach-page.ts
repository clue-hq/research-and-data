import { z } from "zod";
import type { DirectMailState } from "./direct-mail";

export const OutreachPageSchema = z.object({
  id: z.string(), projectId: z.string(), accountId: z.string(), contactId: z.string(), mailerId: z.string(),
  version: z.number().int().positive(), reviewedVersion: z.number().nullable(),
  title: z.string(), headline: z.string().trim().min(1).max(180), body: z.string().trim().min(1).max(1200),
  cta: z.string().trim().min(1).max(80), publication: z.enum(["draft", "published"]),
});
export type OutreachPage = z.infer<typeof OutreachPageSchema>;
export const PagePatchSchema = OutreachPageSchema.pick({ headline:true, body:true, cta:true }).partial().strict();
export type PagePatch = z.infer<typeof PagePatchSchema>;
function requirePage(state:DirectMailState,id:string,version:number) {
  const page=state.pages?.find(p=>p.id===id);
  if(!page)throw new Error("This landing page is unavailable.");
  if(page.version!==version)throw new Error("The landing page changed in another view. Reload before saving.");
  const mailer=state.mailers.find(m=>m.id===page.mailerId && m.pageId===page.id && m.accountId===page.accountId && m.contactId===page.contactId);
  if(!mailer)throw new Error("This page is not connected to the recipient.");
  if(!["needs_review","ready"].includes(mailer.stage))throw new Error("The approved outreach is locked. Create a new version before changing it.");
  return {page,mailer};
}
export function updateOutreachPage(state:DirectMailState,id:string,version:number,input:PagePatch) {
  const next=structuredClone(state),{page,mailer}=requirePage(next,id,version);
  Object.assign(page,PagePatchSchema.parse(input),{version:version+1,reviewedVersion:null});
  mailer.revision++;mailer.reviewedRevision=null;mailer.stage="needs_review";
  return next;
}
export function reviewOutreachPage(state:DirectMailState,id:string,version:number) {
  const next=structuredClone(state),{page,mailer}=requirePage(next,id,version);
  page.reviewedVersion=version;mailer.revision++;mailer.reviewedRevision=null;mailer.stage="needs_review";
  return next;
}
/** Begin editing: make a previously reviewed page ineligible in every view immediately. */
export function invalidatePageReview(state:DirectMailState,id:string,version:number){
 const next=structuredClone(state),{page,mailer}=requirePage(next,id,version);
 page.reviewedVersion=null;mailer.revision++;mailer.reviewedRevision=null;mailer.stage='needs_review';
 return next;
}
