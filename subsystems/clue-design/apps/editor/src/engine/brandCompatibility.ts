import type {
  BrandCompatibilityReport,
  BrandCompatibilityStatus,
  BrandKitRef,
  BrandKitSummary,
  Diagnostic,
  Scene,
  TokenChange,
  TokenChangeKind
} from "./contracts";
import {
  diagnosticFromUnknown,
  diagnosticsFromUnknown,
  isRecord,
  responseStatus
} from "./brandDiagnostics";
import { lumenFetch } from "./editorConfig";

export interface BrandCompatibilityRequest {
  scene: Scene;
  currentBrandKit: BrandKitSummary | null;
  targetBrandKit: BrandKitSummary | null;
}

export interface BrandCompatibilityResult {
  report: BrandCompatibilityReport | null;
  diagnostics: Diagnostic[];
  status?: "ok" | "failed";
}

export type BrandCompatibilityRunner = (
  request: BrandCompatibilityRequest
) => BrandCompatibilityResult | Promise<BrandCompatibilityResult>;

export interface ApiBrandCompatibilityRunnerOptions {
  apiBaseUrl: string;
  fromRef?: BrandKitRef;
  toRef?: BrandKitRef;
  persistReport?: boolean;
}

export function createApiBrandCompatibilityRunner({
  apiBaseUrl,
  fromRef,
  toRef,
  persistReport = true
}: ApiBrandCompatibilityRunnerOptions): BrandCompatibilityRunner {
  return async ({ scene, currentBrandKit, targetBrandKit }) => {
    const effectiveFromRef = fromRef ?? scene.meta.brand_kit ?? summaryRef(currentBrandKit);
    const effectiveToRef = toRef ?? summaryRef(targetBrandKit);
    if (!effectiveFromRef || !effectiveToRef) {
      return {
        report: null,
        diagnostics: [
          {
            severity: "warning",
            phase: "brand",
            code: "EDITOR_BRAND_COMPATIBILITY_REFS_REQUIRED",
            message: "Brand compatibility requires both source and target Brand Kit references.",
            subject: { kind: "document" },
            hint: "Select a stored Brand Kit version before checking compatibility."
          }
        ]
      };
    }

    const url = new URL("/brand-kits/compatibility", apiBaseUrl);
    const response = await lumenFetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({
        from_ref: {
          brand_kit_id: effectiveFromRef.id,
          version: effectiveFromRef.version
        },
        to_ref: {
          brand_kit_id: effectiveToRef.id,
          version: effectiveToRef.version
        },
        persist_report: persistReport
      })
    });

    if (!response.ok) {
      throw new Error(`Brand compatibility request failed with HTTP ${response.status}`);
    }

    const payload: unknown = await response.json();
    return {
      report: compatibilityReportFromUnknown(payload),
      diagnostics: diagnosticsFromUnknown(payload, "BRAND_COMPATIBILITY"),
      status: responseStatus(payload)
    };
  };
}

function summaryRef(summary: BrandKitSummary | null): BrandKitRef | null {
  return summary
    ? {
        id: summary.id,
        version: summary.version
      }
    : null;
}

function compatibilityReportFromUnknown(payload: unknown): BrandCompatibilityReport | null {
  if (!isRecord(payload) || !isRecord(payload.report)) {
    return null;
  }

  const report = payload.report;
  const from = brandKitRefFromUnknown(report.from);
  const to = brandKitRefFromUnknown(report.to);
  if (!from || !to) {
    return null;
  }

  return {
    from,
    to,
    status: compatibilityStatus(report.status),
    diagnostics: Array.isArray(report.diagnostics)
      ? report.diagnostics.flatMap((diagnostic) => diagnosticFromUnknown(diagnostic, "BRAND_COMPATIBILITY"))
      : [],
    token_changes: Array.isArray(report.token_changes)
      ? report.token_changes.flatMap(tokenChangeFromUnknown)
      : []
  };
}

function brandKitRefFromUnknown(value: unknown): BrandKitRef | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.version !== "number") {
    return null;
  }
  return {
    id: value.id,
    version: value.version
  };
}

function tokenChangeFromUnknown(value: unknown): TokenChange[] {
  if (!isRecord(value) || typeof value.path !== "string") {
    return [];
  }
  return [
    {
      path: value.path,
      kind: tokenChangeKind(value.kind),
      from_kind: typeof value.from_kind === "string" ? value.from_kind : null,
      to_kind: typeof value.to_kind === "string" ? value.to_kind : null
    }
  ];
}

function compatibilityStatus(value: unknown): BrandCompatibilityStatus {
  switch (value) {
    case "compatible":
    case "warning":
    case "migration_required":
    case "incompatible":
      return value;
    default:
      return "warning";
  }
}

function tokenChangeKind(value: unknown): TokenChangeKind {
  switch (value) {
    case "added":
    case "removed":
    case "type_changed":
    case "role_changed":
    case "mode_coverage_changed":
    case "asset_removed":
    case "font_license_changed":
      return value;
    default:
      return "removed";
  }
}
