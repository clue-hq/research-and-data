import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SelectionOverlay } from "../SelectionOverlay";

const pageOrigin = { x: 100, y: 50 };

describe("SelectionOverlay (Wave 3 C3d)", () => {
  it("renders a selection box, 8 resize handles, and a rotate handle", () => {
    const { container } = render(
      <SelectionOverlay
        selection={{ box: { x: 10, y: 20, width: 100, height: 60 }, rotation: 0 }}
        pageOrigin={pageOrigin}
        zoom={2}
      />
    );
    expect(container.querySelectorAll('[data-role="resize-handle"]')).toHaveLength(8);
    expect(container.querySelector('[data-role="selection-box"]')).not.toBeNull();
    expect(container.querySelector('[data-role="rotate-handle"]')).not.toBeNull();

    // top-left handle maps to pageOrigin + box.topLeft × zoom = (100+10*2, 50+20*2) = (120, 90).
    const tl = container.querySelector('[data-handle="top-left"]')!;
    // handle is centered, drawn at center - size/2 (8/2=4).
    expect(Number(tl.getAttribute("x"))).toBeCloseTo(120 - 4, 6);
    expect(Number(tl.getAttribute("y"))).toBeCloseTo(90 - 4, 6);

    const br = container.querySelector('[data-handle="bottom-right"]')!;
    // (100 + (10+100)*2, 50 + (20+60)*2) = (320, 210)
    expect(Number(br.getAttribute("x"))).toBeCloseTo(320 - 4, 6);
    expect(Number(br.getAttribute("y"))).toBeCloseTo(210 - 4, 6);
  });

  it("hides handles for layout-managed selections but still outlines them", () => {
    const { container } = render(
      <SelectionOverlay
        selection={{ box: { x: 0, y: 0, width: 50, height: 50 }, rotation: 0 }}
        pageOrigin={pageOrigin}
        zoom={1}
        showHandles={false}
      />
    );
    expect(container.querySelectorAll('[data-role="resize-handle"]')).toHaveLength(0);
    expect(container.querySelector('[data-role="rotate-handle"]')).toBeNull();
    expect(container.querySelector('[data-role="selection-box"]')).not.toBeNull();
  });

  it("draws container child outlines and a label", () => {
    const { container } = render(
      <SelectionOverlay
        selection={{ box: { x: 0, y: 0, width: 200, height: 100 }, rotation: 0 }}
        containerChildren={[
          { x: 10, y: 10, width: 30, height: 20 },
          { x: 60, y: 40, width: 30, height: 20 }
        ]}
        containerLabel="Hero · 2 inside"
        pageOrigin={pageOrigin}
        zoom={1}
      />
    );
    expect(container.querySelectorAll('[data-role="container-child"]')).toHaveLength(2);
    expect(container.querySelector('[data-role="container-label"]')?.textContent).toContain("Hero");
  });

  it("draws the marquee rect", () => {
    const { container } = render(
      <SelectionOverlay
        selection={null}
        marquee={{ x: 5, y: 5, width: 40, height: 30 }}
        pageOrigin={pageOrigin}
        zoom={1}
      />
    );
    const marquee = container.querySelector('[data-role="marquee"]')!;
    expect(Number(marquee.getAttribute("width"))).toBe(40);
    expect(Number(marquee.getAttribute("x"))).toBe(105); // 100 + 5
  });
});
