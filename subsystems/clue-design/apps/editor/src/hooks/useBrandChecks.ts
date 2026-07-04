import { useMemo, useState, type Dispatch, type SetStateAction } from "react";
import type { BrandCompatibilityRunner } from "@/engine/brandCompatibility";
import type { BrandGovernanceRunner } from "@/engine/brandGovernance";
import type {
  BrandCompatibilityReport,
  BrandKitRef,
  BrandKitSummary,
  Diagnostic,
  Scene
} from "@/engine/contracts";

/**
 * The Brand Kit checking leg of the editor shell: which stored kit is
 * effective for the scene, whether a newer version exists to compare
 * against, and the governance/compatibility check flows (server-side
 * runners injected by the shell; both optional — the flows surface honest
 * "port not wired" advice when absent).
 *
 * The deps object is rebuilt every render (same closure semantics as the
 * inline originals) — never memoize it.
 */
export interface UseBrandChecksDeps {
  scene: Scene;
  availableBrandKits: BrandKitSummary[];
  brandGovernanceRunner?: BrandGovernanceRunner;
  brandCompatibilityRunner?: BrandCompatibilityRunner;
  setDiagnostics: Dispatch<SetStateAction<Diagnostic[]>>;
}

export function useBrandChecks(deps: UseBrandChecksDeps) {
  const {
    scene,
    availableBrandKits,
    brandGovernanceRunner,
    brandCompatibilityRunner,
    setDiagnostics
  } = deps;

  const [isBrandGovernanceRunning, setIsBrandGovernanceRunning] = useState(false);
  const [isBrandCompatibilityRunning, setIsBrandCompatibilityRunning] = useState(false);
  const [brandCompatibilityReport, setBrandCompatibilityReport] =
    useState<BrandCompatibilityReport | null>(null);

  const effectiveBrandKit = useMemo(
    () =>
      scene.meta.brand_kit
        ? availableBrandKits.find(
            (brandKit) =>
              brandKit.id === scene.meta.brand_kit?.id &&
              brandKit.version === scene.meta.brand_kit?.version
          )
        : null,
    [availableBrandKits, scene.meta.brand_kit]
  );
  const compatibilityTarget = useMemo(
    () => latestBrandKitVersion(availableBrandKits, scene.meta.brand_kit),
    [availableBrandKits, scene.meta.brand_kit]
  );

  const runBrandGovernance = async () => {
    if (!scene.meta.brand_kit) {
      setDiagnostics([
        {
          severity: "warning",
          phase: "brand",
          code: "EDITOR_BRAND_KIT_REQUIRED",
          message: "No Brand Kit is attached to this document.",
          subject: { kind: "document" },
          hint: "Attach a stored Brand Kit before running strict brand governance."
        }
      ]);
      return;
    }

    if (!brandGovernanceRunner) {
      setDiagnostics([
        {
          severity: "advice",
          phase: "brand",
          code: "EDITOR_BRAND_GOVERNANCE_PORT",
          message: "Brand governance UI is wired; provide a BrandGovernanceRunner to call the API/core validator.",
          subject: { kind: "document" },
          hint: "Use createApiBrandGovernanceRunner against POST /documents/{id}/brand-governance."
        }
      ]);
      return;
    }

    setIsBrandGovernanceRunning(true);
    setDiagnostics([
      {
        severity: "advice",
        phase: "brand",
        code: "EDITOR_BRAND_GOVERNANCE_RUNNING",
        message: "Running Brand Kit governance checks.",
        subject: { kind: "document" },
        hint: null
      }
    ]);

    try {
      const result = await brandGovernanceRunner({
        scene,
        brandKit: effectiveBrandKit ?? null
      });
      setDiagnostics(
        result.diagnostics.length > 0
          ? result.diagnostics
          : [
              {
                severity: "advice",
                phase: "brand",
                code: "EDITOR_BRAND_GOVERNANCE_OK",
                message: "Brand Kit governance passed with no diagnostics.",
                subject: { kind: "document" },
                hint: null
              }
            ]
      );
    } catch (error) {
      setDiagnostics([
        {
          severity: "error",
          phase: "brand",
          code: "EDITOR_BRAND_GOVERNANCE_FAILED",
          message: error instanceof Error ? error.message : "Brand governance request failed.",
          subject: { kind: "document" },
          hint: "Check the editor API connection and retry the Brand Kit check."
        }
      ]);
    } finally {
      setIsBrandGovernanceRunning(false);
    }
  };

  const runBrandCompatibility = async () => {
    if (!scene.meta.brand_kit) {
      setDiagnostics([
        {
          severity: "warning",
          phase: "brand",
          code: "EDITOR_BRAND_KIT_REQUIRED",
          message: "No Brand Kit is attached to this document.",
          subject: { kind: "document" },
          hint: "Attach a stored Brand Kit before checking compatibility."
        }
      ]);
      return;
    }

    if (!compatibilityTarget) {
      setBrandCompatibilityReport(null);
      setDiagnostics([
        {
          severity: "advice",
          phase: "brand",
          code: "EDITOR_BRAND_COMPATIBILITY_CURRENT",
          message: "No newer stored Brand Kit version is available for this document.",
          subject: { kind: "document" },
          hint: "Compatibility warnings appear when a later version of the same Brand Kit is available."
        }
      ]);
      return;
    }

    if (!brandCompatibilityRunner) {
      setDiagnostics([
        {
          severity: "advice",
          phase: "brand",
          code: "EDITOR_BRAND_COMPATIBILITY_PORT",
          message: "Brand compatibility UI is wired; provide a BrandCompatibilityRunner to call the API/core report.",
          subject: { kind: "document" },
          hint: "Use createApiBrandCompatibilityRunner against POST /brand-kits/compatibility."
        }
      ]);
      return;
    }

    setIsBrandCompatibilityRunning(true);
    setDiagnostics([
      {
        severity: "advice",
        phase: "brand",
        code: "EDITOR_BRAND_COMPATIBILITY_RUNNING",
        message: "Checking Brand Kit version compatibility.",
        subject: { kind: "document" },
        hint: null
      }
    ]);

    try {
      const result = await brandCompatibilityRunner({
        scene,
        currentBrandKit: effectiveBrandKit ?? null,
        targetBrandKit: compatibilityTarget
      });
      setBrandCompatibilityReport(result.report);
      const reportDiagnostics = result.diagnostics.length > 0 ? result.diagnostics : result.report?.diagnostics ?? [];
      setDiagnostics(
        reportDiagnostics.length > 0
          ? reportDiagnostics
          : [
              {
                severity: "advice",
                phase: "brand",
                code: "EDITOR_BRAND_COMPATIBILITY_OK",
                message:
                  result.report && result.report.token_changes.length > 0
                    ? "Brand Kit compatibility report completed with token changes to review."
                    : "Brand Kit compatibility report passed with no token changes.",
                subject: { kind: "document" },
                hint: null
              }
            ]
      );
    } catch (error) {
      setBrandCompatibilityReport(null);
      setDiagnostics([
        {
          severity: "error",
          phase: "brand",
          code: "EDITOR_BRAND_COMPATIBILITY_FAILED",
          message: error instanceof Error ? error.message : "Brand compatibility request failed.",
          subject: { kind: "document" },
          hint: "Check the editor API connection and retry the compatibility check."
        }
      ]);
    } finally {
      setIsBrandCompatibilityRunning(false);
    }
  };

  return {
    isBrandGovernanceRunning,
    isBrandCompatibilityRunning,
    brandCompatibilityReport,
    setBrandCompatibilityReport,
    effectiveBrandKit,
    compatibilityTarget,
    runBrandGovernance,
    runBrandCompatibility
  };
}

function latestBrandKitVersion(
  brandKits: BrandKitSummary[],
  currentRef: BrandKitRef | null
): BrandKitSummary | null {
  if (!currentRef) {
    return null;
  }

  return (
    brandKits
      .filter((brandKit) => brandKit.id === currentRef.id && brandKit.version > currentRef.version)
      .sort((left, right) => right.version - left.version)[0] ?? null
  );
}
