import { z } from "zod";
import { MailerPatchSchema } from "../model/direct-mail";

const DraftSchema = z.object({ revision: z.number().int().positive(), patch: MailerPatchSchema });
export type PendingMailerDraft = z.infer<typeof DraftSchema>;
const key = (id: string) => `clue-direct-mail-draft:${id}`;
/** Per-tab recovery buffer. A stale buffer never overwrites the shared record. */
export function readPendingDraft(id: string): PendingMailerDraft | null {
  if (typeof sessionStorage === "undefined") return null;
  try { const raw = sessionStorage.getItem(key(id)); return raw ? DraftSchema.parse(JSON.parse(raw)) : null; } catch { return null; }
}
export function writePendingDraft(id: string, draft: PendingMailerDraft | null): boolean {
  try { if (draft) sessionStorage.setItem(key(id), JSON.stringify(draft)); else sessionStorage.removeItem(key(id)); return true; } catch { return false; }
}
