import { fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Diagnostic, Scene } from "@/engine/contracts";
import type { EditorAgentResult, AgentRunEvent } from "@/engine/agentRunner";
import type { TargetChip } from "@/hooks/useTargetChips";
import {
  AgentChatPanel,
  type AcceptedTurnRecord,
  type AgentChatMessage
} from "../AgentChatPanel";

const noopInstructions = {
  draft: "",
  dirty: false,
  saving: false,
  canSave: false,
  error: null,
  onDraftChange: () => {},
  onSave: () => {}
};

function renderChips(
  targetChips: TargetChip[],
  handlers: { onRemoveTargetChip?: (id: string) => void; onClearTargetChips?: () => void } = {}
) {
  return render(
    <AgentChatPanel
      messages={[]}
      draft=""
      isRunning={false}
      proposal={null}
      pendingReview={false}
      queuedMessages={[]}
      runEvents={[] as AgentRunEvent[]}
      targetChips={targetChips}
      compareView={null}
      invalidCheckpoints={new Set<string>()}
      isReverting={false}
      suggestions={[]}
      standingInstructions={noopInstructions}
      activePageId="page_a4"
      selectedNodeId={null}
      diagnostics={[]}
      onRemoveTargetChip={handlers.onRemoveTargetChip ?? (() => {})}
      onClearTargetChips={handlers.onClearTargetChips ?? (() => {})}
      onDraftChange={() => {}}
      onSend={() => {}}
      onQueueMessage={() => {}}
      onRemoveQueuedMessage={() => {}}
      onApplyProposal={() => {}}
      onAcceptProposal={() => {}}
      onRejectProposal={() => {}}
      onCompareTurn={() => {}}
      onExitCompare={() => {}}
      onRevertTurn={() => {}}
    />
  );
}

function diagnostic(code: string, message: string): Diagnostic {
  return {
    severity: "error",
    phase: "operation",
    code,
    message,
    subject: { kind: "document" },
    hint: "Remove the unsupported token."
  };
}

/** A failed Phase-A turn that repeated the SAME diagnostic and the SAME preview
 * artifact across repair iterations — the case that produced React duplicate-key
 * warnings before the keys were index-qualified. */
function repeatedProposal(): EditorAgentResult {
  return {
    status: "failed",
    summary: "Maximum Phase A repair iterations reached.",
    dsl_blocks: [],
    operations: [],
    draft_scene: null,
    stop_reason: "max_iterations",
    acceptance_scope: null,
    diagnostics: [
      diagnostic("agent_runtime.diagnostic", "unknown property valign"),
      diagnostic("agent_runtime.diagnostic", "unknown property valign")
    ],
    trace: { run_id: "run_x", trace_dir: ".lumen-runs/run_x", preview_paths: [] },
    artifacts: [
      { format: "svg", page_id: null, filename: "preview.svg", path: ".lumen-runs/run_x/iterations/003/preview.svg", data_url: null, mime_type: null },
      { format: "png", page_id: null, filename: "preview.png", path: ".lumen-runs/run_x/iterations/003/preview.svg", data_url: null, mime_type: null }
    ]
  };
}

function renderPanel(proposal: EditorAgentResult) {
  return render(
    <AgentChatPanel
      messages={[]}
      draft=""
      isRunning={false}
      proposal={proposal}
      pendingReview={false}
      queuedMessages={[]}
      runEvents={[]}
      targetChips={[]}
      compareView={null}
      invalidCheckpoints={new Set<string>()}
      isReverting={false}
      suggestions={[]}
      standingInstructions={noopInstructions}
      activePageId="page_a4"
      selectedNodeId={null}
      diagnostics={[]}
      onRemoveTargetChip={() => {}}
      onClearTargetChips={() => {}}
      onDraftChange={() => {}}
      onSend={() => {}}
      onQueueMessage={() => {}}
      onRemoveQueuedMessage={() => {}}
      onApplyProposal={() => {}}
      onAcceptProposal={() => {}}
      onRejectProposal={() => {}}
      onCompareTurn={() => {}}
      onExitCompare={() => {}}
      onRevertTurn={() => {}}
    />
  );
}

describe("AgentChatPanel duplicate-key regression", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders repeated diagnostics and artifacts without a React duplicate-key warning", () => {
    const errors: string[] = [];
    vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
      errors.push(args.map((a) => String(a)).join(" "));
    });

    const { container } = renderPanel(repeatedProposal());

    // Both repeated rows render…
    expect(container.querySelectorAll(".agent-diagnostic-list li")).toHaveLength(2);
    expect(container.querySelectorAll(".agent-artifact-list li")).toHaveLength(2);
    // …and no "same key" warning was logged.
    expect(errors.some((message) => /same key/i.test(message))).toBe(false);
  });
});

describe("AgentChatPanel target chips (2c)", () => {
  it("renders chips with layer name + node id and fires remove/clear", () => {
    const removed: string[] = [];
    let cleared = 0;
    const { getByText, getByLabelText } = renderChips(
      [
        { id: "node_headline", name: "Headline" },
        { id: "node_cta", name: "CTA Button" }
      ],
      {
        onRemoveTargetChip: (id) => removed.push(id),
        onClearTargetChips: () => {
          cleared += 1;
        }
      }
    );
    // Moda two-layer display: friendly name + the node id.
    expect(getByText("Headline")).toBeInTheDocument();
    expect(getByText("node_headline")).toBeInTheDocument();
    expect(getByText("Editing 2 layers")).toBeInTheDocument();

    fireEvent.click(getByLabelText("Remove edit target: CTA Button"));
    expect(removed).toEqual(["node_cta"]);

    fireEvent.click(getByText("Clear"));
    expect(cleared).toBe(1);
  });

  it("renders no target strip when there are no chips", () => {
    const { queryByLabelText } = renderChips([]);
    expect(queryByLabelText("Edit targets")).toBeNull();
  });
});

