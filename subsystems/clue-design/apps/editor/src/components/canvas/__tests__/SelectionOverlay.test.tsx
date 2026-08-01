import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SelectionOverlay, focalFromScreenPoint } from "../SelectionOverlay";

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
        disabledReason="Selection is managed by an auto-layout parent."
      />
    );
    expect(container.querySelectorAll('[data-role="resize-handle"]')).toHaveLength(0);
    expect(container.querySelector('[data-role="rotate-handle"]')).toBeNull();
    expect(container.querySelector('[data-role="selection-box"]')).not.toBeNull();
    expect(container.querySelector('[data-role="disabled-handle-notice"]')?.textContent).toContain("auto-layout");
  });

  it("4c-C: shows resize handles but not the rotate handle when they're split", () => {
    const { container } = render(
      <SelectionOverlay
        selection={{ box: { x: 0, y: 0, width: 50, height: 50 }, rotation: 0 }}
        pageOrigin={pageOrigin}
        zoom={1}
        showHandles={false}
        showResizeHandles
        showRotateHandle={false}
      />
    );
    expect(container.querySelectorAll('[data-role="resize-handle"]')).toHaveLength(8);
    expect(container.querySelector('[data-role="rotate-handle"]')).toBeNull();
    // Handles are on, so the disabled-handle notice must not show even
    // though showHandles itself is false.
    expect(container.querySelector('[data-role="disabled-handle-notice"]')).toBeNull();
  });

  it("4c-C: showResizeHandles/showRotateHandle default to showHandles when omitted", () => {
    const { container } = render(
      <SelectionOverlay
        selection={{ box: { x: 0, y: 0, width: 50, height: 50 }, rotation: 0 }}
        pageOrigin={pageOrigin}
        zoom={1}
        showHandles={false}
        disabledReason="Selection is managed by an auto-layout parent."
      />
    );
    expect(container.querySelectorAll('[data-role="resize-handle"]')).toHaveLength(0);
    expect(container.querySelector('[data-role="rotate-handle"]')).toBeNull();
    expect(container.querySelector('[data-role="disabled-handle-notice"]')).not.toBeNull();
  });

  it("4c-C: draws a solid insertion-indicator line, mapped like a snap guide", () => {
    const { container } = render(
      <SelectionOverlay
        selection={null}
        pageOrigin={pageOrigin}
        zoom={2}
        insertionIndicator={{ axis: "y", position: 30, from: 0, to: 100 }}
      />
    );
    const indicator = container.querySelector('[data-role="reorder-insertion-indicator"]')!;
    expect(indicator).not.toBeNull();
    expect(indicator.getAttribute("data-axis")).toBe("y");
    expect(indicator.getAttribute("stroke-dasharray")).toBeNull();
    // axis "y" -> horizontal line at fixed y=30, spanning x from 0 to 100.
    // screen = pageOrigin + p * zoom.
    expect(Number(indicator.getAttribute("x1"))).toBeCloseTo(pageOrigin.x + 0 * 2, 6);
    expect(Number(indicator.getAttribute("y1"))).toBeCloseTo(pageOrigin.y + 30 * 2, 6);
    expect(Number(indicator.getAttribute("x2"))).toBeCloseTo(pageOrigin.x + 100 * 2, 6);
    expect(Number(indicator.getAttribute("y2"))).toBeCloseTo(pageOrigin.y + 30 * 2, 6);
  });

  it("4d: renders both safe-area and bleed margin guides mapped via toScreen", () => {
    const { container } = render(
      <SelectionOverlay
        selection={null}
        pageOrigin={pageOrigin}
        zoom={2}
        marginGuides={{
          safeArea: { x: 12, y: 12, width: 186, height: 273 },
          bleed: { x: -3, y: -3, width: 216, height: 303 }
        }}
      />
    );
    const safeArea = container.querySelector('[data-role="margin-guide-safe-area"]')!;
    expect(safeArea).not.toBeNull();
    expect(Number(safeArea.getAttribute("x"))).toBeCloseTo(pageOrigin.x + 12 * 2, 6);
    expect(Number(safeArea.getAttribute("y"))).toBeCloseTo(pageOrigin.y + 12 * 2, 6);
    expect(Number(safeArea.getAttribute("width"))).toBeCloseTo(186 * 2, 6);
    expect(Number(safeArea.getAttribute("height"))).toBeCloseTo(273 * 2, 6);
    expect(safeArea.getAttribute("stroke-dasharray")).toBe("4 3");

    const bleed = container.querySelector('[data-role="margin-guide-bleed"]')!;
    expect(bleed).not.toBeNull();
    expect(Number(bleed.getAttribute("x"))).toBeCloseTo(pageOrigin.x + -3 * 2, 6);
    expect(Number(bleed.getAttribute("y"))).toBeCloseTo(pageOrigin.y + -3 * 2, 6);
    expect(Number(bleed.getAttribute("width"))).toBeCloseTo(216 * 2, 6);
    expect(Number(bleed.getAttribute("height"))).toBeCloseTo(303 * 2, 6);
  });

  it("W3: renders the trim (page-box) guide when marginGuides carries one, colored via the trim token", () => {
    const { container } = render(
      <SelectionOverlay
        selection={null}
        pageOrigin={pageOrigin}
        zoom={2}
        marginGuides={{
          safeArea: { x: 12, y: 12, width: 186, height: 273 },
          bleed: { x: -3, y: -3, width: 216, height: 303 },
          trim: { x: 0, y: 0, width: 210, height: 297 }
        }}
      />
    );
    const trim = container.querySelector('[data-role="margin-guide-trim"]')!;
    expect(trim).not.toBeNull();
    expect(Number(trim.getAttribute("x"))).toBeCloseTo(pageOrigin.x + 0 * 2, 6);
    expect(Number(trim.getAttribute("width"))).toBeCloseTo(210 * 2, 6);
    expect(trim.getAttribute("stroke")).toBe("var(--guide-trim)");
    // Safe-area + bleed now read their tokens too.
    expect(container.querySelector('[data-role="margin-guide-safe-area"]')?.getAttribute("stroke")).toBe("var(--guide-safe)");
    expect(container.querySelector('[data-role="margin-guide-bleed"]')?.getAttribute("stroke")).toBe("var(--guide-bleed)");
  });

  it("W3: omits the trim guide when marginGuides has no trim (print feature off)", () => {
    const { container } = render(
      <SelectionOverlay
        selection={null}
        pageOrigin={pageOrigin}
        zoom={1}
        marginGuides={{ safeArea: { x: 12, y: 12, width: 186, height: 273 }, bleed: null }}
      />
    );
    expect(container.querySelector('[data-role="margin-guide-trim"]')).toBeNull();
    expect(container.querySelector('[data-role="margin-guide-safe-area"]')).not.toBeNull();
  });

  it("4d: renders neither margin guide when marginGuides is null", () => {
    const { container } = render(<SelectionOverlay selection={null} pageOrigin={pageOrigin} zoom={1} marginGuides={null} />);
    expect(container.querySelector('[data-role="margin-guide-safe-area"]')).toBeNull();
    expect(container.querySelector('[data-role="margin-guide-bleed"]')).toBeNull();
  });

  it("4d: renders only the safe-area guide when bleed is null", () => {
    const { container } = render(
      <SelectionOverlay
        selection={null}
        pageOrigin={pageOrigin}
        zoom={1}
        marginGuides={{ safeArea: { x: 12, y: 12, width: 186, height: 273 }, bleed: null }}
      />
    );
    expect(container.querySelector('[data-role="margin-guide-safe-area"]')).not.toBeNull();
    expect(container.querySelector('[data-role="margin-guide-bleed"]')).toBeNull();
  });

  it("draws hover chrome separately from selected chrome", () => {
    const { container } = render(
      <SelectionOverlay
        selection={{ box: { x: 0, y: 0, width: 50, height: 50 }, rotation: 0 }}
        hover={{ box: { x: 80, y: 10, width: 30, height: 30 }, rotation: 0 }}
        pageOrigin={pageOrigin}
        zoom={1}
      />
    );
    expect(container.querySelector('[data-role="selection-box"]')).not.toBeNull();
    expect(container.querySelector('[data-role="hover-box"]')).not.toBeNull();
  });

  it("draws a subtle slot-bound accent when slot keys exist", () => {
    const { container } = render(
      <SelectionOverlay
        selection={{ box: { x: 0, y: 0, width: 50, height: 50 }, rotation: 0 }}
        pageOrigin={pageOrigin}
        zoom={1}
        slotKeys={["contact.full_name", "contact.title"]}
      />
    );
    expect(container.querySelector('[data-role="slot-bound-accent"]')?.textContent).toContain("2 slots");
  });

  it("draws a diagnostics badge and warning/error stroke for selected issues", () => {
    const { container, rerender } = render(
      <SelectionOverlay
        selection={{ box: { x: 0, y: 0, width: 50, height: 50 }, rotation: 0 }}
        pageOrigin={pageOrigin}
        zoom={1}
        diagnosticCounts={{ errors: 0, warnings: 2 }}
      />
    );
    expect(container.querySelector('[data-role="diagnostic-badge"]')?.textContent).toContain("2");
    expect(container.querySelector('[data-role="selection-box"]')?.getAttribute("stroke")).toBe("#f59e0b");

    rerender(
      <SelectionOverlay
        selection={{ box: { x: 0, y: 0, width: 50, height: 50 }, rotation: 0 }}
        pageOrigin={pageOrigin}
        zoom={1}
        diagnosticCounts={{ errors: 1, warnings: 2 }}
      />
    );
    expect(container.querySelector('[data-role="diagnostic-badge"]')?.textContent).toContain("3");
    expect(container.querySelector('[data-role="selection-box"]')?.getAttribute("stroke")).toBe("#ef4444");
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

  it("draws a focal-point dot only when a focal + callback are provided (image nodes)", () => {
    const base = {
      selection: { box: { x: 0, y: 0, width: 100, height: 80 }, rotation: 0 },
      pageOrigin,
      zoom: 1
    } as const;
    const { container, rerender } = render(<SelectionOverlay {...base} />);
    expect(container.querySelector('[data-role="focal-point"]')).toBeNull();

    rerender(<SelectionOverlay {...base} focal={{ x: 0.5, y: 0.5 }} onFocalChange={vi.fn()} />);
    const dot = container.querySelector('[data-testid="focal-handle"]')!;
    // 0.5/0.5 focal of a 100×80 box at origin (0,0): center (50,40) → screen pageOrigin + center.
    expect(Number(dot.getAttribute("cx"))).toBeCloseTo(pageOrigin.x + 50, 6);
    expect(Number(dot.getAttribute("cy"))).toBeCloseTo(pageOrigin.y + 40, 6);
  });

  describe("(h) draw-the-box reveal chrome (S2.1)", () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    const cornerReveal = (seq: number, overrides = {}) => ({
      seq,
      flashBox: { x: 120, y: 90, width: 200, height: 60 },
      label: "text · headline",
      drawMode: "corner" as const,
      travelMs: 200,
      drawMs: 300,
      materializeFadeMs: 250,
      reducedMotion: false,
      cursorFrom: null,
      ...overrides
    });

    it("draws the outline top-left→bottom-right, riding the cursor to BR, then fades after materialize", () => {
      vi.useFakeTimers();
      const { container } = render(
        <SelectionOverlay selection={null} pageOrigin={pageOrigin} zoom={1} reveal={cornerReveal(5)} />
      );
      const group = () => container.querySelector('[data-role="agent-reveal"]') as HTMLElement;
      const box = () => container.querySelector('[data-role="agent-reveal-box"]') as HTMLElement;
      const cursor = () => container.querySelector('[data-role="agent-reveal-cursor"]') as HTMLElement;

      // The box lands on the revealed node's screen box (already px — no toScreen).
      expect(Number(box().getAttribute("x"))).toBe(120);
      expect(Number(box().getAttribute("width"))).toBe(200);
      // The per-element draw/fade durations feed CSS as vars on the group.
      expect(group().style.getPropertyValue("--reveal-draw-ms")).toBe("300ms");
      expect(group().style.getPropertyValue("--reveal-fade-ms")).toBe("250ms");
      // The label chip names the element.
      expect(container.querySelector(".agent-reveal-label-text")?.textContent).toBe("text · headline");
      expect(container.querySelector(".agent-reveal-cursor-glyph")).not.toBeNull();

      // travel stage: box collapsed (not drawn), cursor at the top-left.
      expect(group().getAttribute("data-stage")).toBe("travel");
      expect(box().classList.contains("is-drawn")).toBe(false);
      act(() => {
        vi.advanceTimersByTime(1); // the mount "glide" tick fires
      });
      expect(cursor().style.getPropertyValue("--reveal-cursor-x")).toBe("120px");
      expect(cursor().style.getPropertyValue("--reveal-cursor-ms")).toBe("200ms");

      // draw stage: box drags to full (is-drawn), cursor rides the bottom-right.
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(group().getAttribute("data-stage")).toBe("draw");
      expect(box().classList.contains("is-drawn")).toBe(true);
      expect(box().classList.contains("is-fading")).toBe(false);
      expect(cursor().style.getPropertyValue("--reveal-cursor-x")).toBe("320px"); // 120 + 200
      expect(cursor().style.getPropertyValue("--reveal-cursor-y")).toBe("150px"); // 90 + 60
      expect(cursor().style.getPropertyValue("--reveal-cursor-ms")).toBe("300ms");

      // materialize stage: the outline fades once the content has landed.
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(group().getAttribute("data-stage")).toBe("materialize");
      expect(box().classList.contains("is-fading")).toBe(true);
      // Never draws a selection box — reveal chrome is independent of selection.
      expect(container.querySelector('[data-role="selection-box"]')).toBeNull();
    });

    it("keys the chrome on seq so a new reveal restarts the draw machine", () => {
      vi.useFakeTimers();
      const { container, rerender } = render(
        <SelectionOverlay selection={null} pageOrigin={pageOrigin} zoom={1} reveal={cornerReveal(5)} />
      );
      act(() => {
        vi.advanceTimersByTime(600); // first reveal fully materialized
      });
      expect(
        container.querySelector('[data-role="agent-reveal"]')?.getAttribute("data-stage")
      ).toBe("materialize");

      rerender(
        <SelectionOverlay
          selection={null}
          pageOrigin={pageOrigin}
          zoom={1}
          reveal={cornerReveal(6, { flashBox: { x: 300, y: 200, width: 100, height: 40 } })}
        />
      );
      // The seq-keyed remount restarts at travel for the new element.
      expect(
        container.querySelector('[data-role="agent-reveal"]')?.getAttribute("data-stage")
      ).toBe("travel");
    });

    it("an add_page reveal renders a whole-artboard outline with no corner cursor", () => {
      vi.useFakeTimers();
      const { container } = render(
        <SelectionOverlay
          selection={null}
          pageOrigin={pageOrigin}
          zoom={1}
          reveal={cornerReveal(7, { drawMode: "artboard", label: "artboard · Page 1" })}
        />
      );
      const box = container.querySelector('[data-role="agent-reveal-box"]') as HTMLElement;
      expect(box.classList.contains("is-artboard")).toBe(true);
      expect(box.classList.contains("is-corner")).toBe(false);
      // No corner-drag cursor for a whole-artboard placeholder.
      expect(container.querySelector('[data-role="agent-reveal-cursor"]')).toBeNull();
    });

    it("reduced motion renders a static outline with no travel/draw stages", () => {
      const { container } = render(
        <SelectionOverlay
          selection={null}
          pageOrigin={pageOrigin}
          zoom={1}
          reveal={cornerReveal(8, { reducedMotion: true })}
        />
      );
      const group = container.querySelector('[data-role="agent-reveal"]') as HTMLElement;
      const box = container.querySelector('[data-role="agent-reveal-box"]') as HTMLElement;
      // No animated stages: straight to the settled, static outline.
      expect(group.getAttribute("data-stage")).toBe("materialize");
      expect(box.classList.contains("is-static")).toBe(true);
    });
  });

  it("renders no reveal chrome when reveal is null", () => {
    const { container } = render(
      <SelectionOverlay selection={null} pageOrigin={pageOrigin} zoom={1} reveal={null} />
    );
    expect(container.querySelector('[data-role="agent-reveal"]')).toBeNull();
  });
});

describe("focalFromScreenPoint", () => {
  const box = { x: 100, y: 50, width: 200, height: 100 };
  const origin = { x: 10, y: 20 };

  it("maps the box-center screen point to a 0.5/0.5 focal", () => {
    // descriptor center (200,100) → screen origin + center*zoom = (410,220)
    expect(focalFromScreenPoint({ x: 410, y: 220 }, box, origin, 2)).toEqual({ x: 0.5, y: 0.5 });
  });

  it("maps the box top-left screen point to 0/0", () => {
    expect(focalFromScreenPoint({ x: 210, y: 120 }, box, origin, 2)).toEqual({ x: 0, y: 0 });
  });

  it("clamps points outside the box to the 0..1 range", () => {
    expect(focalFromScreenPoint({ x: -1000, y: -1000 }, box, origin, 2)).toEqual({ x: 0, y: 0 });
    expect(focalFromScreenPoint({ x: 100000, y: 100000 }, box, origin, 2)).toEqual({ x: 1, y: 1 });
  });
});
