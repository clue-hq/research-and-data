import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { AgentRunEvent, EditorAgentResult, EditorAgentRunner } from "@/engine/agentRunner";
import type { Operation, Scene } from "@/engine/contracts";
import type {
  EngineApplyOutcome,
  EngineStructuredEditOutcome,
  OptimisticEnginePort
} from "@/engine/wasmEngine";
import { updateDocumentTitle } from "@/engine/operations";
import { useAgentTurn, type UseAgentTurnDeps } from "../useAgentTurn";

// K1.6: the accept path re-measures the engine scene (kit-resolved fields)
// BEFORE building the freeze, so the bake never reads a skeleton-type solve.
// jsdom has no real CanvasKit; these mocks stand in for the loaded bundle and
// the measurement pass so the ordering seam is testable.
const K16_MEASUREMENT_MARKER = [{ content: "marker" }];
vi.mock("@/engine/canvaskit/loadCanvasKit", () => ({
  loadCanvasKit: vi.fn().mockResolvedValue({ ck: {}, fontProvider: {} })
}));
vi.mock("@/engine/canvaskit/skiaMeasurements", () => ({
  skiaMeasurements: vi.fn(() => K16_MEASUREMENT_MARKER)
}));

/**
 * Handoff-absolute (Accept seam): acceptAgentPreview merges the turn's own
 * ops with a `freeze_layout` bake into ONE commitAppliedOperations call —
 * one undo frame, one server checkpoint — per the coordinator's merge
 * design. These tests exercise that merge directly against a fake engine, so
 * they don't depend on the real WASM artifact being built.
 */

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}

/** A minimal fake engine: applyOperations just no-ops the scene through
 * (the preview path only needs `accepted: true` and a scene to hold), and
 * applyStructuredEdit is a test-controlled stub standing in for the real
 * `freeze_layout` outcome. */
function createFakeEngine(options: {
  freezeOutcome: EngineStructuredEditOutcome;
}): OptimisticEnginePort & { applyStructuredEdit: (edit: unknown) => EngineStructuredEditOutcome } {
  let scene = cloneScene();
  return {
    kind: "wasm",
    get scene() {
      return scene;
    },
    version: { schema_version: 1, engine_commit: "test", text_measurement: "heuristic" },
    reset(next: Scene) {
      scene = next;
    },
    applyOperations(operations: Operation[]): EngineApplyOutcome {
      // The preview path applies the turn's operations directly to the
      // fake scene by stamping the document title — good enough to prove
      // identity through the accept flow without a real solver.
      const titleOp = operations.find((op) => op.kind === "update_document");
      if (titleOp && titleOp.kind === "update_document" && titleOp.patch.title?.kind === "set") {
        scene = { ...scene, meta: { ...scene.meta, title: titleOp.patch.title.value } };
      }
      return {
        accepted: true,
        scene,
        diagnostics: [],
        inverseOperations: [updateDocumentTitle(cloneScene().meta.title)],
        appliedOperations: operations.length
      };
    },
    applyStructuredEdit() {
      if (options.freezeOutcome.accepted) {
        scene = options.freezeOutcome.scene;
      }
      return options.freezeOutcome;
    }
  };
}

function acceptedOutcome(scene: Scene, operations: Operation[] = []): EngineStructuredEditOutcome {
  return {
    accepted: true,
    scene,
    diagnostics: [],
    inverseOperations: operations.length > 0 ? [{ kind: "noop" } as unknown as Operation] : [],
    appliedOperations: operations.length,
    operations,
    edit: null
  };
}

function proposedResult(operations: Operation[]): EditorAgentResult {
  return {
    status: "proposed",
    summary: "Proposed a change.",
    dsl_blocks: [],
    operations,
    draft_scene: null,
    stop_reason: "edit_scoped_acceptance",
    acceptance_scope: "edit",
    diagnostics: [],
    trace: { run_id: "run_test", trace_dir: null, preview_paths: [] },
    artifacts: []
  };
}

