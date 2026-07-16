import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { usePrintFeature } from "../usePrintFeature";

const STORAGE_KEY = "lumen.editor.print-and-bleed";

describe("usePrintFeature", () => {
  afterEach(() => {
    window.localStorage.removeItem(STORAGE_KEY);
  });

  it("defaults to false (feature off per product decision D6)", () => {
    const { result } = renderHook(() => usePrintFeature());
    expect(result.current.printFeatureEnabled).toBe(false);
  });

  it("toggle flips the value and persists it to localStorage", () => {
    const { result } = renderHook(() => usePrintFeature());

    act(() => result.current.togglePrintFeature());
    expect(result.current.printFeatureEnabled).toBe(true);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("true");

    act(() => result.current.togglePrintFeature());
    expect(result.current.printFeatureEnabled).toBe(false);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("false");
  });

  it("re-init reads a previously stored true value", () => {
    window.localStorage.setItem(STORAGE_KEY, "true");
    const { result } = renderHook(() => usePrintFeature());
    expect(result.current.printFeatureEnabled).toBe(true);
  });
});
