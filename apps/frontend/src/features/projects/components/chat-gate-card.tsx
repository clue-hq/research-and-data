import {
  Confirmation,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRequest,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
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
 * `unavailable` is the honest fourth state. A gate can only be answered by
 * echoing back the subject digest and the server-derived maximum spend; when
 * this deployment served neither, the card shows the request, disables the
 * controls, and says why — instead of offering a button whose click the server
 * would refuse.
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
}: {
  busy?: boolean;
  card: GateCardModel;
  onDecide: (card: GateCardModel, decision: GateDecision) => void;
}) {
  const amount = formatCents(card.amountCents, card.currency);
  const answerable = card.state === "requested" && !busy;

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
        <ConfirmationActions className={styles.planApprovalActions}>
          {card.permittedDecisions.map((decision) => (
            <ConfirmationAction
              className={decision === "approved" ? styles.acceptButton : undefined}
              disabled={!answerable}
              key={decision}
              onClick={() => onDecide(card, decision)}
            >
              {DECISION_COPY[decision]}
            </ConfirmationAction>
          ))}
        </ConfirmationActions>
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
        </div>
      ) : null}
    </Confirmation>
  );
}
