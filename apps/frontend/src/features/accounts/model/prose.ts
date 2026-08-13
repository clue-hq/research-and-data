import { z } from "zod";

export const ProseResearchOutcomeSchema = z.enum([
  "completed",
  "needs_review",
]);

const AvailableProseSchema = z.object({
  state: z.literal("available"),
  paragraphs: z.array(z.string().min(1)).min(1),
  researchOutcome: ProseResearchOutcomeSchema,
});

const NotComposedProseSchema = z.object({
  state: z.literal("not_composed"),
  paragraphs: z.array(z.never()).max(0).default([]),
  researchOutcome: z.null().default(null),
});

const RestrictedProseSchema = z.object({
  state: z.literal("restricted"),
  paragraphs: z.array(z.never()).max(0).default([]),
  researchOutcome: z.null().default(null),
});

/** The live Lane-E synthesis value, an honest absence, or a withheld value. */
export const ProseReadSchema = z.discriminatedUnion("state", [
  AvailableProseSchema,
  NotComposedProseSchema,
  RestrictedProseSchema,
]);

export type ProseRead = z.infer<typeof ProseReadSchema>;

export type ProsePresentation =
  | { kind: "paragraphs"; paragraphs: string[] }
  | { kind: "message"; message: string };

/** Resolve the three wire states without consulting unrelated research status. */
export function prosePresentation(
  prose: ProseRead,
  copy: { empty: string; restricted: string },
): ProsePresentation {
  if (prose.state === "available") {
    return { kind: "paragraphs", paragraphs: prose.paragraphs };
  }
  return {
    kind: "message",
    message: prose.state === "restricted" ? copy.restricted : copy.empty,
  };
}
