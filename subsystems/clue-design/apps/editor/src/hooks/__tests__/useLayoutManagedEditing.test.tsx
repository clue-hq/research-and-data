import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useLayoutManagedEditing } from "../useLayoutManagedEditing";

describe("useLayoutManagedEditing", () => {
  it("applies immediately and persists per change when a document exists", async () => {
    const saveRunner = vi.fn(async (_id: string, value: boolean) => value);
    const { result } = renderHook(() =>
      useLayoutManagedEditing({
        activeDocumentId: "doc_1",
        initialEnabled: false,
        saveRunner
      })
    );

    await act(async () => result.current.setEnabled(true));
    expect(result.current.enabled).toBe(true);
    expect(saveRunner).toHaveBeenCalledWith("doc_1", true);

    await act(async () => result.current.setEnabled(false));
    expect(result.current.enabled).toBe(false);
    expect(saveRunner).toHaveBeenLastCalledWith("doc_1", false);
  });

  it("stays local without a document, and auto-persists once the id appears", async () => {
    const saveRunner = vi.fn(async (_id: string, value: boolean) => value);
    const { result, rerender } = renderHook(
      ({ documentId }: { documentId: string | null }) =>
        useLayoutManagedEditing({
          activeDocumentId: documentId,
          initialEnabled: false,
          saveRunner
        }),
      { initialProps: { documentId: null as string | null } }
    );

    await act(async () => result.current.setEnabled(true));
    expect(result.current.enabled).toBe(true);
    expect(saveRunner).not.toHaveBeenCalled();

    // The first Accept mints the document → the non-default value self-persists.
    rerender({ documentId: "doc_new" });
    await act(async () => {});
    expect(saveRunner).toHaveBeenCalledWith("doc_new", true);
  });

  it("keeps governing the session when persistence fails (best-effort save)", async () => {
    const saveRunner = vi.fn(async () => {
      throw new Error("network down");
    });
    const { result } = renderHook(() =>
      useLayoutManagedEditing({
        activeDocumentId: "doc_1",
        initialEnabled: false,
        saveRunner
      })
    );

    await act(async () => result.current.setEnabled(true));
    expect(result.current.enabled).toBe(true);
    expect(saveRunner).toHaveBeenCalledWith("doc_1", true);
  });
});
