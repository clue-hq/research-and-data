import { z } from "zod";
import { MailerPatchSchema, type Mailer } from "../model/direct-mail";

const DraftSchema = z.object({ revision: z.number().int().positive(), patch: MailerPatchSchema, base: MailerPatchSchema.optional() });
export type PendingMailerDraft = z.infer<typeof DraftSchema>;
const key = (id: string) => `clue-direct-mail-draft:${id}`;
export function draftBase(mailer: Mailer) {
  return MailerPatchSchema.parse(Object.fromEntries(Object.keys(MailerPatchSchema.shape).map(key => [key, mailer[key as keyof Mailer]])));
}
/** Revision-only changes can merge. Overlapping or legacy unknown edits require a choice. */
export function draftConflicts(draft: PendingMailerDraft, saved: Mailer) {
  if (draft.revision === saved.revision) return [];
  return (Object.keys(draft.patch) as (keyof PendingMailerDraft["patch"])[]).filter(key => {
    const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
    return !same(saved[key], draft.patch[key]) && (!draft.base || !same(saved[key], draft.base[key]));
  });
}
/** Per-tab recovery buffer. A stale buffer never overwrites the shared record. */
export function readPendingDraft(id: string): PendingMailerDraft | null {
  if (typeof sessionStorage === "undefined") return null;
  try { const raw = sessionStorage.getItem(key(id)); return raw ? DraftSchema.parse(JSON.parse(raw)) : null; } catch { return null; }
}
export function writePendingDraft(id: string, draft: PendingMailerDraft | null): boolean {
  try { if (draft) sessionStorage.setItem(key(id), JSON.stringify(draft)); else sessionStorage.removeItem(key(id)); return true; } catch { return false; }
}
