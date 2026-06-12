import type { Diagnostic, DiagnosticSubject, ExportProfile, PageId, Scene } from "./contracts";

export interface EditorExportRequest {
  scene: Scene;
  profile: ExportProfile;
  pageIds: PageId[];
  documentId?: string;
}

export interface EditorExportArtifact {
  format: ExportProfile["format"];
  page_id: PageId | null;
  asset_id: string | null;
  filename: string;
  sidecar_filename: string | null;
  mime_type: string;
  byte_length: number;
  dimensions: EditorExportArtifactDimensions | null;
  data_url: string | null;
  text: string | null;
  sidecar_json: string | null;
  sidecar_summary: EditorExportSidecarSummary | null;
}

export interface EditorExportArtifactDimensions {
  width: number;
  height: number;
  unit: string;
  source: string;
}

export interface EditorExportSidecarSummary {
  profile_name: string | null;
  page_count: number;
  node_count: number;
  slot_count: number;
  page_ids: PageId[];
  slot_keys: string[];
}

export interface EditorExportResult {
  status: "ok" | "failed";
  diagnostics: Diagnostic[];
  artifacts: EditorExportArtifact[];
}

export type EditorExportRunner = (
  request: EditorExportRequest
) => EditorExportResult | Promise<EditorExportResult>;

export interface ApiExportRunnerOptions {
  apiBaseUrl: string;
  documentId?: string;
}

export function createApiExportRunner({ apiBaseUrl, documentId: configuredDocumentId }: ApiExportRunnerOptions): EditorExportRunner {
  return async ({ scene, profile, pageIds, documentId }) => {
    const effectiveDocumentId = documentId ?? configuredDocumentId;
    const response = await fetch(exportUrl(apiBaseUrl, effectiveDocumentId), {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify(exportPayload(scene, profile, pageIds, effectiveDocumentId))
    });

    if (!response.ok) {
      throw new Error(`Export request failed with HTTP ${response.status}`);
    }

    return exportResultFromUnknown(await response.json());
  };
}

function exportUrl(apiBaseUrl: string, documentId?: string): URL {
  if (!documentId) {
    return new URL("/export-preview", apiBaseUrl);
  }
  return new URL(`/documents/${encodeURIComponent(documentId)}/export`, apiBaseUrl);
}

function exportPayload(
  scene: Scene,
  profile: ExportProfile,
  pageIds: PageId[],
  documentId?: string
): Record<string, unknown> {
  if (documentId) {
    return {
      format: profile.format,
      page_ids: pageIds,
      profile
    };
  }
  return {
    scene,
    format: profile.format,
    page_ids: pageIds,
    profile
  };
}

export function defaultEditorExportProfile(): ExportProfile {
  return {
    name: "preview_svg",
    format: "svg",
    pdf_intent: "preview",
    raster: null,
    include_bleed: false,
    embed_fonts: false
  };
}

export function builtInExportProfiles(): ExportProfile[] {
  return [
    defaultEditorExportProfile(),
    {
      name: "preview_png",
      format: "png",
      pdf_intent: null,
      raster: {
        scale: 1,
        dpi: 96
      },
      include_bleed: false,
      embed_fonts: false
    },
    {
      name: "preview_pdf",
      format: "pdf",
      pdf_intent: "preview",
      raster: null,
      include_bleed: false,
      embed_fonts: false
    },
    {
      name: "high_res_png",
      format: "png",
      pdf_intent: null,
      raster: {
        scale: 2,
        dpi: 300
      },
      include_bleed: false,
      embed_fonts: false
    },
    {
      name: "print_pdf",
      format: "pdf",
      pdf_intent: "print",
      raster: null,
      include_bleed: true,
      embed_fonts: true
    }
  ];
}

export function exportProfilesForScene(scene: Scene): ExportProfile[] {
  const profilesByName = new Map<string, ExportProfile>();
  for (const profile of builtInExportProfiles()) {
    profilesByName.set(profile.name, profile);
  }
  for (const profile of scene.export_profiles ?? []) {
    profilesByName.set(profile.name, profile);
  }
  return [...profilesByName.values()];
}

function exportResultFromUnknown(payload: unknown): EditorExportResult {
  if (!isRecord(payload)) {
    return {
      status: "failed",
      diagnostics: [exportDiagnostic("EDITOR_EXPORT_INVALID_RESPONSE", "Export API returned a non-object response.")],
      artifacts: []
    };
  }

  const exportPayload = isRecord(payload.export) ? payload.export : {};
  return {
    status: payload.status === "ok" ? "ok" : "failed",
    diagnostics: diagnosticsFromUnknown(payload),
    artifacts: Array.isArray(exportPayload.artifacts)
      ? exportPayload.artifacts.flatMap(artifactFromUnknown)
      : []
  };
}

