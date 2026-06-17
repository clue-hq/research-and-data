"use client";

import { useEffect, useRef, useState } from "react";
import { FileWarning } from "lucide-react";
import type { DiagnosticSubject, PageId, Scene } from "@/engine/contracts";
import type { EditorExportArtifact, EditorExportResult } from "@/engine/exportRunner";
import { artifactForPage } from "@/engine/exportParity";

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
  void scene;
  void onSelectSubject;

  return (
    <section className="export-preview-shell">
      <div className="export-preview-body">
        {artifact?.data_url ? (
          <ArtifactPreview artifact={artifact} />
        ) : (
          <EmptyPreview />
        )}
      </div>
    </section>
  );
}

function ArtifactPreview({ artifact }: { artifact: EditorExportArtifact }) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [frameSize, setFrameSize] = useState<{ width: number; height: number } | null>(null);
  const aspectRatio = artifactPreviewAspectRatio(artifact);
  const previewSize = previewMediaSize(artifact, frameSize);
  const previewStyle = {
    aspectRatio,
    ...(previewSize ? { width: `${previewSize.width}px`, height: `${previewSize.height}px` } : {})
  };

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || typeof ResizeObserver === "undefined") {
      return;
    }
    const updateFrameSize = () => {
      const rect = frame.getBoundingClientRect();
      setFrameSize({ width: rect.width, height: rect.height });
    };
    updateFrameSize();
    const observer = new ResizeObserver(updateFrameSize);
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);

  if (artifact.format === "pdf") {
    return (
      <div ref={frameRef} className="artifact-preview-frame">
        <div className="artifact-preview-media" style={previewStyle}>
          <iframe title="Export preview artifact" src={artifact.data_url ?? undefined} />
        </div>
      </div>
    );
  }
  return (
    <div ref={frameRef} className="artifact-preview-frame">
      <div className="artifact-preview-media" style={previewStyle}>
        <img src={artifact.data_url ?? undefined} alt="Export preview artifact" />
      </div>
    </div>
  );
}

function previewMediaSize(
  artifact: EditorExportArtifact,
  frameSize: { width: number; height: number } | null
): { width: number; height: number } | null {
  const artifactWidth = artifact.dimensions?.width;
  const artifactHeight = artifact.dimensions?.height;
  if (!frameSize || !artifactWidth || !artifactHeight || artifactWidth <= 0 || artifactHeight <= 0) {
    return null;
  }
  const ratio = artifactWidth / artifactHeight;
  let width = frameSize.width;
  let height = width / ratio;
  if (height > frameSize.height) {
    height = frameSize.height;
    width = height * ratio;
  }
  return {
    width: Math.max(1, Math.floor(width)),
    height: Math.max(1, Math.floor(height))
  };
}

function artifactPreviewAspectRatio(artifact: EditorExportArtifact): string {
  const width = artifact.dimensions?.width;
  const height = artifact.dimensions?.height;
  if (!width || !height || width <= 0 || height <= 0) {
    return "1 / 1";
  }
  return `${width} / ${height}`;
}

function EmptyPreview() {
  return (
    <div className="empty-state">
      <FileWarning aria-hidden size={18} />
      Export the active page to preview the artifact.
    </div>
  );
}
