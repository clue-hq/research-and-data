import { afterEach, describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { AssetRecord, Node, Scene } from "../contracts";
import { setTokenColorMap } from "../renderAdapter";
import { editorRenderDiagnostics, heuristicMeasurementDiagnostic } from "../renderDiagnostics";

describe("heuristic measurement diagnostic", () => {
  it("emits a loud EDITOR_HEURISTIC_MEASUREMENT error only when measurement is heuristic", () => {
    const diagnostic = heuristicMeasurementDiagnostic("heuristic");
    expect(diagnostic).not.toBeNull();
    expect(diagnostic).toEqual(
      expect.objectContaining({
        severity: "error",
        code: "EDITOR_HEURISTIC_MEASUREMENT",
        subject: { kind: "document" }
      })
    );
    expect(diagnostic?.message).toMatch(/measurement degraded/i);
    expect(diagnostic?.message).toMatch(/font engine unavailable/i);
  });

  it("is silent while measurement is exact (skia) or not yet resolved (pending)", () => {
    expect(heuristicMeasurementDiagnostic("skia")).toBeNull();
    expect(heuristicMeasurementDiagnostic("pending")).toBeNull();
  });
});

describe("editor render diagnostics", () => {
  afterEach(() => {
    // The diagnostics consult renderAdapter's module-level token map (K0.5);
    // reset it so map state never leaks across cases.
    setTokenColorMap({});
  });

  it("K0.5: does NOT report token fallback for paints the kit map actually resolves", () => {
    const scene = cloneScene();
    scene.nodes.node_token_card = tokenCardNode();
    scene.pages.page_a4.children = ["node_contact_name", "node_token_card"];

    // Without the map: the token paints are genuinely on the heuristic.
    const before = editorRenderDiagnostics(scene, "page_a4");
    expect(
      before.some(
        (diagnostic) =>
          diagnostic.code === "EDITOR_RENDER_TOKEN_FALLBACK" &&
          diagnostic.message.includes("paint token surface.card")
      )
    ).toBe(true);
    expect(
      before.some(
        (diagnostic) =>
          diagnostic.code === "EDITOR_RENDER_TOKEN_FALLBACK" &&
          diagnostic.message.includes("color token border.brand")
      )
    ).toBe(true);

    // With the attached kit's values loaded, the same paints render the real
    // colors — reporting "uses a local fallback color" would be false.
    setTokenColorMap({ "surface.card": "#ffffff", "border.brand": "#00525c" });
    const after = editorRenderDiagnostics(scene, "page_a4");
    expect(
      after.some(
        (diagnostic) =>
          diagnostic.code === "EDITOR_RENDER_TOKEN_FALLBACK" &&
          (diagnostic.message.includes("paint token surface.card") ||
            diagnostic.message.includes("color token border.brand"))
      )
    ).toBe(false);
    // Non-color token fallbacks (dimensions, typography) are untouched by the
    // color map and still report.
    expect(after.some((diagnostic) => diagnostic.message.includes("Token Card width"))).toBe(true);
  });

  it("reports canvas preview approximations for gradients, tokens, images, and text shaping", () => {
    const scene = cloneScene();
    scene.pages.page_a4.background = [
      {
        id: "page_gradient",
        paint: {
          kind: "linear_gradient",
          angle: 90,
          stops: [
            {
              color: {
                kind: "token",
                token: "surface.brand"
              },
              position: 0
            },
            {
              color: {
                kind: "hex",
                value: "#ffffff"
              },
              position: 1
            }
          ]
        }
      }
    ];

    scene.nodes.node_token_card = tokenCardNode();
    scene.nodes.node_logo = imageNode();
    scene.assets.asset_logo_demo = assetRecord("asset_logo_demo", "Demo Logo", "logo");
    scene.nodes.node_contact_name.kind = {
      kind: "text",
      content: "مرحبا",
      font_family: "Inter",
      font_size: 16,
      font_weight: 700,
      align: "left",
      direction: "rtl",
      line_height_token: "type.headline.line_height",
      letter_spacing_token: "type.headline.tracking",
      max_lines: 2,
      style_token: "type.headline"
    };
    scene.pages.page_a4.children = ["node_contact_name", "node_token_card", "node_logo"];

    const diagnostics = editorRenderDiagnostics(scene, "page_a4");

    expect(diagnostics.map((diagnostic) => diagnostic.code)).toEqual(
      expect.arrayContaining([
        "EDITOR_RENDER_GRADIENT_APPROXIMATION",
        "EDITOR_RENDER_TOKEN_FALLBACK",
        "EDITOR_RENDER_TEXT_CLAMP_APPROXIMATION",
        "EDITOR_RENDER_TEXT_SHAPING_APPROXIMATION"
      ])
    );
    expect(diagnostics.some((diagnostic) => diagnostic.message.includes("Token Card width"))).toBe(true);
    expect(diagnostics.some((diagnostic) => diagnostic.message.includes("line height uses unresolved token"))).toBe(true);
    expect(diagnostics.some((diagnostic) => diagnostic.message.includes("letter spacing uses unresolved token"))).toBe(true);
    expect(diagnostics.some((diagnostic) => diagnostic.message.includes("max_lines(2)"))).toBe(true);
    // Step 2: a ready image asset now renders real pixels, so it no longer
    // emits the placeholder advisory.
    expect(diagnostics.some((diagnostic) => diagnostic.code === "EDITOR_RENDER_IMAGE_PLACEHOLDER")).toBe(false);
  });

  it("does not warn about token dimensions after computed geometry is available", () => {
    const scene = cloneScene();
    const node = tokenCardNode();
    node.fills = [];
    node.strokes = [];
    node.corner.token = null;
    node.opacity_token = null;
    node.computed = {
      layout_bounds: {
        x: 24,
        y: 24,
        width: 320,
        height: 160
      },
      render_bounds: {
        x: 24,
        y: 24,
        width: 320,
        height: 160
      }
    };
    scene.nodes.node_token_card = node;
    scene.pages.page_a4.children = ["node_token_card"];

    const diagnostics = editorRenderDiagnostics(scene, "page_a4");

    expect(diagnostics).toEqual([]);
  });

  it("warns when auto-layout preview is using fallback geometry before preflight", () => {
    const scene = cloneScene();
    const node = tokenCardNode();
    node.kind = {
      kind: "auto_layout",
      direction: "column",
      wrap: false
    };
    node.size = {
      width: {
        kind: "fixed",
        value: 320
      },
      height: {
        kind: "fixed",
        value: 160
      }
    };
    node.fills = [];
    node.strokes = [];
    node.corner.token = null;
    node.opacity_token = null;
    node.layout = {
      gap: 12,
      padding: [16, 16, 16, 16],
      grow: 0,
      align_x: "start",
      align_y: "start"
    };
    scene.nodes.node_token_card = node;
    scene.pages.page_a4.children = ["node_token_card"];

    const diagnostics = editorRenderDiagnostics(scene, "page_a4");

    expect(diagnostics).toEqual([
      expect.objectContaining({
        severity: "warning",
        code: "EDITOR_RENDER_LAYOUT_PREFLIGHT_REQUIRED",
        message: expect.stringContaining("fallback geometry until preflight runs")
      })
    ]);
  });
});

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}

