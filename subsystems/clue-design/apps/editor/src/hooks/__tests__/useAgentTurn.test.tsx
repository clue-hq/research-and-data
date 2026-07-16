import { act, render, renderHook, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { AgentRunEvent, EditorAgentResult, EditorAgentRunner } from "@/engine/agentRunner";
import type { Operation, Scene } from "@/engine/contracts";
import type { EditorHistoryFrame } from "@/hooks/useEditHistory";
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

describe("useAgentTurn — live design streaming reveal theater (S2)", () => {
  // S2 replaces S1's apply-whole-batch with a paced pump, so these tests drive
  // fake timers and advance them to flush reveal-steps.
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  // A reveal-step is a VISUAL op (`insert_node`) so `stepsFromOps` gives one step
  // per op; `id` is a marker the fake engine joins into scene.meta.title so
  // cumulative application is observable. `boom` makes the engine throw.
  const insertOp = (id: string) =>
    ({
      kind: "insert_node",
      id,
      node: { id: `node_${id}` },
      parent: { kind: "page", id: "page_a4" },
      index: 0
    }) as unknown as Operation;

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

  /** An engine that materializes each inserted node WITH computed layout bounds,
   * so `currentReveal.bounds` (read off the applied scene) is observable. */
  function createRevealMetadataEngine(
    bounds: { x: number; y: number; width: number; height: number }
  ): OptimisticEnginePort {
    let scene: Scene = cloneScene();
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
        const nodes = { ...scene.nodes };
        for (const op of operations) {
          const nodeId = (op as unknown as { node?: { id?: string } }).node?.id;
          if (nodeId) {
            nodes[nodeId] = {
              ...(nodes[nodeId] ?? {}),
              id: nodeId,
              computed: { layout_bounds: bounds, render_bounds: bounds }
            } as unknown as Scene["nodes"][string];
          }
        }
        scene = { ...scene, nodes };
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

  const tick = (ms: number) => {
    act(() => {
      vi.advanceTimersByTime(ms);
    });
  };

  // S2.1 uncompressed per-step timeline for a bounds-less insert (the stream
  // engine sets no computed bounds, so drawMs falls back to ADD_PAGE_DRAW_MS):
  //   firstLead 120 → runStep (engine applies, content HELD) → +travel(200)
  //   +draw(300) = materialize@+500 (held setScene fires) → +pause(120) → next.
  const FIRST_LEAD = 120;
  const TRAVEL = 200;
  const DRAW = 300; // ADD_PAGE_DRAW_MS fallback for bounds-less inserts
  const PAUSE = 120;
  const APPLY_TO_MATERIALIZE = TRAVEL + DRAW; // 500
  const STEP_ADVANCE = APPLY_TO_MATERIALIZE + PAUSE; // 620

  const streamTitlesFrom = (setSceneMock: ReturnType<typeof vi.fn>) =>
    setSceneMock.mock.calls
      .map((call) => (call[0] as Scene)?.meta?.title)
      .filter((title) => typeof title === "string" && /^n1(,n\d+)*$/.test(title as string));

  it("(a) the pump paces one element at a time, holding the content until the box finishes drawing (deduping replays)", async () => {
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const setSceneMock = deps.setScene as unknown as ReturnType<typeof vi.fn>;
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(1, [insertOp("n1"), insertOp("n2"), insertOp("n3")]));
    });
    // A duplicate/replayed seq enqueues nothing.
    act(() => {
      ctl.emit(compileEvent(1, [insertOp("n1"), insertOp("n2"), insertOp("n3")]));
    });

    // Paced from the start: nothing applies until the first lead elapses.
    expect(engine.applyLog.length).toBe(0);
    tick(FIRST_LEAD - 1);
    expect(engine.applyLog.length).toBe(0);
    tick(1); // firstLead → step 1 applies to the ENGINE (ahead of display)…
    expect(engine.applyLog).toEqual([[insertOp("n1")]]);
    expect(engine.scene.meta.title).toBe("n1");
    // …but the content is HELD: the display has not yet been shown "n1".
    expect(streamTitlesFrom(setSceneMock)).toEqual([]);

    tick(APPLY_TO_MATERIALIZE); // box finishes drawing → held setScene fires
    expect(streamTitlesFrom(setSceneMock)).toEqual(["n1"]);

    tick(PAUSE); // step 2 applies
    expect(engine.applyLog.length).toBe(2);
    tick(APPLY_TO_MATERIALIZE);
    tick(PAUSE); // step 3 applies
    tick(APPLY_TO_MATERIALIZE);
    expect(engine.applyLog).toEqual([[insertOp("n1")], [insertOp("n2")], [insertOp("n3")]]);
    expect(engine.scene.meta.title).toBe("n1,n2,n3");
    expect(streamTitlesFrom(setSceneMock)).toEqual(["n1", "n1,n2", "n1,n2,n3"]);
    expect(result.current.agentStream).toMatchObject({
      active: true,
      lastAppliedSeq: 1,
      stepsApplied: 3,
      brokenStream: false,
      revealQueueLength: 0
    });
  });

  it("(b) a large batch compresses to fit the cap, but never below the 250ms/element floor", async () => {
    // 40 elements uncompressed ≈ 40 × 620 ≈ 24.8s (> 15s cap): the pace
    // compresses so the whole batch drains within the cap.
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const { result } = renderHook(() => useAgentTurn(deps));
    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(1, Array.from({ length: 40 }, (_, i) => insertOp(`n${i}`))));
    });
    // Compressed: the first element applies well before the uncompressed 120ms
    // first-lead, and the whole batch drains within MAX_BATCH_REVEAL_MS.
    tick(60);
    expect(engine.applyLog.length).toBeGreaterThanOrEqual(1);
    tick(15000);
    expect(engine.applyLog.length).toBe(40);
    expect(result.current.agentStream.stepsApplied).toBe(40);

    // The floor holds: 200 elements CANNOT be over-compressed into the cap —
    // each element still takes at least ~250ms, so the batch overruns the cap.
    const ctl2 = controllableRunner();
    const engine2 = createStreamEngine();
    const { deps: deps2 } = buildDeps({ agentRunner: ctl2.runner, engineRef: { current: engine2 } });
    const { result: result2 } = renderHook(() => useAgentTurn(deps2));
    await act(async () => {
      void result2.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl2.emit(compileEvent(1, Array.from({ length: 200 }, (_, i) => insertOp(`m${i}`))));
    });
    tick(15000);
    expect(engine2.applyLog.length).toBeLessThan(200); // floor kept it from fitting
    tick(60000);
    expect(engine2.applyLog.length).toBe(200); // …but it still fully drains
  });

  it("(c) a new batch arriving mid-reveal fast-forwards the pending backlog in one apply, then paces the new batch", async () => {
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(1, [insertOp("n1"), insertOp("n2"), insertOp("n3")]));
    });
    tick(FIRST_LEAD); // n1 applied to the engine; n2 + n3 still queued
    expect(engine.scene.meta.title).toBe("n1");

    // A newer batch arrives while the backlog is pending → drain it instantly.
    act(() => {
      ctl.emit(compileEvent(2, [insertOp("n4")]));
    });
    expect(engine.scene.meta.title).toBe("n1,n2,n3"); // backlog fast-forwarded (no tick)
    // The drain was ONE apply of the remaining ops, not two paced ticks.
    expect(engine.applyLog).toEqual([[insertOp("n1")], [insertOp("n2"), insertOp("n3")]]);

    tick(FIRST_LEAD + APPLY_TO_MATERIALIZE); // now the new batch paces
    expect(engine.scene.meta.title).toBe("n1,n2,n3,n4");
  });

  it("(d) done mid-reveal cancels the pump and reconciles to the SAME canonical preview as a non-streamed run (invariant)", async () => {
    // Streamed run: resolve while a reveal-step is STILL queued (mid-reveal).
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
      streamed.emit(compileEvent(1, [insertOp("n1"), insertOp("n2")]));
    });
    tick(FIRST_LEAD); // n1 applied to the engine; n2 still queued behind the pump
    expect(streamEngine.scene.meta.title).toBe("n1");
    await act(async () => {
      streamed.resolve(proposedResult([insertOp("n1"), insertOp("n2")]));
    });
    const streamedPreviewTitle = resultA.current.agentPreview?.previewScene.meta.title;

    // Non-streamed run: identical canonical proposal, zero streamed batches.
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
      plain.resolve(proposedResult([insertOp("n1"), insertOp("n2")]));
    });
    const plainPreviewTitle = resultB.current.agentPreview?.previewScene.meta.title;

    expect(streamedPreviewTitle).toBe("n1,n2");
    expect(streamedPreviewTitle).toBe(plainPreviewTitle);
    // The previewed base is the true pre-turn base (title ""), never a partial
    // streamed scene — the leakage a naive engine reuse would introduce.
    expect(resultA.current.agentPreview?.baseScene.meta.title).toBe("");
    // The pump is dead — no stray tick mutates the reconciled scene.
    tick(500);
    expect(resultA.current.agentStream.active).toBe(false);
  });

  it("(e) a step the engine throws on keeps S1's broken semantics (stop applying, hold last good, still previews canonical)", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(1, [insertOp("n1"), insertOp("boom"), insertOp("n3")]));
    });
    tick(FIRST_LEAD); // n1 applies
    tick(STEP_ADVANCE); // materialize n1, then boom applies → throws → stream broken
    tick(STEP_ADVANCE); // n3 must NOT apply (pump cancelled)

    expect(result.current.agentStream.brokenStream).toBe(true);
    expect(result.current.agentStream.stepsApplied).toBe(1);
    expect(consoleError).toHaveBeenCalled();
    expect(engine.applyLog).toEqual([[insertOp("n1")], [insertOp("boom")]]);

    // Streaming never breaks the turn: the canonical proposal still previews,
    // reconciled from base (title "n1,n3"), not the broken streamed scene.
    await act(async () => {
      ctl.resolve(proposedResult([insertOp("n1"), insertOp("n3")]));
    });
    expect(result.current.agentPreview?.previewScene.meta.title).toBe("n1,n3");
    consoleError.mockRestore();
  });

  it("(f) each reveal-step exposes metadata (node id, page, kind, computed bounds) plus the phase timing", async () => {
    const bounds = { x: 24, y: 32, width: 180, height: 30 };
    const ctl = controllableRunner();
    const engine = createRevealMetadataEngine(bounds);
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(3, [insertOp("n1")]));
    });
    tick(FIRST_LEAD); // step applies + publishes the reveal

    const reveal = result.current.agentStream.currentReveal;
    expect(reveal).toMatchObject({
      seq: 3,
      kind: "insert_node",
      nodeId: "node_n1",
      pageId: "page_a4",
      bounds,
      reducedMotion: false
    });
    // Uncompressed single step: travel + fade are the nominal constants; the
    // draw scales with the box diagonal into the [DRAW_MIN, DRAW_MAX] band.
    expect(reveal?.travelMs).toBe(200);
    expect(reveal?.materializeFadeMs).toBe(250);
    expect(reveal?.drawMs).toBeGreaterThanOrEqual(250);
    expect(reveal?.drawMs).toBeLessThanOrEqual(500);
  });

  it("(f2) an add_page step materializes IMMEDIATELY (the artboard IS the placeholder) while insert_node steps stay held through their draw; the reveal carries its label", async () => {
    // Review fix (S2.1): a held page has no artboard in the DISPLAYED scene for
    // the chrome to anchor to, so pages must land instantly with the outline
    // drawing over them — only node content is held back.
    const addPageOp = {
      kind: "add_page",
      page: { id: "page_new" }
    } as unknown as Operation;
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const setSceneMock = deps.setScene as unknown as ReturnType<typeof vi.fn>;
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(1, [addPageOp, insertOp("n1")]));
    });

    // streamTitlesFrom filters to insert-marker chains, so this test reads the
    // raw title sequence (add_page markers included) directly.
    const allTitles = () =>
      setSceneMock.mock.calls
        .map((call) => (call[0] as Scene)?.meta?.title)
        .filter((title): title is string => typeof title === "string" && title.length > 0);

    tick(FIRST_LEAD); // step 1 (add_page) applies…
    // …and materializes IMMEDIATELY (no hold): the artboard placeholder is on
    // the displayed scene while its whole-artboard outline draws over it.
    expect(allTitles()).toEqual(["add_page"]);
    expect(result.current.agentStream.currentReveal?.label).toBe("artboard");

    tick(STEP_ADVANCE); // add_page draw+pause elapse → step 2 (insert n1) applies
    // The node step is HELD — nothing new displayed until its box finishes.
    expect(allTitles()).toEqual(["add_page"]);
    tick(APPLY_TO_MATERIALIZE); // n1's box completes → held content lands
    expect(allTitles()).toEqual(["add_page", "add_page,n1"]);
  });

  it("(g) a failed run mid-reveal cancels the pump and restores the pre-turn base like Reject (replaceScene with base)", async () => {
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const replaceSceneMock = deps.replaceScene as unknown as ReturnType<typeof vi.fn>;
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(1, [insertOp("n1"), insertOp("n2")]));
    });
    tick(FIRST_LEAD); // n1 applied to the engine; n2 still queued
    expect(engine.scene.meta.title).toBe("n1");

    await act(async () => {
      ctl.reject(new Error("agent exploded"));
    });

    const restored = replaceSceneMock.mock.calls
      .map((call) => call[0] as Scene)
      .find((scene) => scene?.meta?.title === "");
    expect(restored).toBeDefined();
    expect(result.current.agentStream.active).toBe(false);
    // The cancelled pump never fires again.
    tick(1000);
    expect(engine.scene.meta.title).toBe("n1");
  });

  it("(h) checklist events without operations populate runEvents and never touch the scene", async () => {
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
    tick(200);

    expect(setSceneMock.mock.calls.length).toBe(setSceneCallsBefore);
    expect(engine.applyLog).toEqual([]);
    expect(result.current.runEvents.map((event) => event.seq)).toEqual([1, 2]);
    expect(result.current.agentStream).toMatchObject({ active: true, stepsApplied: 0 });
  });

  it("(i) done arriving DURING the draw phase (engine applied, setScene HELD) reconciles to the canonical preview with no streamed frame shown after", async () => {
    // The display-lags-engine window: the step's ops are applied to the engine
    // but its held setScene has NOT fired yet. A `done` landing here must never
    // leak that un-materialized streamed frame — it reconciles from base.
    const ctl = controllableRunner();
    const engine = createStreamEngine();
    const { deps } = buildDeps({ agentRunner: ctl.runner, engineRef: { current: engine } });
    const setSceneMock = deps.setScene as unknown as ReturnType<typeof vi.fn>;
    const { result } = renderHook(() => useAgentTurn(deps));

    await act(async () => {
      void result.current.sendAgentPrompt("build");
    });
    act(() => {
      ctl.emit(compileEvent(1, [insertOp("n1")]));
    });
    // Advance INTO the draw phase: the engine has applied "n1", but we are before
    // materialize (FIRST_LEAD < now < FIRST_LEAD + APPLY_TO_MATERIALIZE).
    tick(FIRST_LEAD + 100);
    expect(engine.scene.meta.title).toBe("n1"); // engine ran ahead
    // The held content was NOT shown to the display yet.
    expect(streamTitlesFrom(setSceneMock)).toEqual([]);

    // `done` lands mid-draw → reconcile to the canonical proposal from base.
    await act(async () => {
      ctl.resolve(proposedResult([insertOp("n1")]));
    });
    expect(result.current.agentPreview?.previewScene.meta.title).toBe("n1");
    expect(result.current.agentPreview?.baseScene.meta.title).toBe("");
    // The single "n1" frame the display ever sees is the CANONICAL preview
    // (applied from base), not the held streamed frame.
    const n1FramesAfterDone = streamTitlesFrom(setSceneMock).filter((title) => title === "n1").length;
    expect(n1FramesAfterDone).toBe(1);

    // The stale materialize timer never fires: advancing past its due time adds
    // no second streamed frame after done.
    tick(APPLY_TO_MATERIALIZE + PAUSE + 1000);
    expect(streamTitlesFrom(setSceneMock).filter((title) => title === "n1").length).toBe(1);
    expect(result.current.agentStream.active).toBe(false);
  });
});

