"use client";

import {
  Confirmation,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRequest,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import { useState, type FormEvent } from "react";
import type { GateDecision } from "../model/chat-parts";
import { formatCents, type GateCardModel } from "../model/chat-gate";
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

const DECISION_COPY: Record<GateDecision, string> = {
  approved: "Approve",
  rejected: "Reject",
  revised: "Revise",
};

const DECISION_RECORDED: Record<GateDecision, string> = {
  approved: "Approved",
  rejected: "Rejected",
  revised: "Revision requested",
};

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
  onDecide: (
    card: GateCardModel,
    decision: GateDecision,
    revisionRequest?: string,
  ) => void;
  onRecover: (card: GateCardModel) => void;
}) {
  const [revising, setRevising] = useState(false);
  const [revisionRequest, setRevisionRequest] = useState("");
  const amount = formatCents(card.amountCents, card.currency);
  const answerable = card.state === "requested" && !busy;
  const revisionText = revisionRequest.trim();

  function choose(decision: GateDecision) {
    if (decision === "revised" && card.kind === "icp_confirmation") {
      setRevising(true);
      return;
    }
    onDecide(card, decision);
  }

  function submitRevision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!answerable || !revisionText) return;
    onDecide(card, "revised", revisionText);
  }

  return (
    <Confirmation
      approval={{
        id: card.gateId,
        ...(card.decision === null ? {} : { approved: card.decision === "approved" }),
      }}
      className={styles.planApproval}
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
        {card.state === "requested" && !revising ? (
          <ConfirmationActions className={styles.planApprovalActions}>
            {card.permittedDecisions.map((decision) => (
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
                {DECISION_COPY[decision]}
              </ConfirmationAction>
            ))}
          </ConfirmationActions>
        ) : null}
        {card.state === "requested" && revising ? (
          <form className={styles.gateRevisionForm} onSubmit={submitRevision}>
            <label htmlFor={`gate-revision-${card.gateId}`}>
              Requested ICP changes
            </label>
            <textarea
              autoFocus
              id={`gate-revision-${card.gateId}`}
              maxLength={4_000}
              onChange={(event) => setRevisionRequest(event.target.value)}
              placeholder="Describe what Stage 0 should change in the next ICP version."
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
                Request revision
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
            {DECISION_RECORDED[card.decision]}
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
