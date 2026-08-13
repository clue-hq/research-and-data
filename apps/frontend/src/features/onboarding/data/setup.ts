import { z } from "zod";

/**
 * FI-4 slice 2 — the workspace-setup transport (BFF-fronted; the caller has a membership by
 * the time setup starts, so the generic /api/clue proxy serves it). `status: "complete"`
 * means the FAST recon lane finished — the release-into-the-app signal; the background lane
 * keeps running after the user has left the screen. `starting` = the submission is durably
 * captured but no recon row is visible yet (driver warm-up / the lane's enclosing
 * transaction).
 */
/**
 * One Client-KB field's latest reported state (FI-4 slice 3). The backend has ALREADY reduced
 * the recon run's at-least-once progress events to one entry per field (last-writer-wins by
 * event `seq`) and ordered them by Client-KB baseline order — the client must not re-reduce,
 * it never sees `seq`.
 */
export const SetupFieldStateSchema = z.object({
  field_key: z.string().min(1),
  // Open on purpose: the lane vocabulary is the backend's ("fast" / "background"), and a third
  // lane must not fail the parse. Readers compare against the known names.
  lane: z.string(),
  // `.catch`: an additive per-field status must degrade to the in-flight state, never kill the
  // poll loop (the FE-N2 ruling, applied per field).
  status: z.enum(["started", "resolved", "empty", "failed"]).catch("started"),
});

export const SetupStatusSchema = z.object({
  // `.catch`: an additive backend status must never silently kill the poll loop (review
  // FE-N2); an unknown value degrades to the surfaced-terminal `unavailable` state.
  status: z
    .enum(["unavailable", "none", "starting", "running", "complete", "failed"])
    .catch("unavailable"),
  recon_run_id: z.string().nullable().optional().default(null),
  fast_status: z.string().nullable().optional().default(null),
  background_status: z.string().nullable().optional().default(null),
  company_website: z.string().nullable().optional().default(null),
  fast_client_kb_version: z.number().nullable().optional().default(null),
  fact_count: z.number().nullable().optional().default(null),
  // Real per-field motion. Empty until the running lane emits its first field event (and on
  // any pre-slice-3 payload).
  fields: z.array(SetupFieldStateSchema).optional().default([]),
  // null = "we do not know yet" (a lane that has not reached COMPLETED, or a failed lane) —
  // never a fabricated `false`.
  fast_budget_exhausted: z.boolean().nullable().optional().default(null),
  background_budget_exhausted: z.boolean().nullable().optional().default(null),
});

export type SetupFieldState = z.infer<typeof SetupFieldStateSchema>;
export type SetupStatus = z.infer<typeof SetupStatusSchema>;

export class SetupApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, options: { status: number; code: string }) {
    super(message);
    this.name = "SetupApiError";
    this.status = options.status;
    this.code = options.code;
  }
}

async function refusalOf(response: Response, fallback: string): Promise<SetupApiError> {
  let code = "HTTP_ERROR";
  let message = fallback;
  try {
    const payload = (await response.json()) as {
      error?: { code?: string; message?: string };
      detail?: { error?: string; reason?: string };
    };
    if (payload.error?.code) code = payload.error.code;
    if (payload.error?.message) message = payload.error.message;
    if (payload.detail?.error) code = payload.detail.error;
    if (payload.detail?.reason) message = payload.detail.reason;
  } catch {
    // Non-JSON body; keep the fallback.
  }
  return new SetupApiError(message, { status: response.status, code });
}

export async function startWorkspaceSetup(): Promise<void> {
  const response = await fetch("/api/clue/stage0/setup", {
    method: "POST",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw await refusalOf(response, `Setup start failed with status ${response.status}`);
  }
}

export async function readSetupStatus(): Promise<SetupStatus> {
  const response = await fetch("/api/clue/stage0/setup/current", {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw await refusalOf(
      response,
      `Setup status read failed with status ${response.status}`,
    );
  }
  return SetupStatusSchema.parse(await response.json());
}