describe("AgentChatPanel turn actions (2d)", () => {
  const emptySceneRef = { meta: {}, pages: {}, nodes: {} } as unknown as Scene;
  const turnMessage = (checkpoint: string | null): AgentChatMessage => ({
    id: `msg_${checkpoint ?? "creation"}`,
    role: "system",
    content: "Accepted 3 agent changes.",
    turn: {
      key: `msg_${checkpoint ?? "creation"}`,
      checkpoint,
      beforeScene: emptySceneRef,
      afterScene: emptySceneRef,
      operationCount: 3
    }
  });

  function renderTurnRow(overrides: {
    invalidCheckpoints?: ReadonlySet<string>;
    onCompareTurn?: (turn: AcceptedTurnRecord, view: "before" | "after") => void;
    onRevertTurn?: (turn: AcceptedTurnRecord) => void;
  } = {}) {
    return render(
      <AgentChatPanel
        messages={[turnMessage("agent-turn-run_1")]}
        draft=""
        isRunning={false}
        proposal={null}
        pendingReview={false}
        queuedMessages={[]}
        runEvents={[]}
        targetChips={[]}
        compareView={null}
        invalidCheckpoints={overrides.invalidCheckpoints ?? new Set<string>()}
        isReverting={false}
        suggestions={[]}
        standingInstructions={noopInstructions}
        activePageId="page_a4"
        selectedNodeId={null}
        diagnostics={[]}
        onRemoveTargetChip={() => {}}
        onClearTargetChips={() => {}}
        onDraftChange={() => {}}
        onSend={() => {}}
        onQueueMessage={() => {}}
        onRemoveQueuedMessage={() => {}}
        onApplyProposal={() => {}}
        onAcceptProposal={() => {}}
        onRejectProposal={() => {}}
        onCompareTurn={overrides.onCompareTurn ?? (() => {})}
        onExitCompare={() => {}}
        onRevertTurn={overrides.onRevertTurn ?? (() => {})}
      />
    );
  }

  it("renders Compare and a two-step Revert confirm under an accepted turn", () => {
    const compared: Array<[AcceptedTurnRecord, string]> = [];
    const reverted: AcceptedTurnRecord[] = [];
    const { getByText, queryByText } = renderTurnRow({
      onCompareTurn: (turn, view) => compared.push([turn, view]),
      onRevertTurn: (turn) => reverted.push(turn)
    });

    fireEvent.click(getByText("Compare"));
    expect(compared[0]?.[0].checkpoint).toBe("agent-turn-run_1");
    expect(compared[0]?.[1]).toBe("before");

    // Revert is two-step: the first click only arms the inline confirm.
    fireEvent.click(getByText("Revert…"));
    expect(reverted).toHaveLength(0);
    expect(getByText("Undo everything after this turn?")).toBeInTheDocument();
    fireEvent.click(getByText("Confirm revert"));
    expect(reverted[0]?.checkpoint).toBe("agent-turn-run_1");
    // Cancel path leaves no confirm behind.
    expect(queryByText("Undo everything after this turn?")).toBeNull();
  });

  it("renders an invalidated checkpoint as honestly non-revertible", () => {
    const { getByText, queryByText } = renderTurnRow({
      invalidCheckpoints: new Set(["agent-turn-run_1"])
    });
    expect(getByText("No longer revertible")).toBeInTheDocument();
    expect(queryByText("Compare")).toBeNull();
    expect(queryByText("Revert…")).toBeNull();
  });

  it("never offers Revert for a creation turn (null checkpoint) but keeps Compare", () => {
    // The e2e-caught case: an empty-canvas Accept folds into the creation
    // seed (no server envelope), so the turn is non-revertible from birth.
    const { getByText, queryByText } = render(
      <AgentChatPanel
        messages={[turnMessage(null)]}
        draft=""
        isRunning={false}
        proposal={null}
        pendingReview={false}
        queuedMessages={[]}
        runEvents={[]}
        targetChips={[]}
        compareView={null}
        invalidCheckpoints={new Set<string>()}
        isReverting={false}
        suggestions={[]}
        standingInstructions={noopInstructions}
        activePageId="page_a4"
        selectedNodeId={null}
        diagnostics={[]}
        onRemoveTargetChip={() => {}}
        onClearTargetChips={() => {}}
        onDraftChange={() => {}}
        onSend={() => {}}
        onQueueMessage={() => {}}
        onRemoveQueuedMessage={() => {}}
        onApplyProposal={() => {}}
        onAcceptProposal={() => {}}
        onRejectProposal={() => {}}
        onCompareTurn={() => {}}
        onExitCompare={() => {}}
        onRevertTurn={() => {}}
      />
    );
    expect(getByText("Compare")).toBeInTheDocument();
    expect(getByText("Not revertible (created the document)")).toBeInTheDocument();
    expect(queryByText("Revert…")).toBeNull();
  });
});