function artifactFromUnknown(value: unknown): EditorExportArtifact[] {
  if (!isRecord(value)) {
    return [];
  }
  const format = exportFormat(value.format);
  if (!format) {
    return [];
  }
  const sidecarSummary = sidecarSummaryFromUnknown(value.sidecar_summary);
  return [
    {
      format,
      page_id: typeof value.page_id === "string" ? value.page_id : null,
      asset_id: typeof value.asset_id === "string" ? value.asset_id : null,
      filename: typeof value.filename === "string" ? value.filename : fallbackArtifactFilename(value, format, sidecarSummary),
      sidecar_filename: typeof value.sidecar_filename === "string" ? value.sidecar_filename : fallbackSidecarFilename(value, sidecarSummary),
      mime_type: typeof value.mime_type === "string" ? value.mime_type : "application/octet-stream",
      byte_length: typeof value.byte_length === "number" ? value.byte_length : 0,
      dimensions: dimensionsFromUnknown(value.dimensions),
      data_url: typeof value.data_url === "string" ? value.data_url : null,
      text: typeof value.text === "string" ? value.text : null,
      sidecar_json: typeof value.sidecar_json === "string" ? value.sidecar_json : null,
      sidecar_summary: sidecarSummary
    }
  ];
}

function fallbackArtifactFilename(
  value: Record<string, unknown>,
  format: ExportProfile["format"],
  sidecarSummary: EditorExportSidecarSummary | null
): string {
  const page = fallbackNameScope(value, sidecarSummary);
  const extension = format === "figma_manifest" ? "json" : format;
  return `${page}.${extension}`;
}

function fallbackSidecarFilename(
  value: Record<string, unknown>,
  sidecarSummary: EditorExportSidecarSummary | null
): string | null {
  if (typeof value.sidecar_json !== "string") {
    return null;
  }
  const page = fallbackNameScope(value, sidecarSummary);
  return `${page}.sidecar.json`;
}

function fallbackNameScope(value: Record<string, unknown>, sidecarSummary: EditorExportSidecarSummary | null): string {
  if (typeof value.page_id === "string") {
    return safeFilenamePart(value.page_id);
  }
  if (sidecarSummary?.page_ids.length === 1) {
    return safeFilenamePart(sidecarSummary.page_ids[0]);
  }
  return "document";
}

function safeFilenamePart(value: string): string {
  return value.trim().replaceAll(/[^A-Za-z0-9._-]+/g, "_").replaceAll(/^[._-]+|[._-]+$/g, "") || "document";
}

function dimensionsFromUnknown(value: unknown): EditorExportArtifactDimensions | null {
  if (!isRecord(value)) {
    return null;
  }
  if (typeof value.width !== "number" || typeof value.height !== "number") {
    return null;
  }
  return {
    width: value.width,
    height: value.height,
    unit: typeof value.unit === "string" ? value.unit : "unknown",
    source: typeof value.source === "string" ? value.source : "unknown"
  };
}

function sidecarSummaryFromUnknown(value: unknown): EditorExportSidecarSummary | null {
  if (!isRecord(value)) {
    return null;
  }
  return {
    profile_name: typeof value.profile_name === "string" ? value.profile_name : null,
    page_count: typeof value.page_count === "number" ? value.page_count : 0,
    node_count: typeof value.node_count === "number" ? value.node_count : 0,
    slot_count: typeof value.slot_count === "number" ? value.slot_count : 0,
    page_ids: Array.isArray(value.page_ids)
      ? value.page_ids.filter((pageId): pageId is PageId => typeof pageId === "string")
      : [],
    slot_keys: Array.isArray(value.slot_keys)
      ? value.slot_keys.filter((slotKey): slotKey is string => typeof slotKey === "string")
      : []
  };
}

function diagnosticsFromUnknown(payload: Record<string, unknown>): Diagnostic[] {
  const diagnostics = payload.diagnostics;
  if (Array.isArray(diagnostics)) {
    return diagnostics.flatMap(diagnosticFromUnknown);
  }
  if (isRecord(diagnostics) && Array.isArray(diagnostics.current)) {
    return diagnostics.current.flatMap(diagnosticFromUnknown);
  }
  return [];
}

function diagnosticFromUnknown(value: unknown): Diagnostic[] {
  if (!isRecord(value)) {
    return [];
  }
  return [
    {
      severity: value.severity === "error" || value.severity === "warning" || value.severity === "advice" ? value.severity : "warning",
      phase: diagnosticPhase(value.phase),
      code: typeof value.code === "string" ? value.code : "EDITOR_EXPORT_DIAGNOSTIC",
      message: typeof value.message === "string" ? value.message : "Export returned a diagnostic without a message.",
      subject: diagnosticSubject(value.subject),
      hint: typeof value.hint === "string" ? value.hint : null
    }
  ];
}

function exportDiagnostic(code: string, message: string): Diagnostic {
  return {
    severity: "error",
    phase: "export",
    code,
    message,
    subject: null,
    hint: null
  };
}

function exportFormat(value: unknown): ExportProfile["format"] | null {
  switch (value) {
    case "svg":
    case "png":
    case "pdf":
    case "figma_manifest":
      return value;
    default:
      return null;
  }
}

function diagnosticPhase(value: unknown): Diagnostic["phase"] {
  switch (value) {
    case "contract":
    case "operation":
    case "validation":
    case "brand":
    case "dsl":
    case "layout":
    case "export":
      return value;
    default:
      return "export";
  }
}

function diagnosticSubject(value: unknown): DiagnosticSubject | null {
  if (!isRecord(value) || typeof value.kind !== "string") {
    return null;
  }
  switch (value.kind) {
    case "document":
      return { kind: "document" };
    case "page":
    case "node":
    case "slot":
    case "asset":
      return typeof value.id === "string" ? { kind: value.kind, id: value.id } : null;
    default:
      return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
