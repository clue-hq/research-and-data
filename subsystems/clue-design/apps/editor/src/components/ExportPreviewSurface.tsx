"use client";

import { FileWarning, Image as ImageIcon } from "lucide-react";
import type { Diagnostic, DiagnosticSubject, PageId, Scene } from "@/engine/contracts";
import type { EditorExportArtifact, EditorExportResult } from "@/engine/exportRunner";
import { artifactForPage, exportParityReport } from "@/engine/exportParity";
import { exportPreviewApprovalState, type ExportPreviewApprovalState } from "@/engine/exportPreviewApproval";

interface ExportPreviewSurfaceProps {
  scene: Scene;
  activePageId: PageId | null;
  exportResult: EditorExportResult | null;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}

export function ExportPreviewSurface({
  scene,
  activePageId,
  exportResult,
  onSelectSubject
}: ExportPreviewSurfaceProps) {
  const artifact = artifactForPage(exportResult, activePageId);
  const activePage = activePageId ? scene.pages[activePageId] ?? null : null;
  const report = exportParityReport(scene, activePageId, exportResult);
  const diagnostics = previewDiagnostics(report.diagnostics, exportResult?.diagnostics ?? []);
  const approval = exportPreviewApprovalState({
    artifact,
    exportResult,
    parityStatus: report.status,
    diagnostics
  });

  return (
    <section className="export-preview-shell">
      <div className="export-preview-toolbar">
        <span>
          <ImageIcon aria-hidden size={15} />
          Export Preview
        </span>
        <ParityBadge status={report.status} />
      </div>
      <div className="export-preview-body">
        {artifact?.data_url ? (
          <div className="artifact-preview-frame">
            <ArtifactPreview artifact={artifact} />
            <ArtifactPreviewMeta artifact={artifact} />
          </div>
        ) : (
          <EmptyPreview />
        )}
      </div>
      <div className="export-preview-diagnostics" aria-live="polite">
        <PreviewScopeSummary activePageName={activePage?.name ?? null} activePageId={activePageId} artifact={artifact} />
        <ApprovalSummary approval={approval} />
        {report.canvas && report.export ? (
          <p className="muted">
            Canvas {formatSize(report.canvas)} · Export {formatSize(report.export)}
          </p>
        ) : null}
        <ul className="diagnostic-list">
          {diagnostics.map((diagnostic) => (
            <DiagnosticItem
              key={`${diagnostic.code}-${diagnostic.message}`}
              diagnostic={diagnostic}
              onSelectSubject={onSelectSubject}
            />
          ))}
        </ul>
      </div>
    </section>
  );
}

function PreviewScopeSummary({
  activePageName,
  activePageId,
  artifact
}: {
  activePageName: string | null;
  activePageId: PageId | null;
  artifact: EditorExportArtifact | null;
}) {
  return (
    <dl className="preview-scope-summary" aria-label="Export preview scope">
      <div>
        <dt>Artboard</dt>
        <dd>{activePageName ?? activePageId ?? "No active artboard"}</dd>
      </div>
      <div>
        <dt>Profile</dt>
        <dd>{artifact?.sidecar_summary?.profile_name ?? "No preview profile"}</dd>
      </div>
    </dl>
  );
}

function ApprovalSummary({ approval }: { approval: ExportPreviewApprovalState }) {
  return (
    <div className={`preview-approval ${approval.status}`}>
      <strong>{approval.title}</strong>
      <span>{approval.message}</span>
    </div>
  );
}

function DiagnosticItem({
  diagnostic,
  onSelectSubject
}: {
  diagnostic: Diagnostic;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}) {
  const subjectLabel = diagnostic.subject ? diagnosticSubjectLabel(diagnostic.subject) : null;
  const canSelect = Boolean(onSelectSubject && diagnostic.subject && diagnostic.subject.kind !== "document");
  return (
    <li className={diagnostic.severity}>
      <strong>{diagnostic.code}</strong>
      <span>{diagnostic.message}</span>
      {diagnostic.subject ? (
        <button
          type="button"
          className="diagnostic-subject-button"
          disabled={!canSelect}
          onClick={() => diagnostic.subject && onSelectSubject?.(diagnostic.subject)}
        >
          {canSelect ? `Show ${subjectLabel}` : subjectLabel}
        </button>
      ) : null}
    </li>
  );
}