function buildDeps(overrides: Partial<UseAgentTurnDeps> = {}): {
  deps: UseAgentTurnDeps;
  commitCalls: Array<{
    previousScene: Scene;
    operations: Operation[];
    nextScene: Scene;
    inverseOperations: Operation[] | null;
  }>;
} {
  const commitCalls: Array<{
    previousScene: Scene;
    operations: Operation[];
    nextScene: Scene;
    inverseOperations: Operation[] | null;
  }> = [];
  const deps: UseAgentTurnDeps = {
    agentRunner: vi.fn() as unknown as EditorAgentRunner,
    engineRef: { current: null },
    scene: cloneScene(),
    activeDocumentId: null,
    activePageId: "page_a4",
    selectedNodeId: null,
    targetNodeIds: [],
    agentInstructions: null,
    layoutManagedEditing: false,
    // K1.6(b): default the server bake to "declined" so the existing tests
    // exercise the client-side fallback deterministically; the server-bake
    // tests inject a fake result explicitly.
    acceptBakeRunner: async () => null,
    diagnostics: [],
    setDiagnostics: vi.fn(),
    setScene: vi.fn(),
    replaceScene: vi.fn(),
    setActivePageId: vi.fn(),
    setSelectedNodeId: vi.fn(),
    setUndoStack: vi.fn(),
    setRedoStack: vi.fn(),
    setBrandCompatibilityReport: vi.fn(),
    setPreflightResult: vi.fn(),
    setExportResult: vi.fn(),
    setWorkspaceMode: vi.fn(),
    commitAppliedOperations: vi.fn<UseAgentTurnDeps["commitAppliedOperations"]>(
      (previousScene, operations, nextScene, _persistOptions, inverseOperations) => {
        commitCalls.push({
          previousScene,
          operations,
          nextScene,
          inverseOperations: inverseOperations ?? null
        });
        return "persisted";
      }
    ),
    runExportForScene: vi.fn().mockResolvedValue(undefined),
    applyOperations: vi.fn(),
    ...overrides
  };
  return { deps, commitCalls };
}

