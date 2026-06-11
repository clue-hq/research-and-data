import type { Diagnostic, Scene } from "./contracts";
import { diagnosticSeverity, diagnosticSubject, isRecord } from "./brandDiagnostics";

export interface EditorPreflightRequest {
  scene: Scene;
}

export interface EditorPreflightResult {
  status: "applied" | "failed";
  diagnostics: Diagnostic[];
  scene: Scene | null;
  preflight: {
    has_errors: boolean;
    brand_ref_operations: number;
    token_operations: number;
    layout_operations: number;
  };
  brand_kit: {
    source: string | null;
    id: string | null;
    version: number | null;
    name: string | null;
  };
}

export type EditorPreflightRunner = (
  request: EditorPreflightRequest
) => EditorPreflightResult | Promise<EditorPreflightResult>;

export interface ApiPreflightRunnerOptions {
  apiBaseUrl: string;
}

export function createApiPreflightRunner({ apiBaseUrl }: ApiPreflightRunnerOptions): EditorPreflightRunner {
  return async ({ scene }) => {
    const response = await fetch(new URL("/preflight-preview", apiBaseUrl), {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({
        scene
      })
    });

    if (!response.ok) {
      throw new Error(`Preflight request failed with HTTP ${response.status}`);
    }

    return preflightResultFromUnknown(await response.json());
  };
}

export function preflightResultFromUnknown(payload: unknown): EditorPreflightResult {
  if (!isRecord(payload)) {
    return failedPreflight("EDITOR_PREFLIGHT_INVALID_RESPONSE", "Preflight API returned a non-object response.");
  }

  return {
    status: payload.status === "applied" ? "applied" : "failed",
    diagnostics: diagnosticsFromUnknown(payload),
    scene: isRecord(payload.scene) ? (payload.scene as unknown as Scene) : null,
    preflight: preflightSummaryFromUnknown(payload.preflight),
    brand_kit: brandKitSummaryFromUnknown(payload.brand_kit)
  };
}

function preflightSummaryFromUnknown(value: unknown): EditorPreflightResult["preflight"] {
  if (!isRecord(value)) {
    return {
      has_errors: true,
      brand_ref_operations: 0,
      token_operations: 0,
      layout_operations: 0
    };
  }
  return {
    has_errors: value.has_errors === true,
    brand_ref_operations: numberOrZero(value.brand_ref_operations),
    token_operations: numberOrZero(value.token_operations),
    layout_operations: numberOrZero(value.layout_operations)
  };
}

function brandKitSummaryFromUnknown(value: unknown): EditorPreflightResult["brand_kit"] {
  if (!isRecord(value)) {
    return {
      source: null,
      id: null,
      version: null,
      name: null
    };
  }
  return {
    source: typeof value.source === "string" ? value.source : null,
    id: typeof value.id === "string" ? value.id : null,
    version: typeof value.version === "number" ? value.version : null,
    name: typeof value.name === "string" ? value.name : null
  };
}

function diagnosticsFromUnknown(payload: Record<string, unknown>): Diagnostic[] {
  const diagnostics = Array.isArray(payload.diagnostics) ? payload.diagnostics : [];
  return diagnostics.flatMap(diagnosticFromUnknown);
}

function diagnosticFromUnknown(value: unknown): Diagnostic[] {
  if (!isRecord(value)) {
    return [];
  }
  return [
    {
      severity: diagnosticSeverity(value.severity),
      phase: diagnosticPhase(value.phase),
      code: typeof value.code === "string" ? value.code : "EDITOR_PREFLIGHT_DIAGNOSTIC",
      message: typeof value.message === "string" ? value.message : "Preflight returned a diagnostic without a message.",
      subject: diagnosticSubject(value.subject),
      hint: typeof value.hint === "string" ? value.hint : null
    }
  ];
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
      return "validation";
  }
}

function failedPreflight(code: string, message: string): EditorPreflightResult {
  return {
    status: "failed",
    diagnostics: [
      {
        severity: "error",
        phase: "validation",
        code,
        message,
        subject: null,
        hint: null
      }
    ],
    scene: null,
    preflight: {
      has_errors: true,
      brand_ref_operations: 0,
      token_operations: 0,
      layout_operations: 0
    },
    brand_kit: {
      source: null,
      id: null,
      version: null,
      name: null
    }
  };
}

function numberOrZero(value: unknown): number {
  return typeof value === "number" ? value : 0;
}
