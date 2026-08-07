import { describe, expect, it } from "vitest";
import type { Diagnostic } from "../contracts";
import { mergeStickyDiagnostics } from "../diagnosticsPolicy";

function diagnostic(code: string, message = code): Diagnostic {
  return {
    severity: "error",
    phase: "operation",
    code,
    message,
    subject: { kind: "document" },
    hint: null
  };
}

describe("mergeStickyDiagnostics", () => {
  const persistFailed = diagnostic("EDITOR_WASM_EDIT_PERSIST_FAILED");
  const cosmetic = diagnostic("EDITOR_PREFLIGHT_OK");

  it("carries a sticky error through an unrelated overwrite", () => {
    // The 2a-recorded race: a cosmetic flow replaces the list wholesale and
    // the "edits aren't saving" signal must survive it.
    expect(mergeStickyDiagnostics([persistFailed], [cosmetic])).toEqual([
      persistFailed,
      cosmetic
    ]);
  });

  it("carries a sticky error through a clear-to-empty write", () => {
    expect(mergeStickyDiagnostics([persistFailed], [])).toEqual([persistFailed]);
  });

  it("lets a fresh write of the same code supersede the sticky entry", () => {
    const fresher = diagnostic("EDITOR_WASM_EDIT_PERSIST_FAILED", "attempt 2 failed");
    expect(mergeStickyDiagnostics([persistFailed], [fresher])).toEqual([fresher]);
  });

  it("does not make non-sticky diagnostics survive", () => {
    expect(mergeStickyDiagnostics([cosmetic], [diagnostic("OTHER")])).toEqual([
      diagnostic("OTHER")
    ]);
  });

  it("carries multiple sticky codes independently", () => {
    const createFailed = diagnostic("EDITOR_DOCUMENT_CREATE_FAILED");
    expect(
      mergeStickyDiagnostics([persistFailed, createFailed], [cosmetic])
    ).toEqual([persistFailed, createFailed, cosmetic]);
  });
});
