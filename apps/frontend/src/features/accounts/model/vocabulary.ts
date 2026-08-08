import { z } from "zod";

/**
 * Shared wire vocabulary for the backend read layer (`/frontend/v1`).
 *
 * Every schema here mirrors the as-built contract recorded in
 * `docs/api-contracts/accounts.md` ("As-built backend read API (FI-2 slice 1)").
 * Two rules govern this file:
 *
 * 1. Absence is a legitimate answer (D-4). Anything the backend can correctly
 *    leave empty is `.nullable()`, never floored with `.min(1)` or `.url()`.
 * 2. Only genuinely closed backend vocabularies become `z.enum`. An open token
 *    space stays `z.string()` so a new backend value renders as an unknown
 *    label instead of crashing the parser.
 */

/** ISO-8601 UTC timestamp. Kept as a string: the frontend owns all formatting (D-5). */
export const IsoTimestampSchema = z.string();

/**
 * The honest per-`(account, project)` research status.
 *
 * Backed by a closed backend `StrEnum`. `not_launchable` is ratified into the
 * vocabulary ahead of Lane D (FI-1 D-6) so the schema is not widened twice; the
 * slice-1 backend cannot emit it yet.
 */
export const ResearchStatusSchema = z.enum([
  "not_started",
  "in_progress",
  "needs_review",
  "completed",
  "suspended",
  "not_launchable",
]);

/** Buying-committee personas — a closed backend DB enum (`core.enums.Persona`). */
export const PersonaSchema = z.enum([
  "champion",
  "economic_buyer",
  "technical_evaluator",
  "blocker",
]);

/**
 * The merge's freshness disposition for the claim that won.
 *
 * Exactly two values reach this wire: the backend's third disposition
 * (`expired`) is a retention age-out that can never win a merge.
 */
export const FreshnessSchema = z.enum(["fresh", "stale"]);

/**
 * How a project acquired an account.
 *
 * Deliberately NOT an enum: the backend stores the raw registered channel
 * string behind a CHECK constraint (`discovered`/`imported`/`manual`/
 * `directive` today) precisely so a read does not crash on a channel a later
 * migration adds. Render through a label lookup with a fallback.
 */
export const AddedViaSchema = z.string();

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

/**
 * An opaque claim payload.
 *
 * `neutralFacts[].value`, `insights[].value`, `narratives[].value`,
 * `professionalFacts[].value`, `registryIds` and `hqGeo` are passed through
 * verbatim from the claim, so their internal keys are the writer's (snake_case)
 * and are not part of this layer's camelCase vocabulary. They are typed as
 * unknown JSON per `fieldKey` and rendered generically.
 */
export const JsonValueSchema: z.ZodType<JsonValue> = z.lazy(() =>
  z.union([
    z.string(),
    z.number(),
    z.boolean(),
    z.null(),
    z.array(JsonValueSchema),
    z.record(z.string(), JsonValueSchema),
  ]),
);

/**
 * The shared error envelope.
 *
 * `code` is an OPEN set — the six codes this surface raises deliberately plus
 * the generic framework ones (`NOT_FOUND`, `BAD_REQUEST`, …). A closed
 * `z.enum` would turn a new backend code into a client-side parse crash
 * instead of a displayable error, so it is parsed as a plain string.
 */
export const ApiErrorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string().nullable().default(null),
    requestId: z.string().nullable().default(null),
  }),
});

export type ApiErrorEnvelope = z.infer<typeof ApiErrorEnvelopeSchema>;
export type Freshness = z.infer<typeof FreshnessSchema>;
export type Persona = z.infer<typeof PersonaSchema>;
export type ResearchStatus = z.infer<typeof ResearchStatusSchema>;
