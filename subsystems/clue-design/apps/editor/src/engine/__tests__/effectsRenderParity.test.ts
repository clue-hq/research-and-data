import { describe, expect, it } from "vitest";
import type { Effect, Node, Page, Scene } from "../contracts";
import {
  konvaFillProps,
  konvaShadowProps,
  konvaStrokeProps,
  nodeDescriptor,
  paintDescriptor
} from "../renderAdapter";

/**
 * Effects Contract V0, slice X5: the Konva preview must render what the
 * SVG exporter renders for the V0 surface — real gradients (all stops, no
 * first-stop flattening), full painting order, dash/cap/join, and drop
 * shadows. These tests pin the descriptor mapping the canvas consumes.
 */

function pxPage(children: string[]): Page {
  return {
    id: "page_card",
    name: "Card",
    size: {
      width: 400,
      height: 300,
      unit: "px",
      preset: "custom",
      orientation: "landscape"
    },
    children,
    bleed: null,
    safe_area: null,
    background: []
  };
}

function cardNode(partial: Partial<Node>): Node {
  return {
    id: "card",
    name: null,
    kind: { kind: "rect" },
    transform: { x: 24, y: 24, rotation: 0, skew_x: 0, skew_y: 0, flip_x: false, flip_y: false },
    size: {
      width: { kind: "fixed", value: 200 },
      height: { kind: "fixed", value: 100 }
    },
    children: [],
    fills: [],
    strokes: [],
    corner: { top_left: 0, top_right: 0, bottom_right: 0, bottom_left: 0 },
    opacity: 1,
    clip: false,
    layout: null,
    computed: null,
    locked: false,
    ...partial
  };
}

function sceneWith(node: Node): Scene {
  return {
    schema_version: 1,
    meta: {
      id: "doc_fx_editor",
      title: "Effects Editor",
      artifact_type: null,
      medium: null,
      brand_kit: null,
      status: { kind: "draft" }
    },
    pages: { page_card: pxPage([node.id]) },
    nodes: { [node.id]: node },
    slots: {},
    assets: {},
    export_profiles: []
  };
}

function dropShadow(id: string, overrides: Partial<Effect["kind"]> = {}): Effect {
  return {
    id,
    kind: {
      kind: "drop_shadow",
      color: { kind: "hex", value: "#000000" },
      opacity: 0.18,
      x: 0,
      y: 8,
      blur: 24,
      spread: 0,
      ...overrides
    }
  };
}

