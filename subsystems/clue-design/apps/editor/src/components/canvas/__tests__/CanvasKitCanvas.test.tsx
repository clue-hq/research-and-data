import { createEvent, fireEvent, render, screen } from "@testing-library/react";
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
    disabledReason,
    showResizeHandles,
    showRotateHandle,
    guides,
    insertionIndicator,
    marginGuides,
    reveal
  }: {
    hover: unknown;
    slotKeys: string[];
    diagnosticCounts: { errors: number; warnings: number };
    disabledReason: string | null;
    showResizeHandles?: boolean;
    showRotateHandle?: boolean;
    guides?: unknown[];
    insertionIndicator?: { axis: string; position: number; from: number; to: number } | null;
    marginGuides?: { safeArea: unknown; bleed: unknown } | null;
    reveal?: { drawMode: string; label: string } | null;
  }) => (
    <div
      data-testid="selection-overlay"
      data-hover={hover ? "yes" : "no"}
      data-slot-keys={slotKeys.join(",")}
      data-diagnostics={`${diagnosticCounts.errors}/${diagnosticCounts.warnings}`}
      data-disabled-reason={disabledReason ?? ""}
      data-show-resize-handles={showResizeHandles ? "yes" : "no"}
      data-show-rotate-handle={showRotateHandle ? "yes" : "no"}
      data-guides-count={(guides ?? []).length}
      data-indicator={insertionIndicator ? JSON.stringify(insertionIndicator) : ""}
      data-reveal-draw-mode={reveal?.drawMode ?? ""}
      data-reveal-label={reveal?.label ?? ""}
    >
      {marginGuides?.safeArea ? <div data-role="margin-guide-safe-area" /> : null}
      {marginGuides?.bleed ? <div data-role="margin-guide-bleed" /> : null}
    </div>
  )
}));

const scene = cloneScene();

/**
 * `fireEvent.pointerUp(el, { pointerId })` silently drops `pointerId` in this
 * suite: `PointerEvent` is stubbed to `MouseEvent` (jsdom's real
 * `PointerEvent` isn't used here), and `MouseEvent`'s constructor ignores
 * unrecognized init properties. Assigning `pointerId` on the constructed
 * event directly (own-property write, unlike the constructor init) makes it
 * observable at `event.pointerId` — needed here because
 * `CanvasKitCanvas`'s pan-drag guard compares `panDragRef.current?.pointerId
 * === event.pointerId`, and `undefined === undefined` would otherwise always
 * short-circuit a bare pointerUp before it reaches `dispatch`.
 */
