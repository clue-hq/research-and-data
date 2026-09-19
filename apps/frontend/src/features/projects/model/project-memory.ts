import { z } from "zod";

/**
 * A project-scope memory note, as the scoped-memory seam serves it.
 *
 * These are advisory preferences and learnings, never facts — the backend
 * refuses a fact-shaped note outright — so nothing here carries provenance
 * beyond the thread it was typed from. A note with no source thread was added
 * by the human directly.
 */

export const ProjectMemoryNoteSchema = z.object({
  id: z.string().min(1),
  text: z.string().min(1),
  sourceThreadId: z.string().nullable(),
  sourceThreadTitle: z.string().nullable(),
  createdAt: z.string().min(1),
});

export type ProjectMemoryNote = z.infer<typeof ProjectMemoryNoteSchema>;

const NoteWire = z.object({
  id: z.string().min(1),
  text: z.string().min(1),
  source_thread_id: z.string().nullable(),
  source_thread_title: z.string().nullable(),
  created_at: z.string().min(1),
});

function fromWire(wire: z.infer<typeof NoteWire>): ProjectMemoryNote {
  return ProjectMemoryNoteSchema.parse({
    id: wire.id,
    text: wire.text,
    sourceThreadId: wire.source_thread_id,
    sourceThreadTitle: wire.source_thread_title,
    createdAt: wire.created_at,
  });
}

export const ProjectMemoryListResponseSchema = z
  .object({ data: z.array(NoteWire) })
  .transform((response) => response.data.map(fromWire));

/**
 * One written note. `verdict` is how reconciliation disposed of the submission
 * (`add`/`update`/`supersede`/`noop`) — parsed so the envelope is validated in
 * full, and carried on the result so a caller can say "we already knew that".
 */
export const ProjectMemoryNoteResponseSchema = z
  .object({
    data: NoteWire,
    verdict: z.string().nullable().optional(),
  })
  .transform((response) => ({
    note: fromWire(response.data),
    verdict: response.verdict ?? null,
  }));