function diagnosticSubjectLabel(subject: DiagnosticSubject): string {
  switch (subject.kind) {
    case "document":
      return "document";
    case "page":
      return `artboard ${subject.id}`;
    case "node":
      return `node ${subject.id}`;
    case "slot":
      return `slot ${subject.id}`;
    case "asset":
      return `asset ${subject.id}`;
  }
}

function previewDiagnostics(parityDiagnostics: Diagnostic[], exportDiagnostics: Diagnostic[]): Diagnostic[] {
  const seen = new Set<string>();
  return [...parityDiagnostics, ...exportDiagnostics].filter((diagnostic) => {
    const key = `${diagnostic.code}:${diagnostic.message}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function ArtifactPreview({ artifact }: { artifact: EditorExportArtifact }) {
  if (artifact.format === "svg" || artifact.format === "pdf") {
    return <iframe title="Export preview artifact" src={artifact.data_url ?? undefined} />;
  }
  return <img src={artifact.data_url ?? undefined} alt="Export preview artifact" />;
}

function ArtifactPreviewMeta({ artifact }: { artifact: EditorExportArtifact }) {
  return (
    <dl className="artifact-preview-meta" aria-label="Export preview artifact details">
      <div>
        <dt>Artifact</dt>
        <dd>
          {artifact.format.toUpperCase()} · {artifact.page_id ? `page ${artifact.page_id}` : "document"}
        </dd>
      </div>
      <div>
        <dt>Size</dt>
        <dd>{artifact.byte_length} bytes</dd>
      </div>
      <div>
        <dt>Filename</dt>
        <dd>{artifact.filename}</dd>
      </div>
      <div>
        <dt>Dimensions</dt>
        <dd>{artifact.dimensions ? artifactDimensionLabel(artifact) : "unavailable"}</dd>
      </div>
      {artifact.sidecar_summary ? (
        <div>
          <dt>Sidecar</dt>
          <dd>
            {artifact.sidecar_summary.profile_name ?? "profile"} · {artifact.sidecar_summary.page_count}{" "}
            {artifact.sidecar_summary.page_count === 1 ? "page" : "pages"} · {artifact.sidecar_summary.node_count}{" "}
            {artifact.sidecar_summary.node_count === 1 ? "node" : "nodes"} · {artifact.sidecar_summary.slot_count}{" "}
            {artifact.sidecar_summary.slot_count === 1 ? "slot" : "slots"}
            {artifact.sidecar_summary.slot_keys.length > 0 ? ` · slots ${artifact.sidecar_summary.slot_keys.join(", ")}` : ""}
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

function artifactDimensionLabel(artifact: EditorExportArtifact): string {
  if (!artifact.dimensions) {
    return "unavailable";
  }
  return `${formatNumber(artifact.dimensions.width)} x ${formatNumber(artifact.dimensions.height)} ${artifact.dimensions.unit} · ${artifact.dimensions.source}`;
}

function EmptyPreview() {
  return (
    <div className="empty-state">
      <FileWarning aria-hidden size={18} />
      Export the active page to preview the artifact.
    </div>
  );
}

function ParityBadge({ status }: { status: "match" | "mismatch" | "unavailable" }) {
  return <strong className={`parity-badge ${status}`}>{status === "match" ? "Parity OK" : status === "mismatch" ? "Mismatch" : "No export"}</strong>;
}

function formatSize(size: { width: number; height: number }): string {
  return `${formatNumber(size.width)} x ${formatNumber(size.height)}`;
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}