function firePointerUp(element: Element, init: { clientX: number; clientY: number; pointerId: number }) {
  const event = createEvent.pointerUp(element, init) as PointerEvent & { pointerId: number };
  event.pointerId = init.pointerId;
  fireEvent(element, event);
}

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

  describe("4d: Show margins toggle", () => {
    it("renders with aria-pressed=false by default and calls the toggle callback on click", () => {
      const onToggleMarginGuides = vi.fn();
      renderCanvasKit({ selectedNodeId: null, onToggleMarginGuides });

      const button = screen.getByRole("button", { name: "Show margins" });
      expect(button).toHaveAttribute("aria-pressed", "false");

      fireEvent.click(button);
      expect(onToggleMarginGuides).toHaveBeenCalledTimes(1);
    });

    it("reflects showMarginGuides=true via aria-pressed and the active class", () => {
      renderCanvasKit({ selectedNodeId: null, showMarginGuides: true });

      const button = screen.getByRole("button", { name: "Show margins" });
      expect(button).toHaveAttribute("aria-pressed", "true");
      expect(button.className).toContain("active");
    });

    it("passes the active page's safe-area rect to the overlay when the toggle is on", () => {
      renderCanvasKit({ selectedNodeId: null, showMarginGuides: true });

      const overlay = screen.getByTestId("selection-overlay");
      expect(overlay.querySelector('[data-role="margin-guide-safe-area"]')).not.toBeNull();
      // The fixture page has no bleed rect.
      expect(overlay.querySelector('[data-role="margin-guide-bleed"]')).toBeNull();
    });

    it("passes no margin guides to the overlay when the toggle is off", () => {
      renderCanvasKit({ selectedNodeId: null, showMarginGuides: false });

      const overlay = screen.getByTestId("selection-overlay");
      expect(overlay.querySelector('[data-role="margin-guide-safe-area"]')).toBeNull();
      expect(overlay.querySelector('[data-role="margin-guide-bleed"]')).toBeNull();
    });
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

    it("does not freeze a Stack-managed press when layout-managed editing is enabled (advanced opt-out)", () => {
      vi.stubGlobal("PointerEvent", MouseEvent);
      const stackScene = stackManagedScene();
      const hitTest = vi.fn(() => ({ hit: "node_contact_name", stack: ["node_contact_name"] }));
      const engine = { hitTest } as unknown as OptimisticEnginePort;
      const onStructuredEdit = vi.fn().mockReturnValue(null);

      renderCanvasKit({
        scene: stackScene,
        selectedNodeId: null,
        engine,
        onStructuredEdit,
        layoutManagedEditing: true
      });

      fireEvent.pointerDown(screen.getByTestId("canvaskit-interaction-layer"), {
        clientX: 40,
        clientY: 40,
        pointerId: 1
      });

      expect(onStructuredEdit).not.toHaveBeenCalled();
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

  describe("4c-C managed gestures (layoutManagedEditing: drag-to-reorder + resize)", () => {
    it("does not ghost-move and commits exactly one move edit when dropped past the sibling's midpoint", () => {
      vi.stubGlobal("PointerEvent", MouseEvent);
      const twoChildStack = stackManagedTwoChildScene();
      const hitTest = vi.fn(() => ({ hit: "node_contact_name", stack: ["node_contact_name"] }));
      const engine = { hitTest } as unknown as OptimisticEnginePort;
      const onStructuredEdit = vi.fn().mockReturnValue(null);
      const onOperations = vi.fn();

      render(
        <CanvasKitCanvas
          scene={twoChildStack}
          activePageId="page_a4"
          selectedNodeId={null}
          onSelectNode={() => {}}
          onSelectPage={() => {}}
          onOperations={onOperations}
          engine={engine}
          workspaceModel={createWorkspaceModel(twoChildStack, "page_a4", [])}
          workspaceViewport={defaultWorkspaceViewport()}
          onWorkspaceViewportChange={() => {}}
          workspaceTool="select"
          onWorkspaceToolChange={() => {}}
          workspaceFitTarget="manual"
          onWorkspaceFitTargetChange={() => {}}
          onStructuredEdit={onStructuredEdit}
          layoutManagedEditing
        />
      );

      const layer = screen.getByTestId("canvaskit-interaction-layer");
      // node_contact_name spans mm y [0,50]; sibling spans mm y [50,100].
      // Descriptor px = scene mm * unitScale(mm); drag past y=75mm (sibling's
      // midpoint) to force "after sibling".
      const unitScale = 96 / 25.4;
      fireEvent.pointerDown(layer, { clientX: 10, clientY: 10 * unitScale, pointerId: 1 });
      fireEvent.pointerMove(layer, { clientX: 10, clientY: 75 * unitScale, pointerId: 1 });

      // No ghost preview: the stage tree still reports node_contact_name at
      // its solved position (unchanged descriptor coordinates), not a
      // translated preview box — verified indirectly via onOperations never
      // firing for this drag (a geometry move would call onOperations).
      expect(onOperations).not.toHaveBeenCalled();
      expect(screen.getByTestId("selection-overlay")).toHaveAttribute("data-guides-count", "0");
      const indicatorAttr = screen.getByTestId("selection-overlay").getAttribute("data-indicator");
      expect(indicatorAttr).toBeTruthy();
      expect(JSON.parse(indicatorAttr as string)).toMatchObject({ axis: "y" });

      firePointerUp(layer, { clientX: 10, clientY: 75 * unitScale, pointerId: 1 });

      expect(onStructuredEdit).toHaveBeenCalledTimes(1);
      expect(onStructuredEdit).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "move_after", node_id: "node_contact_name", anchor: "sibling" })
      );
      expect(onOperations).not.toHaveBeenCalled();
    });

    it("commits nothing when the drop resolves to the node's current position", () => {
      vi.stubGlobal("PointerEvent", MouseEvent);
      const twoChildStack = stackManagedTwoChildScene();
      const hitTest = vi.fn(() => ({ hit: "node_contact_name", stack: ["node_contact_name"] }));
      const engine = { hitTest } as unknown as OptimisticEnginePort;
      const onStructuredEdit = vi.fn().mockReturnValue(null);

      renderCanvasKit({
        scene: twoChildStack,
        selectedNodeId: null,
        engine,
        onStructuredEdit,
        layoutManagedEditing: true
      });

      const layer = screen.getByTestId("canvaskit-interaction-layer");
      const unitScale = 96 / 25.4;
      // Drag within node_contact_name's own slot (y=10mm -> y=20mm): the drop
      // index doesn't change, so nothing commits.
      fireEvent.pointerDown(layer, { clientX: 10, clientY: 10 * unitScale, pointerId: 1 });
      fireEvent.pointerMove(layer, { clientX: 10, clientY: 20 * unitScale, pointerId: 1 });
      firePointerUp(layer, { clientX: 10, clientY: 20 * unitScale, pointerId: 1 });

      expect(onStructuredEdit).not.toHaveBeenCalled();
    });

    it("cancels the reorder (no commit) on pointercancel mid-gesture", () => {
      vi.stubGlobal("PointerEvent", MouseEvent);
      const twoChildStack = stackManagedTwoChildScene();
      const hitTest = vi.fn(() => ({ hit: "node_contact_name", stack: ["node_contact_name"] }));
      const engine = { hitTest } as unknown as OptimisticEnginePort;
      const onStructuredEdit = vi.fn().mockReturnValue(null);

      renderCanvasKit({
        scene: twoChildStack,
        selectedNodeId: null,
        engine,
        onStructuredEdit,
        layoutManagedEditing: true
      });

      const layer = screen.getByTestId("canvaskit-interaction-layer");
      const unitScale = 96 / 25.4;
      fireEvent.pointerDown(layer, { clientX: 10, clientY: 10 * unitScale, pointerId: 1 });
      fireEvent.pointerMove(layer, { clientX: 10, clientY: 75 * unitScale, pointerId: 1 });
      fireEvent.pointerCancel(layer, { pointerId: 1 });
      firePointerUp(layer, { clientX: 10, clientY: 75 * unitScale, pointerId: 1 });

      expect(onStructuredEdit).not.toHaveBeenCalled();
      expect(screen.getByTestId("selection-overlay")).toHaveAttribute("data-indicator", "");
    });

    it("exposes resize handles (not rotate) for a selected managed Stack child in layout-managed-editing mode", () => {
      const twoChildStack = stackManagedTwoChildScene();

      renderCanvasKit({
        scene: twoChildStack,
        selectedNodeId: "node_contact_name",
        layoutManagedEditing: true
      });

      const overlay = screen.getByTestId("selection-overlay");
      expect(overlay).toHaveAttribute("data-show-resize-handles", "yes");
      expect(overlay).toHaveAttribute("data-show-rotate-handle", "no");
    });

    it("keeps handles off for a selected managed Stack child when layout-managed editing is off", () => {
      const twoChildStack = stackManagedTwoChildScene();

      renderCanvasKit({
        scene: twoChildStack,
        selectedNodeId: "node_contact_name"
      });

      const overlay = screen.getByTestId("selection-overlay");
      expect(overlay).toHaveAttribute("data-show-resize-handles", "no");
      expect(overlay).toHaveAttribute("data-show-rotate-handle", "no");
    });

    it("commits a size-only update through onOperations when dragging a managed node's resize handle", () => {
      vi.stubGlobal("PointerEvent", MouseEvent);
      const twoChildStack = stackManagedTwoChildScene();
      const hitTest = vi.fn(() => ({ hit: "node_contact_name", stack: ["node_contact_name"] }));
      const engine = { hitTest } as unknown as OptimisticEnginePort;
      const onOperations = vi.fn();
      const unitScale = 96 / 25.4;

      render(
        <CanvasKitCanvas
          scene={twoChildStack}
          activePageId="page_a4"
          selectedNodeId="node_contact_name"
          onSelectNode={() => {}}
          onSelectPage={() => {}}
          onOperations={onOperations}
          engine={engine}
          workspaceModel={createWorkspaceModel(twoChildStack, "page_a4", [])}
          workspaceViewport={defaultWorkspaceViewport()}
          onWorkspaceViewportChange={() => {}}
          workspaceTool="select"
          onWorkspaceToolChange={() => {}}
          workspaceFitTarget="manual"
          onWorkspaceFitTargetChange={() => {}}
          layoutManagedEditing
        />
      );

      const layer = screen.getByTestId("canvaskit-interaction-layer");
      // node_contact_name's descriptor box is [0,0]-[50,50]mm * unitScale;
      // its bottom-right resize handle sits at (50mm, 50mm) in descriptor px.
      const handlePx = 50 * unitScale;
      fireEvent.pointerDown(layer, { clientX: handlePx, clientY: handlePx, pointerId: 1 });
      fireEvent.pointerMove(layer, { clientX: handlePx + 20, clientY: handlePx + 20, pointerId: 1 });
      firePointerUp(layer, { clientX: handlePx + 20, clientY: handlePx + 20, pointerId: 1 });

      expect(onOperations).toHaveBeenCalledTimes(1);
      const [ops] = onOperations.mock.calls[0] as [Array<{ kind: string; patch?: Record<string, unknown> }>];
      expect(ops).toHaveLength(1);
      expect(ops[0]).toMatchObject({ kind: "update_node", node_id: "node_contact_name" });
      expect(ops[0].patch?.transform).toEqual({ kind: "unchanged" });
      expect((ops[0].patch?.size as { kind: string }).kind).toBe("set");
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

/** A vertical (column) Stack container with TWO children —
 * `node_contact_name` (y mm [0,50]) then `sibling` (y mm [50,100]) — for
 * exercising 4c-C drag-to-reorder / managed resize against a real second
 * sibling to anchor against. */
function stackManagedTwoChildScene(): Scene {
  const next = cloneScene();
  const template = next.nodes.node_contact_name;
  next.nodes.node_contact_name = {
    ...template,
    computed: {
      layout_bounds: { x: 0, y: 0, width: 50, height: 50 },
      render_bounds: { x: 0, y: 0, width: 50, height: 50 }
    }
  };
  next.nodes.sibling = {
    ...template,
    id: "sibling",
    name: "Sibling",
    children: [],
    computed: {
      layout_bounds: { x: 0, y: 50, width: 50, height: 50 },
      render_bounds: { x: 0, y: 50, width: 50, height: 50 }
    }
  };
  next.nodes.stack = {
    ...template,
    id: "stack",
    name: "Stack",
    kind: { kind: "auto_layout", direction: "column", wrap: false },
    layout: { gap: 0, grow: 0, padding: [0, 0, 0, 0], layout_mode: "stack" },
    children: ["node_contact_name", "sibling"],
    computed: {
      layout_bounds: { x: 0, y: 0, width: 50, height: 100 },
      render_bounds: { x: 0, y: 0, width: 50, height: 100 }
    }
  };
  next.pages.page_a4 = { ...next.pages.page_a4, children: ["stack"] };
  return next;
}

describe("(g) S2 reveal-theater viewport auto-follow", () => {
  function twoPageScene(): Scene {
    const next = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    next.pages.page_b = {
      ...(JSON.parse(JSON.stringify(next.pages.page_a4)) as Scene["pages"]["page_a4"]),
      id: "page_b",
      name: "Page B",
      children: []
    };
    return next;
  }

  const reveal = (pageId: string, seq: number) => ({
    seq,
    kind: "insert_node",
    nodeId: null,
    pageId,
    bounds: null,
    label: "designing…",
    travelMs: 200,
    drawMs: 300,
    materializeFadeMs: 250,
    reducedMotion: false
  });

  function renderFollow(agentReveal: ReturnType<typeof reveal>) {
    const twoPage = twoPageScene();
    const onWorkspaceViewportChange = vi.fn();
    const onWorkspaceFitTargetChange = vi.fn();
    const commonProps = {
      activePageId: "page_a4" as const,
      selectedNodeId: null,
      onSelectNode: () => {},
      onOperations: () => {},
      engine: null,
      diagnostics: [],
      workspaceModel: createWorkspaceModel(twoPage, "page_a4", []),
      workspaceViewport: defaultWorkspaceViewport(),
      onWorkspaceViewportChange,
      workspaceTool: "select" as const,
      onWorkspaceToolChange: () => {},
      workspaceFitTarget: "manual" as const,
      onWorkspaceFitTargetChange
    };
    const utils = render(
      <CanvasKitCanvas scene={twoPage} {...commonProps} agentReveal={agentReveal} />
    );
    // The built-in pan-clamp effect passes a FUNCTION updater; only auto-follow
    // passes a viewport OBJECT. Count the object calls to isolate the follow.
    const fitCount = () =>
      onWorkspaceViewportChange.mock.calls.filter((call) => typeof call[0] !== "function").length;
    const rerenderFollow = (nextReveal: ReturnType<typeof reveal>) =>
      utils.rerender(
        <CanvasKitCanvas scene={twoPage} {...commonProps} agentReveal={nextReveal} />
      );
    return { ...utils, fitCount, rerenderFollow };
  }

  it("fits the viewport on the first reveal and on each page change, but not within the same page", () => {
    const { fitCount, rerenderFollow } = renderFollow(reveal("page_a4", 1));
    expect(fitCount()).toBe(1); // first reveal → fit page_a4

    rerenderFollow(reveal("page_a4", 2)); // same page, next element → no re-fit
    expect(fitCount()).toBe(1);

    rerenderFollow(reveal("page_b", 3)); // page change → fit page_b
    expect(fitCount()).toBe(2);
  });

  it("is suppressed permanently for the run once the user pans (user wins)", () => {
    const { container, fitCount, rerenderFollow } = renderFollow(reveal("page_a4", 1));
    expect(fitCount()).toBe(1);

    // The user pans mid-run — auto-follow must never fire again this run.
    const layer = container.querySelector('[data-testid="canvaskit-interaction-layer"]')!;
    fireEvent.wheel(layer, { deltaY: 120 });

    rerenderFollow(reveal("page_b", 2)); // page change that would normally fit
    expect(fitCount()).toBe(1); // suppressed — user override latched
  });

  it("is suppressed permanently for the run once the user clicks a Fit button (user wins)", () => {
    const { fitCount, rerenderFollow } = renderFollow(reveal("page_a4", 1));
    expect(fitCount()).toBe(1); // first reveal → fit page_a4

    // A Fit-button click mid-run is an explicit manual viewport action (D4:
    // "user wins"); it must latch the override exactly like wheel/pan. The
    // click itself fits (count grows to 2), but the NEXT page reveal must not.
    fireEvent.click(screen.getByRole("button", { name: "Fit current artboard" }));
    expect(fitCount()).toBe(2);

    rerenderFollow(reveal("page_b", 2)); // page change that would normally fit
    expect(fitCount()).toBe(2); // suppressed — the fit click latched the override
  });
});

describe("(h) S2.1 reveal-chrome mapping", () => {
  const renderReveal = (agentReveal: {
    seq: number;
    kind: string;
    nodeId: string | null;
    pageId: string;
    bounds: null;
    label: string;
  }) =>
    render(
      <CanvasKitCanvas
        scene={minimalScene}
        activePageId="page_a4"
        selectedNodeId={null}
        onSelectNode={() => {}}
        onOperations={() => {}}
        engine={null}
        diagnostics={[]}
        workspaceModel={createWorkspaceModel(minimalScene, "page_a4", [])}
        workspaceViewport={defaultWorkspaceViewport()}
        onWorkspaceViewportChange={() => {}}
        workspaceTool="select"
        onWorkspaceToolChange={() => {}}
        workspaceFitTarget="manual"
        onWorkspaceFitTargetChange={() => {}}
        agentReveal={{
          ...agentReveal,
          travelMs: 200,
          drawMs: 300,
          materializeFadeMs: 250,
          reducedMotion: false
        }}
      />
    );

  it("maps an insert_node reveal to a corner-drag box and passes the reveal's OWN label through", () => {
    renderReveal({
      seq: 1,
      kind: "insert_node",
      nodeId: "node_contact_name",
      pageId: "page_a4",
      bounds: null,
      label: "text · Contact Name"
    });
    const overlay = screen.getByTestId("selection-overlay");
    expect(overlay).toHaveAttribute("data-reveal-draw-mode", "corner");
    // Review fix (S2.1): the label rides the reveal (derived from the APPLIED
    // scene at publish time) — the displayed scene lags the engine during the
    // draw window, so the mapping layer must NOT look the node up itself.
    expect(overlay).toHaveAttribute("data-reveal-label", "text · Contact Name");
  });

  it("maps an add_page reveal to a whole-artboard placeholder", () => {
    renderReveal({
      seq: 2,
      kind: "add_page",
      nodeId: null,
      pageId: "page_a4",
      bounds: null,
      label: "artboard · A4"
    });
    expect(screen.getByTestId("selection-overlay")).toHaveAttribute("data-reveal-draw-mode", "artboard");
  });
});

function renderCanvasKit({
  scene: canvasScene = scene,
  selectedNodeId,
  diagnostics = [],
  engine = null,
  workspaceTool = "select",
  workspaceFitTarget = "manual",
  onStructuredEdit,
  layoutManagedEditing,
  showMarginGuides,
  onToggleMarginGuides
}: {
  scene?: Scene;
  selectedNodeId: string | null;
  diagnostics?: Diagnostic[];
  engine?: OptimisticEnginePort | null;
  workspaceTool?: "select" | "hand";
  workspaceFitTarget?: "current" | "all" | "manual";
  onStructuredEdit?: (edit: StructuredEdit) => Scene | null;
  layoutManagedEditing?: boolean;
  showMarginGuides?: boolean;
  onToggleMarginGuides?: () => void;
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
      layoutManagedEditing={layoutManagedEditing}
      showMarginGuides={showMarginGuides}
      onToggleMarginGuides={onToggleMarginGuides}
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
