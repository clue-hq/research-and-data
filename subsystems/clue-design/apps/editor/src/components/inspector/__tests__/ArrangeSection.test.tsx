import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Node, Scene } from "@/engine/contracts";
import { ArrangeSection } from "../ArrangeSection";

/** page -> three unlocked, unmanaged page-level siblings a, b, c (z-order
 * a, b, c) — mirrors engine/__tests__/sceneQueries.test.ts's siblingScene,
 * the minimal fixture for arrange (z-order + group) coverage. */
function siblingScene(): Scene {
  const template: Node = {
    id: "template",
    name: "Template",
    kind: { kind: "rect" },
    transform: { x: 0, y: 0, rotation: 0 },
    size: { width: { kind: "fixed", value: 10 }, height: { kind: "fixed", value: 10 } },
    opacity: 1,
    locked: false,
    children: []
  } as unknown as Node;
  const a: Node = { ...template, id: "a", name: "A" };
  const b: Node = { ...template, id: "b", name: "B" };
  const c: Node = { ...template, id: "c", name: "C" };
  return {
    document: { id: "doc", title: "Doc", artifact_type: "linkedin_ad" },
    pages: {
      page_a4: {
        id: "page_a4",
        name: "A4 Letter",
        size: { width: 210, height: 297, unit: "mm" },
        children: ["a", "b", "c"]
      }
    },
    nodes: { a, b, c },
    slots: {},
    assets: {}
  } as unknown as Scene;
}

/** page -> three unlocked, pinned (position_mode "absolute") page-level
 * siblings with distinct page-space boxes — the fixture for align/
 * distribute coverage, since those need a resolvable page-space box per
 * node (`siblingScene`'s plain template has none). */
function pinnedSiblingScene(): Scene {
  const template: Node = {
    id: "template",
    name: "Template",
    kind: { kind: "rect" },
    transform: { x: 0, y: 0, rotation: 0 },
    size: { width: { kind: "fixed", value: 10 }, height: { kind: "fixed", value: 10 } },
    opacity: 1,
    locked: false,
    position_mode: "absolute",
    children: []
  } as unknown as Node;
  const a: Node = { ...template, id: "a", name: "A", absolute_box: { x: 0, y: 0, width: 10, height: 10 } };
  const b: Node = { ...template, id: "b", name: "B", absolute_box: { x: 50, y: 30, width: 20, height: 40 } };
  const c: Node = { ...template, id: "c", name: "C", absolute_box: { x: 100, y: 60, width: 30, height: 10 } };
  return {
    document: { id: "doc", title: "Doc", artifact_type: "linkedin_ad" },
    pages: {
      page_a4: {
        id: "page_a4",
        name: "A4 Letter",
        size: { width: 210, height: 297, unit: "mm" },
        children: ["a", "b", "c"]
      }
    },
    nodes: { a, b, c },
    slots: {},
    assets: {}
  } as unknown as Scene;
}

