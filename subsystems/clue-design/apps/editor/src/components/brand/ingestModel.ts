import type { IngestJob } from "@/engine/brandLibrary";

/** Shared display helpers for the ingest surface — kept pure for testing. */

export const INGEST_POLL_MS = 1500;

const KIND_LABELS: Record<string, string> = {
  website: "Website",
  pdf: "Brand PDF",
  asset_upload: "Assets"
};

export function jobKindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

export function jobStageText(job: IngestJob): string {
  if (job.status === "succeeded") {
    return "Done";
  }
  if (job.status === "failed") {
    return "Failed";
  }
  return job.stage ?? (job.status === "queued" ? "Queued" : "Working…");
}

export function jobProgressPercent(job: IngestJob): number {
  if (job.status === "succeeded") {
    return 100;
  }
  const value = job.progress ?? 0;
  return Math.max(0, Math.min(100, Math.round(value * 100)));
}

export function jobErrorMessage(job: IngestJob): string {
  const error = job.error as { message?: string; code?: string } | string | null | undefined;
  if (!error) {
    return "Ingestion failed.";
  }
  if (typeof error === "string") {
    return error;
  }
  return error.message ?? error.code ?? "Ingestion failed.";
}
