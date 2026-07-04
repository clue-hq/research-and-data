import { describe, expect, it } from "vitest";
import phaseFManifest from "../../../../../crates/lumen-core/fixtures/conformance/phase_f_manifest.json";
import type { AssetRecord, Color, Node, Page, Scene } from "../contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { colorToCss, nodeDescriptor, pageDescriptor, sceneUnitFromCanvas, sizeFromCanvas } from "../renderAdapter";

describe("render adapter", () => {
  it("projects page dimensions into canvas units", () => {
    const page = minimalScene.pages.page_a4;
    const descriptor = pageDescriptor(page);

    expect(descriptor.width).toBeCloseTo(793.7, 1);
    expect(descriptor.height).toBeCloseTo(1122.5, 1);
  });

  it("projects canonical A4 page dimensions directly in layout points", () => {
    const page: Page = {
      ...minimalScene.pages.page_a4,
      size: {
        width: 595.2755905511812,
        height: 841.8897637795276,
        unit: "pt",
        preset: "a4",
        orientation: "portrait",
        source: {
          width: 210,
          height: 297,
          unit: "mm"
        },
        output: {
          physical: {
            width: 210,
            height: 297,
            unit: "mm"
          }
        }
      }
    };

    const descriptor = pageDescriptor(page);

    expect(descriptor.width).toBeCloseTo(595.3, 1);
    expect(descriptor.height).toBeCloseTo(841.9, 1);
    expect(descriptor.unitScale).toBe(1);
  });

  it("projects custom px page dimensions without preset coercion", () => {
    const page = {
      ...minimalScene.pages.page_a4,
      size: {
        width: 1080,
        height: 1080,
        unit: "px" as const,
        preset: "custom" as const,
        orientation: "landscape" as const
      }
    };
    const descriptor = pageDescriptor(page);

    expect(descriptor.width).toBe(1080);
    expect(descriptor.height).toBe(1080);
  });

  it("projects Phase F conformance artifact sizes and probe nodes from the shared manifest", () => {
    for (const artifact of phaseFManifest.artifacts) {
      if (!("page" in artifact) || !artifact.page || !("probe_node" in artifact) || !artifact.probe_node) {
        continue;
      }

      const scene = sceneFromManifestArtifact(artifact);
      const page = scene.pages[artifact.page.id];
      const node = scene.nodes[artifact.probe_node.id];
      const pageScale = unitScaleForTest(page.size.unit);
      const pageView = pageDescriptor(page);
      const nodeView = nodeDescriptor(scene, node, page);

      expect(pageView.width, artifact.id).toBeCloseTo(artifact.page.width * pageScale, 2);
      expect(pageView.height, artifact.id).toBeCloseTo(artifact.page.height * pageScale, 2);
      expect(nodeView.x, artifact.id).toBeCloseTo(artifact.probe_node.x * pageScale, 2);
      expect(nodeView.y, artifact.id).toBeCloseTo(artifact.probe_node.y * pageScale, 2);
      expect(nodeView.width, artifact.id).toBeCloseTo(artifact.probe_node.width * pageScale, 2);
      expect(nodeView.height, artifact.id).toBeCloseTo(artifact.probe_node.height * pageScale, 2);
    }
  });

  it("maps a text node to an editor render descriptor", () => {
    const page = minimalScene.pages.page_a4;
    const node = minimalScene.nodes.node_contact_name;
    const descriptor = nodeDescriptor(minimalScene, node, page);

    expect(descriptor.id).toBe("node_contact_name");
    expect(descriptor.kind).toBe("text");
    expect(descriptor.text?.content).toBe("Dr. Priya Sharma");
    expect(descriptor.x).toBeCloseTo(90.7, 1);
    expect(descriptor.slotKeys).toEqual(["contact.full_name"]);
  });

  it("sorts all slot bindings for canvas badge rendering", () => {
    const scene = cloneScene();
    scene.slots.slot_contact_title = {
      ...scene.slots.slot_contact_name,
      id: "slot_contact_title",
      key: "contact.title",
      label: "Contact title",
      bound_nodes: ["node_contact_name"]
    };

    const descriptor = nodeDescriptor(scene, scene.nodes.node_contact_name, scene.pages.page_a4);

    expect(descriptor.slotKeys).toEqual(["contact.full_name", "contact.title"]);
  });

  it("preserves text layout and direction fields for Konva preview", () => {
    const scene = cloneScene();
    scene.nodes.node_contact_name.kind = {
      kind: "text",
      content: "Line one\nLine two",
      font_family: "Inter",
      font_size: 16,
      font_weight: 500,
      align: "right",
      line_height: 1.45,
      letter_spacing: 0.8,
      max_lines: 2,
      wrap: "wrap",
      direction: "rtl"
    };

    const descriptor = nodeDescriptor(scene, scene.nodes.node_contact_name, scene.pages.page_a4);

    expect(descriptor.text).toMatchObject({
      content: "Line one\nLine two",
      fontFamily: "Inter",
      fontSize: expect.closeTo(60.47, 1),
      fontWeight: 500,
      align: "right",
      lineHeight: 1.45,
      letterSpacing: expect.closeTo(3.02, 1),
      maxLines: 2,
      wrap: "wrap",
      direction: "rtl"
    });
  });

  it("preserves image asset labels and IDs for canvas placeholders", () => {
    const scene = cloneScene();
    scene.assets.asset_logo_demo = assetRecord("asset_logo_demo", "Demo Account Logo", "logo");
    scene.nodes.node_contact_name = {
      ...scene.nodes.node_contact_name,
      kind: {
        kind: "image",
        asset_id: "asset_logo_demo",
        alt: "Account logo"
      },
      source_asset_id: "asset_logo_demo"
    };

    const descriptor = nodeDescriptor(scene, scene.nodes.node_contact_name, scene.pages.page_a4);

    expect(descriptor.image).toEqual({
      assetId: "asset_logo_demo",
      sourceAssetId: "asset_logo_demo",
      alt: "Account logo",
      assetLabel: "Demo Account Logo",
      assetKind: "logo",
      assetStatus: "ready",
      fit: null,
      focalPoint: null,
      naturalAspectRatio: null
    });
  });

  it("carries fit, focal point, and natural aspect ratio for raster image placement", () => {
    const scene = cloneScene();
    const raster = assetRecord("asset_hero", "Hero Photo", "raster_image");
    raster.raster = {
      pixel_width: 1600,
      pixel_height: 900,
      dpi_x: null,
      dpi_y: null,
      has_alpha: false,
      color_profile: null,
      aspect_ratio: null
    };
    scene.assets.asset_hero = raster;
    scene.nodes.node_contact_name = {
      ...scene.nodes.node_contact_name,
      kind: { kind: "image", asset_id: "asset_hero", alt: "Hero" },
      source_asset_id: "asset_hero",
      asset_placement: { fit: "cover", focal_point: { x: 0.25, y: 0.75 }, alt_text: "Hero" }
    };

    const descriptor = nodeDescriptor(scene, scene.nodes.node_contact_name, scene.pages.page_a4);

    expect(descriptor.image?.fit).toBe("cover");
    expect(descriptor.image?.focalPoint).toEqual({ x: 0.25, y: 0.75 });
    expect(descriptor.image?.naturalAspectRatio).toBeCloseTo(1600 / 900, 6);
  });

  it("preserves vector source asset metadata for canvas placeholders and parity diagnostics", () => {
    const scene = cloneScene();
    scene.assets.asset_vector_logo = assetRecord("asset_vector_logo", "Vector Logo", "vector");
    scene.nodes.node_contact_name = {
      ...scene.nodes.node_contact_name,
      kind: {
        kind: "vector",
        path_data: "M0 0H24V24H0Z"
      },
      source_asset_id: "asset_vector_logo"
    };

    const descriptor = nodeDescriptor(scene, scene.nodes.node_contact_name, scene.pages.page_a4);

    expect(descriptor.vector).toEqual({
      pathData: "M0 0H24V24H0Z",
      sourceAssetId: "asset_vector_logo",
      assetLabel: "Vector Logo",
      assetKind: "vector",
      assetStatus: "ready"
    });
  });

  it("uses computed layout bounds for hug/fill-sized nodes", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const node: Node = {
      ...scene.nodes.node_contact_name,
      kind: {
        kind: "auto_layout",
        direction: "row",
        wrap: false
      },
      size: {
        width: {
          kind: "hug"
        },
        height: {
          kind: "fill",
          value: {
            weight: 1
          }
        }
      },
      computed: {
        layout_bounds: {
          x: 24,
          y: 40,
          width: 120,
          height: 32
        },
        render_bounds: {
          x: 24,
          y: 40,
          width: 124,
          height: 36
        }
      }
    };
    scene.nodes[node.id] = node;

    const descriptor = nodeDescriptor(scene, node, page);

    expect(descriptor.width).toBeCloseTo(453.5, 1);
    expect(descriptor.height).toBeCloseTo(120.9, 1);
    expect(descriptor.x).toBeCloseTo(90.7, 1);
    expect(descriptor.y).toBeCloseTo(151.2, 1);
  });

  it("uses computed child coordinates relative to a computed parent like export", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    page.size = {
      width: 1080,
      height: 1080,
      unit: "px",
      preset: "custom",
      orientation: "landscape"
    };
    page.children = ["parent_frame"];

    const parent: Node = {
      ...scene.nodes.node_contact_name,
      id: "parent_frame",
      name: "Parent frame",
      kind: {
        kind: "frame"
      },
      children: ["child_text"],
      computed: {
        layout_bounds: {
          x: 100,
          y: 60,
          width: 400,
          height: 180
        },
        render_bounds: {
          x: 100,
          y: 60,
          width: 400,
          height: 180
        }
      }
    };
    const child: Node = {
      ...scene.nodes.node_contact_name,
      id: "child_text",
      name: "Child text",
      children: [],
      computed: {
        layout_bounds: {
          x: 124,
          y: 84,
          width: 320,
          height: 48
        },
        render_bounds: {
          x: 124,
          y: 84,
          width: 320,
          height: 48
        }
      }
    };
    scene.nodes = {
      parent_frame: parent,
      child_text: child
    };

    const parentDescriptor = nodeDescriptor(scene, parent, page);
    const childDescriptor = nodeDescriptor(scene, child, page, {
      x: parent.computed!.layout_bounds.x,
      y: parent.computed!.layout_bounds.y
    });

    expect(parentDescriptor.x).toBe(100);
    expect(parentDescriptor.y).toBe(60);
    expect(childDescriptor.x).toBe(24);
    expect(childDescriptor.y).toBe(24);
    expect(childDescriptor.width).toBe(320);
    expect(childDescriptor.height).toBe(48);
  });

  it("accepts Rust-serialized token dimensions as unresolved editor sizes", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const node: Node = {
      ...scene.nodes.node_contact_name,
      size: {
        width: {
          kind: "token",
          value: {
            token: "space.xl"
          }
        },
        height: {
          kind: "token",
          value: {
            token: "space.md"
          }
        }
      },
      computed: null
    };
    scene.nodes[node.id] = node;

    const descriptor = nodeDescriptor(scene, node, page);

    expect(descriptor.width).toBe(0);
    expect(descriptor.height).toBe(0);
  });

  it("keeps logical groups non-visual when they have no fills", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const node: Node = {
      ...scene.nodes.node_contact_name,
      kind: {
        kind: "group"
      },
      fills: [],
      strokes: []
    };
    scene.nodes[node.id] = node;

    const descriptor = nodeDescriptor(scene, node, page);

    expect(descriptor.fill).toBe("transparent");
    expect(descriptor.stroke).toBeNull();
  });

  it("converts CSS alpha-last hex to CSS rgba", () => {
    const color: Color = {
      kind: "hex",
      value: "#ff000080"
    };

    expect(colorToCss(color)).toBe("rgba(255, 0, 0, 0.502)");
  });

  it("round trips canvas measurements back to scene units", () => {
    const page = minimalScene.pages.page_a4;

    expect(sceneUnitFromCanvas(96, page)).toBeCloseTo(25.4, 2);
    expect(sizeFromCanvas(96, 192, page)).toEqual({
      width: {
        kind: "fixed",
        value: 25.4
      },
      height: {
        kind: "fixed",
        value: 50.8
      }
    });
  });

  // Coordinate-model fix: the transform fallback (computed absent) must be
  // layout-safe. For a layout-managed node (an auto-layout child) `transform`
  // is not its real position — flow owns it — so the fallback renders it at
  // its container origin, not at a meaningless authored transform. With the
  // engine relaying out on load this fallback rarely fires, but it must never
  // jump a flow-positioned node when it does.
  it("renders an un-laid-out auto-layout child at its container origin, not its transform", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const parent: Node = {
      ...scene.nodes.node_contact_name,
      id: "stack",
      name: "Stack",
      kind: { kind: "auto_layout", direction: "column", wrap: false },
      fills: [],
      strokes: [],
      children: ["stack_child"],
      computed: null
    };
    const child: Node = {
      ...scene.nodes.node_contact_name,
      id: "stack_child",
      name: "Stack child",
      transform: { ...scene.nodes.node_contact_name.transform, x: 999, y: 999 },
      children: [],
      computed: null
    };
    scene.nodes = { stack: parent, stack_child: child };
    scene.pages.page_a4 = { ...page, children: ["stack"] };

    const descriptor = nodeDescriptor(scene, child, scene.pages.page_a4, { x: 0, y: 0 });

    expect(descriptor.x).toBe(0);
    expect(descriptor.y).toBe(0);
  });

  it("renders an un-laid-out free child at its authored transform", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const parent: Node = {
      ...scene.nodes.node_contact_name,
      id: "frame",
      name: "Frame",
      kind: { kind: "frame" },
      fills: [],
      strokes: [],
      children: ["frame_child"],
      computed: null
    };
    const child: Node = {
      ...scene.nodes.node_contact_name,
      id: "frame_child",
      name: "Frame child",
      transform: { ...scene.nodes.node_contact_name.transform, x: 12, y: 34 },
      children: [],
      computed: null
    };
    scene.nodes = { frame: parent, frame_child: child };
    scene.pages.page_a4 = { ...page, children: ["frame"] };

    const scale = unitScaleForTest(scene.pages.page_a4.size.unit);
    const descriptor = nodeDescriptor(scene, child, scene.pages.page_a4, { x: 0, y: 0 });

    expect(descriptor.x).toBeCloseTo(12 * scale, 3);
    expect(descriptor.y).toBeCloseTo(34 * scale, 3);
  });

  // Wave 3 C1: descriptor carries the full shadow stack and an SVG-contour
  // outline so the CanvasKit renderer can chain shadows and stroke dashes with
  // export-matching geometry. Konva ignores both.
  it("carries the full drop-shadow stack in allShadows (Konva fields preserved)", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const node: Node = {
      ...scene.nodes.node_contact_name,
      effects: [
        dropShadow("s1", "#000000", 0.2, 0, 4, 12),
        dropShadow("s2", "#101010", 0.1, 0, 8, 24)
      ]
    };
    scene.nodes[node.id] = node;

    const descriptor = nodeDescriptor(scene, node, page);

    expect(descriptor.allShadows).toHaveLength(2);
    // Konva-era fields stay: first shadow + count of the rest.
    expect(descriptor.shadow).toEqual(descriptor.allShadows[0]);
    expect(descriptor.extraShadowCount).toBe(1);
    expect(descriptor.allShadows[1].offsetY).toBeCloseTo(8 * unitScaleForTest(page.size.unit), 3);
  });

  it("emits a rounded-rect contour starting at (r,0) for a uniform corner radius", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const scale = unitScaleForTest(page.size.unit);
    const node: Node = {
      ...scene.nodes.node_contact_name,
      kind: { kind: "rect" },
      size: { width: { kind: "fixed", value: 100 }, height: { kind: "fixed", value: 60 } },
      corner: { top_left: 8, top_right: 8, bottom_right: 8, bottom_left: 8 },
      computed: null
    };
    scene.nodes[node.id] = node;

    const path = nodeDescriptor(scene, node, page).contourPath!;
    const r = 8 * scale;
    // Starts at (r, 0) — the SVG <rect rx> contour start, not drawRRect's.
    expect(path.startsWith(`M${round3(r)} 0`)).toBe(true);
    expect(path).toContain("A"); // has corner arcs
    expect(path.endsWith("Z")).toBe(true);
  });

  it("squares a non-uniform corner contour (export has no per-corner radii)", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const scale = unitScaleForTest(page.size.unit);
    const node: Node = {
      ...scene.nodes.node_contact_name,
      kind: { kind: "rect" },
      size: { width: { kind: "fixed", value: 100 }, height: { kind: "fixed", value: 60 } },
      corner: { top_left: 8, top_right: 0, bottom_right: 8, bottom_left: 0 },
      computed: null
    };
    scene.nodes[node.id] = node;

    const path = nodeDescriptor(scene, node, page).contourPath!;
    expect(path).toBe(`M0 0H${round3(100 * scale)}V${round3(60 * scale)}H0Z`);
    expect(path).not.toContain("A");
  });

  it("emits an ellipse contour from the rightmost point", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const scale = unitScaleForTest(page.size.unit);
    const node: Node = {
      ...scene.nodes.node_contact_name,
      kind: { kind: "ellipse" },
      size: { width: { kind: "fixed", value: 80 }, height: { kind: "fixed", value: 40 } },
      computed: null
    };
    scene.nodes[node.id] = node;

    const path = nodeDescriptor(scene, node, page).contourPath!;
    expect(path.startsWith(`M${round3(80 * scale)} ${round3(20 * scale)}`)).toBe(true);
    expect(path.endsWith("Z")).toBe(true);
  });

  it("has no contour for kinds that carry their own geometry (text)", () => {
    const scene = cloneScene();
    const descriptor = nodeDescriptor(scene, scene.nodes.node_contact_name, scene.pages.page_a4);
    expect(descriptor.contourPath).toBeNull();
  });
});

