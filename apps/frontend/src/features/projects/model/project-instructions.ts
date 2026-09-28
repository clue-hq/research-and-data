import { z } from "zod";

/**
 * A project's standing instructions — one document (`project/instructions.md`),
 * not a free-text column.
 *
 * `revision` is that document's version, and it rides back into the save as
 * `expected_revision`: a concurrent editor's write is refused rather than
 * silently overwritten. `null` data means nothing has ever been saved, which is
 * a different state from "saved and empty" and is kept distinct here.
 */

export const ProjectInstructionsSchema = z.object({
  body: z.string(),
  revision: z.number().int(),
  updatedAt: z.string().min(1),
});

export type ProjectInstructions = z.infer<typeof ProjectInstructionsSchema>;

const InstructionsWire = z.object({
  body: z.string(),
  revision: z.number().int(),
  updated_at: z.string().min(1),
});

function fromWire(wire: z.infer<typeof InstructionsWire>): ProjectInstructions {
  return ProjectInstructionsSchema.parse({
    body: wire.body,
    revision: wire.revision,
    updatedAt: wire.updated_at,
  });
}

export const ProjectInstructionsResponseSchema = z
  .object({ data: InstructionsWire.nullable() })
  .transform((response) =>
    response.data === null ? null : fromWire(response.data),
  );
