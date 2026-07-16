"use client";

import { useMemo, useState } from "react";
import { Download, Eye, Printer } from "lucide-react";
import type { ExportProfile, Page, PageId, Scene } from "@/engine/contracts";
import type { EditorExportArtifact, EditorExportResult, PrintReadyReport } from "@/engine/exportRunner";
import { estimatePngPixelSize, exportProfilesForScene, MAX_RASTER_PIXELS } from "@/engine/exportRunner";
import {
  hasBookletImposition,
  IMPOSED_MARKS_SKIPPED_RULE,
  printReadyNotableRules,
  printReadyPill,
  shouldShowPrintNudge
} from "@/engine/printReadiness";
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
  /** Print workstream W3 master toggle: gates the bleed/marks control and the
   * print-readiness surfacing. Off by default — the panel behaves as today. */
  printFeatureEnabled?: boolean;
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
  onPanelStateChange,
  printFeatureEnabled = false
}: ExportPanelProps) {
  const profiles = exportProfilesForScene(scene);
  const pages = Object.values(scene.pages);
  const activePage = activePageId ? scene.pages[activePageId] ?? null : null;
  const [nudgeDismissed, setNudgeDismissed] = useState(false);

  const selectedProfile = panelState?.draftProfile ?? profiles.find((p) => p.name === panelState?.profileName) ?? null;
  const showNudge =
    !nudgeDismissed &&
    shouldShowPrintNudge({
      printFeatureEnabled,
      profile: selectedProfile,
      activePage,
      hasExportResult: exportResult !== null
    });

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
        printFeatureEnabled={printFeatureEnabled}
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
          {printFeatureEnabled && exportResult.printReady ? (
            <PrintReadyBlock report={exportResult.printReady} />
          ) : null}
          {showNudge ? <PrintNudge onDismiss={() => setNudgeDismissed(true)} /> : null}
        </div>
      ) : pages.length === 0 ? (
        <p className="muted">Add an artboard before exporting.</p>
      ) : null}
    </section>
  );
}