/**
 * Regression (adversarial-review divergence seam): the reload-RESUME settle
 * path must consume the EXPLICIT pre-turn seed (turnSeedRef, armed on mount),
 * never closure `scene` — which progressive streaming has since mutated to the
 * half-built streamed scene. Two failures shared one root cause:
 *   (1) `showAgentDraftScene` pushed an undo frame capturing the STREAMED scene
 *       (undo history is durable → "nothing streamed is ever persisted" broke);
 *   (2) `draftIsUnchangedSeed` compared the draft against the STREAMED scene,
 *       suppressing the honest unchanged-seed message.
 * Both are pinned here against the same resume harness the refuter used.
 */
describe("useAgentTurn — resume-path settles against the explicit pre-turn seed", () => {
  const streamMarkerOp = (id: string) =>
    ({
      kind: "insert_node",
      id,
      node: { id: `node_${id}` },
      parent: { kind: "page", id: "page_a4" },
      index: 0
    }) as unknown as Operation;

  const streamCompileEvent = (seq: number, operations: unknown): AgentRunEvent => ({
    seq,
    type: "dsl_compiled",
    data: { iteration: 1, operations } as AgentRunEvent["data"]
  });

  /** An engine that CONCATENATES inserted markers into meta.title, so the live
   * scene visibly diverges from the seed as streamed steps apply. */
  function titleStreamEngine(): OptimisticEnginePort {
    const start = { ...cloneScene(), meta: { ...cloneScene().meta, title: "" } };
    let scene: Scene = start;
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
        const markers = operations.map((op) => (op as unknown as { id?: string }).id ?? op.kind);
        const prev = scene.meta.title ? scene.meta.title.split(",") : [];
        scene = { ...scene, meta: { ...scene.meta, title: [...prev, ...markers].join(",") } };
        return { accepted: true, scene, diagnostics: [], inverseOperations: [], appliedOperations: operations.length };
      }
    } as OptimisticEnginePort;
  }

  function controllableResume() {
    let captured: ((event: AgentRunEvent) => void) | undefined;
    let resolveRun!: (result: EditorAgentResult) => void;
    const resumeRun: NonNullable<UseAgentTurnDeps["resumeRun"]> = (_runId, onEvent) => {
      captured = onEvent;
      return new Promise<EditorAgentResult>((resolve) => {
        resolveRun = resolve;
      });
    };
    return {
      resumeRun,
      emit: (event: AgentRunEvent) => captured?.(event),
      resolve: (result: EditorAgentResult) => resolveRun(result)
    };
  }

  function failedWithDraft(draftTitle: string): EditorAgentResult {
    const draft = { ...cloneScene(), meta: { ...cloneScene().meta, title: draftTitle } };
    return {
      status: "failed",
      summary: "Run failed, draft available.",
      dsl_blocks: [],
      operations: [],
      draft_scene: draft,
      stop_reason: "quality_loop_exhausted",
      acceptance_scope: null,
      diagnostics: [],
      trace: { run_id: "run_resume", trace_dir: null, preview_paths: [] },
      artifacts: []
    };
  }

  type HookApi = ReturnType<typeof useAgentTurn>;

  /** Holds `scene` in real state so the hook's progressive setScene mutates the
   * deps.scene it re-renders with — exactly like EditorApp. Captures the hook's
   * return + the pushed undo frames for assertions. */
  function ResumeHarness(props: {
    engine: OptimisticEnginePort;
    resume: ReturnType<typeof controllableResume>;
    capture: { hook: HookApi | null; undoFrames: EditorHistoryFrame[] };
  }) {
    const [scene, setScene] = useState<Scene>(() => ({
      ...cloneScene(),
      meta: { ...cloneScene().meta, title: "" }
    }));
    const undoRef = useRef<EditorHistoryFrame[]>([]);
    props.capture.hook = useAgentTurn({
      agentRunner: (() => {}) as unknown as UseAgentTurnDeps["agentRunner"],
      engineRef: { current: props.engine },
      scene,
      activeDocumentId: "doc_1",
      activePageId: "page_a4",
      selectedNodeId: null,
      targetNodeIds: [],
      agentInstructions: null,
      layoutManagedEditing: false,
      acceptBakeRunner: async () => null,
      diagnostics: [],
      setDiagnostics: () => {},
      setScene: (updater) =>
        setScene((current) =>
          typeof updater === "function" ? (updater as (s: Scene) => Scene)(current) : updater
        ),
      replaceScene: (next) => setScene(next),
      setActivePageId: () => {},
      setSelectedNodeId: () => {},
      setUndoStack: (updater) => {
        const next =
          typeof updater === "function"
            ? (updater as (s: EditorHistoryFrame[]) => EditorHistoryFrame[])(undoRef.current)
            : updater;
        undoRef.current = next;
        props.capture.undoFrames.length = 0;
        props.capture.undoFrames.push(...next);
      },
      setRedoStack: () => {},
      setBrandCompatibilityReport: () => {},
      setPreflightResult: () => {},
      setExportResult: () => {},
      setWorkspaceMode: () => {},
      commitAppliedOperations: () => "persisted",
      runExportForScene: async () => {},
      applyOperations: () => {},
      resumeRun: props.resume.resumeRun
    });
    return null;
  }

  beforeEach(() => {
    vi.useFakeTimers();
    window.sessionStorage.setItem("lumen.activeAgentRun", "run_resume");
  });
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    window.sessionStorage.clear();
  });

  it("(1) the draft undo frame captures the true pre-turn base, not the streamed scene", async () => {
    const engine = titleStreamEngine();
    const resume = controllableResume();
    const capture = { hook: null as HookApi | null, undoFrames: [] as EditorHistoryFrame[] };

    await act(async () => {
      render(<ResumeHarness engine={engine} resume={resume} capture={capture} />);
    });
    // A streamed batch arrives on replay and the pump applies it, mutating the
    // React `scene` to the half-built "n1".
    act(() => {
      resume.emit(streamCompileEvent(1, [streamMarkerOp("n1")]));
    });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(engine.scene.meta.title).toBe("n1");

    // The run finishes FAILED with an inspectable, changed draft.
    await act(async () => {
      resume.resolve(failedWithDraft("DRAFT"));
      await Promise.resolve();
    });

    expect(capture.undoFrames).toHaveLength(1);
    // The frame's scene is the pre-turn base (title ""), never the streamed "n1".
    expect(capture.undoFrames[0].scene.meta.title).toBe("");
  });

  it("(2) an unchanged-seed draft is detected on resume even after streaming mutated the scene", async () => {
    const engine = titleStreamEngine();
    const resume = controllableResume();
    const capture = { hook: null as HookApi | null, undoFrames: [] as EditorHistoryFrame[] };

    await act(async () => {
      render(<ResumeHarness engine={engine} resume={resume} capture={capture} />);
    });
    act(() => {
      resume.emit(streamCompileEvent(1, [streamMarkerOp("n1")]));
    });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(engine.scene.meta.title).toBe("n1"); // streamed away from the seed

    // The draft equals the PRE-TURN seed (title "") — nothing ever applied.
    await act(async () => {
      resume.resolve(failedWithDraft(""));
      await Promise.resolve();
    });

    // Honest unchanged-seed handling: the draft is nulled (no "draft visible"
    // on an unchanged canvas) and the system explains it — proving the compare
    // ran against the seed, not the streamed "n1" (which would read as changed).
    expect(capture.hook?.agentProposal?.draft_scene).toBeNull();
    expect(
      capture.hook?.agentMessages.some((message) =>
        message.content.includes("could not produce any applicable changes")
      )
    ).toBe(true);
    // No draft undo frame is pushed for an unchanged seed.
    expect(capture.undoFrames).toHaveLength(0);
  });
});