describe("effects render parity (Konva descriptor)", () => {
  it("maps linear gradients with every stop in order, matching the SVG stop list", () => {
    const node = cardNode({
      fills: [
        {
          id: "fill_gradient",
          paint: {
            kind: "linear_gradient",
            angle: 90,
            stops: [
              { color: { kind: "hex", value: "#ffffff" }, position: 0 },
              { color: { kind: "hex", value: "#d8d1c3" }, position: 0.5 },
              { color: { kind: "hex", value: "#256c70" }, position: 1 }
            ]
          }
        }
      ]
    });
    const scene = sceneWith(node);
    const descriptor = nodeDescriptor(scene, node, scene.pages.page_card);

    expect(descriptor.fills).toHaveLength(1);
    const paint = descriptor.fills[0].paint;
    expect(paint.kind).toBe("linear_gradient");
    if (paint.kind !== "linear_gradient") {
      throw new Error("expected linear gradient");
    }
    // No first-stop flattening: all three stops survive in order.
    expect(paint.colorStops).toEqual([0, "#ffffff", 0.5, "#d8d1c3", 1, "#256c70"]);
    // 90deg rotates the unit gradient vector to point down the box.
    expect(paint.start).toEqual({ x: 0, y: 0 });
    expect(paint.end.x).toBeCloseTo(0, 5);
    expect(paint.end.y).toBeCloseTo(100, 5);
  });

  it("maps radial gradients from the box center", () => {
    const paint = paintDescriptor(
      {
        kind: "radial_gradient",
        stops: [
          { color: { kind: "hex", value: "#ffffff" }, position: 0 },
          { color: { kind: "hex", value: "#000000" }, position: 1 }
        ]
      },
      200,
      100
    );
    expect(paint).toEqual({
      kind: "radial_gradient",
      center: { x: 100, y: 50 },
      startRadius: 0,
      endRadius: 100,
      colorStops: [0, "#ffffff", 1, "#000000"]
    });
  });

  it("preserves painting order: fills bottom-to-top then strokes", () => {
    const node = cardNode({
      fills: [
        { id: "fill_base", paint: { kind: "solid", color: { kind: "hex", value: "#ffffff" } } },
        { id: "fill_tint", paint: { kind: "solid", color: { kind: "hex", value: "#f5f1e9" } } }
      ],
      strokes: [
        {
          id: "stroke_outer",
          paint: { kind: "solid", color: { kind: "hex", value: "#111827" } },
          width: 2
        },
        {
          id: "stroke_inner",
          paint: { kind: "solid", color: { kind: "hex", value: "#256c70" } },
          width: 1
        }
      ]
    });
    const scene = sceneWith(node);
    const descriptor = nodeDescriptor(scene, node, scene.pages.page_card);

    expect(descriptor.fills.map((layer) => layer.id)).toEqual(["fill_base", "fill_tint"]);
    expect(descriptor.strokes.map((layer) => layer.id)).toEqual(["stroke_outer", "stroke_inner"]);
  });

  it("maps dash, cap, and join to Konva stroke props", () => {
    const node = cardNode({
      strokes: [
        {
          id: "stroke_border",
          paint: { kind: "solid", color: { kind: "hex", value: "#111827" } },
          width: 1,
          dash: [6, 4],
          cap: "round",
          join: "bevel"
        }
      ]
    });
    const scene = sceneWith(node);
    const descriptor = nodeDescriptor(scene, node, scene.pages.page_card);
    const layer = descriptor.strokes[0];

    expect(layer.dash).toEqual([6, 4]);
    expect(layer.lineCap).toBe("round");
    expect(layer.lineJoin).toBe("bevel");

    expect(konvaStrokeProps(layer)).toEqual({
      stroke: "#111827",
      strokeWidth: 1,
      lineCap: "round",
      lineJoin: "bevel",
      dash: [6, 4]
    });
  });

  it("defaults cap and join when the Rust core omitted them", () => {
    const node = cardNode({
      strokes: [
        {
          id: "stroke_border",
          paint: { kind: "solid", color: { kind: "hex", value: "#111827" } },
          width: 1
        }
      ]
    });
    const scene = sceneWith(node);
    const layer = nodeDescriptor(scene, node, scene.pages.page_card).strokes[0];

    expect(layer.dash).toBeNull();
    expect(layer.lineCap).toBe("butt");
    expect(layer.lineJoin).toBe("miter");
  });

  it("maps the topmost drop shadow to Konva shadow props and counts the rest", () => {
    const node = cardNode({
      effects: [dropShadow("shadow_crisp", { y: 1, blur: 2 }), dropShadow("shadow_soft")]
    });
    const scene = sceneWith(node);
    const descriptor = nodeDescriptor(scene, node, scene.pages.page_card);

    expect(descriptor.shadow).toEqual({
      color: "#000000",
      opacity: 0.18,
      offsetX: 0,
      offsetY: 1,
      blur: 2,
      spreadApproximated: false
    });
    expect(descriptor.extraShadowCount).toBe(1);

    expect(konvaShadowProps(descriptor.shadow)).toEqual({
      shadowEnabled: true,
      shadowColor: "#000000",
      shadowOpacity: 0.18,
      shadowOffsetX: 0,
      shadowOffsetY: 1,
      shadowBlur: 2
    });
  });

  it("flags spread shadows as approximated", () => {
    const node = cardNode({ effects: [dropShadow("shadow_spread", { spread: 4 })] });
    const scene = sceneWith(node);
    const descriptor = nodeDescriptor(scene, node, scene.pages.page_card);
    expect(descriptor.shadow?.spreadApproximated).toBe(true);
  });

  it("emits no shadow props for nodes without effects", () => {
    const node = cardNode({});
    const scene = sceneWith(node);
    const descriptor = nodeDescriptor(scene, node, scene.pages.page_card);
    expect(descriptor.shadow).toBeNull();
    expect(konvaShadowProps(descriptor.shadow)).toEqual({});
  });

  it("scales stroke dash and shadow geometry into canvas units for mm pages", () => {
    const node = cardNode({
      strokes: [
        {
          id: "stroke_border",
          paint: { kind: "solid", color: { kind: "hex", value: "#111827" } },
          width: 1,
          dash: [6, 4]
        }
      ],
      effects: [dropShadow("shadow_soft")]
    });
    const scene = sceneWith(node);
    const mmPage: Page = {
      ...scene.pages.page_card,
      size: { ...scene.pages.page_card.size, unit: "mm" }
    };
    const descriptor = nodeDescriptor(scene, node, mmPage);
    const mmScale = 96 / 25.4;

    expect(descriptor.strokes[0].dash?.[0]).toBeCloseTo(6 * mmScale, 5);
    expect(descriptor.shadow?.offsetY).toBeCloseTo(8 * mmScale, 5);
    expect(descriptor.shadow?.blur).toBeCloseTo(24 * mmScale, 5);
  });

  it("maps gradient paints into Konva fill props", () => {
    expect(
      konvaFillProps({
        kind: "linear_gradient",
        start: { x: 0, y: 0 },
        end: { x: 200, y: 0 },
        colorStops: [0, "#ffffff", 1, "#000000"]
      })
    ).toEqual({
      fillLinearGradientStartPoint: { x: 0, y: 0 },
      fillLinearGradientEndPoint: { x: 200, y: 0 },
      fillLinearGradientColorStops: [0, "#ffffff", 1, "#000000"]
    });

    expect(
      konvaFillProps({
        kind: "radial_gradient",
        center: { x: 100, y: 50 },
        startRadius: 0,
        endRadius: 100,
        colorStops: [0, "#ffffff", 1, "#000000"]
      })
    ).toEqual({
      fillRadialGradientStartPoint: { x: 100, y: 50 },
      fillRadialGradientEndPoint: { x: 100, y: 50 },
      fillRadialGradientStartRadius: 0,
      fillRadialGradientEndRadius: 100,
      fillRadialGradientColorStops: [0, "#ffffff", 1, "#000000"]
    });
  });
});
