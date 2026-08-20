import { describe, expect, it } from "../../__tests__/vitest-shim";
import {
  angleFromPivot,
  handlePoint,
  normalizeAngle,
  resizeBox,
  rotatePoint,
  snapAngle,
  type Box
} from "../transformerMath";

const BOX: Box = { x: 0, y: 0, width: 100, height: 100 };

describe("transformer resize math (Wave 3 C3c)", () => {
  it("drags a corner, anchoring the opposite corner", () => {
    const out = resizeBox(BOX, "bottom-right", { x: 150, y: 120 });
    expect(out).toEqual({ x: 0, y: 0, width: 150, height: 120 });
  });

  it("drags the top-left, keeping the bottom-right fixed", () => {
    const out = resizeBox(BOX, "top-left", { x: 20, y: 30 });
    expect(out).toEqual({ x: 20, y: 30, width: 80, height: 70 });
    // Bottom-right corner unchanged.
    expect(out.x + out.width).toBe(100);
    expect(out.y + out.height).toBe(100);
  });

  it("an edge handle moves only one axis", () => {
    const out = resizeBox(BOX, "right", { x: 140, y: 9999 });
    expect(out).toEqual({ x: 0, y: 0, width: 140, height: 100 });
  });

  it("clamps to the minimum size without flipping (anchor stays put)", () => {
    const out = resizeBox(BOX, "right", { x: -50, y: 50 }, { minWidth: 2 });
    expect(out.x).toBe(0);
    expect(out.width).toBe(2);
  });

  it("aspect-locks a corner drag to the original ratio", () => {
    const wide: Box = { x: 0, y: 0, width: 100, height: 50 }; // ratio 2:1
    const out = resizeBox(wide, "bottom-right", { x: 200, y: 60 }, { aspectLocked: true });
    // Driven by the dominant (width) change, height follows the ratio.
    expect(out).toEqual({ x: 0, y: 0, width: 200, height: 100 });
  });

  it("resizes in the local frame under rotation, keeping the anchor fixed (BR)", () => {
    const box: Box = { x: 100, y: 100, width: 100, height: 100 };
    // pointer chosen so the local drag is (120, 80) under 90° rotation.
    const out = resizeBox(box, "bottom-right", { x: 20, y: 220 }, { rotation: 90 });
    expect(out.x).toBeCloseTo(100, 6);
    expect(out.y).toBeCloseTo(100, 6);
    expect(out.width).toBeCloseTo(120, 6);
    expect(out.height).toBeCloseTo(80, 6);
  });

  it("resizes under rotation from the top-left, keeping the rotated BR corner fixed", () => {
    const box: Box = { x: 100, y: 100, width: 100, height: 100 };
    const out = resizeBox(box, "top-left", { x: 70, y: 120 }, { rotation: 90 });
    expect(out.x).toBeCloseTo(70, 6);
    expect(out.y).toBeCloseTo(120, 6);
    expect(out.width).toBeCloseTo(80, 6);
    expect(out.height).toBeCloseTo(70, 6);
    // The rotated bottom-right corner (origin + R(90)·(w,h)) is preserved at (0,200).
    const br = rotatePoint({ x: out.width, y: out.height }, 90);
    expect(out.x + br.x).toBeCloseTo(0, 6);
    expect(out.y + br.y).toBeCloseTo(200, 6);
  });
});

describe("transformer rotate math", () => {
  it("computes the angle from a pivot to a pointer", () => {
    expect(angleFromPivot({ x: 0, y: 0 }, { x: 10, y: 0 })).toBeCloseTo(0, 6);
    expect(angleFromPivot({ x: 0, y: 0 }, { x: 0, y: 10 })).toBeCloseTo(90, 6); // y-down
    expect(angleFromPivot({ x: 0, y: 0 }, { x: -10, y: 0 })).toBeCloseTo(180, 6);
  });

  it("snaps angles to a step and normalizes", () => {
    expect(snapAngle(47, 15)).toBe(45);
    expect(snapAngle(8, 15)).toBe(15);
    expect(snapAngle(52, 0)).toBe(52); // step 0 = no snap
    expect(normalizeAngle(-90)).toBe(270);
    expect(normalizeAngle(450)).toBe(90);
  });
});

describe("handle placement", () => {
  it("places handles at box corners/edges and rotates them", () => {
    const box: Box = { x: 10, y: 20, width: 100, height: 60 };
    expect(handlePoint(box, "top-left")).toEqual({ x: 10, y: 20 });
    expect(handlePoint(box, "bottom-right")).toEqual({ x: 110, y: 80 });
    expect(handlePoint(box, "top")).toEqual({ x: 60, y: 20 });
    // Under 90° rotation the bottom-right corner swings about the origin.
    const rotated = handlePoint({ x: 0, y: 0, width: 100, height: 100 }, "bottom-right", 90);
    expect(rotated.x).toBeCloseTo(-100, 6);
    expect(rotated.y).toBeCloseTo(100, 6);
  });
});
