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
