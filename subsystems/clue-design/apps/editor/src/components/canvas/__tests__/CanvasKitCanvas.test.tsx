import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Diagnostic, Scene } from "@/engine/contracts";
import type { OptimisticEnginePort } from "@/engine/wasmEngine";
import { createWorkspaceModel } from "@/engine/workspaceLayout";
import { defaultWorkspaceViewport } from "@/engine/workspaceViewport";
import { CanvasKitCanvas } from "../CanvasKitCanvas";

vi.mock("../CanvasKitStage", () => ({
  CanvasKitStage: () => <div data-testid="canvaskit-stage" />
}));

vi.mock("../TextEditOverlay", () => ({
  TextEditOverlay: () => <textarea data-testid="text-edit-overlay" />
}));

vi.mock("../SelectionOverlay", () => ({
  SelectionOverlay: ({
    hover,
    slotKeys,
    diagnosticCounts,
    disabledReason
  }: {
    hover: unknown;
    slotKeys: string[];
    diagnosticCounts: { errors: number; warnings: number };
    disabledReason: string | null;
  }) => (
    <div
      data-testid="selection-overlay"
      data-hover={hover ? "yes" : "no"}
      data-slot-keys={slotKeys.join(",")}
      data-diagnostics={`${diagnosticCounts.errors}/${diagnosticCounts.warnings}`}
      data-disabled-reason={disabledReason ?? ""}
    />
  )
}));

const scene = cloneScene();

describe("CanvasKitCanvas polish chrome wiring", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("passes hover hit-test results into the DOM/SVG overlay", () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    const hitTest = vi.fn((pageId: string, x: number, y: number) => ({
      hit: pageId && Number.isFinite(x) && Number.isFinite(y) ? "node_contact_name" : null,
      stack: ["node_contact_name"]
    }));
    const engine = { hitTest } as unknown as OptimisticEnginePort;

    renderCanvasKit({ engine, selectedNodeId: null });
    const overlayHost = screen.getByTestId("canvaskit-interaction-layer");

    fireEvent.pointerMove(overlayHost, { clientX: 40, clientY: 40, pointerId: 1 });

    expect(hitTest).toHaveBeenCalledOnce();
    const [pageId, x, y] = hitTest.mock.calls[0];
    expect(pageId).toBe("page_a4");
    expect(x).toBeCloseTo(10.583333333333332);
    expect(y).toBeCloseTo(10.583333333333332);
    expect(screen.getByTestId("selection-overlay")).toHaveAttribute("data-hover", "yes");
  });

  it("passes slot keys, diagnostic counts, and disabled reasons into the overlay", () => {
    const lockedScene = cloneScene();
    lockedScene.nodes.node_contact_name.locked = true;
    const diagnostics: Diagnostic[] = [
      diagnostic("error", { kind: "node", id: "node_contact_name" }),
      diagnostic("warning", { kind: "slot", id: "slot_contact_name" })
    ];

    renderCanvasKit({
      scene: lockedScene,
      selectedNodeId: "node_contact_name",
      diagnostics
    });

    const overlay = screen.getByTestId("selection-overlay");
    expect(overlay).toHaveAttribute("data-slot-keys", "contact.full_name");
    expect(overlay).toHaveAttribute("data-diagnostics", "1/1");
    expect(overlay).toHaveAttribute("data-disabled-reason", expect.stringMatching(/locked/i));
  });
});

function renderCanvasKit({
  scene: canvasScene = scene,
  selectedNodeId,
  diagnostics = [],
  engine = null
}: {
  scene?: Scene;
  selectedNodeId: string | null;
  diagnostics?: Diagnostic[];
  engine?: OptimisticEnginePort | null;
}) {
  return render(
    <CanvasKitCanvas
      scene={canvasScene}
      activePageId="page_a4"
      selectedNodeId={selectedNodeId}
      onSelectNode={() => {}}
      onSelectPage={() => {}}
      onOperation={() => {}}
      engine={engine}
      diagnostics={diagnostics}
      workspaceModel={createWorkspaceModel(canvasScene, "page_a4", diagnostics)}
      workspaceViewport={defaultWorkspaceViewport()}
      onWorkspaceViewportChange={() => {}}
      workspaceTool="select"
      onWorkspaceToolChange={() => {}}
      workspaceFitTarget="manual"
      onWorkspaceFitTargetChange={() => {}}
    />
  );
}

function cloneScene(): Scene {
  const next = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  next.nodes.node_contact_name.computed = {
    layout_bounds: { x: 24, y: 32, width: 180, height: 30 },
    render_bounds: { x: 24, y: 32, width: 180, height: 30 }
  };
  return next;
}

function diagnostic(severity: Diagnostic["severity"], subject: Diagnostic["subject"]): Diagnostic {
  return {
    severity,
    phase: "validation",
    code: `TEST_${severity}`,
    message: `${severity} diagnostic`,
    subject,
    hint: null
  };
}
