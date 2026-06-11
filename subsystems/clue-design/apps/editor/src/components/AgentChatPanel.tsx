import { AlertTriangle, Bot, CheckCircle2, FileCode2, Send, Sparkles } from "lucide-react";
import type { FormEvent } from "react";
import type { Diagnostic, NodeId, Operation, PageId } from "@/engine/contracts";
import type { EditorAgentResult } from "@/engine/agentRunner";

export interface AgentChatMessage {
  id: string;
  role: "user" | "agent" | "system";
  content: string;
}

export interface AgentChatPanelProps {
  messages: AgentChatMessage[];
  draft: string;
  isRunning: boolean;
  proposal: EditorAgentResult | null;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  diagnostics: Diagnostic[];
  onDraftChange: (value: string) => void;
  onSend: (prompt: string) => void;
  onApplyProposal: () => void;
}

export function AgentChatPanel({
  messages,
  draft,
  isRunning,
  proposal,
  activePageId,
  selectedNodeId,
  diagnostics,
  onDraftChange,
  onSend,
  onApplyProposal
}: AgentChatPanelProps) {
  const submitPrompt = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed || isRunning) {
      return;
    }
    onSend(trimmed);
  };

  return (
    <section className="inspector-section agent-chat-panel" aria-label="Agent chat">
      <div className="section-heading">
        <Bot aria-hidden size={15} />
        Agent chat
      </div>
      <div className="agent-context-strip" aria-label="Agent context">
        <span>Page {activePageId ?? "none"}</span>
        <span>Selection {selectedNodeId ?? "none"}</span>
        <span>{diagnostics.length} diagnostic{diagnostics.length === 1 ? "" : "s"}</span>
      </div>
      <div className="agent-message-list" aria-label="Agent conversation">
        {messages.length === 0 ? (
          <p className="muted">
            Ask the agent to create or repair the current design. The editor will pass the active scene,
            page, selection, and diagnostics as context.
          </p>
        ) : (
          messages.map((message) => (
            <article key={message.id} className={`agent-message ${message.role}`}>
              <span>{message.role === "user" ? "You" : message.role === "agent" ? "Agent" : "System"}</span>
              <p>{message.content}</p>
            </article>
          ))
        )}
      </div>
      {proposal ? (
        <AgentProposalCard
          proposal={proposal}
          isRunning={isRunning}
          onApplyProposal={onApplyProposal}
        />
      ) : null}
      <form className="agent-chat-form" onSubmit={submitPrompt}>
        <label className="field">
          <span>Message the agent</span>
          <textarea
            value={draft}
            onChange={(event) => onDraftChange(event.target.value)}
            placeholder="Ask for a square ad, repair overflow, or update the selected section."
            rows={4}
          />
        </label>
        <button type="submit" disabled={isRunning || !draft.trim()}>
          <Send aria-hidden size={15} />
          {isRunning ? "Sending" : "Send"}
        </button>
      </form>
    </section>
  );
}