function PrintReadyBlock({ report }: { report: PrintReadyReport }) {
  const pill = printReadyPill(report);
  const notable = printReadyNotableRules(report);
  return (
    <div className="print-ready" data-role="print-ready" data-status={report.status}>
      <div className="print-ready-head">
        <span className={`print-ready-pill ${pill.tone}`} data-role="print-ready-pill">
          {pill.label}
        </span>
        <small className="muted">{report.ruleset}</small>
      </div>
      {notable.length > 0 ? (
        <ul className="print-ready-rules">
          {notable.map((rule) => (
            <li key={rule.id} data-role="print-ready-rule" data-rule-status={rule.status}>
              <span className={`print-ready-rule-dot ${rule.status}`} aria-hidden />
              <span className="print-ready-rule-detail">{rule.detail || rule.id}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function PrintNudge({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div className="print-nudge" data-role="print-nudge" role="note">
      <Printer aria-hidden size={14} />
      <span>Enable “Print &amp; bleed” to add a bleed margin and crop marks to this print PDF.</span>
      <button type="button" className="print-nudge-dismiss" aria-label="Dismiss print hint" onClick={onDismiss}>
        Dismiss
      </button>
    </div>
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
  onPanelStateChange,
  printFeatureEnabled
}: {
  scene: Scene;
  profiles: ExportProfile[];
  pageIds: PageId[];
  activePageId: PageId | null;
  isExporting: boolean;
  onExport: (profile: ExportProfile, pageIds: PageId[]) => void;
  panelState?: ExportPanelState;
  onPanelStateChange?: (state: ExportPanelState) => void;
  printFeatureEnabled: boolean;
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
  const activePage = activePageId ? scene.pages[activePageId] ?? null : null;
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
      {profile && profile.format === "png" ? (
        <RasterScaleField
          profile={profile}
          activePage={activePage}
          onChange={(nextProfile) => updateState({ draftProfile: nextProfile })}
        />
      ) : null}
      {profile && printFeatureEnabled && profile.format === "pdf" ? (
        <PrintBleedField profile={profile} onChange={(nextProfile) => updateState({ draftProfile: nextProfile })} />
      ) : null}
      {profile && printFeatureEnabled && profile.format === "pdf" ? (
        <BookletField profile={profile} onChange={(nextProfile) => updateState({ draftProfile: nextProfile })} />
      ) : null}
      {profile && printFeatureEnabled && profile.format === "pdf" ? (
        <ProofField profile={profile} onChange={(nextProfile) => updateState({ draftProfile: nextProfile })} />
      ) : null}
      {profile && printFeatureEnabled && profile.format === "pdf" && profile.pdf_intent === "print" ? (
        <CmykField profile={profile} onChange={(nextProfile) => updateState({ draftProfile: nextProfile })} />
      ) : null}
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

/** PNG output-scale presets (Figma convention). A saved profile with a
 * non-preset scale still renders — its value joins the options so the
 * select always shows the truth. */
export const RASTER_SCALE_PRESETS = [0.5, 0.75, 1, 1.5, 2, 3, 4];

function RasterScaleField({
  profile,
  activePage,
  onChange
}: {
  profile: ExportProfile;
  activePage: Page | null;
  onChange: (profile: ExportProfile) => void;
}) {
  const scale = profile.raster?.scale ?? 1;
  const options = RASTER_SCALE_PRESETS.includes(scale)
    ? RASTER_SCALE_PRESETS
    : [...RASTER_SCALE_PRESETS, scale].sort((a, b) => a - b);
  const estimate = activePage ? estimatePngPixelSize(activePage, profile.raster) : null;
  const overBudget = estimate ? estimate.width * estimate.height > MAX_RASTER_PIXELS : false;
  return (
    <label className="field" data-role="raster-scale">
      <span>Size</span>
      <select
        value={String(scale)}
        onChange={(event) =>
          onChange(
            normalizeProfile({
              ...profile,
              raster: {
                scale: Number(event.target.value),
                dpi: profile.raster?.dpi ?? 96
              }
            })
          )
        }
      >
        {options.map((preset) => (
          <option key={preset} value={String(preset)}>
            {preset}x
          </option>
        ))}
      </select>
      {estimate ? (
        <small className="muted" data-role="raster-scale-size">
          {estimate.width} × {estimate.height} px
          {overBudget ? " — exceeds the 150 MP export limit" : ""}
        </small>
      ) : null}
    </label>
  );
}

function PrintBleedField({
  profile,
  onChange
}: {
  profile: ExportProfile;
  onChange: (profile: ExportProfile) => void;
}) {
  return (
    <label className="toggle-field" data-role="include-bleed-marks">
      <input
        type="checkbox"
        checked={Boolean(profile.include_bleed && profile.include_marks)}
        onChange={(event) =>
          onChange(
            normalizeProfile({
              ...profile,
              include_bleed: event.target.checked,
              include_marks: event.target.checked
            })
          )
        }
      />
      Include bleed + crop marks
      {hasBookletImposition(profile) ? (
        <small className="muted" data-role="imposed-marks-note">
          Skipped on imposed booklet sheets ({IMPOSED_MARKS_SKIPPED_RULE}).
        </small>
      ) : null}
    </label>
  );
}

function BookletField({
  profile,
  onChange
}: {
  profile: ExportProfile;
  onChange: (profile: ExportProfile) => void;
}) {
  return (
    <label className="toggle-field" data-role="booklet-imposition">
      <input
        type="checkbox"
        checked={hasBookletImposition(profile)}
        onChange={(event) =>
          onChange(
            normalizeProfile({
              ...profile,
              imposition: event.target.checked ? "booklet" : undefined
            })
          )
        }
      />
      Booklet imposition (2-up saddle-stitch)
    </label>
  );
}

function ProofField({
  profile,
  onChange
}: {
  profile: ExportProfile;
  onChange: (profile: ExportProfile) => void;
}) {
  return (
    <label className="toggle-field" data-role="proof-export">
      <input
        type="checkbox"
        checked={Boolean(profile.proof)}
        onChange={(event) =>
          onChange(
            normalizeProfile({
              ...profile,
              proof: event.target.checked ? true : undefined
            })
          )
        }
      />
      Proof export (marks + slug + control strip)
      {profile.proof ? (
        <small className="muted" data-role="proof-note">
          Not for production runs (LUME0431).
        </small>
      ) : null}
    </label>
  );
}

function CmykField({
  profile,
  onChange
}: {
  profile: ExportProfile;
  onChange: (profile: ExportProfile) => void;
}) {
  // Proof exports carry an sRGB control strip that a CMYK conversion would
  // falsify (export.cmyk_proof_conflict); the two are mutually exclusive
  // and proof wins — normalizeProfile drops color while proof is on.
  const proofActive = Boolean(profile.proof);
  return (
    <label className="toggle-field" data-role="cmyk-color">
      <input
        type="checkbox"
        checked={profile.color === "cmyk"}
        disabled={proofActive}
        onChange={(event) =>
          onChange(
            normalizeProfile({
              ...profile,
              color: event.target.checked ? "cmyk" : undefined
            })
          )
        }
      />
      CMYK for offset press (print intent only)
      {proofActive ? (
        <small className="muted" data-role="cmyk-proof-note">
          Unavailable with proof export — the proof&apos;s control strip stays sRGB.
        </small>
      ) : null}
    </label>
  );
}

export function formatPatch(format: ExportProfile["format"], profile: ExportProfile): Partial<ExportProfile> {
  if (format === "png") {
    return {
      format,
      raster: profile.raster ?? {
        scale: 1,
        dpi: 96
      },
      pdf_intent: null,
      include_bleed: false,
      include_marks: false,
      imposition: undefined,
      proof: undefined,
      color: undefined,
      embed_fonts: false
    };
  }
  if (format === "pdf") {
    // Preserve include_bleed / include_marks / embed_fonts / imposition / proof
    // across the switch — they are the print controls and only PDF exposes them,
    // so clearing them here would silently drop the user's choice every time
    // they toggle format.
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
    include_marks: false,
    imposition: undefined,
    proof: undefined,
    color: undefined,
    // SVG: fonts embed by default (@font-face subsets) so the export does
    // not depend on viewer-installed fonts.
    embed_fonts: true
  };
}

export function normalizeProfile(profile: ExportProfile): ExportProfile {
  // Booklet imposition and proof mode are print/PDF-only concerns; strip them
  // for any other format so they never ride along on a raster or plain vector
  // export.
  const imposition = profile.format === "pdf" ? profile.imposition : undefined;
  const proof = profile.format === "pdf" ? profile.proof : undefined;
  // CMYK is valid ONLY on print-intent PDFs (export.cmyk_requires_print_intent)
  // and never on proof exports (export.cmyk_proof_conflict — the proof's sRGB
  // control strip would be falsified by the conversion); strip it for any
  // other combination so the editor can never emit an invalid request.
  const color =
    profile.format === "pdf" && profile.pdf_intent === "print" && !proof
      ? profile.color
      : undefined;
  if (profile.format !== "png") {
    // SVG/PDF: keep include_bleed / include_marks / embed_fonts as set.
    return {
      ...profile,
      raster: null,
      imposition,
      proof,
      color
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
    include_marks: false,
    imposition,
    proof,
    color,
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
