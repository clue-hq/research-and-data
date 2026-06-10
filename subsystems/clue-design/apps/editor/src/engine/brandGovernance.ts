import type { BrandKitSummary, Diagnostic, Scene } from "./contracts";
import { diagnosticsFromUnknown, responseStatus } from "./brandDiagnostics";

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
      diagnostics: diagnosticsFromUnknown(payload, "BRAND_GOVERNANCE"),
      status: responseStatus(payload)
    };
  };
}