describe("useAgentTurn — accept-time freeze merge (handoff-absolute)", () => {
  it("merges a non-empty freeze outcome into the SAME commitAppliedOperations call as the turn's ops", async () => {
    const turnOps = [updateDocumentTitle("Agent Authored Ad")];
    const agentRunner = vi.fn().mockResolvedValue(proposedResult(turnOps));
    const frozenScene = { ...cloneScene(), meta: { ...cloneScene().meta, title: "Agent Authored Ad" } };
    // A marker op/inverse distinguishable from the turn's own update_document
    // ops, so the merge order assertion below is unambiguous.
    const freezeOp = { kind: "freeze_marker" } as unknown as Operation;
    const freezeInverse = { kind: "unfreeze_marker" } as unknown as Operation;
    const engine = createFakeEngine({
      freezeOutcome: {
        accepted: true,
        scene: frozenScene,
        diagnostics: [],
        inverseOperations: [freezeInverse],
        appliedOperations: 1,
        operations: [freezeOp],
        edit: {
          kind: "freeze_layout",
          touched_targets: [],
          intent: "freeze_layout",
          checkpoint_label: null,
          inverse_operations: [freezeInverse],
          lineage: null
        }
      }
    });
    const { deps, commitCalls } = buildDeps({
      agentRunner,
      engineRef: { current: engine }
    });

    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      await result.current.sendAgentPrompt("Make it punchier.");
    });
    await waitFor(() => expect(result.current.agentPreview).not.toBeNull());

    await act(async () => {
      await result.current.acceptAgentPreview();
    });

    // Exactly one commit call for the whole accept — not two.
    expect(commitCalls).toHaveLength(1);
    const call = commitCalls[0];
    // Merged operations: turn ops first, then the freeze's op appended.
    expect(call.operations).toEqual([...turnOps, freezeOp]);
    // Merged inverses: freeze's inverse FIRST (undo peels the freeze off
    // before the turn's content, per the coordinator's ordering spec).
    expect(call.inverseOperations?.[0]).toEqual(freezeInverse);
    expect(call.inverseOperations).toHaveLength(2);
    // The merged frame lands against the frozen scene.
    expect(call.nextScene).toBe(frozenScene);
  });

  it("K1.6(b): a successful server bake supplies scene + ops and SKIPS the client freeze", async () => {
    const turnOps = [updateDocumentTitle("Agent Authored Ad")];
    const agentRunner = vi.fn().mockResolvedValue(proposedResult(turnOps));
    const bakedScene = {
      ...cloneScene(),
      meta: { ...cloneScene().meta, title: "Agent Authored Ad" }
    };
    const resolutionOp = { kind: "resolution_marker" } as unknown as Operation;
    const freezeOp = { kind: "freeze_marker" } as unknown as Operation;
    const freezeInverse = { kind: "unfreeze_marker" } as unknown as Operation;
    const engine = createFakeEngine({
      freezeOutcome: acceptedOutcome(cloneScene(), [])
    });
    const clientFreeze = vi.spyOn(engine, "applyStructuredEdit");
    const resetCalls: Scene[] = [];
    const baseReset = engine.reset.bind(engine);
    engine.reset = (next: Scene) => {
      resetCalls.push(next);
      baseReset(next);
    };
    const acceptBakeRunner = vi.fn().mockResolvedValue({
      scene: bakedScene,
      resolutionOperations: [resolutionOp],
      freezeOperations: [freezeOp],
      freezeInverseOperations: [freezeInverse]
    });
    const { deps, commitCalls } = buildDeps({
      agentRunner,
      engineRef: { current: engine },
      acceptBakeRunner
    });

    const { result } = renderHook(() => useAgentTurn(deps));
    await act(async () => {
      await result.current.sendAgentPrompt("Make it punchier.");
    });
    await waitFor(() => expect(result.current.agentPreview).not.toBeNull());
    await act(async () => {
      await result.current.acceptAgentPreview();
    });

    // The server bake got the accepted scene; the engine displays its result;
    // the client-side freeze never ran.
    expect(acceptBakeRunner).toHaveBeenCalledTimes(1);
    expect(resetCalls).toEqual([bakedScene]);
    expect(clientFreeze).not.toHaveBeenCalled();
    // One commit: turn ops, then resolution ops, then freeze ops; inverses
    // lead with the freeze inverse.
    expect(commitCalls).toHaveLength(1);
    expect(commitCalls[0].operations).toEqual([...turnOps, resolutionOp, freezeOp]);
    expect(commitCalls[0].inverseOperations?.[0]).toEqual(freezeInverse);
    expect(commitCalls[0].nextScene).toBe(bakedScene);
  });

  it("K1.6(b): a throwing bake runner falls back to the client-side freeze", async () => {
    const turnOps = [updateDocumentTitle("Agent Authored Ad")];
    const agentRunner = vi.fn().mockResolvedValue(proposedResult(turnOps));
    const freezeOp = { kind: "freeze_marker" } as unknown as Operation;
    const engine = createFakeEngine({
      freezeOutcome: acceptedOutcome(cloneScene(), [freezeOp])
    });
    const clientFreeze = vi.spyOn(engine, "applyStructuredEdit");
    const { deps, commitCalls } = buildDeps({
      agentRunner,
      engineRef: { current: engine },
      acceptBakeRunner: vi.fn().mockRejectedValue(new Error("api down"))
    });

    const { result } = renderHook(() => useAgentTurn(deps));
    await act(async () => {
      await result.current.sendAgentPrompt("Make it punchier.");
    });
    await waitFor(() => expect(result.current.agentPreview).not.toBeNull());
    await act(async () => {
      await result.current.acceptAgentPreview();
    });

    expect(clientFreeze).toHaveBeenCalledTimes(1);
    expect(commitCalls).toHaveLength(1);
    expect(commitCalls[0].operations).toEqual([...turnOps, freezeOp]);
  });

  it("K1.6: re-measures the engine scene BEFORE building the freeze (bake sees resolved type)", async () => {
    const turnOps = [updateDocumentTitle("Agent Authored Ad")];
    const agentRunner = vi.fn().mockResolvedValue(proposedResult(turnOps));
    const callOrder: string[] = [];
    const base = createFakeEngine({
      freezeOutcome: acceptedOutcome(cloneScene(), [])
    });
    const baseFreeze = base.applyStructuredEdit.bind(base);
    const engine = Object.create(base, {
      setMeasurements: {
        value: (measurements: unknown) => {
          callOrder.push("setMeasurements");
          expect(measurements).toBe(K16_MEASUREMENT_MARKER);
        }
      },
      applyStructuredEdit: {
        value: (edit: unknown) => {
          callOrder.push("applyStructuredEdit");
          return baseFreeze(edit);
        }
      }
    });
    const { deps } = buildDeps({ agentRunner, engineRef: { current: engine } });

    const { result } = renderHook(() => useAgentTurn(deps));
    await act(async () => {
      await result.current.sendAgentPrompt("Make it punchier.");
    });
    await waitFor(() => expect(result.current.agentPreview).not.toBeNull());
    await act(async () => {
      await result.current.acceptAgentPreview();
    });

    // The measurement injection (which relayouts) must precede the freeze —
    // a freeze from a stale solve bakes pre-resolution container heights
    // (the LUMV0801 headline/subtitle overlap from the K1.5 live proof).
    expect(callOrder).toEqual(["setMeasurements", "applyStructuredEdit"]);
  });

  it("skips the freeze entirely when layout-managed editing is enabled (advanced opt-out)", async () => {
    const turnOps = [updateDocumentTitle("Agent Authored Ad")];
    const agentRunner = vi.fn().mockResolvedValue(proposedResult(turnOps));
    const freezeOp = { kind: "freeze_marker" } as unknown as Operation;
    const engine = createFakeEngine({
      freezeOutcome: acceptedOutcome(cloneScene(), [freezeOp])
    });
    const applyStructuredEdit = vi.spyOn(engine, "applyStructuredEdit");
    const { deps, commitCalls } = buildDeps({
      agentRunner,
      engineRef: { current: engine },
      layoutManagedEditing: true
    });

    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      await result.current.sendAgentPrompt("Make it punchier.");
    });
    await waitFor(() => expect(result.current.agentPreview).not.toBeNull());

    await act(async () => {
      await result.current.acceptAgentPreview();
    });

    // The engine's freeze path is never consulted, and the committed batch is
    // exactly the turn's own ops — the Stack containers stay live.
    expect(applyStructuredEdit).not.toHaveBeenCalled();
    expect(commitCalls).toHaveLength(1);
    expect(commitCalls[0].operations).toEqual(turnOps);
  });

  it("does not merge anything when the freeze outcome is empty (already frozen / nothing to freeze)", async () => {
    const turnOps = [updateDocumentTitle("Agent Authored Ad")];
    const agentRunner = vi.fn().mockResolvedValue(proposedResult(turnOps));
    const engine = createFakeEngine({
      freezeOutcome: acceptedOutcome(cloneScene(), [])
    });
    const { deps, commitCalls } = buildDeps({
      agentRunner,
      engineRef: { current: engine }
    });

    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      await result.current.sendAgentPrompt("Make it punchier.");
    });
    await waitFor(() => expect(result.current.agentPreview).not.toBeNull());

    await act(async () => {
      await result.current.acceptAgentPreview();
    });

    expect(commitCalls).toHaveLength(1);
    // Merged operations equal the turn's own ops verbatim — no freeze noop
    // appended when there is nothing to freeze.
    expect(commitCalls[0].operations).toEqual(turnOps);
  });

  it("reports the turn's own operation count in the acceptance chat message, not the merged count", async () => {
    const turnOps = [updateDocumentTitle("Agent Authored Ad")];
    const agentRunner = vi.fn().mockResolvedValue(proposedResult(turnOps));
    const frozenScene = { ...cloneScene(), meta: { ...cloneScene().meta, title: "Agent Authored Ad" } };
    const engine = createFakeEngine({
      freezeOutcome: acceptedOutcome(frozenScene, [{ kind: "noop" } as unknown as Operation])
    });
    const { deps } = buildDeps({ agentRunner, engineRef: { current: engine } });

    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      await result.current.sendAgentPrompt("Make it punchier.");
    });
    await waitFor(() => expect(result.current.agentPreview).not.toBeNull());

    await act(async () => {
      await result.current.acceptAgentPreview();
    });

    const acceptedMessage = result.current.agentMessages.find((message) =>
      message.content.startsWith("Accepted")
    );
    expect(acceptedMessage?.content).toContain("Accepted 1 agent change.");
    expect(acceptedMessage?.turn?.operationCount).toBe(1);
  });
});

