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
  type ProductSelectionOption,
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

/**
 * The set-valued product gate's groups, in the order the card shows them.
 *
 * The headings are plain language, not the catalog's `offering_kind` strings:
 * a marketer reads "Partner programs", never `partner_program`. Anything the
 * catalog does not classify — or classifies with a kind we do not know — falls
 * into "Other" rather than disappearing off the card.
 */
const PRODUCT_SET_GROUPS = [
  { heading: "Products", kind: "product" },
  { heading: "Platforms", kind: "platform" },
  { heading: "Integrations", kind: "integration" },
  { heading: "Partner programs", kind: "partner_program" },
  { heading: "Services", kind: "service" },
  { heading: "Other", kind: "other" },
] as const;

const PRODUCT_SET_KINDS: ReadonlySet<string> = new Set(
  PRODUCT_SET_GROUPS.map((group) => group.kind),
);

function productSetGroups(
  options: readonly ProductSelectionOption[],
): ReadonlyArray<{ heading: string; options: readonly ProductSelectionOption[] }> {
  return PRODUCT_SET_GROUPS.map((group) => ({
    heading: group.heading,
    options: options.filter((option) =>
      group.kind === "other"
        ? option.offeringKind === null || !PRODUCT_SET_KINDS.has(option.offeringKind)
        : option.offeringKind === group.kind,
    ),
  })).filter((group) => group.options.length > 0);
}

/** The card's own state, mapped onto the vendored primitive's lifecycle. */
const PRIMITIVE_STATE = {
  requested: "approval-requested",
  responded: "approval-responded",
  denied: "output-denied",
  withdrawn: "output-denied",
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
  // The boxes start where the durable record says they start: an answered gate
  // shows the ids the human actually chose, an open one the project's saved
  // selection or — failing that — the agent's suggestion. From then on they are
  // the human's. An archived row can never be checked.
  const [checkedProductIds, setCheckedProductIds] = useState<ReadonlySet<string>>(() => {
    if (card.productSet === null) return new Set<string>();
    // An answered gate is a receipt: it shows exactly the ids that were
    // recorded, unfiltered. Only a *pre-check* has to skip archived rows.
    if (card.productSet.selectedIds.length > 0) {
      return new Set(card.productSet.selectedIds);
    }
    return new Set(
      card.productSet.preselectedIds.filter((productId) =>
        card.productSet?.options.some(
          (option) => option.productId === productId && option.status !== "archived",
        ),
      ),
    );
  });
  const amount =
    card.kind === "product_selection" || card.kind === "product_set_selection"
      ? null
      : formatCents(card.amountCents, card.currency);
  const answerable = card.state === "requested" && !busy;
  const revisionText = revisionRequest.trim();
  const productSet = card.productSet;
  // Emitted in the card's own order, so the list the server records is the list
  // the human read top to bottom.
  const chosenProductIds = (productSet?.options ?? [])
    .filter((option) => checkedProductIds.has(option.productId))
    .map((option) => option.productId);
  const answeredProductNames = (productSet?.options ?? [])
    .filter((option) => productSet?.selectedIds.includes(option.productId))
    .map((option) => option.name)
    .join(", ");

  function toggleProduct(productId: string) {
    setCheckedProductIds((current) => {
      const next = new Set(current);
      if (next.has(productId)) next.delete(productId);
      else next.add(productId);
      return next;
    });
  }

  function choose(decision: GateDecision) {
    if (decision === "revised" && card.revisionKind !== null) {
      setRevising(true);
      return;
    }
    if (decision === "approved" && card.kind === "product_set_selection") {
      onDecide(card, {
        kind: "product_set_selection",
        decision: "approved",
        selectedProductIds: chosenProductIds,
      });
      return;
    }
    onDecide(card, { kind: "decision", decision });
  }

  function submitRevision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!answerable || !revisionText) return;
    onDecide(card, {
      kind: card.revisionKind === "discovery"
        ? "discovery_revision"
        : "icp_revision",
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
        {card.kind === "product_set_selection" && productSet !== null ? (
          <div className={styles.productSetGroups}>
            {productSetGroups(productSet.options).map((group) => (
              <div className={styles.productSetGroup} key={group.heading}>
                <div className={styles.productSetGroupHeading}>{group.heading}</div>
                {group.options.map((option) => {
                  const archived = option.status === "archived";
                  return (
                    <label
                      className={styles.productSetOption}
                      data-archived={archived ? "true" : undefined}
                      key={option.productId}
                    >
                      <input
                        checked={checkedProductIds.has(option.productId)}
                        disabled={!answerable || archived}
                        onChange={() => toggleProduct(option.productId)}
                        type="checkbox"
                      />
                      <span className={styles.productSetOptionBody}>
                        <span className={styles.productSetOptionName}>
                          <strong>{option.name}</strong>
                          {option.possibleDuplicate ? (
                            <span
                              className={styles.productSetDuplicate}
                              title={option.duplicateReason ?? undefined}
                            >
                              Possible duplicate
                            </span>
                          ) : null}
                        </span>
                        {option.shortDescription ? (
                          <span>{option.shortDescription}</span>
                        ) : null}
                        {option.family ? (
                          <span className={styles.productSetOptionMeta}>
                            {option.family}
                          </span>
                        ) : null}
                        {option.lifecycle && option.lifecycle !== "active" ? (
                          <small className={styles.productSetOptionMeta}>
                            {option.lifecycle}
                          </small>
                        ) : null}
                      </span>
                    </label>
                  );
                })}
              </div>
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
                  disabled={
                    !answerable ||
                    (decision === "approved" &&
                      card.kind === "product_set_selection" &&
                      chosenProductIds.length === 0)
                  }
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
              placeholder={
                card.revisionKind === "discovery"
                  ? "For example: start with 50 accounts and exclude current customers."
                  : "For example: focus on multi-site practices with at least three providers."
              }
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
            {answeredProductNames ? ` — ${answeredProductNames}` : ""}
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
