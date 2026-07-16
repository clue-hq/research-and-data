import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { EditorExportResult } from "@/engine/exportRunner";
import type { EditorPreflightResult } from "@/engine/preflightRunner";
import { useExportPreflight, type UseExportPreflightDeps } from "../useExportPreflight";

/**
 * Pins the per-call result contract of runExportForScene: callers that act
 * on an export's outcome (the topbar download flow) get THIS call's result
 * or null — never a signal that survives into someone else's export. The
 * old ambient downloadAfterExportRef leaked exactly that way: an aborted
 * topbar export left the flag armed and the next panel preview silently
 * downloaded its artifacts.
 */

function appliedPreflight(): EditorPreflightResult {
  return {
    status: "applied",
    diagnostics: [],
    scene: minimalScene,
    preflight: {
      has_errors: false,
      brand_ref_operations: 0,
      token_operations: 0,
      layout_operations: 0
    },
    brand_kit: { source: null, id: null, version: null, name: null }
  };
}

function okExport(): EditorExportResult {
  return {
    status: "ok",
    diagnostics: [],
    artifacts: [
      {
        format: "png",
        page_id: "page_a4",
        asset_id: null,
        filename: "page_a4.png",
        sidecar_filename: null,
        mime_type: "image/png",
        byte_length: 8,
        dimensions: null,
        data_url: "data:image/png;base64,AAAA",
        text: null,
        sidecar_json: null,
        sidecar_summary: null
      }
    ],
    printReady: null
  };
}

function makeDeps(overrides: Partial<UseExportPreflightDeps> = {}): UseExportPreflightDeps {
  return {
    exportRunner: vi.fn().mockResolvedValue(okExport()),
    preflightRunner: vi.fn().mockResolvedValue(appliedPreflight()),
    scene: minimalScene,
    activePageId: "page_a4",
    getActiveDocumentId: () => null,
    replaceScene: vi.fn(),
    setDiagnostics: vi.fn(),
    setEditorPanelMode: vi.fn(),
    setWorkspaceMode: vi.fn(),
    ...overrides
  };
}

describe("useExportPreflight runExportForScene result contract", () => {
  it("resolves with the export result on success", async () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useExportPreflight(deps));

    let exported: EditorExportResult | null = null;
    await act(async () => {
      exported = await result.current.runExportForScene(minimalScene, undefined, ["page_a4"]);
    });
    expect(exported).not.toBeNull();
    expect(exported!.status).toBe("ok");
    expect(exported!.artifacts).toHaveLength(1);
  });

  it("resolves with the failed result so callers can decline to download", async () => {
    const deps = makeDeps({
      exportRunner: vi.fn().mockResolvedValue({
        status: "failed",
        diagnostics: [],
        artifacts: [],
        printReady: null
      } satisfies EditorExportResult)
    });
    const { result } = renderHook(() => useExportPreflight(deps));

    let exported: EditorExportResult | null = null;
    await act(async () => {
      exported = await result.current.runExportForScene(minimalScene, undefined, ["page_a4"]);
    });
    expect(exported).not.toBeNull();
    expect(exported!.status).toBe("failed");
  });

  it("resolves null and never calls the runner when no pages are in scope", async () => {
    const exportRunner = vi.fn();
    const deps = makeDeps({ exportRunner, activePageId: null });
    const { result } = renderHook(() => useExportPreflight(deps));

    let exported: EditorExportResult | null = okExport();
    await act(async () => {
      exported = await result.current.runExportForScene(minimalScene, undefined, []);
    });
    expect(exported).toBeNull();
    expect(exportRunner).not.toHaveBeenCalled();
  });

  it("resolves null when the export request throws", async () => {
    const deps = makeDeps({
      exportRunner: vi.fn().mockRejectedValue(new Error("connection refused"))
    });
    const { result } = renderHook(() => useExportPreflight(deps));

    let exported: EditorExportResult | null = okExport();
    await act(async () => {
      exported = await result.current.runExportForScene(minimalScene, undefined, ["page_a4"]);
    });
    expect(exported).toBeNull();
  });
});
