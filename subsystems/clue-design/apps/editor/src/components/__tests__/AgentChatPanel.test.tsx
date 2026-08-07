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

/** RC: shared render helper for the reference-attachment surface. */
function renderReferencesPanel(
  overrides: Partial<Parameters<typeof AgentChatPanel>[0]> = {}
) {
  return render(
    <AgentChatPanel
      messages={[]}
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
      {...overrides}
    />
  );
}

function pendingReference(n: number) {
  return {
    assetId: `asset_ref_${n}`,
    label: `wash-${n}.png`,
    thumbnailUrl: `http://api.test/assets/asset_ref_${n}/thumbnail`
  };
}

describe("AgentChatPanel — RC reference attachments", () => {
  it("renders the attach button only when the shell wires onAttachReferences", () => {
    const { queryByLabelText, rerender } = renderReferencesPanel();
    expect(queryByLabelText("Attach references")).toBeNull();
    rerender(
      <AgentChatPanel
        messages={[]}
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
        onAttachReferences={() => {}}
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
    expect(queryByLabelText("Attach references")).not.toBeNull();
  });

  it("fires onAttachReferences with the picked files and resets the input", () => {
    const onAttachReferences = vi.fn();
    const { getByLabelText, container } = renderReferencesPanel({ onAttachReferences });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.accept).toBe("image/png,image/jpeg,image/webp,image/gif,image/svg+xml");
    expect(input.multiple).toBe(true);
    expect(getByLabelText("Attach references")).toBeEnabled();

    const file = new File(["x"], "wash.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(onAttachReferences).toHaveBeenCalledTimes(1);
    expect(onAttachReferences.mock.calls[0][0]).toEqual([file]);
    expect(input.value).toBe("");
  });

  it("renders pending references as removable thumbnail chips", () => {
    const onRemoveReference = vi.fn();
    const { getByLabelText, getByText, getByAltText } = renderReferencesPanel({
      onAttachReferences: () => {},
      onRemoveReference,
      pendingReferences: [pendingReference(1), pendingReference(2)]
    });
    expect(getByText("2 references for the next turn")).toBeInTheDocument();
    const thumbnail = getByAltText("wash-1.png") as HTMLImageElement;
    expect(thumbnail.src).toBe("http://api.test/assets/asset_ref_1/thumbnail");
    fireEvent.click(getByLabelText("Remove reference: wash-2.png"));
    expect(onRemoveReference).toHaveBeenCalledWith("asset_ref_2");
  });

  it("disables the attach button at the 4-reference cap with an explanatory title", () => {
    const { getByLabelText } = renderReferencesPanel({
      onAttachReferences: () => {},
      onRemoveReference: () => {},
      pendingReferences: [1, 2, 3, 4].map(pendingReference)
    });
    const button = getByLabelText("Attach references");
    expect(button).toBeDisabled();
    expect(button.getAttribute("title")).toContain("at most 4 references");
  });

  it("shows a loading state while uploads are in flight", () => {
    const { getByLabelText } = renderReferencesPanel({
      onAttachReferences: () => {},
      isUploadingReferences: true
    });
    const button = getByLabelText("Attach references");
    expect(button).toBeDisabled();
    expect(button.getAttribute("title")).toContain("Uploading");
  });

  it("shows a user message's attachments in the transcript", () => {
    const messages: AgentChatMessage[] = [
      {
        id: "user_1",
        role: "user",
        content: "Match these washes.",
        attachments: [
          { assetId: "asset_ref_1", label: "wash-1.png" },
          { assetId: "asset_ref_2", label: "wash-2.png" }
        ]
      }
    ];
    const { getByLabelText } = renderReferencesPanel({ messages });
    expect(getByLabelText("Turn attachments").textContent).toContain("wash-1.png, wash-2.png");
  });
});
