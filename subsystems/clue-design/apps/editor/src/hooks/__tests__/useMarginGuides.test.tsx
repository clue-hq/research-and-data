import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useMarginGuides } from "../useMarginGuides";

const STORAGE_KEY = "lumen.editor.show-margin-guides";

describe("useMarginGuides", () => {
  afterEach(() => {
    window.localStorage.removeItem(STORAGE_KEY);
  });

  it("defaults to false", () => {
    const { result } = renderHook(() => useMarginGuides());
    expect(result.current.showMarginGuides).toBe(false);
  });

  it("toggle flips the value and persists it to localStorage", () => {
    const { result } = renderHook(() => useMarginGuides());

    act(() => result.current.toggleMarginGuides());
    expect(result.current.showMarginGuides).toBe(true);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("true");

    act(() => result.current.toggleMarginGuides());
    expect(result.current.showMarginGuides).toBe(false);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("false");
  });

  it("re-init reads a previously stored true value", () => {
    window.localStorage.setItem(STORAGE_KEY, "true");
    const { result } = renderHook(() => useMarginGuides());
    expect(result.current.showMarginGuides).toBe(true);
  });
});
