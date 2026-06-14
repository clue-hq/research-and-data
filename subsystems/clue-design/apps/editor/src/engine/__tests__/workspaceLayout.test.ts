import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Diagnostic, Node, Page, Scene } from "../contracts";
import { normalizePageSize } from "../pageGeometry";
import {
  artboardAtWorkspacePoint,
  artboardLocalPointToWorkspace,
  artboardLocalRectToWorkspace,
  createWorkspaceModel,
  layoutWorkspaceArtboards,
  workspacePointToArtboardLocal
} from "../workspaceLayout";

describe("workspace layout", () => {
  it("creates one deterministic workspace frame per page", () => {
    const scene = sceneWithPages([
      page("page_square", "Square Ad", 1080, 1080, "px"),
      page("page_letter", "Letter", 8.5, 11, "in"),
      page("page_banner", "Banner", 1200, 628, "px")
    ]);

    const first = createWorkspaceModel(scene, "page_letter", [], { rowWidth: 4000 });
    const second = createWorkspaceModel(scene, "page_letter", [], { rowWidth: 4000 });

    expect(first).toEqual(second);
    expect(first.artboards).toHaveLength(3);
    expect(first.activeArtboard?.pageId).toBe("page_letter");
    expect(first.artboards.map((artboard) => artboard.workspaceRect)).toEqual([
      { x: 0, y: 0, width: 1080, height: 1080 },
      { x: 1260, y: 0, width: 612, height: 792 },
      { x: 2052, y: 0, width: 1200, height: 628 }
    ]);
  });

  it("wraps rows without overlapping differently sized artboards", () => {
    const placed = layoutWorkspaceArtboards(
      [
        { pageId: "a", name: "A", width: 1000, height: 400 },
        { pageId: "b", name: "B", width: 700, height: 900 },
        { pageId: "c", name: "C", width: 600, height: 300 }
      ],
      { gap: 100, rowWidth: 1500 }
    );

    expect(placed.map((item) => item.workspaceRect)).toEqual([
      { x: 0, y: 0, width: 1000, height: 400 },
      { x: 0, y: 500, width: 700, height: 900 },
      { x: 800, y: 500, width: 600, height: 300 }
    ]);
    expect(placed[0].workspaceRect.y + placed[0].workspaceRect.height).toBeLessThanOrEqual(
      placed[1].workspaceRect.y
    );
  });

  it("uses canonical layout dimensions instead of physical source metadata", () => {
    const scene = sceneWithPages([page("page_a4", "A4", 210, 297, "mm")]);
    const model = createWorkspaceModel(scene, "page_a4");
    const artboard = model.artboards[0];

    expect(scene.pages.page_a4.size.source).toMatchObject({ width: 210, height: 297, unit: "mm" });
    expect(scene.pages.page_a4.size.output?.physical).toMatchObject({ width: 210, height: 297, unit: "mm" });
    expect(artboard.workspaceRect.width).toBeCloseTo(595.276, 3);
    expect(artboard.workspaceRect.height).toBeCloseTo(841.89, 2);
  });

  it("rolls diagnostics up to owning artboards", () => {
    const scene = sceneWithPages([page("page_one", "One", 600, 400, "px"), page("page_two", "Two", 600, 400, "px")]);
    scene.nodes.node_on_page_two = node("node_on_page_two");
    scene.pages.page_two.children.push("node_on_page_two");
    scene.nodes.node_asset = {
      ...node("node_asset"),
      kind: {
        kind: "image",
        asset_id: "asset_hero",
        alt: "Hero"
      },
      source_asset_id: null
    };
    scene.pages.page_two.children.push("node_asset");
    scene.slots.slot_dynamic_name = {
      ...minimalScene.slots.slot_contact_name,
      id: "slot_dynamic_name",
      key: "dynamic.name",
      scope: {
        kind: "page",
        id: "page_two"
      },
      bound_nodes: ["node_on_page_two"]
    };
    const diagnostics: Diagnostic[] = [
      diagnostic("error", { kind: "page", id: "page_one" }),
      diagnostic("warning", { kind: "node", id: "node_on_page_two" }),
      diagnostic("warning", { kind: "slot", id: "slot_dynamic_name" }),
      diagnostic("error", { kind: "asset", id: "asset_hero" }),
      diagnostic("advice", { kind: "node", id: "node_on_page_two" }),
      diagnostic("error", { kind: "document" })
    ];

    const model = createWorkspaceModel(scene, "page_one", diagnostics);

    expect(model.artboards.find((artboard) => artboard.pageId === "page_one")?.diagnosticsSummary).toEqual({
      errorCount: 1,
      warningCount: 0
    });
    expect(model.artboards.find((artboard) => artboard.pageId === "page_two")?.diagnosticsSummary).toEqual({
      errorCount: 1,
      warningCount: 2
    });
  });

  it("converts between workspace and artboard-local coordinates", () => {
    const scene = sceneWithPages([page("page_one", "One", 600, 400, "px"), page("page_two", "Two", 300, 200, "px")]);
    const model = createWorkspaceModel(scene, "page_two", [], { rowWidth: 4000 });
    const artboard = model.artboards[1];
    const workspacePoint = artboardLocalPointToWorkspace(artboard, { x: 25, y: 40 });

    expect(workspacePoint).toEqual({ x: 805, y: 40 });
    expect(workspacePointToArtboardLocal(artboard, workspacePoint)).toEqual({ x: 25, y: 40 });
    expect(artboardLocalRectToWorkspace(artboard, { x: 10, y: 20, width: 30, height: 40 })).toEqual({
      x: 790,
      y: 20,
      width: 30,
      height: 40
    });
    expect(artboardAtWorkspacePoint(model, workspacePoint)?.pageId).toBe("page_two");
  });
});

function sceneWithPages(pages: Page[]): Scene {
  return {
    schema_version: 1,
    meta: {
      id: "scene_workspace_test",
      title: "Workspace Test",
      artifact_type: "test",
      medium: "digital",
      brand_kit: null,
      status: { kind: "draft" }
    },
    pages: Object.fromEntries(pages.map((item) => [item.id, item])),
    nodes: {},
    slots: {},
    assets: {},
    export_profiles: []
  };
}

function page(id: string, name: string, width: number, height: number, unit: Page["size"]["unit"]): Page {
  return {
    id,
    name,
    size: normalizePageSize({ width, height, unit }),
    children: [],
    bleed: null,
    safe_area: null,
    background: []
  };
}

function node(id: string): Node {
  return {
    id,
    name: id,
    locked: false,
    children: [],
    transform: {
      x: 0,
      y: 0,
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
      flip_x: false,
      flip_y: false
    },
    size: {
      width: { kind: "fixed", value: 100 },
      height: { kind: "fixed", value: 100 }
    },
    opacity: 1,
    fills: [],
    strokes: [],
    effects: [],
    corner: {
      top_left: 0,
      top_right: 0,
      bottom_right: 0,
      bottom_left: 0
    },
    clip: false,
    layout: null,
    source_asset_id: null,
    computed: null,
    kind: { kind: "frame" }
  };
}

function diagnostic(severity: Diagnostic["severity"], subject: Diagnostic["subject"]): Diagnostic {
  return {
    severity,
    phase: "validation",
    code: `TEST_${severity.toUpperCase()}`,
    message: "Test diagnostic",
    subject,
    hint: null
  };
}
