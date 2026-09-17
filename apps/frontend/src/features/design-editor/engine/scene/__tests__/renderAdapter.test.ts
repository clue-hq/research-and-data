import { afterEach, describe, expect, it } from "../../__tests__/vitest-shim";
import phaseFManifest from "./__fixtures__/phase_f_manifest.json";
import type { AssetRecord, Color, Node, Page, Paint, Scene } from "../contracts";
import { minimalScene } from "./__fixtures__/minimalScene";
import {
  colorToCss,
  nodeDescriptor,
  paintDescriptor,
  paintToCss,
  pageDescriptor,
  sceneUnitFromCanvas,
  resolvedTextFields,
  resolveTokenNumber,
  setKitTokenMaps,
  setTokenColorMap,
  sizeFromCanvas,
  subscribeTokenColors,
  tokenColorsGenerationSnapshot,
  tokenPaintResolves,
  tokenSwatchCss,
  valignOffset
} from "../renderAdapter";

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

  describe("token paint resolution (4d: canvas token fidelity)", () => {
    afterEach(() => {
      // Module-level registry (see renderAdapter's `tokenColorMap` doc
      // comment) — reset after every test so map state never leaks across
      // cases in this file.
      setTokenColorMap({});
    });

    it("tokenSwatchCss resolves a mapped token to the kit value (the color the canvas paints)", () => {
      setTokenColorMap({ "surface.brand": "#123456" });
      expect(tokenSwatchCss("surface.brand")).toBe("#123456");
      // `$`-prefixed author form hits the same map entry.
      expect(tokenSwatchCss("$surface.brand")).toBe("#123456");
    });

    it("tokenSwatchCss falls through to the same heuristic the paint path uses on a map miss", () => {
      setTokenColorMap({});
      expect(tokenSwatchCss("text.primary")).toBe("#27231d");
      expect(tokenSwatchCss("surface.page")).toBe("#f8f4ec");
      expect(tokenSwatchCss("accent.primary")).toBe("#256c70");
      expect(tokenSwatchCss("unmapped.custom")).toBe("#b7aa96");
      // Identical to what the paint path would produce for the same token.
      expect(tokenSwatchCss("surface.page")).toBe(paintToCss({ kind: "token", token: "surface.page" }));
    });

    it("WITHOUT a map, pins the pre-existing string-heuristic fallback", () => {
      const color: Color = { kind: "token", token: "surface.page" };
      expect(colorToCss(color)).toBe("#f8f4ec");

      const paint: Paint = { kind: "token", token: "surface.page" };
      expect(paintToCss(paint)).toBe("#f8f4ec");
      expect(paintDescriptor(paint, 100, 100)).toEqual({ kind: "solid", color: "#f8f4ec" });
    });

    it("WITH a map, resolves to the real mapped value instead of the heuristic", () => {
      setTokenColorMap({
        "surface.page": "#FFFFFF",
        "surface.card": "#FFFFFF",
        "surface.inverse": "#0F172A"
      });

      expect(colorToCss({ kind: "token", token: "surface.page" })).toBe("#FFFFFF");
      expect(paintToCss({ kind: "token", token: "surface.card" })).toBe("#FFFFFF");
      expect(paintDescriptor({ kind: "token", token: "surface.inverse" }, 100, 100)).toEqual({
        kind: "solid",
        color: "#0F172A"
      });

      // The three real values are distinct, unlike the heuristic (which
      // painted every "surface" token the same cream).
      expect(new Set(["#FFFFFF", "#FFFFFF", "#0F172A"]).size).toBeLessThan(3);
      const pageColor = colorToCss({ kind: "token", token: "surface.page" });
      const inverseColor = colorToCss({ kind: "token", token: "surface.inverse" });
      expect(pageColor).not.toBe(inverseColor);
    });

    it("WITH a map, a token the map doesn't know still falls through to the heuristic", () => {
      setTokenColorMap({ "surface.page": "#FFFFFF" });

      // "unmapped.custom" contains none of the heuristic's substrings
      // (text/surface/accent/primary), so it hits the catch-all fallback.
      expect(colorToCss({ kind: "token", token: "unmapped.custom" })).toBe("#b7aa96");
      expect(paintToCss({ kind: "token", token: "accent.primary" })).toBe("#256c70");
    });

    it("page background fills and node fills both consult the map", () => {
      setTokenColorMap({ "surface.page": "#FFFFFF" });
      const page: Page = {
        ...minimalScene.pages.page_a4,
        background: [
          {
            id: "paint_page_bg",
            paint: { kind: "token", token: "surface.page" }
          }
        ]
      };
      expect(pageDescriptor(page).background).toBe("#FFFFFF");

      setTokenColorMap({ "surface.card": "#FFFFFF" });
      const scene = cloneScene();
      const node: Node = {
        ...scene.nodes.node_contact_name,
        fills: [{ id: "paint_node_fill", paint: { kind: "token", token: "surface.card" } }],
        strokes: []
      };
      scene.nodes[node.id] = node;
      const descriptor = nodeDescriptor(scene, node, page);
      expect(descriptor.fill).toBe("#FFFFFF");
      expect(descriptor.fills[0]?.paint).toEqual({ kind: "solid", color: "#FFFFFF" });
    });

    it("K0.5: setTokenColorMap notifies subscribers and bumps the generation (repaint trigger)", () => {
      const before = tokenColorsGenerationSnapshot();
      let notified = 0;
      const unsubscribe = subscribeTokenColors(() => {
        notified += 1;
      });

      setTokenColorMap({ "surface.brand": "#00525c" });
      expect(notified).toBe(1);
      expect(tokenColorsGenerationSnapshot()).toBe(before + 1);

      unsubscribe();
      setTokenColorMap({});
      expect(notified).toBe(1);
      expect(tokenColorsGenerationSnapshot()).toBe(before + 2);
    });

    it("K0.5: tokenPaintResolves reports map hits vs heuristic-fallback misses", () => {
      setTokenColorMap({ "surface.brand": "#00525c" });
      expect(tokenPaintResolves("surface.brand")).toBe(true);
      expect(tokenPaintResolves("$surface.brand")).toBe(true);
      expect(tokenPaintResolves("surface.page")).toBe(false);
    });

    it("K1.5: resolvedTextFields applies the kit type role over skeleton literals", () => {
      setKitTokenMaps({
        colors: {},
        typography: {
          "type.headline": {
            fontFamily: "Source Sans 3",
            fontSize: 80,
            fontWeight: 800,
            lineHeight: 1.05
          }
        },
        numbers: { "type.size.7xl": 96, "radius.button": 12 }
      });
      // The K1 live-proof skeleton: Inter 16 literals + a style token.
      const styled = resolvedTextFields({
        font_family: "Inter",
        font_size: 16,
        font_weight: 400,
        style_token: "type.headline"
      });
      expect(styled).toEqual({
        fontFamily: "Source Sans 3",
        fontSize: 80,
        fontWeight: 800,
        lineHeight: 1.05,
        letterSpacing: 0
      });
      // font_size_token overrides the role size; unresolved tokens keep literals.
      expect(
        resolvedTextFields({
          font_family: "Inter",
          font_size: 16,
          font_weight: 400,
          style_token: "type.headline",
          font_size_token: "type.size.7xl"
        }).fontSize
      ).toBe(96);
      expect(
        resolvedTextFields({
          font_family: "Inter",
          font_size: 16,
          font_weight: 400,
          style_token: "type.ghost"
        }).fontSize
      ).toBe(16);
      expect(resolveTokenNumber("radius.button")).toBe(12);
      expect(resolveTokenNumber("$radius.button")).toBe(12);
      expect(resolveTokenNumber("radius.ghost")).toBeNull();
    });

    it("typography roles override leading and tracking tokens as the export resolver does", () => {
      setKitTokenMaps({ colors: {}, typography: {
        "type.headline": { lineHeight: 1.12, letterSpacing: -0.6 },
      }, numbers: { "type.leading": 1.4, "type.tracking": 2 } });
      const text = { font_family: "Inter", font_size: 16, font_weight: 400,
        style_token: "type.headline", line_height_token: "type.leading",
        letter_spacing_token: "type.tracking" };
      expect(resolvedTextFields(text).lineHeight).toBe(1.12);
      expect(resolvedTextFields(text).letterSpacing).toBe(-0.6);
      expect(resolvedTextFields({ ...text, style_token: null }).lineHeight).toBe(1.4);
      expect(resolvedTextFields({ ...text, style_token: null }).letterSpacing).toBe(2);
    });

    it("K0.5: direct oklch scene colors paint as hex (CanvasKit parseColor cannot read oklch)", () => {
      const color: Color = {
        kind: "oklch",
        l: 0.4,
        c: 0.07382381488920986,
        h: 207.87981654900904,
        alpha: 1
      };
      // Same value the engine resolves for the Insight kit's surface.brand.
      expect(colorToCss(color)).toBe("#00525c");
    });
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

  it("emits a per-corner arc contour when corners differ (A4 per-corner radii)", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const s = unitScaleForTest(page.size.unit);
    const node: Node = {
      ...scene.nodes.node_contact_name,
      kind: { kind: "rect" },
      size: { width: { kind: "fixed", value: 100 }, height: { kind: "fixed", value: 60 } },
      corner: { top_left: 8, top_right: 0, bottom_right: 8, bottom_left: 0 },
      computed: null
    };
    scene.nodes[node.id] = node;

    // E-A4 landed per-corner radii end-to-end (the SVG exporter now emits a
    // per-corner arc <path>); the canvas contour mirrors it. The tl/br corners
    // round; the zero tr/bl corners degenerate to zero-radius arcs (linetos).
    const path = nodeDescriptor(scene, node, page).contourPath!;
    const n = round3;
    const w = 100 * s;
    const h = 60 * s;
    const r = 8 * s;
    expect(path).toBe(
      `M${n(r)} 0H${n(w)}A0 0 0 0 1 ${n(w)} 0V${n(h - r)}` +
        `A${n(r)} ${n(r)} 0 0 1 ${n(w - r)} ${n(h)}H0A0 0 0 0 1 0 ${n(h)}` +
        `V${n(r)}A${n(r)} ${n(r)} 0 0 1 ${n(r)} 0Z`
    );
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

describe("A7a vertical alignment", () => {
  it("valignOffset applies the clamped-slack formula (top=0, center=0.5, bottom=1)", () => {
    // Slack present: box (100) taller than content (40) → 60px of slack.
    expect(valignOffset(100, 40, "top")).toBe(0);
    expect(valignOffset(100, 40, "center")).toBe(30);
    expect(valignOffset(100, 40, "bottom")).toBe(60);
  });

  it("valignOffset clamps overflow to a no-op (never paints above the top edge)", () => {
    // Content taller than the box → negative slack clamps to 0 for every mode.
    expect(valignOffset(40, 100, "top")).toBe(0);
    expect(valignOffset(40, 100, "center")).toBe(0);
    expect(valignOffset(40, 100, "bottom")).toBe(0);
    // Exact fit → zero slack.
    expect(valignOffset(40, 40, "bottom")).toBe(0);
  });

  it("the text descriptor carries valign, defaulting to \"top\" when the node omits it", () => {
    const page = minimalScene.pages.page_a4;
    const base = minimalScene.nodes.node_contact_name as Node;

    const defaulted = nodeDescriptor(minimalScene, base, page);
    expect(defaulted.text?.valign).toBe("top");

    const centered: Node = {
      ...structuredClone(base),
      kind: { ...structuredClone(base.kind), valign: "center" } as Node["kind"]
    };
    expect(nodeDescriptor(minimalScene, centered, page).text?.valign).toBe("center");

    const bottom: Node = {
      ...structuredClone(base),
      kind: { ...structuredClone(base.kind), valign: "bottom" } as Node["kind"]
    };
    expect(nodeDescriptor(minimalScene, bottom, page).text?.valign).toBe("bottom");
  });
});

describe("A7b italic descriptor", () => {
  const page = minimalScene.pages.page_a4;
  const base = minimalScene.nodes.node_contact_name as Node;

  it("carries block italic, defaulting to false when the node omits it", () => {
    expect(nodeDescriptor(minimalScene, base, page).text?.italic).toBe(false);

    const italicNode: Node = {
      ...structuredClone(base),
      kind: { ...structuredClone(base.kind), italic: true } as Node["kind"]
    };
    expect(nodeDescriptor(minimalScene, italicNode, page).text?.italic).toBe(true);
  });

  it("carries span italic verbatim — false preserved (override), absent → null (inherit)", () => {
    const spanned: Node = {
      ...structuredClone(base),
      kind: {
        ...structuredClone(base.kind),
        italic: true,
        spans: [
          // Explicit de-italicize: false must survive as false, NOT collapse to
          // null (the override merge `span.italic ?? block` depends on it).
          { start: 0, end: 3, italic: false },
          // Italic span inside an upright region.
          { start: 4, end: 7, italic: true },
          // No italic channel → inherit (null in descriptor form).
          { start: 8, end: 11, font_weight: 700 }
        ]
      } as Node["kind"]
    };
    const spans = nodeDescriptor(minimalScene, spanned, page).text?.spans;
    expect(spans?.[0].italic).toBe(false);
    expect(spans?.[1].italic).toBe(true);
    expect(spans?.[2].italic).toBeNull();
  });
});
