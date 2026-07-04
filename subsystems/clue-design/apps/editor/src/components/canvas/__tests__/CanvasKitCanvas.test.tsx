import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Diagnostic, Node, Scene } from "@/engine/contracts";
import type { StructuredEdit } from "@/engine/structuredEdits";
import type { OptimisticEnginePort } from "@/engine/wasmEngine";
import { createWorkspaceModel } from "@/engine/workspaceLayout";
import { defaultWorkspaceViewport } from "@/engine/workspaceViewport";
import { CanvasKitCanvas } from "../CanvasKitCanvas";

vi.mock("../CanvasKitStage", () => ({
  CanvasKitStage: ({ artboards }: { artboards: Array<{ nodes: DrawNodeForTest[] }> }) => (
    <div data-testid="canvaskit-stage" data-tree={JSON.stringify(artboards.map((artboard) => artboard.nodes.map(nodeSummary)))} />
  )
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

  it("exposes pressed state for workspace tool and fit controls", () => {
    renderCanvasKit({
      selectedNodeId: null,
      workspaceTool: "hand",
      workspaceFitTarget: "current"
    });

    expect(screen.getByRole("button", { name: "Select tool" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Pan tool" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Fit current artboard" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Fit all artboards" })).toHaveAttribute("aria-pressed", "false");
  });

  it("emits one structured [lumen-hit] line per pointer-down when ?debug=hit is set", () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    window.history.replaceState(null, "", "?debug=hit");
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    try {
      const hitTest = vi.fn(() => ({ hit: "node_contact_name", stack: ["node_contact_name"] }));
      const engine = { hitTest } as unknown as OptimisticEnginePort;
      renderCanvasKit({ engine, selectedNodeId: null });

      fireEvent.pointerDown(screen.getByTestId("canvaskit-interaction-layer"), {
        clientX: 40,
        clientY: 40,
        pointerId: 1
      });

      const traceCall = log.mock.calls.find((call) => call[0] === "[lumen-hit]");
      expect(traceCall).toBeDefined();
      const payload = JSON.parse(String(traceCall?.[1])) as Record<string, unknown>;
      expect(payload).toMatchObject({
        event: "down",
        engine: true,
        tool: "select",
        page: "page_a4",
        hit: "node_contact_name",
        target: "node",
        node: "node_contact_name"
      });
      expect(payload.scene).toHaveLength(2);
    } finally {
      log.mockRestore();
      window.history.replaceState(null, "", window.location.pathname);
    }
  });

  it("emits no [lumen-hit] trace without the debug flag", () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    try {
      const hitTest = vi.fn(() => ({ hit: "node_contact_name", stack: ["node_contact_name"] }));
      const engine = { hitTest } as unknown as OptimisticEnginePort;
      renderCanvasKit({ engine, selectedNodeId: null });

      fireEvent.pointerDown(screen.getByTestId("canvaskit-interaction-layer"), {
        clientX: 40,
        clientY: 40,
        pointerId: 1
      });

      expect(log.mock.calls.find((call) => call[0] === "[lumen-hit]")).toBeUndefined();
    } finally {
      log.mockRestore();
    }
  });

  it("passes nested CanvasKit draw descriptors in parent-local coordinates", () => {
    const nestedScene = cloneScene();
    const parent: Node = {
      ...nestedScene.nodes.node_contact_name,
      id: "parent_frame",
      name: "Parent frame",
      kind: { kind: "frame" },
      fills: [],
      strokes: [],
      children: ["child_text"],
      computed: {
        layout_bounds: { x: 100, y: 60, width: 320, height: 200 },
        render_bounds: { x: 100, y: 60, width: 320, height: 200 }
      }
    };
    const child: Node = {
      ...nestedScene.nodes.node_contact_name,
      id: "child_text",
      name: "Child text",
      children: [],
      computed: {
        layout_bounds: { x: 124, y: 84, width: 180, height: 30 },
        render_bounds: { x: 124, y: 84, width: 180, height: 30 }
      }
    };
    nestedScene.nodes = { parent_frame: parent, child_text: child };
    nestedScene.pages.page_a4 = { ...nestedScene.pages.page_a4, children: ["parent_frame"] };

    renderCanvasKit({ scene: nestedScene, selectedNodeId: null });

    const tree = JSON.parse(screen.getByTestId("canvaskit-stage").dataset.tree ?? "[]") as NodeSummaryForTest[][];
    const parentSummary = tree[0]?.[0];
    const childSummary = parentSummary?.children[0];
    const scale = 96 / 25.4;
    expect(parentSummary).toMatchObject({ id: "parent_frame" });
    expect(parentSummary.x).toBeCloseTo(100 * scale);
    expect(parentSummary.y).toBeCloseTo(60 * scale);
    expect(childSummary).toMatchObject({ id: "child_text" });
    expect(childSummary.x).toBeCloseTo(24 * scale);
    expect(childSummary.y).toBeCloseTo(24 * scale);
  });

  describe("handoff-absolute lazy seam: freeze on gesture", () => {
    it("freezes silently on pointer-down when the press hits a Stack-managed child, before the gesture starts", () => {
      vi.stubGlobal("PointerEvent", MouseEvent);
      const stackScene = stackManagedScene();
      const hitTest = vi.fn(() => ({ hit: "node_contact_name", stack: ["node_contact_name"] }));
      const engine = { hitTest } as unknown as OptimisticEnginePort;
      const onStructuredEdit = vi.fn().mockReturnValue(null);

      renderCanvasKit({ scene: stackScene, selectedNodeId: null, engine, onStructuredEdit });

      fireEvent.pointerDown(screen.getByTestId("canvaskit-interaction-layer"), {
        clientX: 40,
        clientY: 40,
        pointerId: 1
      });

      expect(onStructuredEdit).toHaveBeenCalledTimes(1);
      expect(onStructuredEdit).toHaveBeenCalledWith(expect.objectContaining({ kind: "freeze_layout" }));
    });

    it("does not freeze when the pressed node is already directly geometry-editable", () => {
      vi.stubGlobal("PointerEvent", MouseEvent);
      const hitTest = vi.fn(() => ({ hit: "node_contact_name", stack: ["node_contact_name"] }));
      const engine = { hitTest } as unknown as OptimisticEnginePort;
      const onStructuredEdit = vi.fn().mockReturnValue(null);

      // Default fixture scene: node_contact_name is a top-level page child,
      // not Stack-managed — already free.
      renderCanvasKit({ selectedNodeId: null, engine, onStructuredEdit });

      fireEvent.pointerDown(screen.getByTestId("canvaskit-interaction-layer"), {
        clientX: 40,
        clientY: 40,
        pointerId: 1
      });

      expect(onStructuredEdit).not.toHaveBeenCalled();
    });

    it("does not freeze a locked node under a Stack parent (freeze cannot fix locking)", () => {
      vi.stubGlobal("PointerEvent", MouseEvent);
      const stackScene = stackManagedScene();
      stackScene.nodes.node_contact_name.locked = true;
      const hitTest = vi.fn(() => ({ hit: "node_contact_name", stack: ["node_contact_name"] }));
      const engine = { hitTest } as unknown as OptimisticEnginePort;
      const onStructuredEdit = vi.fn().mockReturnValue(null);

      renderCanvasKit({ scene: stackScene, selectedNodeId: null, engine, onStructuredEdit });

      fireEvent.pointerDown(screen.getByTestId("canvaskit-interaction-layer"), {
        clientX: 40,
        clientY: 40,
        pointerId: 1
      });

      expect(onStructuredEdit).not.toHaveBeenCalled();
    });

    it("does not freeze on an empty-space press (no node hit)", () => {
      vi.stubGlobal("PointerEvent", MouseEvent);
      const stackScene = stackManagedScene();
      const hitTest = vi.fn(() => ({ hit: null, stack: [] }));
      const engine = { hitTest } as unknown as OptimisticEnginePort;
      const onStructuredEdit = vi.fn().mockReturnValue(null);

      renderCanvasKit({ scene: stackScene, selectedNodeId: null, engine, onStructuredEdit });

      fireEvent.pointerDown(screen.getByTestId("canvaskit-interaction-layer"), {
        clientX: 40,
        clientY: 40,
        pointerId: 1
      });

      expect(onStructuredEdit).not.toHaveBeenCalled();
    });
  });
});

/** A scene where `node_contact_name` is the sole child of a Stack
 * auto-layout container — solver-managed, blocked only by layout ownership
 * (the handoff-absolute lazy seam's freeze target). */
function stackManagedScene(): Scene {
  const next = cloneScene();
  next.nodes.stack = {
    ...next.nodes.node_contact_name,
    id: "stack",
    name: "Stack",
    kind: { kind: "auto_layout", direction: "column", wrap: false },
    children: ["node_contact_name"],
    computed: {
      layout_bounds: { x: 24, y: 32, width: 180, height: 30 },
      render_bounds: { x: 24, y: 32, width: 180, height: 30 }
    }
  };
  next.pages.page_a4 = { ...next.pages.page_a4, children: ["stack"] };
  return next;
}

function renderCanvasKit({
  scene: canvasScene = scene,
  selectedNodeId,
  diagnostics = [],
  engine = null,
  workspaceTool = "select",
  workspaceFitTarget = "manual",
  onStructuredEdit
}: {
  scene?: Scene;
  selectedNodeId: string | null;
  diagnostics?: Diagnostic[];
  engine?: OptimisticEnginePort | null;
  workspaceTool?: "select" | "hand";
  workspaceFitTarget?: "current" | "all" | "manual";
  onStructuredEdit?: (edit: StructuredEdit) => Scene | null;
}) {
  return render(
    <CanvasKitCanvas
      scene={canvasScene}
      activePageId="page_a4"
      selectedNodeId={selectedNodeId}
      onSelectNode={() => {}}
      onSelectPage={() => {}}
      onOperations={() => {}}
      engine={engine}
      diagnostics={diagnostics}
      workspaceModel={createWorkspaceModel(canvasScene, "page_a4", diagnostics)}
      workspaceViewport={defaultWorkspaceViewport()}
      onWorkspaceViewportChange={() => {}}
      workspaceTool={workspaceTool}
      onWorkspaceToolChange={() => {}}
      workspaceFitTarget={workspaceFitTarget}
      onWorkspaceFitTargetChange={() => {}}
      onStructuredEdit={onStructuredEdit}
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

interface DrawNodeForTest {
  descriptor: {
    id: string;
    x: number;
    y: number;
  };
  children: DrawNodeForTest[];
}

interface NodeSummaryForTest {
  id: string;
  x: number;
  y: number;
  children: NodeSummaryForTest[];
}

function nodeSummary(node: DrawNodeForTest): NodeSummaryForTest {
  return {
    id: node.descriptor.id,
    x: node.descriptor.x,
    y: node.descriptor.y,
    children: node.children.map(nodeSummary)
  };
}
