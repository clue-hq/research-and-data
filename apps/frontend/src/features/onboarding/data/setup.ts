import { z } from "zod";

/**
 * FI-4 slice 2 — the workspace-setup transport (BFF-fronted; the caller has a membership by
 * the time setup starts, so the generic /api/clue proxy serves it). `status: "complete"`
 * means the FAST recon lane finished — the release-into-the-app signal; the background lane
 * keeps running after the user has left the screen.
 */
export const SetupStatusSchema = z.object({
  status: z.enum(["unavailable", "none", "running", "complete", "failed"]),
  recon_run_id: z.string().nullable().optional().default(null),
  fast_status: z.string().nullable().optional().default(null),
  background_status: z.string().nullable().optional().default(null),
  company_website: z.string().nullable().optional().default(null),
});

export type SetupStatus = z.infer<typeof SetupStatusSchema>;

export class SetupApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "SetupApiError";
    this.status = status;
  }
}

export async function startWorkspaceSetup(): Promise<void> {
  const response = await fetch("/api/clue/stage0/setup", {
    method: "POST",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new SetupApiError(`Setup start failed with status ${response.status}`, response.status);
  }
}

export async function readSetupStatus(): Promise<SetupStatus> {
  const response = await fetch("/api/clue/stage0/setup/current", {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new SetupApiError(
      `Setup status read failed with status ${response.status}`,
      response.status,
    );
  }
  return SetupStatusSchema.parse(await response.json());
}