describe("useAgentTurn — RC turn references", () => {
  const reference = (n: number) => ({
    assetId: `asset_ref_${n}`,
    label: `ref-${n}.png`,
    thumbnailUrl: `http://api.test/assets/asset_ref_${n}/thumbnail`
  });

  it("attachReferences uploads each file and adds pending references", async () => {
    const uploader = vi.fn(async (file: File) => ({
      assetId: `asset_${file.name}`,
      label: file.name,
      thumbnailUrl: `http://api.test/assets/asset_${file.name}/thumbnail`
    }));
    const { deps } = buildDeps({ referenceUploader: uploader });
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      await result.current.attachReferences([
        new File(["a"], "wash-a.png", { type: "image/png" }),
        new File(["b"], "wash-b.png", { type: "image/png" })
      ]);
    });

    expect(uploader).toHaveBeenCalledTimes(2);
    expect(result.current.pendingReferences.map((ref) => ref.assetId)).toEqual([
      "asset_wash-a.png",
      "asset_wash-b.png"
    ]);
    expect(result.current.isUploadingReferences).toBe(false);
  });

  it("enforces the 4-reference cap and dedupes by asset id", async () => {
    const uploader = vi.fn(async (file: File) => ({
      assetId: `asset_${file.name}`,
      label: file.name,
      thumbnailUrl: "http://api.test/thumb"
    }));
    const { deps } = buildDeps({ referenceUploader: uploader });
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      await result.current.attachReferences([
        new File(["1"], "r1.png", { type: "image/png" }),
        new File(["2"], "r2.png", { type: "image/png" }),
        new File(["3"], "r3.png", { type: "image/png" }),
        new File(["4"], "r4.png", { type: "image/png" }),
        new File(["5"], "r5.png", { type: "image/png" })
      ]);
    });
    // Only 4 uploaded; the 5th was dropped with a system note.
    expect(uploader).toHaveBeenCalledTimes(4);
    expect(result.current.pendingReferences).toHaveLength(4);
    expect(
      result.current.agentMessages.some(
        (message) => message.role === "system" && message.content.includes("at most 4")
      )
    ).toBe(true);

    // A duplicate upload result (digest-dedup'd asset id) is not re-added.
    await act(async () => {
      await result.current.removeReference("asset_r4.png");
      await result.current.attachReferences([new File(["3"], "r3.png", { type: "image/png" })]);
      await result.current.attachReferences([new File(["3"], "r3.png", { type: "image/png" })]);
    });
    expect(
      result.current.pendingReferences.filter((ref) => ref.assetId === "asset_r3.png")
    ).toHaveLength(1);
  });

  it("threads reference ids into the runner payload, records attachments, and clears after a successful send", async () => {
    const agentRunner = vi.fn().mockResolvedValue(proposedResult([]));
    const { deps } = buildDeps({
      agentRunner,
      referenceUploader: async () => reference(1)
    });
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      await result.current.attachReferences([new File(["x"], "r.png", { type: "image/png" })]);
    });
    expect(result.current.pendingReferences).toHaveLength(1);

    await act(async () => {
      await result.current.sendAgentPrompt("Match this style.");
    });

    expect(agentRunner).toHaveBeenCalledWith(
      expect.objectContaining({ referenceAssetIds: ["asset_ref_1"] })
    );
    // Per-turn semantics (D8): consumed by the send.
    expect(result.current.pendingReferences).toEqual([]);
    // The transcript records what rode the turn.
    const userMessage = result.current.agentMessages.find((message) => message.role === "user");
    expect(userMessage?.attachments).toEqual([{ assetId: "asset_ref_1", label: "ref-1.png" }]);
  });

  it("a QUEUED message owns its enqueue-time references: drained send carries them, composer is consumed (ship-blocker 2)", async () => {
    // Slow first turn so the second message gets queued while busy.
    let releaseFirstTurn: (value: ReturnType<typeof proposedResult>) => void = () => {};
    const agentRunner = vi
      .fn()
      .mockImplementationOnce(
        () => new Promise((resolve) => (releaseFirstTurn = () => resolve(proposedResult([]))))
      )
      .mockResolvedValue(proposedResult([]));
    let uploadCount = 0;
    const { deps } = buildDeps({
      agentRunner,
      referenceUploader: async () => reference(++uploadCount)
    });
    const { result } = renderHook(() => useAgentTurn(deps));

    // Turn 1: no references, starts and stays busy.
    await act(async () => {
      void result.current.sendAgentPrompt("First turn.");
    });
    expect(result.current.isAgentRunning).toBe(true);

    // While busy: attach a reference and QUEUE a message for it.
    await act(async () => {
      await result.current.attachReferences([new File(["q"], "q.png", { type: "image/png" })]);
    });
    act(() => {
      result.current.queueAgentMessage("Match the attached style.");
    });
    // The queued message consumed the composer's pending references.
    expect(result.current.pendingReferences).toEqual([]);
    expect(result.current.queuedAgentMessages[0]?.references?.map((r) => r.assetId)).toEqual([
      "asset_ref_1"
    ]);

    // Turn 1 finishes (its success-clear must NOT touch the queued snapshot);
    // the drain effect sends the queued message.
    await act(async () => {
      releaseFirstTurn(proposedResult([]));
    });
    await act(async () => {});
    expect(agentRunner).toHaveBeenLastCalledWith(
      expect.objectContaining({ referenceAssetIds: ["asset_ref_1"] })
    );
  });

  it("success-clear is id-scoped: a reference attached mid-flight for the NEXT message survives the running turn", async () => {
    let releaseFirstTurn: (value: ReturnType<typeof proposedResult>) => void = () => {};
    const agentRunner = vi
      .fn()
      .mockImplementationOnce(
        () => new Promise((resolve) => (releaseFirstTurn = () => resolve(proposedResult([]))))
      )
      .mockResolvedValue(proposedResult([]));
    let uploadCount = 0;
    const { deps } = buildDeps({
      agentRunner,
      referenceUploader: async () => reference(++uploadCount)
    });
    const { result } = renderHook(() => useAgentTurn(deps));

    // Attach ref-1 and send turn 1 with it (stays busy).
    await act(async () => {
      await result.current.attachReferences([new File(["a"], "a.png", { type: "image/png" })]);
    });
    await act(async () => {
      void result.current.sendAgentPrompt("Turn with ref 1.");
    });
    expect(result.current.isAgentRunning).toBe(true);

    // Mid-flight: attach ref-2 intended for the NEXT message.
    await act(async () => {
      await result.current.attachReferences([new File(["b"], "b.png", { type: "image/png" })]);
    });

    // Turn 1 completes: only ref-1 (which rode the turn) is consumed.
    await act(async () => {
      releaseFirstTurn(proposedResult([]));
    });
    expect(result.current.pendingReferences.map((r) => r.assetId)).toEqual(["asset_ref_2"]);
  });

  it("keeps pending references when the send fails, so the user can retry", async () => {
    const agentRunner = vi.fn().mockRejectedValue(new Error("api down"));
    const { deps } = buildDeps({
      agentRunner,
      referenceUploader: async () => reference(2)
    });
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      await result.current.attachReferences([new File(["x"], "r.png", { type: "image/png" })]);
      await result.current.sendAgentPrompt("Match this style.");
    });

    expect(result.current.pendingReferences.map((ref) => ref.assetId)).toEqual(["asset_ref_2"]);
  });

  it("surfaces an upload failure as a system message without blocking other files", async () => {
    const uploader = vi
      .fn<(file: File) => Promise<{ assetId: string; label: string; thumbnailUrl: string }>>()
      .mockRejectedValueOnce(new Error("413 too large"))
      .mockResolvedValueOnce(reference(3));
    const { deps } = buildDeps({ referenceUploader: uploader });
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      await result.current.attachReferences([
        new File(["big"], "huge.png", { type: "image/png" }),
        new File(["ok"], "fine.png", { type: "image/png" })
      ]);
    });

    expect(result.current.pendingReferences.map((ref) => ref.assetId)).toEqual(["asset_ref_3"]);
    expect(
      result.current.agentMessages.some(
        (message) =>
          message.role === "system" && message.content.includes("Could not attach huge.png")
      )
    ).toBe(true);
  });
});

