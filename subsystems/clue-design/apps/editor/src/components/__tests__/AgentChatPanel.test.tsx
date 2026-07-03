import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Diagnostic } from "@/engine/contracts";
import type { EditorAgentResult } from "@/engine/agentRunner";
import { AgentChatPanel } from "../AgentChatPanel";

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
      activePageId="page_a4"
      selectedNodeId={null}
      diagnostics={[]}
      onDraftChange={() => {}}
      onSend={() => {}}
      onQueueMessage={() => {}}
      onRemoveQueuedMessage={() => {}}
      onApplyProposal={() => {}}
      onAcceptProposal={() => {}}
      onRejectProposal={() => {}}
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
