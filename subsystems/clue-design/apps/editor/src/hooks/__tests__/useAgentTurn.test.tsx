import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { EditorAgentResult, EditorAgentRunner } from "@/engine/agentRunner";
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
