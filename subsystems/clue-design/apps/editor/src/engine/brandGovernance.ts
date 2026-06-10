import type { BrandKitSummary, Diagnostic, Scene } from "./contracts";

export interface BrandGovernanceRequest {
  scene: Scene;
  brandKit: BrandKitSummary | null;
}

export interface BrandGovernanceResult {
  diagnostics: Diagnostic[];
  status?: "ok" | "failed";
}

export type BrandGovernanceRunner = (
  request: BrandGovernanceRequest
) => BrandGovernanceResult | Promise<BrandGovernanceResult>;

export interface ApiBrandGovernanceRunnerOptions {
  apiBaseUrl: string;
  documentId?: string;
  strictness?: "advisory" | "strict" | "finalize";
}

export function createApiBrandGovernanceRunner({
  apiBaseUrl,
  documentId,
  strictness = "strict"
}: ApiBrandGovernanceRunnerOptions): BrandGovernanceRunner {
  return async ({ scene }) => {
    const url = new URL(
      `/documents/${encodeURIComponent(documentId ?? scene.meta.id)}/brand-governance`,
      apiBaseUrl
    );
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({
        brand_kit_id: scene.meta.brand_kit?.id,
        version: scene.meta.brand_kit?.version,
        strictness
      })
    });

    if (!response.ok) {
      throw new Error(`Brand governance request failed with HTTP ${response.status}`);
    }

    const payload: unknown = await response.json();
    return {
      diagnostics: normalizeDiagnostics(payload),
      status: responseStatus(payload)
    };
  };
}

function normalizeDiagnostics(payload: unknown): Diagnostic[] {
  if (!isRecord(payload) || !Array.isArray(payload.diagnostics)) {
    return [];
  }

  return payload.diagnostics.flatMap((diagnostic) => {
    if (!isRecord(diagnostic)) {
      return [];
    }
    const code = typeof diagnostic.code === "string" ? diagnostic.code : "BRAND_GOVERNANCE";
    const message =
      typeof diagnostic.message === "string"
        ? diagnostic.message
        : "Brand governance returned a diagnostic without a message.";

    return [
      {
        severity: diagnosticSeverity(diagnostic.severity),
        phase: "brand",
        code,
        message,
        subject: diagnosticSubject(diagnostic.subject),
        hint: typeof diagnostic.hint === "string" ? diagnostic.hint : null
      }
    ];
  });
}

function responseStatus(payload: unknown): "ok" | "failed" | undefined {
  if (!isRecord(payload) || typeof payload.status !== "string") {
    return undefined;
  }
  return payload.status === "failed" ? "failed" : "ok";
}

function diagnosticSeverity(value: unknown): Diagnostic["severity"] {
  return value === "error" || value === "warning" || value === "advice" ? value : "warning";
}

function diagnosticSubject(value: unknown): Diagnostic["subject"] {
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
