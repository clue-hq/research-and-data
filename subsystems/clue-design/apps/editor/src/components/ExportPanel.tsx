"use client";

import { useMemo, useState } from "react";
import { Download, Eye } from "lucide-react";
import type { ExportProfile, PageId, Scene } from "@/engine/contracts";
import type { EditorExportArtifact, EditorExportResult } from "@/engine/exportRunner";
import { exportProfilesForScene } from "@/engine/exportRunner";
import { downloadDataUrl } from "./exportArtifactActions";

interface ExportPanelProps {
  scene: Scene;
  activePageId: PageId | null;
  exportResult: EditorExportResult | null;
  isExporting: boolean;
  onExport: (profile: ExportProfile, pageIds: PageId[]) => void;
  onSaveProfile: (profile: ExportProfile) => void;
  onRemoveProfile: (name: string) => void;
  panelState?: ExportPanelState;
  onPanelStateChange?: (state: ExportPanelState) => void;
}

export type ExportScope = "active" | "all";

export interface ExportPanelState {
  profileName: string;
  scope: ExportScope;
  draftProfile: ExportProfile | null;
}

export function ExportPanel({
  scene,
  activePageId,
  exportResult,
  isExporting,
  onExport,
  panelState,
  onPanelStateChange
}: ExportPanelProps) {
  const profiles = exportProfilesForScene(scene);
  const pages = Object.values(scene.pages);

  return (
    <section className="inspector-section">
      <div className="section-heading">
        <Download aria-hidden size={15} />
        Export
      </div>
      <ExportControls
        scene={scene}
        profiles={profiles}
        pageIds={pages.map((page) => page.id)}
        activePageId={activePageId}
        isExporting={isExporting}
        onExport={onExport}
        panelState={panelState}
        onPanelStateChange={onPanelStateChange}
      />
      {exportResult ? (
        <div className="export-summary" aria-live="polite">
          <strong>{exportResult.status === "ok" ? "Export ready" : "Export failed"}</strong>
          {exportResult.artifacts.length > 0 ? (
            exportResult.artifacts.map((artifact, index) => (
              <ExportArtifactRow key={`${artifact.format}-${artifact.page_id ?? index}`} artifact={artifact} />
            ))
          ) : (
            <span>No artifact generated.</span>
          )}
        </div>
      ) : pages.length === 0 ? (
        <p className="muted">Add an artboard before exporting.</p>
      ) : null}
    </section>
  );
}