function dropShadow(
  id: string,
  hex: string,
  opacity: number,
  x: number,
  y: number,
  blur: number
): NonNullable<Node["effects"]>[number] {
  return {
    id,
    kind: { kind: "drop_shadow", color: { kind: "hex", value: hex }, opacity, x, y, blur, spread: 0 }
  };
}

function round3(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}

function assetRecord(id: string, label: string, kind: AssetRecord["kind"]): AssetRecord {
  return {
    id,
    label,
    kind,
    status: "ready",
    source: {
      kind: "workspace",
      asset_id: id
    },
    raster: null,
    vector: null,
    font: null,
    logo: null,
    license: null,
    provenance: {
      created_by: "test",
      created_at: "2026-06-11T00:00:00Z",
      source_label: "test fixture",
      confidence: 1,
      notes: []
    },
    tags: []
  };
}

type ManifestArtifact = (typeof phaseFManifest.artifacts)[number] & {
  page: {
    id: string;
    width: number;
    height: number;
    unit: string;
    preset: string | null;
    orientation: string;
  };
  probe_node: {
    id: string;
    x: number;
    y: number;
    width: number;
    height: number;
  };
};

function sceneFromManifestArtifact(artifact: ManifestArtifact): Scene {
  const scene = cloneScene();
  scene.pages = {
    [artifact.page.id]: {
      id: artifact.page.id,
      name: artifact.label,
      size: {
        width: artifact.page.width,
        height: artifact.page.height,
        unit: unitFromManifest(artifact.page.unit),
        preset: presetFromManifest(artifact.page.preset),
        orientation: orientationFromManifest(artifact.page.orientation)
      },
      children: [artifact.probe_node.id],
      bleed: null,
      safe_area: null,
      background: []
    }
  };
  scene.nodes = {
    [artifact.probe_node.id]: {
      ...scene.nodes.node_contact_name,
      id: artifact.probe_node.id,
      name: artifact.label,
      kind: {
        kind: "rect"
      },
      transform: {
        x: artifact.probe_node.x,
        y: artifact.probe_node.y,
        rotation: 0,
        skew_x: 0,
        skew_y: 0,
        flip_x: false,
        flip_y: false
      },
      size: {
        width: {
          kind: "fixed",
          value: artifact.probe_node.width
        },
        height: {
          kind: "fixed",
          value: artifact.probe_node.height
        }
      },
      children: [],
      fills: [],
      strokes: [],
      computed: null
    }
  };
  return scene;
}

function unitFromManifest(unit: string): Page["size"]["unit"] {
  switch (unit) {
    case "pt":
    case "px":
    case "mm":
    case "in":
      return unit;
    default:
      throw new Error(`Unsupported Phase F manifest unit ${unit}`);
  }
}

function presetFromManifest(preset: string | null): Page["size"]["preset"] {
  switch (preset) {
    case null:
    case "a4":
    case "us_letter":
    case "custom":
    case "linkedin_ad":
    case "envelope_dl":
      return preset;
    default:
      throw new Error(`Unsupported Phase F manifest preset ${preset}`);
  }
}

function orientationFromManifest(orientation: string): Page["size"]["orientation"] {
  switch (orientation) {
    case "portrait":
    case "landscape":
      return orientation;
    default:
      throw new Error(`Unsupported Phase F manifest orientation ${orientation}`);
  }
}

function unitScaleForTest(unit: Page["size"]["unit"]): number {
  switch (unit) {
    case "pt":
    case "px":
      return 1;
    case "mm":
      return 96 / 25.4;
    case "in":
      return 96;
  }
}