function tokenCardNode(): Node {
  return {
    id: "node_token_card",
    name: "Token Card",
    kind: {
      kind: "rect"
    },
    transform: {
      x: 24,
      y: 24,
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
      flip_x: false,
      flip_y: false
    },
    size: {
      width: {
        kind: "token",
        value: {
          token: "size.card.width"
        }
      },
      height: {
        kind: "fixed",
        value: 160
      }
    },
    children: [],
    fills: [
      {
        id: "fill_token",
        paint: {
          kind: "token",
          token: "surface.card"
        }
      }
    ],
    strokes: [
      {
        id: "stroke_token",
        paint: {
          kind: "solid",
          color: {
            kind: "token",
            token: "border.brand"
          }
        },
        width: 1,
        width_token: "stroke.width.sm"
      }
    ],
    corner: {
      top_left: 8,
      top_right: 8,
      bottom_right: 8,
      bottom_left: 8,
      token: "radius.card"
    },
    opacity: 1,
    opacity_token: "opacity.subtle",
    clip: false,
    layout: null,
    computed: null,
    locked: false
  };
}

function imageNode(): Node {
  return {
    id: "node_logo",
    name: "Account Logo",
    kind: {
      kind: "image",
      asset_id: "asset_logo_demo",
      alt: "Demo logo"
    },
    transform: {
      x: 24,
      y: 220,
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
      flip_x: false,
      flip_y: false
    },
    size: {
      width: {
        kind: "fixed",
        value: 96
      },
      height: {
        kind: "fixed",
        value: 48
      }
    },
    children: [],
    fills: [],
    strokes: [],
    corner: {
      top_left: 0,
      top_right: 0,
      bottom_right: 0,
      bottom_left: 0
    },
    opacity: 1,
    source_asset_id: "asset_logo_demo",
    clip: false,
    layout: null,
    computed: null,
    locked: false
  };
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
