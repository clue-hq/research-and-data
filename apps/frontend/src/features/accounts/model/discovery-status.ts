import { z } from "zod";

/**
 * The project's latest discovery run as `/frontend/v1/projects/:id/discovery/current` serves it
 * (spec 2026-09-12 §3). Snake case on the wire, kept as-is: this document is polled, never
 * rendered field by field.
 */
export const DiscoveryRunStatusSchema = z.object({
  run_id: z.string().min(1),
  // `.catch`: an additive backend status must never kill the poll; it reads as "not live".
  status: z
    .enum(["not_started", "in_progress", "needs_review", "completed", "suspended"])
    .catch("completed"),
  asked: z.number().int().nullable(),
  found: z.number().int().nonnegative(),
  verified: z.number().int().nonnegative(),
  shown: z.number().int().nonnegative(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
});

export type DiscoveryRunStatus = z.infer<typeof DiscoveryRunStatusSchema>;

export const DiscoveryRunStatusResponseSchema = z.object({
  data: DiscoveryRunStatusSchema.nullable(),
});

/** Poll while the driver is still working; stop on the first terminal status. */
export function discoveryRunLive(status: DiscoveryRunStatus | null): boolean {
  return status !== null && (status.status === "not_started" || status.status === "in_progress");
}
