import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAgentInstructions } from "../useAgentInstructions";

describe("useAgentInstructions", () => {
  it("sends the trimmed draft with turns immediately; Save persists it", async () => {
    const saveRunner = vi.fn(async (_id: string, value: string | null) => value);
    const { result } = renderHook(() =>
      useAgentInstructions({
        activeDocumentId: "doc_1",
        initialInstructions: null,
        saveRunner
      })
    );

    act(() => result.current.setDraft("  Serif voice only.  "));
    // The turn payload value needs no save.
    expect(result.current.instructions).toBe("Serif voice only.");
    expect(result.current.isDirty).toBe(true);

    await act(async () => {
      await result.current.save();
    });
    expect(saveRunner).toHaveBeenCalledWith("doc_1", "Serif voice only.");
    expect(result.current.isDirty).toBe(false);
  });

  it("cannot save without a document, and auto-saves once the id appears", async () => {
    const saveRunner = vi.fn(async (_id: string, value: string | null) => value);
    const { result, rerender } = renderHook(
      ({ documentId }: { documentId: string | null }) =>
        useAgentInstructions({
          activeDocumentId: documentId,
          initialInstructions: null,
          saveRunner
        }),
      { initialProps: { documentId: null as string | null } }
    );

    act(() => result.current.setDraft("Keep CTAs short."));
    expect(result.current.canSave).toBe(false);
    await act(async () => {
      await result.current.save();
    });
    expect(saveRunner).not.toHaveBeenCalled();

    // The first Accept mints the document → dirty instructions self-persist.
    rerender({ documentId: "doc_new" });
    await act(async () => {});
    expect(saveRunner).toHaveBeenCalledWith("doc_new", "Keep CTAs short.");
  });

  it("keeps the draft and surfaces the error when saving fails", async () => {
    const saveRunner = vi.fn(async () => {
      throw new Error("network down");
    });
    const { result } = renderHook(() =>
      useAgentInstructions({
        activeDocumentId: "doc_1",
        initialInstructions: "Old value",
        saveRunner
      })
    );
    act(() => result.current.setDraft("New value"));
    await act(async () => {
      await result.current.save();
    });
    expect(result.current.saveError).toContain("network down");
    expect(result.current.draft).toBe("New value");
    expect(result.current.isDirty).toBe(true);
  });
});
