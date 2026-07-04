import { AlertTriangle, Bot, Check, CheckCircle2, Crosshair, Eye, FileCode2, History, Loader2, Send, Sparkles, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { Diagnostic, NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import type { AgentRunEvent, EditorAgentResult } from "@/engine/agentRunner";
import {
  briefIsEmpty,
  composeBriefPrompt,
  EMPTY_BRIEF,
  type DesignBrief
} from "@/engine/agentBrief";
import { agentChecklist, agentEventLabel } from "@/engine/agentChecklist";
import type { TargetChip } from "@/hooks/useTargetChips";
import type { CompareView } from "@/hooks/useTurnCheckpoints";

/** An accepted agent turn. `checkpoint` is its server-side anchor — null
 * when the accept's batch got no envelope (the empty-canvas accept whose
 * creation IS its persistence): such a turn is honestly non-revertible.
 * Snapshots power Compare and are session-local (a reload loses Compare;
 * Revert still works off a persisted checkpoint). `key` is the turn's
 * stable client-side identity (checkpoints can be null). */
export interface AcceptedTurnRecord {
  key: string;
  checkpoint: string | null;
  beforeScene: Scene;
  afterScene: Scene;
  operationCount: number;
}

export interface AgentChatMessage {
  id: string;
  role: "user" | "agent" | "system";
  content: string;
  /** Present on the "Accepted N changes" message of an accepted turn —
   * renders the Compare | Revert row beneath it. */
  turn?: AcceptedTurnRecord;
}

/** Phase 2a (Moda's queue): a message typed while the editor is busy —
 * agent running or review pending — waiting to run as the next turn. */
export interface QueuedAgentMessage {
  id: string;
  content: string;
}

export interface AgentChatPanelProps {
  messages: AgentChatMessage[];
  draft: string;
  isRunning: boolean;
  proposal: EditorAgentResult | null;
  /** Phase 0c: a proposed turn is on the canvas awaiting Accept / Reject. */
  pendingReview: boolean;
  queuedMessages: QueuedAgentMessage[];
  /** 2b show-work: live run events driving the Moda plan checklist. */
  runEvents: AgentRunEvent[];
  /** 2c: the chipped edit targets sent with the next turn. */
  targetChips: TargetChip[];
  /** 2d: the active past-turn compare view (null = viewing the live design). */
  compareView: CompareView | null;
  /** 2d: checkpoints no longer on the active history path (already reverted). */
  invalidCheckpoints: ReadonlySet<string>;
  isReverting: boolean;
  /** 2e: post-turn suggestion chips (static heuristics); clicking fills the
   * composer draft, never auto-sends. */
  suggestions: string[];
  /** 2e: per-document standing instructions (sent with every turn; Save
   * persists them on the document). */
  standingInstructions: {
    draft: string;
    dirty: boolean;
    saving: boolean;
    canSave: boolean;
    error: string | null;
    onDraftChange: (value: string) => void;
    onSave: () => void;
  };
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  diagnostics: Diagnostic[];
  onRemoveTargetChip: (id: NodeId) => void;
  onClearTargetChips: () => void;
  onDraftChange: (value: string) => void;
  onSend: (prompt: string) => void;
  onQueueMessage: (content: string) => void;
  onRemoveQueuedMessage: (id: string) => void;
  onApplyProposal: () => void;
  onAcceptProposal: () => void;
  onRejectProposal: () => void;
  onCompareTurn: (turn: AcceptedTurnRecord, view: "before" | "after") => void;
  onExitCompare: () => void;
  onRevertTurn: (turn: AcceptedTurnRecord) => void;
}

export function AgentChatPanel({
  messages,
  draft,
  isRunning,
  proposal,
  pendingReview,
  queuedMessages,
  runEvents,
  targetChips,
  compareView,
  invalidCheckpoints,
  isReverting,
  suggestions,
  standingInstructions,
  activePageId,
  selectedNodeId,
  diagnostics,
  onRemoveTargetChip,
  onClearTargetChips,
  onDraftChange,
  onSend,
  onQueueMessage,
  onRemoveQueuedMessage,
  onApplyProposal,
  onAcceptProposal,
  onRejectProposal,
  onCompareTurn,
  onExitCompare,
  onRevertTurn
}: AgentChatPanelProps) {
  const isBusy = isRunning || pendingReview;
  // 2e Design-Plan pre-brief: form values live here (view state); the prompt
  // composition is the pure engine helper. Applies to direct sends only —
  // queued messages stay verbatim so their chips read as typed.
  const [brief, setBrief] = useState<DesignBrief>(EMPTY_BRIEF);
  const submitPrompt = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) {
      return;
    }
    // While the editor is busy the composer queues instead of sending —
    // Moda's "Type to queue a message…" behavior.
    if (isBusy) {
      onQueueMessage(trimmed);
      onDraftChange("");
      return;
    }
    onSend(composeBriefPrompt(brief, trimmed));
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
      <details className="agent-standing-instructions">
        <summary>
          Standing instructions
          {standingInstructions.draft.trim() ? <em> · active</em> : null}
        </summary>
        <label className="field">
          <span>Applied to every turn on this document</span>
          <textarea
            value={standingInstructions.draft}
            onChange={(event) => standingInstructions.onDraftChange(event.target.value)}
            placeholder="e.g. Always use the serif brand voice; keep CTAs under five words."
            rows={3}
          />
        </label>
        <div className="agent-standing-instructions-actions">
          <button
            type="button"
            disabled={
              !standingInstructions.canSave ||
              !standingInstructions.dirty ||
              standingInstructions.saving
            }
            onClick={standingInstructions.onSave}
          >
            {standingInstructions.saving ? "Saving…" : "Save to document"}
          </button>
          <span className="muted">
            {standingInstructions.error
              ? standingInstructions.error
              : !standingInstructions.canSave
                ? "Saves automatically once the design becomes a document."
                : standingInstructions.dirty
                  ? "Unsaved — still sent with every turn."
                  : "Saved with the document."}
          </span>
        </div>
      </details>
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
              {message.turn ? (
                <TurnActionsRow
                  turn={message.turn}
                  compareView={compareView}
                  invalid={
                    message.turn.checkpoint !== null &&
                    invalidCheckpoints.has(message.turn.checkpoint)
                  }
                  busy={isRunning || pendingReview || isReverting}
                  onCompareTurn={onCompareTurn}
                  onExitCompare={onExitCompare}
                  onRevertTurn={onRevertTurn}
                />
              ) : null}
            </article>
          ))
        )}
      </div>
      {runEvents.length > 0 || isRunning ? (
        <AgentRunChecklist runEvents={runEvents} isRunning={isRunning} />
      ) : null}
      {proposal ? (
        <AgentProposalCard
          proposal={proposal}
          isRunning={isRunning}
          pendingReview={pendingReview}
          onApplyProposal={onApplyProposal}
          onAcceptProposal={onAcceptProposal}
          onRejectProposal={onRejectProposal}
        />
      ) : null}
      {queuedMessages.length > 0 ? (
        <div className="agent-queued-messages" aria-label="Queued messages">
          <span className="agent-queued-label">
            Queued — runs when the agent is free
          </span>
          {queuedMessages.map((message) => (
            <div key={message.id} className="agent-queued-message">
              <p>{message.content}</p>
              <button
                type="button"
                aria-label={`Remove queued message: ${message.content}`}
                onClick={() => onRemoveQueuedMessage(message.id)}
              >
                <X aria-hidden size={13} />
              </button>
            </div>
          ))}
        </div>
      ) : null}
      {targetChips.length > 0 ? (
        <div className="agent-target-chips" aria-label="Edit targets">
          <span className="agent-target-chips-label">
            <Crosshair aria-hidden size={12} />
            Editing {targetChips.length === 1 ? "this layer" : `${targetChips.length} layers`}
            <button type="button" className="agent-target-chips-clear" onClick={onClearTargetChips}>
              Clear
            </button>
          </span>
          <div className="agent-target-chip-row">
            {targetChips.map((chip) => (
              <span key={chip.id} className="agent-target-chip" title={chip.id}>
                <span className="agent-target-chip-name">{chip.name}</span>
                <code className="agent-target-chip-id">{chip.id}</code>
                <button
                  type="button"
                  aria-label={`Remove edit target: ${chip.name}`}
                  onClick={() => onRemoveTargetChip(chip.id)}
                >
                  <X aria-hidden size={12} />
                </button>
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {!isBusy && suggestions.length > 0 && messages.some((message) => message.role !== "user") ? (
        <div className="agent-suggestions" aria-label="Suggested follow-ups">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="agent-suggestion-chip"
              onClick={() => onDraftChange(suggestion)}
            >
              <Sparkles aria-hidden size={12} />
              {suggestion}
            </button>
          ))}
        </div>
      ) : null}
      <details className="agent-prebrief">
        <summary>
          Design brief (optional)
          {!briefIsEmpty(brief) ? <em> · set</em> : null}
        </summary>
        <div className="agent-prebrief-grid">
          <label className="field">
            <span>Variations</span>
            <select
              value={brief.variations}
              onChange={(event) =>
                setBrief({ ...brief, variations: Number(event.target.value) })
              }
            >
              <option value={1}>1 design</option>
              <option value={2}>2 concepts (as pages)</option>
              <option value={3}>3 concepts (as pages)</option>
              <option value={4}>4 concepts (as pages)</option>
            </select>
          </label>
          <label className="field">
            <span>Brand adherence</span>
            <select
              value={brief.brandAdherence}
              onChange={(event) =>
                setBrief({
                  ...brief,
                  brandAdherence: event.target.value as DesignBrief["brandAdherence"]
                })
              }
            >
              <option value="">No preference</option>
              <option value="strict">Strict</option>
              <option value="flexible">Flexible</option>
            </select>
          </label>
          <label className="field">
            <span>Focus</span>
            <input
              type="text"
              value={brief.focus}
              placeholder="e.g. the discount, the venue photo"
              onChange={(event) => setBrief({ ...brief, focus: event.target.value })}
            />
          </label>
          <label className="field">
            <span>Call to action</span>
            <input
              type="text"
              value={brief.cta}
              placeholder="e.g. Book your seat"
              onChange={(event) => setBrief({ ...brief, cta: event.target.value })}
            />
          </label>
        </div>
        <p className="muted">Folded into your next sent message; queued messages stay as typed.</p>
      </details>
      <form className="agent-chat-form" onSubmit={submitPrompt}>
        <label className="field">
          <span>Message the agent</span>
          <textarea
            value={draft}
            onChange={(event) => onDraftChange(event.target.value)}
            placeholder={
              isRunning
                ? "Type to queue a message — it runs when the agent finishes."
                : pendingReview
                  ? "Type to queue a message — it runs after you accept or reject."
                  : "Ask for a square ad, repair overflow, or update the selected section."
            }
            rows={4}
          />
        </label>
        <button type="submit" disabled={!draft.trim()}>
          <Send aria-hidden size={15} />
          {isBusy ? "Queue" : "Send"}
        </button>
      </form>
    </section>
  );
}