function ExportControls({
  scene,
  profiles,
  pageIds,
  activePageId,
  isExporting,
  onExport,
  panelState,
  onPanelStateChange
}: {
  scene: Scene;
  profiles: ExportProfile[];
  pageIds: PageId[];
  activePageId: PageId | null;
  isExporting: boolean;
  onExport: (profile: ExportProfile, pageIds: PageId[]) => void;
  panelState?: ExportPanelState;
  onPanelStateChange?: (state: ExportPanelState) => void;
}) {
  const [uncontrolledState, setUncontrolledState] = useState<ExportPanelState>(() => ({
    profileName: profiles[0]?.name ?? "",
    scope: "active",
    draftProfile: profiles[0] ?? null
  }));
  const state = panelState ?? uncontrolledState;
  const updateState = (patch: Partial<ExportPanelState>) => {
    const nextState = {
      ...state,
      ...patch
    };
    if (onPanelStateChange) {
      onPanelStateChange(nextState);
    } else {
      setUncontrolledState(nextState);
    }
  };
  const selectedProfile = useMemo(
    () => profiles.find((candidate) => candidate.name === state.profileName) ?? profiles[0],
    [state.profileName, profiles]
  );
  const profile = state.draftProfile ?? selectedProfile;
  const visibleProfiles = useMemo(() => {
    if (!profile || profiles.some((candidate) => candidate.name === profile.name)) {
      return profiles;
    }
    return [...profiles, profile];
  }, [profile, profiles]);
  const selectedPageIds = state.scope === "all" ? pageIds : activePageId ? [activePageId] : [];
  void scene;
  return (
    <div className="export-controls">
      <label className="field">
        <span>Profile</span>
        <select
          value={profile?.name ?? ""}
          onChange={(event) => {
            const nextProfile = visibleProfiles.find((candidate) => candidate.name === event.target.value) ?? profiles[0] ?? null;
            updateState({
              profileName: nextProfile?.name ?? "",
              draftProfile: nextProfile
            });
          }}
        >
          {visibleProfiles.map((candidate) => (
            <option key={candidate.name} value={candidate.name}>
              {candidate.name}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Artboard</span>
        <select value={state.scope} onChange={(event) => updateState({ scope: event.target.value as ExportScope })}>
          <option value="active">Selected artboard</option>
          <option value="all">All artboards</option>
        </select>
      </label>
      {profile ? <ExportFormatField profile={profile} onChange={(nextProfile) => updateState({ draftProfile: nextProfile })} /> : null}
      <button
        type="button"
        disabled={!profile || selectedPageIds.length === 0 || isExporting}
        onClick={() => profile && selectedPageIds.length > 0 && onExport(profile, selectedPageIds)}
      >
        <Eye aria-hidden size={15} />
        {isExporting ? "Exporting" : "Generate preview"}
      </button>
    </div>
  );
}

function ExportFormatField({
  profile,
  onChange
}: {
  profile: ExportProfile;
  onChange: (profile: ExportProfile) => void;
}) {
  const update = (patch: Partial<ExportProfile>) => onChange(normalizeProfile({ ...profile, ...patch }));
  return (
    <label className="field">
      <span>Format</span>
      <select
        value={profile.format}
        onChange={(event) => update(formatPatch(event.target.value as ExportProfile["format"], profile))}
      >
        <option value="svg">SVG</option>
        <option value="png">PNG</option>
        <option value="pdf">PDF</option>
      </select>
    </label>
  );
}

function formatPatch(format: ExportProfile["format"], profile: ExportProfile): Partial<ExportProfile> {
  if (format === "png") {
    return {
      format,
      raster: profile.raster ?? {
        scale: 1,
        dpi: 96
      },
      pdf_intent: null,
      include_bleed: false,
      embed_fonts: false
    };
  }
  if (format === "pdf") {
    return {
      format,
      raster: null,
      pdf_intent: profile.pdf_intent ?? "preview"
    };
  }
  return {
    format,
    raster: null,
    pdf_intent: null,
    include_bleed: false,
    embed_fonts: false
  };
}

function normalizeProfile(profile: ExportProfile): ExportProfile {
  if (profile.format !== "png") {
    return {
      ...profile,
      raster: null
    };
  }
  return {
    ...profile,
    raster: {
      scale: clampNumber(profile.raster?.scale ?? 1, 0.1, 8),
      dpi: profile.raster?.dpi === null || profile.raster?.dpi === undefined
        ? null
        : Math.round(clampNumber(profile.raster.dpi, 1, 1200))
    },
    pdf_intent: null,
    include_bleed: false,
    embed_fonts: false
  };
}

function ExportArtifactRow({ artifact }: { artifact: EditorExportArtifact }) {
  return (
    <div className="export-artifact">
      <span>
        {artifact.format.toUpperCase()}
        {artifact.page_id ? ` · ${artifact.page_id}` : ""}
      </span>
      <small>
        {artifact.filename}
      </small>
      {artifact.data_url ? (
        <div className="artifact-actions">
          <button type="button" className="primary-action" onClick={() => downloadDataUrl(artifact.data_url, artifact.filename)}>
            <Download aria-hidden size={14} />
            Download
          </button>
        </div>
      ) : null}
    </div>
  );
}

function clampNumber(value: number, min?: number, max?: number): number {
  if (min !== undefined && value < min) {
    return min;
  }
  if (max !== undefined && value > max) {
    return max;
  }
  return value;
}
