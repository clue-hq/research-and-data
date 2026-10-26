"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type IngestJob,
  fetchIngestJob,
  fetchIngestJobs,
  isSucceededJob,
  isTerminalJob,
  startAssetIngest,
  startPdfIngest,
  startWebsiteIngest
} from "@/engine/brandLibrary";
import {
  INGEST_POLL_MS,
  jobErrorMessage,
  jobKindLabel,
  jobProgressPercent,
  jobStageText
} from "./ingestModel";

type IntakeKind = "website" | "pdf" | "asset_upload";

/** Raw ISO timestamps read like log output; the list needs "Jul 5, 20:41". */
function formatJobTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 16);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

interface IntakeState {
  job: IngestJob | null;
  submitting: boolean;
  error: string | null;
}

const EMPTY: IntakeState = { job: null, submitting: false, error: null };

/**
 * The three intake paths (website / brand PDF / assets) plus moda-style stage
 * progress. On submit a card swaps its form for a progress panel that polls
 * `fetchIngestJob` every 1.5s until the job reaches a terminal state; a recent
 * ingestions list sits below, refreshed on mount and whenever a job settles.
 */
export function IngestConsole({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [website, setWebsite] = useState<IntakeState>(EMPTY);
  const [pdf, setPdf] = useState<IntakeState>(EMPTY);
  const [assets, setAssets] = useState<IntakeState>(EMPTY);
  const [recent, setRecent] = useState<IngestJob[]>([]);

  const refreshRecent = useCallback(() => {
    fetchIngestJobs({ apiBaseUrl })
      .then(setRecent)
      .catch(() => {
        /* recent list is non-critical; leave prior state */
      });
  }, [apiBaseUrl]);

  useEffect(() => {
    refreshRecent();
  }, [refreshRecent]);

  return (
    <div className="ingest-shell">
      <div className="ingest-cards">
        <WebsiteIntake
          apiBaseUrl={apiBaseUrl}
          state={website}
          setState={setWebsite}
          onSettled={refreshRecent}
        />
        <PdfIntake
          apiBaseUrl={apiBaseUrl}
          state={pdf}
          setState={setPdf}
          onSettled={refreshRecent}
        />
        <AssetsIntake
          apiBaseUrl={apiBaseUrl}
          state={assets}
          setState={setAssets}
          onSettled={refreshRecent}
        />
      </div>

      <section className="brand-section">
        <div className="brand-section-head">
          <span className="eyebrow">Recent ingestions</span>
        </div>
        {recent.length === 0 ? (
          <p className="caption">No ingestions yet.</p>
        ) : (
          <ul className="hairline-list ingest-recent">
            {recent.map((job) => (
              <li key={job.job_id}>
                <span className="chip is-uppercase">{jobKindLabel(job.kind)}</span>
                <span className="ingest-recent-stage">{jobStageText(job)}</span>
                <span className="caption mono">{formatJobTime(job.updated_at)}</span>
                {isSucceededJob(job) && job.brand_kit_id ? (
                  <a
                    className="btn btn-quiet btn-sm"
                    href={`/brand/kits/${job.brand_kit_id}`}
                  >
                    Review kit
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/**
 * Polls a running job until terminal. Kicks off on job change; clears its
 * interval on unmount or when the job settles.
 */
function useJobPolling(
  apiBaseUrl: string,
  job: IngestJob | null,
  onUpdate: (job: IngestJob) => void,
  onSettled: () => void
) {
  const updateRef = useRef(onUpdate);
  const settledRef = useRef(onSettled);
  updateRef.current = onUpdate;
  settledRef.current = onSettled;

  const jobId = job && !isTerminalJob(job) ? job.job_id : null;

  useEffect(() => {
    if (!jobId) {
      return;
    }
    const interval = setInterval(() => {
      fetchIngestJob({ apiBaseUrl }, jobId)
        .then((next) => {
          updateRef.current(next);
          if (isTerminalJob(next)) {
            settledRef.current();
          }
        })
        .catch(() => {
          /* transient poll failure — keep trying until unmount */
        });
    }, INGEST_POLL_MS);
    return () => clearInterval(interval);
  }, [apiBaseUrl, jobId]);
}

function ProgressPanel({ job }: { job: IngestJob }) {
  return (
    <div className="ingest-progress">
      <p className="stage-line">{jobStageText(job)}</p>
      <div className="progress-track">
        <div
          className="progress-fill"
          style={{ width: `${jobProgressPercent(job)}%` }}
          data-testid="ingest-progress-fill"
        />
      </div>
    </div>
  );
}

function TerminalPanel({
  job,
  onRetry
}: {
  job: IngestJob;
  onRetry: () => void;
}) {
  if (isSucceededJob(job)) {
    return (
      <div className="ingest-result">
        <span className="status-pill is-approved">Captured</span>
        {job.brand_kit_id ? (
          <a className="btn btn-primary btn-sm" href={`/brand/kits/${job.brand_kit_id}`}>
            Review kit
          </a>
        ) : null}
      </div>
    );
  }
  return (
    <div className="ingest-result">
      <span className="status-pill is-error">{jobErrorMessage(job)}</span>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

function IntakeCard({
  title,
  description,
  state,
  onReset,
  onSettled,
  children
}: {
  title: string;
  description: string;
  state: IntakeState;
  onReset: () => void;
  onSettled: () => void;
  children: React.ReactNode;
}) {
  const job = state.job;
  return (
    <div className="brand-card ingest-card">
      <span className="title ingest-card-title">{title}</span>
      <p className="caption ingest-card-desc">{description}</p>
      {job && isTerminalJob(job) ? (
        <TerminalPanel job={job} onRetry={onReset} />
      ) : job ? (
        <ProgressPanel job={job} />
      ) : (
        children
      )}
      {state.error ? <span className="status-pill is-error">{state.error}</span> : null}
    </div>
  );
}

function WebsiteIntake({
  apiBaseUrl,
  state,
  setState,
  onSettled
}: {
  apiBaseUrl: string;
  state: IntakeState;
  setState: (updater: (prev: IntakeState) => IntakeState) => void;
  onSettled: () => void;
}) {
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");

  useJobPolling(
    apiBaseUrl,
    state.job,
    (job) => setState((prev) => ({ ...prev, job })),
    onSettled
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!url.trim()) {
      return;
    }
    setState(() => ({ ...EMPTY, submitting: true }));
    try {
      const job = await startWebsiteIngest({ apiBaseUrl }, url.trim(), name);
      setState(() => ({ job, submitting: false, error: null }));
      if (isTerminalJob(job)) {
        onSettled();
      }
    } catch (caught) {
      setState(() => ({
        ...EMPTY,
        error: caught instanceof Error ? caught.message : "Could not start scan."
      }));
    }
  }

  return (
    <IntakeCard
      title="Website"
      description="Scan a live site for colors, type, and logos."
      state={state}
      onReset={() => setState(() => EMPTY)}
      onSettled={onSettled}
    >
      <form className="ingest-form" onSubmit={submit}>
        <label className="field">
          <span className="field-label">Site URL</span>
          <input
            type="url"
            aria-label="Site URL"
            placeholder="https://example.com"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field-label">Name (optional)</span>
          <input
            type="text"
            aria-label="Kit name"
            placeholder="Acme"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <button type="submit" className="btn btn-primary btn-sm" disabled={state.submitting}>
          Scan site
        </button>
      </form>
    </IntakeCard>
  );
}

function PdfIntake({
  apiBaseUrl,
  state,
  setState,
  onSettled
}: {
  apiBaseUrl: string;
  state: IntakeState;
  setState: (updater: (prev: IntakeState) => IntakeState) => void;
  onSettled: () => void;
}) {
  useJobPolling(
    apiBaseUrl,
    state.job,
    (job) => setState((prev) => ({ ...prev, job })),
    onSettled
  );

  async function onFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setState(() => ({ ...EMPTY, submitting: true }));
    try {
      const job = await startPdfIngest({ apiBaseUrl }, file);
      setState(() => ({ job, submitting: false, error: null }));
      if (isTerminalJob(job)) {
        onSettled();
      }
    } catch (caught) {
      setState(() => ({
        ...EMPTY,
        error: caught instanceof Error ? caught.message : "Could not read PDF."
      }));
    }
  }

  return (
    <IntakeCard
      title="Brand PDF"
      description="Upload brand guidelines as a PDF."
      state={state}
      onReset={() => setState(() => EMPTY)}
      onSettled={onSettled}
    >
      <label className="dropzone ingest-dropzone">
        <span>Drop a PDF here, or</span>
        <span className="btn btn-ghost btn-sm ingest-choose">Choose a file</span>
        <input
          type="file"
          aria-label="Brand PDF file"
          accept="application/pdf"
          onChange={onFile}
        />
      </label>
    </IntakeCard>
  );
}

function AssetsIntake({
  apiBaseUrl,
  state,
  setState,
  onSettled
}: {
  apiBaseUrl: string;
  state: IntakeState;
  setState: (updater: (prev: IntakeState) => IntakeState) => void;
  onSettled: () => void;
}) {
  useJobPolling(
    apiBaseUrl,
    state.job,
    (job) => setState((prev) => ({ ...prev, job })),
    onSettled
  );

  async function onFiles(event: React.ChangeEvent<HTMLInputElement>) {
    const files = event.target.files ? Array.from(event.target.files) : [];
    event.target.value = "";
    if (files.length === 0) {
      return;
    }
    setState(() => ({ ...EMPTY, submitting: true }));
    try {
      const job = await startAssetIngest({ apiBaseUrl }, files);
      setState(() => ({ job, submitting: false, error: null }));
      if (isTerminalJob(job)) {
        onSettled();
      }
    } catch (caught) {
      setState(() => ({
        ...EMPTY,
        error: caught instanceof Error ? caught.message : "Could not read files."
      }));
    }
  }

  return (
    <IntakeCard
      title="Assets"
      description="Upload logos and images to describe."
      state={state}
      onReset={() => setState(() => EMPTY)}
      onSettled={onSettled}
    >
      <label className="dropzone ingest-dropzone">
        <span>Drop images here, or</span>
        <span className="btn btn-ghost btn-sm ingest-choose">Choose files</span>
        <input
          type="file"
          aria-label="Asset files"
          accept="image/png,image/jpeg,image/webp,image/svg+xml"
          multiple
          onChange={onFiles}
        />
      </label>
    </IntakeCard>
  );
}