/**
 * 2d: the Compare | Revert row under an accepted turn's message. Compare
 * opens the read-only before/after view of THAT turn; Revert (two-step
 * inline confirm, no browser dialogs) undoes every later change batch via
 * the server checkpoint. A checkpoint that left the active history path
 * (already reverted) renders disabled with an honest reason.
 */
function TurnActionsRow({
  turn,
  compareView,
  invalid,
  busy,
  onCompareTurn,
  onExitCompare,
  onRevertTurn
}: {
  turn: AcceptedTurnRecord;
  compareView: CompareView | null;
  invalid: boolean;
  busy: boolean;
  onCompareTurn: (turn: AcceptedTurnRecord, view: "before" | "after") => void;
  onExitCompare: () => void;
  onRevertTurn: (turn: AcceptedTurnRecord) => void;
}) {
  const [confirmingRevert, setConfirmingRevert] = useState(false);
  const comparingThisTurn = compareView?.key === turn.key;

  if (invalid) {
    return (
      <div className="turn-actions" aria-label="Turn actions">
        <span
          className="turn-actions-invalid"
          title="This turn is no longer on the active history path (a revert removed it)."
        >
          <History aria-hidden size={13} />
          No longer revertible
        </span>
      </div>
    );
  }

  if (comparingThisTurn) {
    return (
      <div className="turn-actions" aria-label="Turn actions">
        <span className="turn-actions-comparing">
          <Eye aria-hidden size={13} />
          Comparing this turn
        </span>
        <button type="button" onClick={onExitCompare}>
          Back to current
        </button>
      </div>
    );
  }

  if (confirmingRevert) {
    return (
      <div className="turn-actions" aria-label="Turn actions">
        <span className="turn-actions-confirm">
          Undo everything after this turn?
        </span>
        <button
          type="button"
          className="turn-actions-danger"
          disabled={busy}
          onClick={() => {
            setConfirmingRevert(false);
            onRevertTurn(turn);
          }}
        >
          Confirm revert
        </button>
        <button type="button" onClick={() => setConfirmingRevert(false)}>
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="turn-actions" aria-label="Turn actions">
      <button
        type="button"
        disabled={busy || Boolean(compareView)}
        onClick={() => onCompareTurn(turn, "before")}
      >
        <Eye aria-hidden size={13} />
        Compare
      </button>
      {turn.checkpoint === null ? (
        // The batch got no server envelope (this Accept created the
        // document) — there is no anchor to revert to, so never offer it.
        <span
          className="turn-actions-invalid"
          title="This turn created the document; there is no earlier server state to unwind to."
        >
          <History aria-hidden size={13} />
          Not revertible (created the document)
        </span>
      ) : (
        <button
          type="button"
          disabled={busy || Boolean(compareView)}
          onClick={() => setConfirmingRevert(true)}
        >
          <History aria-hidden size={13} />
          Revert…
        </button>
      )}
    </div>
  );
}

/**
 * Moda's "show work" plan checklist (§1.6): live stage ticks while the agent
 * designs, collapsing behind a "Show work" disclosure once the run settles so
 * the finished conversation stays clean. Pure render — the stage mapping lives
 * in engine/agentChecklist.
 */
function AgentRunChecklist({
  runEvents,
  isRunning
}: {
  runEvents: AgentRunEvent[];
  isRunning: boolean;
}) {
  const steps = agentChecklist(runEvents, isRunning);
  if (steps.length === 0) {
    return null;
  }
  return (
    <div className="agent-run-checklist" aria-label="Agent plan" data-running={isRunning}>
      <ol className="agent-checklist-steps">
        {steps.map((step) => (
          <li key={step.key} className={`agent-checklist-step ${step.status}`}>
            {step.status === "active" ? (
              <Loader2 aria-hidden size={14} className="agent-checklist-spinner" />
            ) : (
              <CheckCircle2 aria-hidden size={14} />
            )}
            <span>{step.label}</span>
          </li>
        ))}
      </ol>
      {runEvents.length > 0 ? (
        <details className="agent-run-worklog">
          <summary>Show work</summary>
          <ol className="agent-worklog-list">
            {runEvents
              .filter((event) => event.type !== "run_started")
              .map((event) => (
                <li key={`${event.seq}-${event.type}`}>{agentEventLabel(event)}</li>
              ))}
          </ol>
        </details>
      ) : null}
    </div>
  );
}

function AgentProposalCard({
  proposal,
  isRunning,
  pendingReview,
  onApplyProposal,
  onAcceptProposal,
  onRejectProposal
}: {
  proposal: EditorAgentResult;
  isRunning: boolean;
  pendingReview: boolean;
  onApplyProposal: () => void;
  onAcceptProposal: () => void;
  onRejectProposal: () => void;
}) {
  const canApply = proposal.status === "proposed" && proposal.operations.length > 0;
  const hasDraftScene = Boolean(proposal.draft_scene);
  return (
    <div className={`agent-proposal ${proposal.status}${pendingReview ? " reviewing" : ""}`}>
      <div className="agent-proposal-heading">
        {pendingReview ? (
          <Eye aria-hidden size={15} />
        ) : proposal.status === "proposed" ? (
          <CheckCircle2 aria-hidden size={15} />
        ) : (
          <AlertTriangle aria-hidden size={15} />
        )}
        <strong>
          {pendingReview
            ? "Reviewing changes"
            : proposal.status === "proposed"
              ? "Proposal ready"
              : hasDraftScene
                ? "Draft visible"
                : "Agent blocked"}
        </strong>
        {proposal.acceptance_scope === "edit" ? (
          <span className="agent-scope-chip" title="The agent verified the requested edit; remaining review notes are advisory.">
            Edit-scoped
          </span>
        ) : null}
      </div>
      <p>{proposal.summary}</p>
      {pendingReview ? (
        <p className="muted">
          The changes are on the canvas. Compare Before/After, then Accept to keep them or Reject to
          restore the previous design.
        </p>
      ) : null}
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
          {proposal.diagnostics.slice(0, 6).map((diagnostic, index) => (
            // Index-qualified: the Phase A repair loop can emit the same
            // diagnostic (code + message) across iterations, so code+message
            // alone is not unique.
            <li
              key={`${index}-${diagnostic.code}-${diagnostic.message}`}
              className={isAdvisoryDiagnostic(diagnostic) ? "advisory" : undefined}
            >
              {isAdvisoryDiagnostic(diagnostic) ? (
                <code className="advisory-chip">Advisory</code>
              ) : (
                <code>{diagnostic.code}</code>
              )}
              <span>{diagnostic.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {proposal.artifacts.length > 0 ? (
        <ul className="agent-artifact-list" aria-label="Agent artifacts">
          {proposal.artifacts.map((artifact, index) => (
            // Index-qualified: repair iterations emit the same artifact path
            // (e.g. preview.svg/preview.png) more than once.
            <li key={`${index}-${artifact.path ?? artifact.filename ?? "artifact"}`}>
              {artifact.format ?? "artifact"} {artifact.filename ?? artifact.path ?? "preview"}
            </li>
          ))}
        </ul>
      ) : null}
      {pendingReview ? (
        <div className="agent-proposal-review-actions">
          <button type="button" className="agent-review-reject" onClick={onRejectProposal}>
            <X aria-hidden size={15} />
            Reject
          </button>
          <button type="button" className="agent-review-accept" onClick={onAcceptProposal}>
            <Check aria-hidden size={15} />
            Accept
          </button>
        </div>
      ) : (
        <button type="button" onClick={onApplyProposal} disabled={!canApply || isRunning}>
          {proposal.status === "failed" && hasDraftScene ? "Draft already shown" : "Review changes"}
        </button>
      )}
    </div>
  );
}

function isAdvisoryDiagnostic(diagnostic: Diagnostic): boolean {
  return diagnostic.code === "agent_runtime.visual_critique_advisory";
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
