import { z } from "zod";
import type { BrandKitDetail } from "./brand-kit";

/** Extraction state and historical kit metadata. Ingestion now approves kits automatically. */

/** The design API's ingestion-job DTO (`ingestion_job_dto`), narrowed to what the page uses. */
export const IngestionJobSchema = z.object({
  job_id: z.string().min(1),
  kind: z.string(),
  // `.catch`: a status this build does not know must degrade to the in-flight reading — never
  // to one that would claim a published kit (the FE-N2 ruling, as slice 3 applied it).
  status: z.enum(["queued", "running", "succeeded", "failed"]).catch("running"),
  /** Present for `kind == "website"` jobs only (slice 4's DTO addition). */
  website_url: z.string().nullish(),
});

export const IngestionJobListSchema = z.object({
  jobs: z.array(IngestionJobSchema),
});

export type IngestionJob = z.infer<typeof IngestionJobSchema>;

/**
 * The kit the page is showing, as the actions need it. Deliberately NOT part of
 * `BrandContextWorkspace` — that schema is the designed page's frozen shape, and a kit's
 * identity, version and approval state are facts about the store, not about the design.
 */
export interface BrandKitMeta {
  id: string;
  version: number;
  approvalStatus: string | null;
  /** The website this kit was ingested from (`brand_kit_json.sources[0].url`), if any. */
  sourceUrl: string | null;
}

export function toBrandKitMeta(detail: BrandKitDetail): BrandKitMeta {
  const source = (detail.brand_kit_json.sources ?? []).find(
    (entry) => entry && typeof entry.url === "string" && entry.url.length > 0,
  );
  return {
    id: detail.brand_kit.id,
    version: detail.brand_kit.version,
    approvalStatus: detail.brand_kit.approval_status ?? null,
    sourceUrl: source?.url ?? null,
  };
}

export type ApprovalTone = "draft" | "unreviewed" | "approved" | "neutral";

export interface ApprovalChip {
  label: string;
  tone: ApprovalTone;
}

/** The three ruled labels, plus the store's own word for anything else (`deprecated` today). */
const RULED_CHIPS: Record<string, ApprovalChip> = {
  approved: { label: "Approved", tone: "approved" },
  draft: { label: "Draft", tone: "draft" },
  generated_unreviewed: { label: "Generated — unreviewed", tone: "unreviewed" },
};

/**
 * The status chip, or `null` when there is nothing to report. No kit means no chip — an
 * unstarted workspace is not "Draft".
 */
export function approvalChip(kit: BrandKitMeta | null): ApprovalChip | null {
  const status = kit?.approvalStatus?.trim();
  if (!status) return null;
  return RULED_CHIPS[status] ?? { label: status, tone: "neutral" };
}

/** A job that is still going to change what this page shows. */
export function isJobActive(job: IngestionJob | null): boolean {
  return job !== null && (job.status === "queued" || job.status === "running");
}

/** Ingestion kinds that never touch the kit: onboarding's ad harvest (and its card job). */
const NON_KIT_KINDS: ReadonlySet<string> = new Set(["ad_assets"]);

/** Any job still capable of changing the kit store. The API orders newest first, so the first
 * match is the most recent active one, but a later terminal job must not hide an older runner. */
export function activeJob(jobs: readonly IngestionJob[]): IngestionJob | null {
  return jobs.find((job) => !NON_KIT_KINDS.has(job.kind) && isJobActive(job)) ?? null;
}

/**
 * The most recent website a workspace asked us to ingest. This is the kit-less rescue's only
 * input: when the first-time auto-ingestion FAILED, no kit was ever born, and the failed job is
 * the only record of which site to retry.
 */
export function latestWebsiteUrl(jobs: readonly IngestionJob[]): string | null {
  for (const job of jobs) {
    const url = job.website_url?.trim();
    if (job.kind === "website" && url) return url;
  }
  return null;
}

/** The body of `POST /brand-kits/ingest/website`. */
export interface ReExtractRequest {
  url: string;
  brand_kit_id?: string;
}

export type ReExtractState =
  /** Ready to fire, with the exact request body. */
  | { kind: "ready"; request: ReExtractRequest }
  /** An ingestion is already running: re-firing would race it. */
  | { kind: "busy" }
  /** Nothing to re-extract FROM — no kit's source and no submitted URL on record. */
  | { kind: "unavailable" };

/**
 * Whether Re-extract can fire, and with what.
 *
 * * An active job wins over everything: one ingestion at a time.
 * * With a kit, the run is a NEW VERSION of that kit (`brand_kit_id`), so the workspace keeps
 *   one brand-kit lineage instead of sprouting a second kit per retry. Its URL is the kit's own
 *   recorded source, falling back to the newest website job's URL for a kit that records none.
 * * With NO kit, the run is a fresh ingestion of the last URL this workspace submitted — the
 *   rescue for a failed first-time auto-ingestion, which is the only way to be kit-less and
 *   still have a job on record.
 * * Neither → unavailable. Typing a fresh URL is future work and needs its own founder ruling.
 */
export function reExtractState(
  kit: BrandKitMeta | null,
  jobs: readonly IngestionJob[],
): ReExtractState {
  if (activeJob(jobs)) return { kind: "busy" };
  const url = kit?.sourceUrl?.trim() || latestWebsiteUrl(jobs);
  if (!url) return { kind: "unavailable" };
  return {
    kind: "ready",
    request: kit ? { url, brand_kit_id: kit.id } : { url },
  };
}

/** Copy for a Colors / Typography panel with nothing in it (founder ruling 2). */
export function panelEmptyMessage(
  panel: "colors" | "typography",
  jobs: readonly IngestionJob[],
): string {
  if (activeJob(jobs)) return "Extracting your brand from your website…";
  return panel === "colors" ? "No colors yet." : "No text styles yet.";
}
