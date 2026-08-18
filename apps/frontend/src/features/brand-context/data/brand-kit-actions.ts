import {
  IngestionJobListSchema,
  type IngestionJob,
  type ReExtractRequest,
} from "../model/brand-kit-actions";

/**
 * Slice 4: the Brand-context page's two mutations and the ingestion-job read behind them.
 *
 * Browser-side, so everything goes through the authenticated BFF (`/api/clue/design`, W1.2):
 * the proxy proves the session and stamps `X-Workspace-Id` server-side. A design-API origin is
 * never reachable from here, and no workspace is ever supplied by this code.
 */
const DESIGN_BFF = "/api/clue/design";

export interface BrandKitActionsSource {
  /** The workspace's ingestion jobs, most recent first; `null` means the read is unavailable. */
  listIngestionJobs(): Promise<IngestionJob[] | null>;
  /** Approve a kit's LATEST version. There is no un-approve affordance, by ruling. */
  approve(brandKitId: string): Promise<void>;
  /** Enqueue one website ingestion; with `brand_kit_id` it publishes that kit's next version. */
  enqueueWebsiteIngestion(request: ReExtractRequest): Promise<void>;
}

async function post(path: string, body: unknown): Promise<void> {
  const response = await fetch(`${DESIGN_BFF}${path}`, {
    body: JSON.stringify(body),
    cache: "no-store",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`design API ${path} responded ${response.status}`);
  }
}

export const httpBrandKitActionsSource: BrandKitActionsSource = {
  async approve(brandKitId) {
    await post(`/brand-kits/${encodeURIComponent(brandKitId)}/approval`, {
      approval_status: "approved",
    });
  },

  async enqueueWebsiteIngestion(request) {
    await post("/brand-kits/ingest/website", request);
  },

  /**
   * Unreadable job state is UNKNOWN job state, not an empty list. The page stays up, but its
   * mutations stay disabled until this read succeeds: treating a refusal as "no active job"
   * would create exactly the duplicate ingestion the disabled-while-running contract prevents.
   */
  async listIngestionJobs() {
    try {
      const response = await fetch(`${DESIGN_BFF}/brand-kits/ingest`, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return null;
      return IngestionJobListSchema.parse(await response.json()).jobs;
    } catch (error) {
      console.warn("[brand-context] the ingestion-job read failed:", error);
      return null;
    }
  },
};

export interface BrandKitActions {
  approve(brandKitId: string): Promise<void>;
  reExtract(request: ReExtractRequest): Promise<void>;
  listIngestionJobs(): Promise<IngestionJob[] | null>;
}

/**
 * The mutations share one SINGLE-FLIGHT guard.
 *
 * The buttons already disable themselves while a run is in flight, but a disabled button is a
 * rendering, not a guarantee: a double click lands both events before React re-renders, and
 * each of these posts is a durable act (a second ingestion job, a second approval write). The
 * guard is here, so it holds whatever the presentation does. Approval and Re-extract are also
 * mutually exclusive: the approval endpoint targets the lineage's latest version, so racing it
 * with a publish could approve a draft the person has not reviewed. A failed attempt releases
 * the guard: a refusal the client can see is a refusal the client may retry.
 */
export function createBrandKitActions(
  source: BrandKitActionsSource = httpBrandKitActionsSource,
): BrandKitActions {
  let inFlight: Promise<void> | null = null;

  function single(run: () => Promise<void>): Promise<void> {
    if (inFlight) return inFlight;
    const started = run().finally(() => {
      inFlight = null;
    });
    inFlight = started;
    return started;
  }

  return {
    approve: (brandKitId) => single(() => source.approve(brandKitId)),
    listIngestionJobs: () => source.listIngestionJobs(),
    reExtract: (request) => single(() => source.enqueueWebsiteIngestion(request)),
  };
}
