import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SnapGuide } from "@/engine/canvasOperations";
import { SnapGuideLayer } from "../CanvasSurface";

/**
 * `react-konva` cannot mount for real in this project's jsdom suite (Konva's
 * Node entry does a bare `require("canvas")`, and that native package isn't
 * installed) — so, matching this codebase's existing convention of mocking
 * the Konva boundary (`EditorCanvas.test.tsx` mocks `CanvasSurface` /
 * `CanvasKitCanvas` the same way), `Group`/`Line` are replaced with plain DOM
 * pass-throughs that keep every non-function prop as a `data-*` attribute.
 */
vi.mock("react-konva", () => {
  const passthrough =
    (name: string) =>
    ({ children, ...rest }: Record<string, unknown>) => {
      const attrs: Record<string, unknown> = { "data-konva": name };
      for (const [key, value] of Object.entries(rest)) {
        if (typeof value !== "function") {
          attrs[`data-${key.toLowerCase()}`] = String(value);
        }
      }
      return <div {...attrs}>{children as never}</div>;
    };
  return {
    Group: passthrough("Group"),
    Line: passthrough("Line")
  };
});

describe("SnapGuideLayer (Konva fallback)", () => {
  it("renders nothing while no guide is engaged", () => {
    const { container } = render(<SnapGuideLayer guides={[]} unitScale={1} />);
    expect(container.querySelectorAll('[data-konva="Line"]')).toHaveLength(0);
  });

  it("renders a vertical line for an x-axis guide, scaled by unitScale", () => {
    const guides: SnapGuide[] = [{ axis: "x", position: 0, from: 40, to: 68 }];
    const { container } = render(<SnapGuideLayer guides={guides} unitScale={2} />);
    const lines = container.querySelectorAll('[data-konva="Line"]');
    expect(lines).toHaveLength(1);
    // points = [x, yFrom, x, yTo] scaled by unitScale=2.
    expect(lines[0].getAttribute("data-points")).toBe("0,80,0,136");
    expect(lines[0].getAttribute("data-stroke")).toBe("#f052cf");
  });

  it("renders a horizontal line for a y-axis guide", () => {
    const guides: SnapGuide[] = [{ axis: "y", position: 72, from: 69, to: 229 }];
    const { container } = render(<SnapGuideLayer guides={guides} unitScale={1} />);
    const lines = container.querySelectorAll('[data-konva="Line"]');
    expect(lines).toHaveLength(1);
    // points = [xFrom, y, xTo, y].
    expect(lines[0].getAttribute("data-points")).toBe("69,72,229,72");
  });

  it("renders one line per engaged guide when both axes snap at once", () => {
    const guides: SnapGuide[] = [
      { axis: "x", position: 72, from: 74, to: 102 },
      { axis: "y", position: 72, from: 69, to: 229 }
    ];
    const { container } = render(<SnapGuideLayer guides={guides} unitScale={1} />);
    expect(container.querySelectorAll('[data-konva="Line"]')).toHaveLength(2);
  });
});