describe("ArrangeSection", () => {
  it("disables to-front/forward for the topmost sibling and to-back/backward for the bottommost", () => {
    const scene = siblingScene();
    render(
      React.createElement(ArrangeSection, {
        scene,
        selectedNode: scene.nodes.c, // front-most (z-order a, b, c)
        selectedNodeIds: ["c"],
        onStructuredEdit: vi.fn()
      })
    );

    expect(screen.getByRole("button", { name: /to front/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^forward$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^backward$/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /to back/i })).toBeEnabled();
  });

  it("emits move_after(last sibling) for to-front on a non-front node", () => {
    const scene = siblingScene();
    const onStructuredEdit = vi.fn();
    render(
      React.createElement(ArrangeSection, {
        scene,
        selectedNode: scene.nodes.a,
        selectedNodeIds: ["a"],
        onStructuredEdit
      })
    );

    fireEvent.click(screen.getByRole("button", { name: /to front/i }));
    expect(onStructuredEdit).toHaveBeenCalledWith({ kind: "move_after", node_id: "a", anchor: "c" });
  });

  it("emits move_before(previous sibling) for backward", () => {
    const scene = siblingScene();
    const onStructuredEdit = vi.fn();
    render(
      React.createElement(ArrangeSection, {
        scene,
        selectedNode: scene.nodes.b,
        selectedNodeIds: ["b"],
        onStructuredEdit
      })
    );

    fireEvent.click(screen.getByRole("button", { name: /^backward$/i }));
    expect(onStructuredEdit).toHaveBeenCalledWith({ kind: "move_before", node_id: "b", anchor: "a" });
  });

  it("enables Group for 2+ same-parent unlocked siblings and emits a group edit", () => {
    const scene = siblingScene();
    const onStructuredEdit = vi.fn();
    render(
      React.createElement(ArrangeSection, {
        scene,
        selectedNode: scene.nodes.a,
        selectedNodeIds: ["a", "b"],
        onStructuredEdit
      })
    );

    const groupButton = screen.getByRole("button", { name: /^group$/i });
    expect(groupButton).toBeEnabled();
    fireEvent.click(groupButton);

    expect(onStructuredEdit).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "group",
        node_ids: ["a", "b"],
        name: "Group"
      })
    );
  });

  it("disables Group for a single-node selection", () => {
    const scene = siblingScene();
    render(
      React.createElement(ArrangeSection, {
        scene,
        selectedNode: scene.nodes.a,
        selectedNodeIds: ["a"],
        onStructuredEdit: vi.fn()
      })
    );

    expect(screen.getByRole("button", { name: /^group$/i })).toBeDisabled();
  });

  it("disables Group when a selected member is locked", () => {
    const scene = siblingScene();
    scene.nodes.b.locked = true;
    render(
      React.createElement(ArrangeSection, {
        scene,
        selectedNode: scene.nodes.a,
        selectedNodeIds: ["a", "b"],
        onStructuredEdit: vi.fn()
      })
    );

    expect(screen.getByRole("button", { name: /^group$/i })).toBeDisabled();
  });

  it("enables Ungroup for a single selected container and emits an ungroup edit", () => {
    const scene = siblingScene();
    scene.nodes.frame = { ...scene.nodes.a, id: "frame", name: "Frame", kind: { kind: "frame" }, children: ["a"] };
    scene.pages.page_a4.children = ["frame", "b", "c"];
    const onStructuredEdit = vi.fn();
    render(
      React.createElement(ArrangeSection, {
        scene,
        selectedNode: scene.nodes.frame,
        selectedNodeIds: ["frame"],
        onStructuredEdit
      })
    );

    const ungroupButton = screen.getByRole("button", { name: /^ungroup$/i });
    expect(ungroupButton).toBeEnabled();
    fireEvent.click(ungroupButton);

    expect(onStructuredEdit).toHaveBeenCalledWith({ kind: "ungroup", node_id: "frame", allow_layout: false });
  });

  it("disables Ungroup for a leaf node", () => {
    const scene = siblingScene();
    render(
      React.createElement(ArrangeSection, {
        scene,
        selectedNode: scene.nodes.a,
        selectedNodeIds: ["a"],
        onStructuredEdit: vi.fn()
      })
    );

    expect(screen.getByRole("button", { name: /^ungroup$/i })).toBeDisabled();
  });

  it("disables every z-order control for a locked node", () => {
    const scene = siblingScene();
    scene.nodes.b.locked = true;
    render(
      React.createElement(ArrangeSection, {
        scene,
        selectedNode: scene.nodes.b,
        selectedNodeIds: ["b"],
        onStructuredEdit: vi.fn()
      })
    );

    expect(screen.getByRole("button", { name: /to front/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^forward$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^backward$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /to back/i })).toBeDisabled();
  });

  describe("Align/Distribute (Phase 4b-3)", () => {
    it("disables every align/distribute button without onOperations", () => {
      const scene = pinnedSiblingScene();
      render(
        React.createElement(ArrangeSection, {
          scene,
          selectedNode: scene.nodes.a,
          selectedNodeIds: ["a", "b", "c"],
          onStructuredEdit: vi.fn()
          // onOperations omitted
        })
      );

      expect(screen.getByRole("button", { name: /^align left$/i })).toBeDisabled();
      expect(screen.getByRole("button", { name: /^distribute horizontally$/i })).toBeDisabled();
    });

    it("enables align at 2+ eligible nodes and emits one batch via onOperations", () => {
      const scene = pinnedSiblingScene();
      const onOperations = vi.fn();
      render(
        React.createElement(ArrangeSection, {
          scene,
          selectedNode: scene.nodes.a,
          selectedNodeIds: ["a", "b"],
          onStructuredEdit: vi.fn(),
          onOperations
        })
      );

      const alignLeft = screen.getByRole("button", { name: /^align left$/i });
      expect(alignLeft).toBeEnabled();
      fireEvent.click(alignLeft);

      expect(onOperations).toHaveBeenCalledTimes(1);
      const ops = onOperations.mock.calls[0][0];
      expect(ops).toHaveLength(1);
      expect(ops[0]).toEqual({
        kind: "update_node",
        node_id: "b",
        patch: expect.objectContaining({
          absolute_box: { kind: "set", value: { x: 0, y: 30, width: 20, height: 40 } }
        })
      });
    });

    it("disables align for a single-node selection", () => {
      const scene = pinnedSiblingScene();
      render(
        React.createElement(ArrangeSection, {
          scene,
          selectedNode: scene.nodes.a,
          selectedNodeIds: ["a"],
          onStructuredEdit: vi.fn(),
          onOperations: vi.fn()
        })
      );

      expect(screen.getByRole("button", { name: /^align left$/i })).toBeDisabled();
    });

    it("disables align when a selected member is locked", () => {
      const scene = pinnedSiblingScene();
      scene.nodes.b.locked = true;
      render(
        React.createElement(ArrangeSection, {
          scene,
          selectedNode: scene.nodes.a,
          selectedNodeIds: ["a", "b"],
          onStructuredEdit: vi.fn(),
          onOperations: vi.fn()
        })
      );

      expect(screen.getByRole("button", { name: /^align left$/i })).toBeDisabled();
    });

    it("disables distribute at 2 nodes, enables at 3+, and emits one batch", () => {
      const scene = pinnedSiblingScene();
      const onOperations = vi.fn();
      const { rerender } = render(
        React.createElement(ArrangeSection, {
          scene,
          selectedNode: scene.nodes.a,
          selectedNodeIds: ["a", "b"],
          onStructuredEdit: vi.fn(),
          onOperations
        })
      );
      expect(screen.getByRole("button", { name: /^distribute horizontally$/i })).toBeDisabled();

      rerender(
        React.createElement(ArrangeSection, {
          scene,
          selectedNode: scene.nodes.a,
          selectedNodeIds: ["a", "b", "c"],
          onStructuredEdit: vi.fn(),
          onOperations
        })
      );
      const distributeButton = screen.getByRole("button", { name: /^distribute horizontally$/i });
      expect(distributeButton).toBeEnabled();
      fireEvent.click(distributeButton);

      expect(onOperations).toHaveBeenCalledTimes(1);
      const ops = onOperations.mock.calls[0][0];
      expect(ops).toHaveLength(1);
      expect(ops[0]).toMatchObject({ kind: "update_node", node_id: "b" });
    });

    it("does not call onOperations when align/distribute would produce zero changes", () => {
      const scene = pinnedSiblingScene();
      // Move b to already be left-aligned with the union (x=0) so align("left") is a no-op.
      scene.nodes.b.absolute_box = { x: 0, y: 30, width: 20, height: 40 };
      const onOperations = vi.fn();
      render(
        React.createElement(ArrangeSection, {
          scene,
          selectedNode: scene.nodes.a,
          selectedNodeIds: ["a", "b"],
          onStructuredEdit: vi.fn(),
          onOperations
        })
      );

      fireEvent.click(screen.getByRole("button", { name: /^align left$/i }));
      expect(onOperations).not.toHaveBeenCalled();
    });
  });
});
