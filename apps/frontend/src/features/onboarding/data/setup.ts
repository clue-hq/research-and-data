import { z } from "zod";

/**
 * The onboarding-lane transport (BFF-fronted; the caller has a membership by the time setup
 * starts, so the generic /api/clue proxy serves it). The screen starts a run with
 * `POST /api/clue/onboarding` and polls `GET /api/clue/onboarding/current`.
 *
 * `status: "complete"` means the four FAST steps finished — the release-into-the-app signal;
 * the background steps keep running after the user has left the screen and never hold the
 * release. `starting` = the run row exists but has not begun (queued).
 */

/**
 * The workspace's most recent design brand-kit ingestion job (brand-kit slice 3). The backend
 * serves job truth and nothing else — the checklist row's mapping is the frontend's
 * (`model/setup-items.ts`). `.catch`: a future job status must degrade to the in-flight state
 * rather than kill the poll loop (the FE-N2 ruling, applied per job), and never to a state that
 * would claim a published kit.
 */
export const SetupBrandKitIngestionSchema = z.object({
  job_id: z.string().min(1),
  status: z.enum(["queued", "running", "succeeded", "failed"]).catch("running"),
});

/** One step of the new onboarding lane, as `GET /onboarding/current` serves it (camelCase, frozen §7). */
export const SetupStepSchema = z.object({
  kind: z.string().min(1),
  subjectRef: z.string().nullable().optional().default(null),
  phase: z.enum(["fast", "background"]).catch("background"),
  // `.catch`: an additive step status degrades to in-flight, never kills the poll (FE-N2).
  status: z.enum(["queued", "running", "completed", "empty", "failed"]).catch("running"),
  startedAt: z.string().nullable().optional().default(null),
  finishedAt: z.string().nullable().optional().default(null),
  costUsd: z.string().optional().default("0"),
  failureCode: z.string().nullable().optional().default(null),
});

export const SetupStatusSchema = z.object({
  // `.catch`: an additive backend status must never silently kill the poll loop (review
  // FE-N2); an unknown value degrades to the surfaced-terminal `unavailable` state.
  status: z
    .enum(["unavailable", "none", "starting", "running", "complete", "failed"])
    .catch("unavailable"),
  run_id: z.string().nullable().optional().default(null),
  steps: z.array(SetupStepSchema).optional().default([]),
  // No ingestion job for the workspace (or a backend that does not serve one) is honest null —
  // the checklist row then claims nothing.
  brand_kit_ingestion: SetupBrandKitIngestionSchema.nullable().optional().default(null),
});

export type SetupBrandKitIngestion = z.infer<typeof SetupBrandKitIngestionSchema>;
export type SetupStep = z.infer<typeof SetupStepSchema>;
export type SetupStatus = z.infer<typeof SetupStatusSchema>;

/** The steps whose completion releases the user (founder ruling 2026-09-12). */
export const FAST_STEP_KINDS = ["overview", "lineup", "reviews", "synthesis"] as const;
/** A step that will never report again. `empty` is a CORRECT outcome, not a failure — the
 * failed/complete split below is made on `failed` alone. */
const STEP_TERMINAL = new Set(["completed", "empty", "failed"]);

/**
 * The run statuses that mean the run finished its work, from the migration's own CHECK
 * (`alembic/versions/0aa95f87eb49_arv2_onboarding_substrate.py:70` — the run vocabulary is
 * `queued | running | completed | completed_with_gaps | failed`).
 *
 * `completed_with_gaps` is the lane's ORDINARY terminal, not a degraded one: `finish_run`
 * settles there whenever any step came back `empty` or `failed`, and `empty` is a correct
 * outcome (nobody could find reviews for this company). Anything not listed here falls to
 * `unavailable`, which is a hard terminal with no "Try again" — so a new run status must be a
 * decision taken here, never an accident.
 */
const RUN_TERMINAL_OK = new Set(["completed", "completed_with_gaps"]);

const OnboardingCurrentWireSchema = z.object({
  runId: z.string().nullable().optional().default(null),
  status: z.string(),
  steps: z.array(SetupStepSchema).optional().default([]),
  // Additive and nullable: a backend that does not serve the job (or a workspace with none)
  // is honest null, and the checklist row then claims nothing.
  brandKitIngestion: z
    .object({ jobId: z.string().min(1), status: z.string() })
    .nullable()
    .optional()
    .default(null),
});

