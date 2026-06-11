"use client";

import { useMemo, useState } from "react";
import { Copy, Download, Eye, Save, Trash2 } from "lucide-react";
import type { Diagnostic, DiagnosticSubject, ExportProfile, PageId, Scene } from "@/engine/contracts";
import type { EditorExportArtifact, EditorExportResult } from "@/engine/exportRunner";
import { exportProfilesForScene } from "@/engine/exportRunner";

interface ExportPanelProps {
  scene: Scene;
  activePageId: PageId | null;
  exportResult: EditorExportResult | null;
  isExporting: boolean;
  onExport: (profile: ExportProfile, pageIds: PageId[]) => void;
  onSaveProfile: (profile: ExportProfile) => void;
  onRemoveProfile: (name: string) => void;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}

const RASTER_EDGE_WARNING_PX = 8192;
const RASTER_AREA_WARNING_PX = 33_000_000;

export function ExportPanel({
  scene,
  activePageId,
  exportResult,
  isExporting,
  onExport,
  onSaveProfile,
  onRemoveProfile,
  onSelectSubject
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
        onSaveProfile={onSaveProfile}
        onRemoveProfile={onRemoveProfile}
        onSelectSubject={onSelectSubject}
      />
      <p className="muted contract-note">
        Export uses the canonical scene page size, computed geometry, and selected profile. Presets do not replace custom
        page dimensions.
      </p>
      {exportResult ? (
        <div className="export-summary" aria-live="polite">
          <strong>{exportResult.status === "ok" ? "Export ready" : "Export failed"}</strong>
          <span>
            {exportResult.artifacts.length} artifact{exportResult.artifacts.length === 1 ? "" : "s"}
          </span>
          {exportResult.artifacts.map((artifact, index) => (
            <ExportArtifactRow key={`${artifact.format}-${artifact.page_id ?? index}`} artifact={artifact} />
          ))}
          {exportResult.diagnostics.length > 0 ? (
            <ExportDiagnosticList diagnostics={exportResult.diagnostics} onSelectSubject={onSelectSubject} />
          ) : null}
        </div>
      ) : pages.length === 0 ? (
        <p className="muted">Add a page before exporting.</p>
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
  onSaveProfile,
  onRemoveProfile,
  onSelectSubject
}: {
  scene: Scene;
  profiles: ExportProfile[];
  pageIds: PageId[];
  activePageId: PageId | null;
  isExporting: boolean;
  onExport: (profile: ExportProfile, pageIds: PageId[]) => void;
  onSaveProfile: (profile: ExportProfile) => void;
  onRemoveProfile: (name: string) => void;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}) {
  const [profileName, setProfileName] = useState(profiles[0]?.name ?? "");
  const [scope, setScope] = useState<"active" | "all">("active");
  const selectedProfile = useMemo(
    () => profiles.find((candidate) => candidate.name === profileName) ?? profiles[0],
    [profileName, profiles]
  );
  const [draftProfile, setDraftProfile] = useState<ExportProfile | null>(() => selectedProfile ?? null);
  const profile = draftProfile ?? selectedProfile;
  const visibleProfiles = useMemo(() => {
    if (!profile || profiles.some((candidate) => candidate.name === profile.name)) {
      return profiles;
    }
    return [...profiles, profile];
  }, [profile, profiles]);
  const selectedPageIds = scope === "all" ? pageIds : activePageId ? [activePageId] : [];
  const readiness = profile ? exportReadinessNotes(scene, profile, selectedPageIds) : [];
  const isSavedProfile = profile ? scene.export_profiles.some((candidate) => candidate.name === profile.name) : false;
  const profileIsInList = profile ? profiles.some((candidate) => candidate.name === profile.name) : false;
  return (
    <div className="export-controls">
      <label className="field">
        <span>Profile</span>
        <select
          value={profile?.name ?? ""}
          onChange={(event) => {
            const nextProfile = visibleProfiles.find((candidate) => candidate.name === event.target.value) ?? profiles[0] ?? null;
            setProfileName(nextProfile?.name ?? "");
            setDraftProfile(nextProfile);
          }}
        >
          {visibleProfiles.map((candidate) => (
            <option key={candidate.name} value={candidate.name}>
              {candidate.name} ({candidate.format}{profile?.name === candidate.name && !profileIsInList ? ", unsaved" : ""})
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Pages</span>
        <select value={scope} onChange={(event) => setScope(event.target.value as "active" | "all")}>
          <option value="active">Active page</option>
          <option value="all">All pages</option>
        </select>
      </label>
      {profile ? <ExportProfileEditor profile={profile} onChange={setDraftProfile} /> : null}
      <button
        type="button"
        disabled={!profile || selectedPageIds.length === 0 || isExporting}
        onClick={() => profile && selectedPageIds.length > 0 && onExport(profile, selectedPageIds)}
      >
        <Eye aria-hidden size={15} />
        {isExporting ? "Exporting" : "Generate preview"}
      </button>
      <div className="button-row">
        <button
          type="button"
          disabled={!profile}
          onClick={() => {
            if (!profile) {
              return;
            }
            setProfileName(profile.name);
            setDraftProfile(profile);
            onSaveProfile(profile);
          }}
        >
          <Save aria-hidden size={15} />
          {isSavedProfile ? "Update saved profile" : "Save profile"}
        </button>
        <button
          type="button"
          disabled={!profile || !isSavedProfile}
          onClick={() => {
            if (!profile) {
              return;
            }
            const fallbackProfile = profiles.find((candidate) => candidate.name !== profile.name) ?? null;
            setProfileName(fallbackProfile?.name ?? "");
            setDraftProfile(fallbackProfile);
            onRemoveProfile(profile.name);
          }}
        >
          <Trash2 aria-hidden size={15} />
          Remove saved
        </button>
      </div>
      {profile && !profileIsInList ? (
        <p className="muted">This profile is an unsaved draft. Save it to keep it with the document.</p>
      ) : null}
      <p className="muted">
        {scene.export_profiles.length} document export profile{scene.export_profiles.length === 1 ? "" : "s"} saved.
      </p>
      {readiness.length > 0 ? (
        <ExportDiagnosticList diagnostics={readiness} compact onSelectSubject={onSelectSubject} />
      ) : null}
    </div>
  );
}

function ExportDiagnosticList({
  diagnostics,
  compact = false,
  onSelectSubject
}: {
  diagnostics: Diagnostic[];
  compact?: boolean;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}) {
  return (
    <ul className={`diagnostic-list${compact ? " compact" : ""}`}>
      {diagnostics.map((diagnostic) => (
        <ExportDiagnosticItem
          key={`${diagnostic.code}-${diagnostic.message}`}
          diagnostic={diagnostic}
          onSelectSubject={onSelectSubject}
        />
      ))}
    </ul>
  );
}

function ExportDiagnosticItem({
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
      return `page ${subject.id}`;
    case "node":
      return `node ${subject.id}`;
    case "slot":
      return `slot ${subject.id}`;
    case "asset":
      return `asset ${subject.id}`;
  }
}

function ExportProfileEditor({
  profile,
  onChange
}: {
  profile: ExportProfile;
  onChange: (profile: ExportProfile) => void;
}) {
  const update = (patch: Partial<ExportProfile>) => onChange(normalizeProfile({ ...profile, ...patch }));
  return (
    <div className="profile-editor" aria-label="Export profile settings">
      <label className="field">
        <span>Profile name</span>
        <input value={profile.name} onChange={(event) => update({ name: sanitizeProfileName(event.target.value) })} />
      </label>
      <label className="field">
        <span>Format</span>
        <select
          value={profile.format}
          onChange={(event) => update(formatPatch(event.target.value as ExportProfile["format"], profile))}
        >
          <option value="svg">SVG</option>
          <option value="png">PNG</option>
          <option value="pdf">PDF</option>
          <option value="figma_manifest">Figma manifest</option>
        </select>
      </label>
      {profile.format === "png" ? (
        <div className="field-grid two">
          <NumberField
            label="Scale"
            value={profile.raster?.scale ?? 1}
            min={0.1}
            max={8}
            step={0.1}
            onCommit={(scale) =>
              update({
                raster: {
                  scale,
                  dpi: profile.raster?.dpi ?? 96
                }
              })
            }
          />
          <NumberField
            label="DPI"
            value={profile.raster?.dpi ?? 96}
            min={1}
            max={1200}
            onCommit={(dpi) =>
              update({
                raster: {
                  scale: profile.raster?.scale ?? 1,
                  dpi: Math.round(dpi)
                }
              })
            }
          />
        </div>
      ) : null}
      {profile.format === "pdf" ? (
        <>
          <label className="field">
            <span>PDF intent</span>
            <select
              value={profile.pdf_intent ?? "preview"}
              onChange={(event) => update({ pdf_intent: event.target.value as "preview" | "print" })}
            >
              <option value="preview">Preview</option>
              <option value="print">Print</option>
            </select>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={profile.include_bleed}
              onChange={(event) => update({ include_bleed: event.target.checked })}
            />
            Include bleed
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={profile.embed_fonts}
              onChange={(event) => update({ embed_fonts: event.target.checked })}
            />
            Request font embedding
          </label>
        </>
      ) : null}
    </div>
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

function sanitizeProfileName(name: string): string {
  const trimmed = name.trim().replace(/\s+/g, "_").toLowerCase();
  return trimmed.length > 0 ? trimmed : "custom_export_profile";
}

function exportReadinessNotes(scene: Scene, profile: ExportProfile, pageIds: PageId[]): Diagnostic[] {
  const notes: Diagnostic[] = [];
  if (profile.pdf_intent === "print") {
    const selectedPages = pageIds.flatMap((pageId) => {
      const page = scene.pages[pageId];
      return page ? [page] : [];
    });
    if (selectedPages.length > 1) {
      notes.push(exportReadinessDiagnostic(
        "warning",
        "PRINT_EXPLICIT_PAGINATION",
        `This print PDF exports ${selectedPages.length} explicit pages. Automatic flowed pagination is not performed in Phase F.`,
        {
          kind: "document"
        },
        "Review each page/artboard explicitly before print handoff."
      ));
      if (hasMixedPageSizes(selectedPages)) {
        notes.push(exportReadinessDiagnostic(
          "warning",
          "PRINT_MIXED_PAGE_SIZES",
          `Selected print pages use mixed sizes: ${selectedPages.map((page) => `${page.name} ${pageSizeLabel(page)}`).join("; ")}.`,
          {
            kind: "document"
          },
          "Many print handoffs expect a consistent trim size. Verify mixed custom artboards before approving the PDF."
        ));
      }
    }
    for (const pageId of pageIds) {
      const page = scene.pages[pageId];
      if (!page) {
        continue;
      }
      if (!page.safe_area) {
        notes.push(exportReadinessDiagnostic(
          "warning",
          `PRINT_SAFE_AREA_${pageId}`,
          `${page.name} has no safe area. Add one before treating print export as ready.`,
          {
            kind: "page",
            id: pageId
          },
          "Use the page inspector to add safe-area metadata."
        ));
      }
      if (profile.include_bleed && !page.bleed) {
        notes.push(exportReadinessDiagnostic(
          "warning",
          `PRINT_BLEED_${pageId}`,
          `${page.name} has no bleed guide but the selected profile includes bleed.`,
          {
            kind: "page",
            id: pageId
          },
          "Use the page inspector to add bleed before print handoff."
        ));
      }
      for (const nodeId of pageNodeIds(scene, pageId)) {
        const node = scene.nodes[nodeId];
        if (!node) {
          continue;
        }
        if (node.kind.kind === "text") {
          const direction = node.kind.direction ?? "ltr";
          if (direction !== "ltr") {
            notes.push(exportReadinessDiagnostic(
              "warning",
              `PRINT_TEXT_DIRECTION_${node.id}`,
              `${node.name ?? node.id} uses ${direction} text direction. Early PDF export does not shape bidirectional text yet.`,
              {
                kind: "node",
                id: node.id
              },
              "Review this text node before final PDF handoff."
            ));
          }
          if (containsNonLatinAlphabetic(node.kind.content)) {
            notes.push(exportReadinessDiagnostic(
              "warning",
              `PRINT_TEXT_NON_LATIN_${node.id}`,
              `${node.name ?? node.id} contains non-Latin text. Early PDF export uses built-in Latin fonts.`,
              {
                kind: "node",
                id: node.id
              },
              "Use a later print-fidelity path with font embedding and shaping before final handoff."
            ));
          }
        }
        if (node.kind.kind === "image") {
          const asset = scene.assets[node.kind.asset_id];
          if (!asset) {
            notes.push(exportReadinessDiagnostic(
              "warning",
              `PRINT_IMAGE_ASSET_${node.id}`,
              `${node.name ?? node.id} references missing image asset ${node.kind.asset_id}.`,
              {
                kind: "node",
                id: node.id
              },
              "Resolve or replace the image asset before exporting."
            ));
            continue;
          }
          const dpiValues = [asset.raster?.dpi_x, asset.raster?.dpi_y].filter(
            (dpi): dpi is number => typeof dpi === "number" && Number.isFinite(dpi)
          );
          if (dpiValues.length === 0) {
            notes.push(exportReadinessDiagnostic(
              "warning",
              `PRINT_IMAGE_DPI_UNKNOWN_${node.id}`,
              `${asset.label} has no DPI metadata. Probe image DPI before treating print export as ready.`,
              {
                kind: "node",
                id: node.id
              },
              "Use the asset pipeline to probe image metadata before print handoff."
            ));
          } else if (Math.min(...dpiValues) < 300) {
            notes.push(exportReadinessDiagnostic(
              "warning",
              `PRINT_IMAGE_DPI_${node.id}`,
              `${asset.label} is ${Math.min(...dpiValues)} DPI. 300 DPI is recommended for print.`,
              {
                kind: "node",
                id: node.id
              },
              "Replace with a higher-resolution image before print handoff."
            ));
          }
        }
      }
    }
    if (profile.embed_fonts) {
      notes.push(exportReadinessDiagnostic(
        "advice",
        "PRINT_FONT_EMBEDDING",
        "Early PDF export reports font embedding/subsetting limitations as export diagnostics.",
        {
          kind: "document"
        },
        "Final font embedding and subsetting belong to the later print-fidelity track."
      ));
    }
  }
  if (profile.format === "png" && profile.raster?.dpi !== null && profile.raster?.dpi !== undefined && profile.raster.dpi < 300) {
    notes.push(exportReadinessDiagnostic(
      "advice",
      "PNG_DPI_PREVIEW",
      "This PNG profile is preview-grade. Use high_res_png for a 300 DPI export request.",
      {
        kind: "document"
      },
      null
    ));
  }
  if (profile.format === "png") {
    for (const pageId of pageIds) {
      const page = scene.pages[pageId];
      if (!page) {
        continue;
      }
      const raster = rasterPixelDimensions(page, profile);
      const area = raster.width * raster.height;
      if (raster.width > RASTER_EDGE_WARNING_PX || raster.height > RASTER_EDGE_WARNING_PX || area > RASTER_AREA_WARNING_PX) {
        notes.push(exportReadinessDiagnostic(
          "warning",
          `PNG_RASTER_SIZE_${pageId}`,
          `${page.name} will export to ${formatNumber(raster.width)} x ${formatNumber(raster.height)} px (${formatMegapixels(area)} MP) with ${profile.name}. Large custom artifacts may be slow or fail during PNG preview/export.`,
          {
            kind: "page",
            id: pageId
          },
          "Reduce the PNG scale/DPI for preview, export this page as SVG/PDF, or split very large artifacts before raster export."
        ));
      }
    }
  }
  return notes;
}

function hasMixedPageSizes(pages: Array<Scene["pages"][PageId]>): boolean {
  const first = pages[0];
  if (!first) {
    return false;
  }
  return pages.slice(1).some((page) => !samePageSize(page, first));
}

function samePageSize(left: Scene["pages"][PageId], right: Scene["pages"][PageId]): boolean {
  return left.size.unit === right.size.unit &&
    left.size.width === right.size.width &&
    left.size.height === right.size.height;
}

function pageSizeLabel(page: Scene["pages"][PageId]): string {
  return `${formatNumber(page.size.width)} x ${formatNumber(page.size.height)} ${page.size.unit}`;
}

function rasterPixelDimensions(page: Scene["pages"][PageId], profile: ExportProfile): { width: number; height: number } {
  const scale = profile.raster?.scale ?? 1;
  const dpi = profile.raster?.dpi ?? 96;
  const widthIn = sceneLengthToInches(page.size.width, page.size.unit, dpi);
  const heightIn = sceneLengthToInches(page.size.height, page.size.unit, dpi);
  return {
    width: Math.max(1, Math.round(widthIn * dpi * scale)),
    height: Math.max(1, Math.round(heightIn * dpi * scale))
  };
}

function sceneLengthToInches(value: number, unit: Scene["pages"][PageId]["size"]["unit"], dpi: number): number {
  switch (unit) {
    case "px":
      return value / dpi;
    case "mm":
      return value / 25.4;
    case "in":
      return value;
  }
}

function formatMegapixels(value: number): string {
  return (value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2);
}

function exportReadinessDiagnostic(
  severity: Diagnostic["severity"],
  code: string,
  message: string,
  subject: DiagnosticSubject,
  hint: string | null
): Diagnostic {
  return {
    severity,
    phase: "export",
    code,
    message,
    subject,
    hint
  };
}

function pageNodeIds(scene: Scene, pageId: PageId): string[] {
  const page = scene.pages[pageId];
  if (!page) {
    return [];
  }

  const ids: string[] = [];
  const visit = (nodeId: string) => {
    ids.push(nodeId);
    for (const childId of scene.nodes[nodeId]?.children ?? []) {
      visit(childId);
    }
  };
  for (const nodeId of page.children) {
    visit(nodeId);
  }
  return ids;
}

function containsNonLatinAlphabetic(value: string): boolean {
  return [...value].some((character) => /\p{L}/u.test(character) && !/[A-Za-z]/.test(character));
}

function ExportArtifactRow({ artifact }: { artifact: EditorExportArtifact }) {
  const [copyStatus, setCopyStatus] = useState<"idle" | "svg_copied" | "sidecar_copied" | "failed">("idle");
  const sidecar = artifact.sidecar_summary;
  const canCopySvg = artifact.format === "svg" && artifact.text !== null;
  const sidecarDataUrl = artifact.sidecar_json
    ? textDataUrl("application/json", artifact.sidecar_json)
    : null;

  async function handleCopySvg() {
    if (!artifact.text) {
      return;
    }
    const copied = await copyText(artifact.text);
    setCopyStatus(copied ? "svg_copied" : "failed");
  }

  async function handleCopySidecar() {
    if (!artifact.sidecar_json) {
      return;
    }
    const copied = await copyText(artifact.sidecar_json);
    setCopyStatus(copied ? "sidecar_copied" : "failed");
  }

  return (
    <div className="export-artifact">
      <span>
        {artifact.format.toUpperCase()} {artifact.page_id ? `page ${artifact.page_id}` : "document"}
      </span>
      <small>
        {artifact.mime_type} · {artifact.byte_length} bytes
      </small>
      <small>Filename {artifact.filename}</small>
      {artifact.dimensions ? (
        <small>
          Dimensions {formatNumber(artifact.dimensions.width)} x {formatNumber(artifact.dimensions.height)}{" "}
          {artifact.dimensions.unit} · {artifact.dimensions.source}
        </small>
      ) : null}
      {sidecar ? (
        <small>
          Sidecar {sidecar.profile_name ?? "unknown profile"} · {sidecar.page_count} page
          {sidecar.page_count === 1 ? "" : "s"} · {sidecar.node_count} node
          {sidecar.node_count === 1 ? "" : "s"} · {sidecar.slot_count} slot
          {sidecar.slot_count === 1 ? "" : "s"}
          {sidecar.page_ids.length > 0 ? ` · pages ${sidecar.page_ids.join(", ")}` : ""}
          {sidecar.slot_keys.length > 0 ? ` · slots ${sidecar.slot_keys.join(", ")}` : ""}
        </small>
      ) : null}
      {artifact.data_url ? (
        <div className="artifact-actions">
          <a href={artifact.data_url} download={artifact.filename}>
            Download
          </a>
          {canCopySvg ? (
            <button type="button" onClick={handleCopySvg}>
              <Copy aria-hidden size={13} />
              Copy SVG
            </button>
          ) : null}
          {sidecarDataUrl ? (
            <>
              <a href={sidecarDataUrl} download={artifact.sidecar_filename ?? `${artifact.filename}.sidecar.json`}>
                Download sidecar
              </a>
              <button type="button" onClick={handleCopySidecar}>
                <Copy aria-hidden size={13} />
                Copy sidecar
              </button>
            </>
          ) : null}
        </div>
      ) : null}
      {copyStatus !== "idle" ? (
        <small aria-live="polite">
          {copyStatus === "svg_copied"
            ? "SVG copied"
            : copyStatus === "sidecar_copied"
              ? "Sidecar copied"
              : "Copy failed"}
        </small>
      ) : null}
    </div>
  );
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "true");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(textarea);
    return copied;
  } catch {
    return false;
  }
}

function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  onCommit
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onCommit: (value: number) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        min={min}
        max={max}
        step={step}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next)) {
            onCommit(clampNumber(next, min, max));
          }
        }}
      />
    </label>
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

function textDataUrl(mimeType: string, text: string): string {
  return `data:${mimeType};charset=utf-8,${encodeURIComponent(text)}`;
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}
