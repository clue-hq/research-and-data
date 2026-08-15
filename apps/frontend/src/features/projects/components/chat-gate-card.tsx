"use client";

import {
  Confirmation,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRequest,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import { useId, useState, type FormEvent } from "react";
import type { GateDecision } from "../model/chat-parts";
import {
  formatCents,
  gateDecisionCopy,
  type GateDecisionInput,
  type GateCardModel,
} from "../model/chat-gate";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

/**
 * The approval card — charter §3.1's `gate` row, driven by the durable object.
 *
 * All four states render, and an answered gate **stays in history** with its
 * controls disabled and the recorded decision on it. That is the point of the
 * ratified two-record substrate: a gate is answered exactly once, and the
 * answer is a durable receipt rather than a card that disappears.
 *
 * `unavailable` is the honest fourth state. It has no decision controls at all:
 * the card becomes a **Human action required** notice with either a durable-read
 * retry or a request for Stage 0 to create a fresh proposal. That keeps a
 * model-only ref from looking one disabled-button toggle away from authority.
 *
 * The cost line is conditional and stays conditional. `formatCents` returns
 * null for a null amount — it never coerces to `0` — so a gate whose amount was
 * withheld (pilot budget controls off) renders *no* cost row: no `$0.00`, no
 * empty currency, no dash standing in for a number nobody may see.
 */

/** The card's own state, mapped onto the vendored primitive's lifecycle. */
const PRIMITIVE_STATE = {
  requested: "approval-requested",
  responded: "approval-responded",
  denied: "output-denied",
  unavailable: "approval-requested",
} as const;

export function ChatGateCard({
  busy = false,
  card,
  onDecide,
  onRecover,
}: {
  busy?: boolean;
  card: GateCardModel;
  onDecide: (card: GateCardModel, input: GateDecisionInput) => void;
  onRecover: (card: GateCardModel) => void;
}) {
  const revisionFieldId = useId();
  const [revising, setRevising] = useState(false);
  const [revisionRequest, setRevisionRequest] = useState("");
  const amount =
    card.kind === "product_selection"
      ? null
      : formatCents(card.amountCents, card.currency);
  const answerable = card.state === "requested" && !busy;
  const revisionText = revisionRequest.trim();

  function choose(decision: GateDecision) {
    if (decision === "revised" && card.kind === "icp_confirmation") {
      setRevising(true);
      return;
    }
    onDecide(card, { kind: "decision", decision });
  }

  function submitRevision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!answerable || !revisionText) return;
    onDecide(card, {
      kind: "icp_revision",
      decision: "revised",
      revisionRequest: revisionText,
    });
  }

  return (
    <Confirmation
      approval={{
        id: card.gateId,
        ...(card.decision === null ? {} : { approved: card.decision === "approved" }),
      }}
      className={styles.planApproval}
      data-gate-kind={card.kind}
      data-gate-state={card.state}
      state={PRIMITIVE_STATE[card.state]}
    >
      <ConfirmationRequest>
        <ConfirmationTitle className={styles.planApprovalTitle}>
          <ProjectIcon name="file-text" size={16} />
          {card.title}
          {amount ? <em> — up to {amount}</em> : null}
        </ConfirmationTitle>
        {card.summary ? <p className={styles.messageText}>{card.summary}</p> : null}
        {card.state === "unavailable" ? (
          <p className={styles.messageText} role="note">
            {card.unavailableReason}
          </p>
        ) : null}
        {card.kind === "product_selection" && card.productOptions.length > 0 ? (
          <div className={styles.productSelectionOptions}>
            {card.productOptions.map((product) => (
              <button
                className={styles.productSelectionOption}
                disabled={!answerable}
                key={product.productId}
                onClick={() =>
                  onDecide(card, {
                    kind: "product_selection",
                    decision: "approved",
                    selectedProductId: product.productId,
                  })
                }
                type="button"
              >
                <strong>{product.name}</strong>
                <span>{product.shortDescription}</span>
              </button>
            ))}
          </div>
        ) : null}
        {card.state === "requested" && !revising ? (
          <ConfirmationActions className={styles.planApprovalActions}>
            {card.permittedDecisions
              .filter(
                (decision) =>
                  card.kind !== "product_selection" || decision !== "approved",
              )
              .map((decision) => (
                <ConfirmationAction
                  className={
                    decision === "approved"
                      ? styles.acceptButton
                      : decision === "rejected"
                        ? styles.gateRejectButton
                        : undefined
                  }
                  disabled={!answerable}
                  key={decision}
                  onClick={() => choose(decision)}
                >
                  {gateDecisionCopy(card.kind, decision)}
                </ConfirmationAction>
              ))}
          </ConfirmationActions>
        ) : null}
        {card.state === "requested" && revising ? (
          <form className={styles.gateRevisionForm} onSubmit={submitRevision}>
            <label htmlFor={revisionFieldId}>
              What would you like changed?
            </label>
            <textarea
              autoFocus
              id={revisionFieldId}
              maxLength={4_000}
              onChange={(event) => setRevisionRequest(event.target.value)}
              placeholder="For example: focus on multi-site practices with at least three providers."
              rows={3}
              value={revisionRequest}
            />
            <div className={styles.gateRevisionFooter}>
              <small>{revisionRequest.length}/4000</small>
              <button
                disabled={busy}
                onClick={() => {
                  setRevising(false);
                  setRevisionRequest("");
                }}
                type="button"
              >
                Cancel
              </button>
              <button disabled={!answerable || !revisionText} type="submit">
                Send changes
              </button>
            </div>
          </form>
        ) : null}
        {card.state === "unavailable" && card.recovery ? (
          <ConfirmationActions className={styles.planApprovalActions}>
            <ConfirmationAction
              disabled={busy}
              onClick={() => onRecover(card)}
            >
              {card.recovery.label}
            </ConfirmationAction>
          </ConfirmationActions>
        ) : null}
      </ConfirmationRequest>
      {card.decision ? (
        <div className={styles.planApprovalTitle} data-decision={card.decision}>
          <ProjectIcon
            name={card.decision === "approved" ? "status-check" : "close"}
            size={14}
          />
          <span>
            {gateDecisionCopy(card.kind, card.decision, true)}
            {card.selectedProductName ? ` — ${card.selectedProductName}` : ""}
            {amount && card.decision === "approved" ? ` — up to ${amount}` : ""}
          </span>
          {card.launches.length > 0 ? (
            <small>
              {card.launches.length === 1
                ? "1 research run launched"
                : `${card.launches.length} research runs launched`}
            </small>
          ) : null}
          {card.revisionRequest ? (
            <small>{`Requested changes: ${card.revisionRequest}`}</small>
          ) : null}
        </div>
      ) : null}
    </Confirmation>
  );
}
