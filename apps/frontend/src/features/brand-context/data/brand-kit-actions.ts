import {
  IngestionJobListSchema,
  type IngestionJob,
  type ReExtractRequest,
} from "../model/brand-kit-actions";

/**
 * Slice 4: the Brand-context page's re-extraction and its ingestion-job read.
 *
 * Browser-side, so everything goes through the authenticated BFF (`/api/clue/design`, W1.2):
 * the proxy proves the session and stamps `X-Workspace-Id` server-side. A design-API origin is
 * never reachable from here, and no workspace is ever supplied by this code.
 */
const DESIGN_BFF = "/api/clue/design";

export interface BrandKitActionsSource {
  /** The workspace's ingestion jobs, most recent first; `null` means the read is unavailable. */
  listIngestionJobs(): Promise<IngestionJob[] | null>;
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
  reExtract(request: ReExtractRequest): Promise<void>;
  listIngestionJobs(): Promise<IngestionJob[] | null>;
}

/** A double click shares the pending extraction request; a failure releases it for retry. */
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
    listIngestionJobs: () => source.listIngestionJobs(),
    reExtract: (request) => single(() => source.enqueueWebsiteIngestion(request)),
  };
}