describe("useAgentTurn — live design streaming (D3)", () => {
  // A streamed batch is an ordinary op; `id` is a marker the fake engine joins
  // into scene.meta.title so cumulative application is observable. `boom` makes
  // the engine throw, standing in for a batch the engine rejects. `stream_marker`
  // is a kind previewAgentProposal's page picker ignores (no parent access).
  const streamOp = (id: string) => ({ kind: "stream_marker", id }) as unknown as Operation;

  /** An engine that records every applyOperations call and builds scene.meta.title
   * by appending each op's marker cumulatively — so "streamed cumulatively" and
   * "canonical from base" produce the SAME title iff no state leaks. */
  function createStreamEngine(): OptimisticEnginePort & { applyLog: Operation[][] } {
    const start = cloneScene();
    start.meta = { ...start.meta, title: "" };
    let scene: Scene = start;
    const applyLog: Operation[][] = [];
    return {
      kind: "wasm",
      applyLog,
      get scene() {
        return scene;
      },
      version: { schema_version: 1, engine_commit: "test", text_measurement: "heuristic" },
      reset(next: Scene) {
        scene = next;
      },
      applyOperations(operations: Operation[]): EngineApplyOutcome {
        applyLog.push(operations);
        const markers = operations.map((op) => {
          const id = (op as unknown as { id?: string }).id;
          if (id === "boom") {
            throw new Error("engine boom");
          }
          return id ?? op.kind;
        });
        const prev = scene.meta.title ? scene.meta.title.split(",") : [];
        scene = { ...scene, meta: { ...scene.meta, title: [...prev, ...markers].join(",") } };
        return {
          accepted: true,
          scene,
          diagnostics: [],
          inverseOperations: [],
          appliedOperations: operations.length
        };
      }
    };
  }

  /** A runner that captures the hook's onEvent so the test drives batches, and
   * hands back a promise the test settles (resolve = done, reject = failure). */
  function controllableRunner() {
    let capturedOnEvent: ((event: AgentRunEvent) => void) | undefined;
    let resolveRun!: (result: EditorAgentResult) => void;
    let rejectRun!: (error: unknown) => void;
    const runner = vi.fn((request: { onEvent?: (event: AgentRunEvent) => void }) => {
      capturedOnEvent = request.onEvent;
      return new Promise<EditorAgentResult>((resolve, reject) => {
        resolveRun = resolve;
        rejectRun = reject;
      });
    }) as unknown as EditorAgentRunner;
    return {
      runner,
      emit: (event: AgentRunEvent) => capturedOnEvent?.(event),
      resolve: (result: EditorAgentResult) => resolveRun(result),
      reject: (error: unknown) => rejectRun(error)
    };
  }

  const compileEvent = (seq: number, operations: unknown): AgentRunEvent => ({
    seq,
    type: "dsl_compiled",
    data: { iteration: 1, operations } as AgentRunEvent["data"]
  });

  it("(a) a progress event carrying operations updates the scene (engine applies the batch, setScene gets the result)", async () => {
    const op1 = streamOp("n1");
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const setSceneMock = deps.setScene as unknown as ReturnType<typeof vi.fn>;
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(1, [op1]));
    });

    expect(engine.applyLog).toContainEqual([op1]);
    const scenes = setSceneMock.mock.calls.map((call) => call[0] as Scene);
    expect(scenes.some((scene) => scene?.meta?.title === "n1")).toBe(true);
  });

  it("(b) applies batches cumulatively in seq order, exposes streaming status, and ignores a duplicate seq", async () => {
    const op1 = streamOp("n1");
    const op2 = streamOp("n2");
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    expect(result.current.agentStream.active).toBe(true);

    act(() => {
      ctl.emit(compileEvent(1, [op1]));
    });
    expect(result.current.agentStream).toMatchObject({
      active: true,
      lastAppliedSeq: 1,
      batchesApplied: 1,
      brokenStream: false
    });
    expect(result.current.agentStream.latestBatch).toEqual({ seq: 1, operations: [op1] });

    act(() => {
      ctl.emit(compileEvent(2, [op2]));
    });
    // A replayed (duplicate) seq must not re-apply.
    act(() => {
      ctl.emit(compileEvent(2, [op2]));
    });

    expect(result.current.agentStream.lastAppliedSeq).toBe(2);
    expect(result.current.agentStream.batchesApplied).toBe(2);
    expect(engine.scene.meta.title).toBe("n1,n2");
    expect(engine.applyLog).toEqual([[op1], [op2]]);

    await act(async () => {
      ctl.resolve(proposedResult([op1, op2]));
    });
    // Status returns to idle once the turn settles.
    expect(result.current.agentStream.active).toBe(false);
  });

  it("(c) malformed or absent operations apply nothing and never crash the stream", async () => {
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(1, "not-an-array"));
    });
    act(() => {
      ctl.emit(compileEvent(2, [42, "x", null]));
    });
    act(() => {
      ctl.emit(compileEvent(3, []));
    });

    expect(engine.applyLog).toEqual([]);
    expect(result.current.agentStream).toMatchObject({
      active: true,
      batchesApplied: 0,
      brokenStream: false
    });
  });

  it("(d) a batch the engine throws on marks the stream broken, skips later batches, and the turn still completes", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const op1 = streamOp("n1");
    const boom = streamOp("boom");
    const op3 = streamOp("n3");
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(1, [op1]));
    });
    act(() => {
      ctl.emit(compileEvent(2, [boom]));
    });
    act(() => {
      ctl.emit(compileEvent(3, [op3]));
    });

    expect(result.current.agentStream.brokenStream).toBe(true);
    expect(result.current.agentStream.batchesApplied).toBe(1);
    expect(consoleError).toHaveBeenCalled();
    // The rejected batch was attempted; the later one was never applied.
    expect(engine.applyLog).toEqual([[op1], [boom]]);

    // Streaming never breaks the turn: the canonical proposal still previews,
    // reconciled from base (title "n1,n3"), not from the broken streamed scene.
    await act(async () => {
      ctl.resolve(proposedResult([op1, op3]));
    });
    expect(result.current.agentPreview).not.toBeNull();
    expect(result.current.agentPreview?.previewScene.meta.title).toBe("n1,n3");
    consoleError.mockRestore();
  });

  it("(e) done: a streamed run reconciles to the SAME preview as a non-streamed run (invariant, catches engine-state leakage)", async () => {
    const op1 = streamOp("n1");
    const op2 = streamOp("n2");

    // Streamed run: both batches arrive before the terminal `done`.
    const streamed = controllableRunner();
    const streamEngine = createStreamEngine();
    const { deps: depsA } = buildDeps({
      agentRunner: streamed.runner,
      engineRef: { current: streamEngine }
    });
    const { result: resultA } = renderHook(() => useAgentTurn(depsA));
    await act(async () => {
      void resultA.current.sendAgentPrompt("build");
    });
    act(() => {
      streamed.emit(compileEvent(1, [op1]));
    });
    act(() => {
      streamed.emit(compileEvent(2, [op2]));
    });
    // Mid-stream the engine holds the cumulative build.
    expect(streamEngine.scene.meta.title).toBe("n1,n2");
    await act(async () => {
      streamed.resolve(proposedResult([op1, op2]));
    });
    const streamedPreviewTitle = resultA.current.agentPreview?.previewScene.meta.title;

    // Non-streamed run: identical canonical proposal, zero batches.
    const plain = controllableRunner();
    const plainEngine = createStreamEngine();
    const { deps: depsB } = buildDeps({
      agentRunner: plain.runner,
      engineRef: { current: plainEngine }
    });
    const { result: resultB } = renderHook(() => useAgentTurn(depsB));
    await act(async () => {
      void resultB.current.sendAgentPrompt("build");
    });
    await act(async () => {
      plain.resolve(proposedResult([op1, op2]));
    });
    const plainPreviewTitle = resultB.current.agentPreview?.previewScene.meta.title;

    expect(streamedPreviewTitle).toBe("n1,n2");
    expect(plainPreviewTitle).toBe("n1,n2");
    expect(streamedPreviewTitle).toBe(plainPreviewTitle);
    // The previewed base is the true pre-turn base (title ""), never a streamed
    // scene — the leakage a naive engine reuse would introduce.
    expect(resultA.current.agentPreview?.baseScene.meta.title).toBe("");
  });

  it("(f) a failed run restores the pre-turn base like Reject (replaceScene with the base scene)", async () => {
    const op1 = streamOp("n1");
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const replaceSceneMock = deps.replaceScene as unknown as ReturnType<typeof vi.fn>;
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(1, [op1]));
    });
    expect(engine.scene.meta.title).toBe("n1");

    await act(async () => {
      ctl.reject(new Error("agent exploded"));
    });

    // The base captured before the first streamed op (title "") was restored.
    const restored = replaceSceneMock.mock.calls
      .map((call) => call[0] as Scene)
      .find((scene) => scene?.meta?.title === "");
    expect(restored).toBeDefined();
    expect(result.current.agentStream.active).toBe(false);
  });

  it("(g) checklist events without operations populate runEvents and never touch the scene", async () => {
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const setSceneMock = deps.setScene as unknown as ReturnType<typeof vi.fn>;
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    const setSceneCallsBefore = setSceneMock.mock.calls.length;

    act(() => {
      ctl.emit({ seq: 1, type: "run_started", data: { run_id: "run_1" } });
    });
    act(() => {
      ctl.emit({ seq: 2, type: "preflight_completed", data: { iteration: 1 } });
    });

    expect(setSceneMock.mock.calls.length).toBe(setSceneCallsBefore);
    expect(engine.applyLog).toEqual([]);
    expect(result.current.runEvents.map((event) => event.seq)).toEqual([1, 2]);
    expect(result.current.agentStream).toMatchObject({ active: true, batchesApplied: 0 });
  });
});