/** `GET /onboarding/current` → the screen's status. Pure; the release rule lives here. */
export function setupStatusFromOnboarding(wire: unknown): SetupStatus {
  const body = OnboardingCurrentWireSchema.parse(wire);
  // What each fast kind owes the release. The PHASE is the backend's to decide
  // (`CLUE_ONBOARDING_REVIEWS_PHASE=background` moves `reviews` off the fast lane), and
  // background work NEVER holds the release — so a fast kind the backend reported only in the
  // background phase owes nothing, and its failure is not the screen's failure either.
  const gating = FAST_STEP_KINDS.map((kind) => {
    const fast = body.steps.find((s) => s.kind === kind && s.phase !== "background") ?? null;
    return { fast, backgrounded: fast === null && body.steps.some((s) => s.kind === kind) };
  });
  // "Nothing is still owed" — not "every step exists": an unreported kind is still to come,
  // while a backgrounded one is never coming to this screen.
  const settled = gating.every(
    (g) => g.backgrounded || (g.fast !== null && STEP_TERMINAL.has(g.fast.status)),
  );
  let status: SetupStatus["status"];
  if (body.status === "none") status = "none";
  else if (body.status === "queued") status = "starting";
  else if (RUN_TERMINAL_OK.has(body.status)) status = "complete";
  else if (body.status === "failed") status = "failed";
  else if (body.status === "running") {
    // The verdict waits for every gating step to settle (ruling R6). A provider error is a
    // STEP outcome and the run carries on, so calling the screen failed on the first failure
    // would strand a user whose other three steps were about to release them — the poll stops
    // on a terminal, and no control here can restart a run.
    if (settled && gating.some((g) => g.fast?.status === "failed")) status = "failed";
    else if (settled) status = "complete";
    else status = "running";
  } else status = "unavailable";
  return SetupStatusSchema.parse({
    status,
    run_id: body.runId,
    steps: body.steps,
    brand_kit_ingestion:
      body.brandKitIngestion === null
        ? null
        : { job_id: body.brandKitIngestion.jobId, status: body.brandKitIngestion.status },
  });
}

/**
 * The profile's website as the lane wants it: a bare registrable host.
 *
 * Scheme, `www.`, path, query, fragment and port are all folded away — anything after the host
 * is the page the user happened to copy, not the company the lane researches.
 */
export function companyDomainOf(companyWebsite: string): string {
  return companyWebsite
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/^www\./, "")
    .replace(/[/?#:].*$/, "");
}

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

export async function startWorkspaceSetup({
  companyWebsite,
}: {
  companyWebsite: string;
}): Promise<void> {
  const companyDomain = companyDomainOf(companyWebsite);
  if (!companyDomain) {
    // A reload after the profile draft was cleared. Posting a blank domain earns a 422, and the
    // screen lets a start failure win over a healthy poll — which would hide a live run. So ask
    // the lane first: a run already open is the answer, and only a lane with nothing running
    // gets to tell the user their website is missing.
    if (await hasOnboardingRun()) return;
    throw new SetupApiError("Your company website is missing. Please retry.", {
      status: 422,
      code: "company_domain_missing",
    });
  }
  const response = await fetch("/api/clue/onboarding", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ company_domain: companyDomain, brand_id: null }),
    cache: "no-store",
  });
  if (response.ok) return;
  const refusal = await refusalOf(response, `Setup start failed with status ${response.status}`);
  // A run already open for this workspace is the replay-safe answer, not a failure.
  if (response.status === 409 && refusal.code === "onboarding_in_progress") return;
  throw refusal;
}

/** Does the workspace already have a run? An unreadable answer counts as "no run". */
async function hasOnboardingRun(): Promise<boolean> {
  try {
    return (await readSetupStatus()).status !== "none";
  } catch {
    return false;
  }
}

export async function readSetupStatus(): Promise<SetupStatus> {
  const response = await fetch("/api/clue/onboarding/current", {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw await refusalOf(response, `Setup status read failed with status ${response.status}`);
  }
  return setupStatusFromOnboarding(await response.json());
}