function AgentProposalCard({
  proposal,
  isRunning,
  onApplyProposal
}: {
  proposal: EditorAgentResult;
  isRunning: boolean;
  onApplyProposal: () => void;
}) {
  const canApply = proposal.status === "proposed" && proposal.operations.length > 0;
  const hasDraftScene = Boolean(proposal.draft_scene);
  return (
    <div className={`agent-proposal ${proposal.status}`}>
      <div className="agent-proposal-heading">
        {proposal.status === "proposed" ? (
          <CheckCircle2 aria-hidden size={15} />
        ) : (
          <AlertTriangle aria-hidden size={15} />
        )}
        <strong>
          {proposal.status === "proposed"
            ? "Proposal ready"
            : hasDraftScene
              ? "Draft visible"
              : "Agent blocked"}
        </strong>
      </div>
      <p>{proposal.summary}</p>
      {proposal.status === "failed" && hasDraftScene ? (
        <p className="muted">
          The latest unapproved draft is shown on the canvas for inspection. It has not been accepted
          as a final proposal.
        </p>
      ) : null}
      {proposal.trace.run_id ? (
        <p className="muted">
          Run <code>{proposal.trace.run_id}</code>
          {proposal.trace.trace_dir ? <> · trace <code>{proposal.trace.trace_dir}</code></> : null}
        </p>
      ) : null}
      {proposal.dsl_blocks.length > 0 ? (
        <details open>
          <summary>
            <FileCode2 aria-hidden size={14} />
            DSL proposed
          </summary>
          {proposal.dsl_blocks.map((block, index) => (
            <pre key={`dsl-${index}`} className="agent-code-preview">
              {block}
            </pre>
          ))}
        </details>
      ) : null}
      {proposal.operations.length > 0 ? (
        <details open>
          <summary>
            <Sparkles aria-hidden size={14} />
            {proposal.operations.length} operation{proposal.operations.length === 1 ? "" : "s"}
          </summary>
          <ol className="agent-operation-list">
            {proposal.operations.slice(0, 8).map((operation, index) => (
              <li key={`${index}-${operation.kind}`}>
                <code>{operationLabel(operation)}</code>
              </li>
            ))}
          </ol>
          {proposal.operations.length > 8 ? (
            <p className="muted">{proposal.operations.length - 8} additional operation{proposal.operations.length - 8 === 1 ? "" : "s"} hidden.</p>
          ) : null}
        </details>
      ) : null}
      {proposal.diagnostics.length > 0 ? (
        <ul className="agent-diagnostic-list" aria-label="Agent diagnostics">
          {proposal.diagnostics.slice(0, 4).map((diagnostic) => (
            <li key={`${diagnostic.code}-${diagnostic.message}`}>
              <code>{diagnostic.code}</code>
              <span>{diagnostic.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {proposal.artifacts.length > 0 ? (
        <ul className="agent-artifact-list" aria-label="Agent artifacts">
          {proposal.artifacts.map((artifact, index) => (
            <li key={`${artifact.path ?? artifact.filename ?? index}`}>
              {artifact.format ?? "artifact"} {artifact.filename ?? artifact.path ?? "preview"}
            </li>
          ))}
        </ul>
      ) : null}
      <button type="button" onClick={onApplyProposal} disabled={!canApply || isRunning}>
        {proposal.status === "failed" && hasDraftScene ? "Draft already shown" : "Apply and preview"}
      </button>
    </div>
  );
}

function operationLabel(operation: Operation): string {
  switch (operation.kind) {
    case "add_page":
      return `add_page ${operation.page.id}`;
    case "remove_page":
      return `remove_page ${operation.page_id}`;
    case "insert_node":
      return `insert_node ${operation.node.id}`;
    case "update_node":
      return `update_node ${operation.node_id}`;
    case "remove_node":
      return `remove_node ${operation.node_id}`;
    case "update_page":
      return `update_page ${operation.page_id}`;
    case "move_node":
      return `move_node ${operation.node_id}`;
    case "upsert_slot":
      return `upsert_slot ${operation.slot.key}`;
    case "remove_slot":
      return `remove_slot ${operation.slot_id}`;
    case "bind_node_to_slot":
      return `bind_node_to_slot ${operation.node_id}`;
    case "unbind_node_from_slot":
      return `unbind_node_from_slot ${operation.node_id}`;
    case "upsert_asset":
      return `upsert_asset ${operation.asset.id}`;
    case "remove_asset":
      return `remove_asset ${operation.asset_id}`;
    case "place_asset_in_node":
      return `place_asset_in_node ${operation.node_id}`;
    case "place_asset_in_slot":
      return `place_asset_in_slot ${operation.slot_id}`;
    case "upsert_export_profile":
      return `upsert_export_profile ${operation.profile.name}`;
    case "remove_export_profile":
      return `remove_export_profile ${operation.name}`;
    case "update_document":
      return "update_document";
  }
}
