import { z } from "zod";
import {
  GateDecisionSchema,
  parseCentAmount,
  type ChatGatePart,
  type GateDecision,
} from "./chat-parts";
import type { GateResponse } from "./chat-turn";
import { profileDisplayName } from "./chat-tool-presentation";
import {
  CRM_WRITE_GATE_KIND,
  crmProposalIdOf,
  crmWriteCard,
  type CrmWriteAnswer,
  type CrmWriteCardModel,
} from "@/features/integrations/model/crm-write";

const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const DURABLE_GATE_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * The durable gate object the approval card renders (charter §3-P5(a), §3.4).
 *
 * **Why this is a repository read and not just the stream part.** A gate is
 * answered by echoing back exactly what was on the screen: `gate_response`
 * requires `expected_subject_sha256` and, for spend-bearing gates only,
 * `expected_estimated_cost_cents`; the server refuses anything that does not
 * match the immutable gate row. The
 * `gate` part the turn stream currently emits carries only the ref, the kind
 * and `state="requested"` (`conversation_turns.py::_project_turn_close` passes
 * nothing else), so the stream alone cannot produce an answerable card. The
 * durable read is therefore the authority for the card's payload, and the
 * stream part is the *signal that a card exists*.
 *
 * The shape mirrors the `thread_gates` projection (`GateView` in
 * `clue_projections/gates.py`) member for member, so the read is a faithful
 * projection of something that already exists rather than a new contract.
 */

const GateAnswerWireSchema = z.object({
  turn_id: z.string(),
  action_ref: z.string(),
  decision: z.string(),
  expected_subject_sha256: z.string().regex(SHA256_PATTERN),
  decision_payload: z.record(z.string(), z.unknown()).default({}),
  selected_option_ref: z.string().nullable().default(null),
  answered_by_user_id: z.string(),
  answered_at: z.string(),
});

const GateLaunchWireSchema = z.object({
  research_run_id: z.string(),
  run_kind: z.string(),
  run_state: z.string(),
  source_action_ref: z.string(),
  approval_refs: z.array(z.string()).default([]),
});

const GateWireSchema = z.object({
  gate_id: z.string().regex(DURABLE_GATE_ID_PATTERN),
  workspace_id: z.string().min(1),
  project_id: z.string().min(1),
  thread_id: z.string().min(1),
  turn_id: z.string().min(1),
  kind: z.string().min(1),
  subject_ref: z.string().min(1),
  subject_revision: z.number().int().nullable().default(null),
  expected_subject_sha256: z.string().regex(SHA256_PATTERN),
  subject_snapshot: z.record(z.string(), z.unknown()).default({}),
  permitted_decisions: z.array(GateDecisionSchema),
  // Optional because the amount is *withheld*, not missing: with the pilot's
  // `CLUE_BUDGET_CONTROLS_ENABLED` off no cost number may reach a human
  // surface, so the route serves `null` while the immutable gate row keeps its
  // `max_spend_cents`. Null rather than `"0"`/`""` deliberately — a withheld
  // amount must never be readable as a real one, and the card must render no
  // cost row at all rather than a fabricated zero.
  max_spend_cents: z.union([z.number(), z.string()]).nullish().default(null),
  currency: z.string().nullable(),
  addressee_user_id: z.string().min(1),
  created_at: z.string(),
  snapshot_erased_at: z.string().nullable().default(null),
  snapshot_erasure_reason: z.string().nullable().default(null),
  answer: GateAnswerWireSchema.nullable().default(null),
  launches: z.array(GateLaunchWireSchema).default([]),
  // Nobody answered it and it can no longer be answered: a newer CRM write card replaced it, or a
  // reconnect closed it (`GATE_WITHDRAWN_SQL`). Never shown as waiting.
  withdrawn: z.boolean().default(false),
});

export interface ChatGateAnswer {
  turnId: string;
  actionRef: string;
  decision: string;
  expectedSubjectSha256: string;
  decisionPayload: Record<string, unknown>;
  selectedOptionRef: string | null;
  answeredByUserId: string;
  answeredAt: string;
}

export interface ChatGateLaunch {
  researchRunId: string;
  runKind: string;
  runState: string;
  sourceActionRef: string;
  approvalRefs: readonly string[];
}

export interface ChatGate {
  gateId: string;
  workspaceId: string;
  projectId: string;
  threadId: string;
  /** The turn that *presented* the gate — not the turn that answered it. */
  turnId: string;
  kind: string;
  subjectRef: string;
  subjectRevision: number | null;
  expectedSubjectSha256: string;
  subjectSnapshot: Record<string, unknown>;
  maxSpendCents: number | null;
  currency: string | null;
  permittedDecisions: readonly GateDecision[];
  addresseeUserId: string;
  createdAt: string;
  snapshotErasedAt: string | null;
  snapshotErasureReason: string | null;
  answer: ChatGateAnswer | null;
  launches: readonly ChatGateLaunch[];
  withdrawn: boolean;
}

export interface GateAnswerDisplay {
  detail: string | null;
  label: string;
}

/**
 * The UI intent for one gate answer. Auxiliary text and product identity live
 * in distinct variants, so neither can be mistaken for the other at a call
 * site or serialized onto the wrong gate kind.
 */
export type GateDecisionInput =
  | { kind: "decision"; decision: GateDecision }
  | {
      kind: "icp_revision";
      decision: "revised";
      revisionRequest: string;
    }
  | {
      kind: "discovery_revision";
      decision: "revised";
      revisionRequest: string;
    }
  | {
      kind: "product_selection";
      decision: "approved";
      selectedProductId: string;
    }
  | {
      kind: "product_set_selection";
      decision: "approved";
      selectedProductIds: readonly string[];
    }
  | {
      kind: "crm_write";
      decision: "approved";
      answer: CrmWriteAnswer;
    };

function toGate(wire: z.infer<typeof GateWireSchema>): ChatGate {
  return {
    gateId: wire.gate_id,
    workspaceId: wire.workspace_id,
    projectId: wire.project_id,
    threadId: wire.thread_id,
    turnId: wire.turn_id,
    kind: wire.kind,
    subjectRef: wire.subject_ref,
    subjectRevision: wire.subject_revision,
    expectedSubjectSha256: wire.expected_subject_sha256,
    subjectSnapshot: wire.subject_snapshot,
    maxSpendCents: parseCentAmount(wire.max_spend_cents),
    currency: wire.currency,
    permittedDecisions: wire.permitted_decisions,
    addresseeUserId: wire.addressee_user_id,
    createdAt: wire.created_at,
    snapshotErasedAt: wire.snapshot_erased_at,
    snapshotErasureReason: wire.snapshot_erasure_reason,
    answer:
      wire.answer === null
        ? null
        : {
            turnId: wire.answer.turn_id,
            actionRef: wire.answer.action_ref,
            decision: wire.answer.decision,
            expectedSubjectSha256: wire.answer.expected_subject_sha256,
            decisionPayload: wire.answer.decision_payload,
            selectedOptionRef: wire.answer.selected_option_ref,
            answeredByUserId: wire.answer.answered_by_user_id,
            answeredAt: wire.answer.answered_at,
          },
    launches: wire.launches.map((launch) => ({
      researchRunId: launch.research_run_id,
      runKind: launch.run_kind,
      runState: launch.run_state,
      sourceActionRef: launch.source_action_ref,
      approvalRefs: launch.approval_refs,
    })),
    withdrawn: wire.withdrawn,
  };
}

export const ChatGateSchema = GateWireSchema.transform(toGate);

export const ChatGateListResponseSchema = z
  .object({ data: z.array(GateWireSchema).default([]) })
  .transform((wire) => wire.data.map(toGate));

/** "Open" is the absence of an answer record (ratified §6-D3), never a column. */
export function isGateOpen(gate: ChatGate): boolean {
  return gate.answer === null && gate.snapshotErasedAt === null && !gate.withdrawn;
}

// --- the card state machine ---------------------------------------------

/**
 * What the approval card is doing, derived from the durable gate.
 *
 * `unavailable` is a first-class state and not an error: it is what the surface
 * shows when the transcript knows a gate exists (the stream said so, or a
 * message carries an `open_gate` ref) but the durable payload could not be
 * read. The card then renders a non-interactive human-action notice and an
 * explicit recovery where one is safe. It never renders disabled decision
 * chrome that implies the reference could become authority by itself. A
 * withheld *amount* is not that case: it is the pilot's normal posture and
 * leaves an otherwise verified card fully answerable.
 */
export type GateCardState =
  | "requested"
  | "responded"
  | "denied"
  | "withdrawn"
  | "unavailable";

export type GateRecoveryKind = "retry_gate_read" | "request_new_gate";

export interface GateRecoveryAction {
  kind: GateRecoveryKind;
  label: string;
}

export interface GateAuthorityFailure {
  reason: string;
  recovery: GateRecoveryAction | null;
}

export interface GateCardModel {
  gateId: string;
  state: GateCardState;
  kind: string;
  title: string;
  summary: string | null;
  subjectRef: string | null;
  subjectRevision: number | null;
  amountCents: number | null;
  currency: string | null;
  expectedSubjectSha256: string | null;
  permittedDecisions: readonly GateDecision[];
  decision: GateDecision | null;
  answeredAt: string | null;
  answeredByUserId: string | null;
  /** Non-null only in `unavailable`; the exact reason the card cannot act. */
  unavailableReason: string | null;
  recovery: GateRecoveryAction | null;
  revisionRequest: string | null;
  revisionKind: "icp" | "discovery" | null;
  /** The research run an approved gate's authority actually launched. */
  launches: readonly ChatGateLaunch[];
  productOptions: readonly ProductSelectionOption[];
  selectedProductId: string | null;
  selectedProductName: string | null;
  /**
   * Non-null only for the set-valued `product_set_selection` gate (O6/D10).
   *
   * A project sells *products*, plural, so the card checks a set rather than
   * picking one. Everything here is read out of the immutable subject snapshot
   * — the catalog it shows, the boxes it pre-checks, and (once answered) the
   * ids the human actually chose — so the card can never drift from the
   * subject the decision was recorded against.
   */
  productSet: GateProductSet | null;
  /** Non-null only for a CRM write permission card: what it asks to change. */
  crmWrite: CrmWriteCardModel | null;
  /** The CRM write proposal the card stands for; its progress is read by this id. */
  crmProposalId: string | null;
  /**
   * A refused answer on a CRM write card, in plain words. The card stays as it was (card spec
   * §4) rather than turning into a notice.
   */
  problem: string | null;
}

export interface GateProductSet {
  options: readonly ProductSelectionOption[];
  /** The boxes checked when the card opens: the saved selection, else the suggestion. */
  preselectedIds: readonly string[];
  /** The version of the project's saved selection, when it already has one. */
  currentSelectionVersion: number | null;
  /** The durable answer's chosen ids; empty while the gate is open. */
  selectedIds: readonly string[];
}

export interface ProductSelectionOption {
  productId: string;
  name: string;
  shortDescription: string;
  aliases: readonly string[];
  status: string;
  /** Catalog front-matter members; null when the catalog does not state one. */
  offeringKind: string | null;
  family: string | null;
  lifecycle: string | null;
  officialUrl: string | null;
  /** Onboarding reconciliation was unsure this row is distinct from another. */
  possibleDuplicate: boolean;
  duplicateReason: string | null;
}

function decisionOf(value: string | null): GateDecision | null {
  const parsed = GateDecisionSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

const GATE_TITLES: Record<string, string> = {
  directive_confirmation: "Review the research plan",
  icp_confirmation: "Review your ideal customer profile",
  product_selection: "Choose this project's product",
  product_set_selection: "Choose this project's products",
  plan_approval: "Review the plan",
  budget_approval: "Review the budget",
  [CRM_WRITE_GATE_KIND]: "Allow changes to your CRM",
};

const SUPPORTED_GATE_KINDS: ReadonlySet<string> = new Set([
  "directive_confirmation",
  "icp_confirmation",
  "product_selection",
  "product_set_selection",
  CRM_WRITE_GATE_KIND,
]);

const RETRY_GATE_READ: GateRecoveryAction = {
  kind: "retry_gate_read",
  label: "Try again",
};

const REQUEST_NEW_GATE: GateRecoveryAction = {
  kind: "request_new_gate",
  label: "Create a new proposal",
};

export function gateTitle(kind: string): string {
  return GATE_TITLES[kind] ?? "Review requested";
}

function isDiscoveryConfiguration(gate: ChatGate): boolean {
  return gate.kind === "directive_confirmation" &&
    gate.subjectSnapshot.subject_kind === "discovery_configuration";
}

export function agentGateIdFromPart(part: ChatGatePart): string | null {
  if (
    part.gateRef.objectType !== "agent_gate" ||
    part.gateRef.objectId === null
  ) {
    return null;
  }
  return DURABLE_GATE_ID_PATTERN.test(part.gateRef.objectId)
    ? part.gateRef.objectId
    : null;
}

function durableGateSummary(gate: ChatGate): string {
  if (gate.kind === "icp_confirmation") {
    const label = profileDisplayName(gate.subjectSnapshot.icp_key);
    return gate.subjectRevision === null
      ? label
      : `${label} · Version ${gate.subjectRevision}`;
  }
  if (gate.kind === "directive_confirmation") {
    const configuration = gate.subjectSnapshot.configuration;
    const accountCount =
      configuration && typeof configuration === "object"
        ? (configuration as Record<string, unknown>).requested_account_count
        : gate.subjectSnapshot.account_count;
    const scope =
      typeof accountCount === "number"
        ? `${accountCount} ${accountCount === 1 ? "account" : "accounts"}`
        : "the selected accounts";
    if (isDiscoveryConfiguration(gate)) {
      return `Discover ${scope} using the approved ICP criteria`;
    }
    return gate.subjectRevision === null
      ? `Research plan for ${scope}`
      : `Research plan for ${scope} · Version ${gate.subjectRevision}`;
  }
  if (gate.kind === "product_selection") {
    const count = productSelectionOptions(gate.subjectSnapshot).length;
    const scope = `${count} ${count === 1 ? "product" : "products"} available`;
    return gate.subjectRevision === null
      ? scope
      : `${scope} · Catalog version ${gate.subjectRevision}`;
  }
  if (gate.kind === "product_set_selection") {
    const options = productSelectionOptions(gate.subjectSnapshot);
    const chosen = answeredProductIds(gate);
    // Once answered, the summary is the receipt: the names the human chose,
    // read back out of the same immutable snapshot the decision was made on.
    if (chosen.length > 0) {
      return chosen
        .map(
          (productId) =>
            options.find((option) => option.productId === productId)?.name ??
            productId,
        )
        .join(", ");
    }
    const preselected = preselectedProductIds(gate.subjectSnapshot).length;
    const noun = options.length === 1 ? "product" : "products";
    return `${options.length} ${noun} available · ${preselected} pre-checked`;
  }
  return "A decision is needed before work can continue.";
}

function notice({
  gate,
  part,
  reason,
  recovery,
}: {
  gate: ChatGate | null;
  part: ChatGatePart;
  reason: string;
  recovery: GateRecoveryAction | null;
}): GateCardModel {
  return {
    gateId: gate?.gateId ?? part.gateRef.objectId ?? part.partId,
    state: "unavailable",
    kind: gate?.kind ?? part.gateKind,
    title: "Human action required",
    summary: gate === null ? null : durableGateSummary(gate),
    subjectRef: gate?.subjectRef ?? null,
    subjectRevision: gate?.subjectRevision ?? null,
    amountCents: null,
    currency: null,
    expectedSubjectSha256: null,
    permittedDecisions: [],
    decision: null,
    answeredAt: null,
    answeredByUserId: null,
    unavailableReason: reason,
    recovery,
    revisionRequest: null,
    revisionKind: null,
    launches: [],
    productOptions: [],
    selectedProductId: null,
    selectedProductName: null,
    productSet: null,
    crmWrite: null,
    crmProposalId: null,
    problem: null,
  };
}

/**
 * Build one card from a stream signal plus its fetched durable authority.
 *
 * The stream part is never a fallback authority, even when it carries a rich
 * snapshot. It only identifies which persisted gate the repository must have
 * returned. This keeps model-authored refs and stale streamed fields outside
 * the decision path by construction.
 */
export function gateCardModel({
  gate,
  part,
  currentUserId,
  currentWorkspaceId,
  expectedProjectId,
  expectedThreadId,
  gateReadAvailable,
  gateReadLoading = false,
  authorityFailure = null,
}: {
  gate: ChatGate | null;
  part: ChatGatePart | null;
  currentUserId: string | null;
  currentWorkspaceId: string | null;
  expectedProjectId: string;
  expectedThreadId: string;
  gateReadAvailable: boolean;
  gateReadLoading?: boolean;
  authorityFailure?: GateAuthorityFailure | null;
}): GateCardModel | null {
  if (gate === null && part === null) return null;
  if (part === null) return null;

  const referencedGateId = agentGateIdFromPart(part);
  if (referencedGateId === null) {
    return notice({
      gate: null,
      part,
      reason:
        "This review request is incomplete, so it cannot be approved yet.",
      recovery: REQUEST_NEW_GATE,
    });
  }
  if (gate === null) {
    if (gateReadLoading) {
      return notice({
        gate: null,
        part,
        reason: "Checking that this proposal is ready for your review…",
        recovery: null,
      });
    }
    return notice({
      gate: null,
      part,
      reason: gateReadAvailable
        ? "This proposal is no longer available. Create a new one to continue."
        : "We couldn't load the approval details. Please try again.",
      recovery: gateReadAvailable ? REQUEST_NEW_GATE : RETRY_GATE_READ,
    });
  }
  if (gate.gateId !== referencedGateId) {
    return notice({
      gate,
      part,
      reason: "This review request is out of date. Please try again.",
      recovery: RETRY_GATE_READ,
    });
  }
  if (
    gate.workspaceId !== currentWorkspaceId ||
    gate.projectId !== expectedProjectId ||
    gate.threadId !== expectedThreadId
  ) {
    return notice({
      gate,
      part,
      reason: "This review request belongs to a different conversation.",
      recovery: RETRY_GATE_READ,
    });
  }
  if (!SUPPORTED_GATE_KINDS.has(gate.kind)) {
    return notice({
      gate,
      part,
      reason: "This type of review is not available here yet.",
      recovery: REQUEST_NEW_GATE,
    });
  }
  const crm = gate.kind === CRM_WRITE_GATE_KIND;
  // A CRM write card has no revision: its subject is the proposal, fixed by the snapshot digest.
  if (!crm && (gate.subjectRevision === null || gate.subjectRevision < 1)) {
    return notice({
      gate,
      part,
      reason: "This proposal is incomplete. Create a new one to continue.",
      recovery: REQUEST_NEW_GATE,
    });
  }
  if (gate.snapshotErasedAt !== null) {
    return notice({
      gate,
      part,
      reason: "This review is unavailable because its reviewed subject was erased.",
      recovery: null,
    });
  }
  if (new Set(gate.permittedDecisions).size !== gate.permittedDecisions.length) {
    return notice({
      gate,
      part,
      reason: "This proposal has conflicting actions. Create a new one to continue.",
      recovery: REQUEST_NEW_GATE,
    });
  }

  const crmWrite = crm ? crmWriteCard(gate.subjectSnapshot) : null;
  const crmProposalId = crm ? crmProposalIdOf(gate.subjectRef) : null;
  if (crm && (crmWrite === null || crmProposalId === null)) {
    return notice({
      gate,
      part,
      reason: "This proposal is incomplete. Ask Clue to propose the changes again.",
      recovery: REQUEST_NEW_GATE,
    });
  }
  const crmParts = { crmWrite, crmProposalId, problem: null };

  const decision = decisionOf(gate.answer?.decision ?? null);
  const productOptions = productSelectionOptions(gate.subjectSnapshot);
  const productSet =
    gate.kind === "product_set_selection" ? productSetOf(gate) : null;
  if (
    (gate.kind === "product_selection" || gate.kind === "product_set_selection") &&
    productOptions.length === 0
  ) {
    return notice({
      gate,
      part,
      reason: "This product proposal has no available choices. Create a new one to continue.",
      recovery: REQUEST_NEW_GATE,
    });
  }
  if (gate.answer !== null && decision === null) {
    return notice({
      gate,
      part,
      reason: "We couldn't confirm the saved decision for this proposal.",
      recovery: null,
    });
  }
  if (decision !== null) {
    if (
      gate.answer?.expectedSubjectSha256 !== gate.expectedSubjectSha256 ||
      !gate.permittedDecisions.includes(decision) ||
      // Any member of the workspace may answer a CRM write card (R-6.8).
      (!crm && gate.answer.answeredByUserId !== gate.addresseeUserId)
    ) {
      return notice({
        gate,
        part,
        reason: "We couldn't confirm the saved decision for this proposal.",
        recovery: null,
      });
    }
    const revisionRequest = gate.answer?.decisionPayload.revision_request;
    const selectedProduct =
      gate.answer?.selectedOptionRef === null
        ? null
        : productOptions.find(
            (product) => product.productId === gate.answer?.selectedOptionRef,
          ) ?? null;
    if (
      gate.kind === "product_selection" &&
      ((decision === "approved" && selectedProduct === null) ||
        (decision !== "approved" && gate.answer?.selectedOptionRef !== null))
    ) {
      return notice({
        gate,
        part,
        reason: "We couldn't confirm the saved product selection.",
        recovery: null,
      });
    }
    // The set-valued receipt is trusted only when every recorded id is still a
    // product of the immutable snapshot, and only an approval may carry any.
    if (
      productSet !== null &&
      ((decision === "approved" &&
        (productSet.selectedIds.length === 0 ||
          !productSet.selectedIds.every((productId) =>
            productSet.options.some((option) => option.productId === productId),
          ))) ||
        (decision !== "approved" &&
          (gate.answer?.selectedOptionRef !== null ||
            stringList(gate.answer?.decisionPayload.selected_option_refs).length >
              0)))
    ) {
      return notice({
        gate,
        part,
        reason: "We couldn't confirm the saved product selection.",
        recovery: null,
      });
    }
    return {
      gateId: gate.gateId,
      state: decision === "approved" ? "responded" : "denied",
      kind: gate.kind,
      title: isDiscoveryConfiguration(gate)
        ? "Review account discovery scope"
        : gateTitle(gate.kind),
      summary: durableGateSummary(gate),
      subjectRef: gate.subjectRef,
      subjectRevision: gate.subjectRevision,
      amountCents: gate.maxSpendCents,
      currency: gate.currency,
      expectedSubjectSha256: gate.expectedSubjectSha256,
      permittedDecisions: gate.permittedDecisions,
      decision,
      answeredAt: gate.answer?.answeredAt ?? null,
      answeredByUserId: gate.answer?.answeredByUserId ?? null,
      unavailableReason: null,
      recovery: null,
      revisionRequest:
        typeof revisionRequest === "string" ? revisionRequest : null,
      revisionKind: gate.kind === "icp_confirmation"
        ? "icp"
        : isDiscoveryConfiguration(gate)
          ? "discovery"
          : null,
      launches: gate.launches,
      productOptions,
      selectedProductId: gate.answer?.selectedOptionRef ?? null,
      selectedProductName: selectedProduct?.name ?? null,
      productSet,
      ...crmParts,
    };
  }
  if (gate.withdrawn) {
    return {
      ...notice({ gate, part, reason: "", recovery: null }),
      state: "withdrawn",
      title: gateTitle(gate.kind),
      unavailableReason: null,
      ...crmParts,
    };
  }
  if (authorityFailure !== null && !crm) {
    return notice({
      gate,
      part,
      reason: authorityFailure.reason,
      recovery: authorityFailure.recovery,
    });
  }
  if (currentUserId === null || (!crm && gate.addresseeUserId !== currentUserId)) {
    return notice({
      gate,
      part,
      reason:
        currentUserId === null
          ? "We couldn't confirm who should review this proposal."
          : "This proposal is waiting for another workspace member.",
      recovery: null,
    });
  }
  if (gate.permittedDecisions.length === 0) {
    return notice({
      gate,
      part,
      reason: "This proposal has no available actions. Create a new one to continue.",
      recovery: REQUEST_NEW_GATE,
    });
  }

  return {
    gateId: gate.gateId,
    state: "requested",
    kind: gate.kind,
    title: isDiscoveryConfiguration(gate)
      ? "Review account discovery scope"
      : gateTitle(gate.kind),
    summary: durableGateSummary(gate),
    subjectRef: gate.subjectRef,
    subjectRevision: gate.subjectRevision,
    amountCents: gate.maxSpendCents,
    currency: gate.currency,
    expectedSubjectSha256: gate.expectedSubjectSha256,
    permittedDecisions: gate.permittedDecisions,
    decision: null,
    answeredAt: null,
    answeredByUserId: null,
    unavailableReason: null,
    recovery: null,
    revisionRequest: null,
    revisionKind: gate.kind === "icp_confirmation"
      ? "icp"
      : isDiscoveryConfiguration(gate)
        ? "discovery"
        : null,
    launches: gate.launches,
    productOptions,
    selectedProductId: null,
    selectedProductName: null,
    productSet,
    ...crmParts,
    problem: authorityFailure?.reason ?? null,
  };
}

export function gateAuthorityFailure(
  code: string,
  backendMessage: string,
): GateAuthorityFailure {
  // The backend message belongs in correlated logs, not customer-facing copy.
  // Touch it here only to make that intentional non-disclosure explicit.
  void backendMessage;
  switch (code) {
    case "GATE_SUBJECT_STALE":
    case "GATE_NOT_FOUND":
      return {
        reason:
          "This proposal changed or is no longer available. Create a new one to continue.",
        recovery: REQUEST_NEW_GATE,
      };
    case "GATE_KIND_UNSUPPORTED":
    case "GATE_DECISION_UNSUPPORTED":
      return {
        reason:
          "This proposal can no longer be reviewed here. Create a new one to continue.",
        recovery: REQUEST_NEW_GATE,
      };
    case "GATE_ALREADY_ANSWERED":
      return {
        reason: "This proposal was already answered. Refresh to see the saved decision.",
        recovery: RETRY_GATE_READ,
      };
    case "GATE_AMOUNT_STALE":
      return {
        reason: "The research plan changed while you were reviewing it. Please try again.",
        recovery: RETRY_GATE_READ,
      };
    case "GATE_FORBIDDEN":
      return {
        reason: "This proposal is waiting for another workspace member.",
        recovery: null,
      };
    default:
      return {
        reason: "We couldn't save your decision. Please try again.",
        recovery: RETRY_GATE_READ,
      };
  }
}

const ICP_DECISION_COPY: Readonly<Record<GateDecision, string>> = {
  approved: "Approve profile",
  rejected: "Reject proposal",
  revised: "Request changes",
};

const RESEARCH_DECISION_COPY: Readonly<Record<GateDecision, string>> = {
  approved: "Start research",
  rejected: "Don't start",
  revised: "Request changes",
};

const ICP_DECISION_RECORDED: Readonly<Record<GateDecision, string>> = {
  approved: "Profile approved",
  rejected: "Proposal rejected",
  revised: "Changes requested",
};

const RESEARCH_DECISION_RECORDED: Readonly<Record<GateDecision, string>> = {
  approved: "Research approved",
  rejected: "Research not approved",
  revised: "Changes requested",
};

const PRODUCT_DECISION_COPY: Readonly<Record<GateDecision, string>> = {
  approved: "Use this product",
  rejected: "Not now",
  revised: "Request changes",
};

const PRODUCT_DECISION_RECORDED: Readonly<Record<GateDecision, string>> = {
  approved: "Product selected",
  rejected: "Product selection declined",
  revised: "Changes requested",
};

const PRODUCT_SET_DECISION_COPY: Readonly<Record<GateDecision, string>> = {
  approved: "Use these products",
  rejected: "Not now",
  revised: "Request changes",
};

const PRODUCT_SET_DECISION_RECORDED: Readonly<Record<GateDecision, string>> = {
  approved: "Products selected",
  rejected: "Product selection declined",
  revised: "Changes requested",
};

const CRM_WRITE_DECISION_COPY: Readonly<Record<GateDecision, string>> = {
  approved: "Allow",
  rejected: "Don't allow",
  revised: "Request changes",
};

const CRM_WRITE_DECISION_RECORDED: Readonly<Record<GateDecision, string>> = {
  approved: "Changes allowed",
  rejected: "Changes not allowed",
  revised: "Changes requested",
};

export function gateDecisionCopy(
  kind: string,
  decision: GateDecision,
  recorded = false,
): string {
  if (kind === CRM_WRITE_GATE_KIND) {
    return recorded ? CRM_WRITE_DECISION_RECORDED[decision] : CRM_WRITE_DECISION_COPY[decision];
  }
  if (kind === "icp_confirmation") {
    return recorded ? ICP_DECISION_RECORDED[decision] : ICP_DECISION_COPY[decision];
  }
  if (kind === "product_set_selection") {
    return recorded
      ? PRODUCT_SET_DECISION_RECORDED[decision]
      : PRODUCT_SET_DECISION_COPY[decision];
  }
  if (kind === "product_selection") {
    return recorded
      ? PRODUCT_DECISION_RECORDED[decision]
      : PRODUCT_DECISION_COPY[decision];
  }
  return recorded
    ? RESEARCH_DECISION_RECORDED[decision]
    : RESEARCH_DECISION_COPY[decision];
}

/** Human presentation of a durable answer receipt, keyed by its answer turn. */
export function gateAnswerDisplay(gate: ChatGate): GateAnswerDisplay | null {
  if (gate.answer === null) return null;
  const decision = decisionOf(gate.answer.decision);
  if (decision === null) {
    return { detail: null, label: "Decision recorded" };
  }
  const revisionRequest = gate.answer.decisionPayload.revision_request;
  const options = productSelectionOptions(gate.subjectSnapshot);
  const selectedProduct = options.find(
    (product) => product.productId === gate.answer?.selectedOptionRef,
  );
  // The set-valued receipt names every product the human chose, read back out
  // of the snapshot that was on screen when they chose it.
  const selectedNames = answeredProductIds(gate)
    .map(
      (productId) =>
        options.find((option) => option.productId === productId)?.name ?? productId,
    )
    .join(", ");
  return {
    detail:
      decision === "revised" && typeof revisionRequest === "string"
        ? revisionRequest.trim() || null
        : decision === "approved" && gate.kind === "product_selection"
          ? selectedProduct?.name ?? null
          : decision === "approved" && gate.kind === "product_set_selection"
            ? selectedNames || null
            : decision === "approved" && gate.kind === CRM_WRITE_GATE_KIND
              ? crmAllowedDetail(gate.answer.decisionPayload)
              : null,
    label: gateDecisionCopy(gate.kind, decision, true),
  };
}

export function gateAnswerResponse(
  card: GateCardModel,
  input: GateDecisionInput,
): GateResponse {
  if (card.state !== "requested" || card.expectedSubjectSha256 === null) {
    throw new Error("This proposal is no longer ready for a decision.");
  }
  if (!card.permittedDecisions.includes(input.decision)) {
    throw new Error("That option is no longer available for this proposal.");
  }
  const trimmedRevision =
    input.kind === "icp_revision" || input.kind === "discovery_revision"
      ? input.revisionRequest.trim()
      : undefined;
  if (trimmedRevision && trimmedRevision.length > 4_000) {
    throw new Error("Please keep the requested changes under 4,000 characters.");
  }
  const revisionKindMatchesGate =
    (card.revisionKind === "icp" && card.kind === "icp_confirmation") ||
    (card.revisionKind === "discovery" && card.kind === "directive_confirmation");
  if (revisionKindMatchesGate && input.decision === "revised") {
    if (!trimmedRevision) {
      throw new Error("Describe what you would like changed before continuing.");
    }
    if (
      (card.revisionKind === "icp" && input.kind !== "icp_revision") ||
      (card.revisionKind === "discovery" && input.kind !== "discovery_revision")
    ) {
      throw new Error("Describe what you would like changed before continuing.");
    }
  } else if (
    input.kind === "icp_revision" || input.kind === "discovery_revision"
  ) {
    throw new Error("Changes can only be added when requesting a revision.");
  }
  if (card.kind === "product_selection" && input.decision === "approved") {
    if (input.kind !== "product_selection") {
      throw new Error("Choose one of the products shown before continuing.");
    }
    if (!card.productOptions.some((product) => product.productId === input.selectedProductId)) {
      throw new Error("That product is no longer available for this proposal.");
    }
  } else if (input.kind === "product_selection") {
    throw new Error("A product can only be selected when approving this choice.");
  }
  if (card.kind === "product_set_selection" && input.decision === "approved") {
    if (input.kind !== "product_set_selection" || input.selectedProductIds.length === 0) {
      throw new Error(
        "Choose at least one of the products shown before continuing.",
      );
    }
    // An archived row is on the card so the human can see it exists; it is
    // never a thing this project can be pointed at.
    const selectable = new Set(
      (card.productSet?.options ?? [])
        .filter((option) => option.status !== "archived")
        .map((option) => option.productId),
    );
    if (
      new Set(input.selectedProductIds).size !== input.selectedProductIds.length ||
      !input.selectedProductIds.every((productId) => selectable.has(productId))
    ) {
      throw new Error("That product is no longer available for this proposal.");
    }
  } else if (input.kind === "product_set_selection") {
    throw new Error("Products can only be chosen when approving this proposal.");
  }
  if (card.kind === CRM_WRITE_GATE_KIND && input.decision === "approved") {
    if (input.kind !== "crm_write" || input.answer.selected_write_ids.length === 0) {
      throw new Error("Tick at least one change to allow.");
    }
  } else if (input.kind === "crm_write") {
    throw new Error("Changes can only be chosen when allowing them.");
  }
  return {
    gateId: card.gateId,
    decision: input.decision,
    expectedSubjectSha256: card.expectedSubjectSha256,
    expectedEstimatedCostCents:
      card.kind === "directive_confirmation" ? card.amountCents : null,
    ...(trimmedRevision ? { revisionRequest: trimmedRevision } : {}),
    ...(input.kind === "product_selection"
      ? { selectedProductId: input.selectedProductId }
      : {}),
    ...(input.kind === "product_set_selection"
      ? { selectedProductIds: [...input.selectedProductIds] }
      : {}),
    ...(input.kind === "crm_write"
      ? {
          crmWrite: {
            selected_write_ids: [...input.answer.selected_write_ids],
            always_allow: [...input.answer.always_allow],
          },
        }
      : {}),
  };
}

/** "3 changes" — the receipt of an allowed CRM write card. */
function crmAllowedDetail(payload: Record<string, unknown>): string | null {
  const count = stringList(payload.selected_write_ids).length;
  if (count === 0) return null;
  return `${count} ${count === 1 ? "change" : "changes"}`;
}

function productSelectionOptions(
  snapshot: Record<string, unknown> | undefined,
): readonly ProductSelectionOption[] {
  if (!snapshot || !Array.isArray(snapshot.products)) return [];
  return snapshot.products.flatMap((candidate) => {
    if (
      !candidate ||
      typeof candidate !== "object" ||
      typeof (candidate as Record<string, unknown>).product_id !== "string" ||
      typeof (candidate as Record<string, unknown>).name !== "string" ||
      typeof (candidate as Record<string, unknown>).short_description !== "string"
    ) {
      return [];
    }
    const item = candidate as Record<string, unknown>;
    return [
      {
        productId: item.product_id as string,
        name: item.name as string,
        shortDescription: item.short_description as string,
        aliases: Array.isArray(item.aliases)
          ? item.aliases.filter((alias): alias is string => typeof alias === "string")
          : [],
        status: typeof item.status === "string" ? item.status : "active",
        offeringKind: optionalText(item.offering_kind),
        family: optionalText(item.family),
        lifecycle: optionalText(item.lifecycle),
        officialUrl: optionalText(item.official_url),
        // Only `model_unsure` is a doubt worth showing a human; every other
        // resolution state is a settled row and gets no chip at all.
        possibleDuplicate: item.resolution_state === "model_unsure",
        duplicateReason:
          item.resolution_state === "model_unsure"
            ? optionalText(item.reconcile_reason)
            : null,
      },
    ];
  });
}

function optionalText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function stringList(value: unknown): readonly string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

/** The saved project selection when there is one, else the agent's suggestion. */
function preselectedProductIds(
  snapshot: Record<string, unknown> | undefined,
): readonly string[] {
  const selection = snapshot?.current_selection;
  if (selection && typeof selection === "object") {
    return stringList((selection as Record<string, unknown>).product_ids);
  }
  return stringList(snapshot?.suggested_product_ids);
}

function currentSelectionVersion(
  snapshot: Record<string, unknown> | undefined,
): number | null {
  const selection = snapshot?.current_selection;
  if (!selection || typeof selection !== "object") return null;
  const version = (selection as Record<string, unknown>).selection_version;
  return typeof version === "number" ? version : null;
}

/**
 * The ids a set-valued gate's durable answer recorded.
 *
 * The route writes them to `decision_payload.selected_option_refs` and leaves
 * the single-valued `selected_option_ref` null, so this is the only place the
 * chosen set can be read from.
 */
function answeredProductIds(gate: ChatGate): readonly string[] {
  if (gate.answer === null || gate.answer.decision !== "approved") return [];
  return stringList(gate.answer.decisionPayload.selected_option_refs);
}

function productSetOf(gate: ChatGate): GateProductSet {
  return {
    options: productSelectionOptions(gate.subjectSnapshot),
    preselectedIds: preselectedProductIds(gate.subjectSnapshot),
    currentSelectionVersion: currentSelectionVersion(gate.subjectSnapshot),
    selectedIds: answeredProductIds(gate),
  };
}

/** Money is formatted by the client (D-5); the backend never sends a string. */
export function formatCents(
  amountCents: number | null,
  currency: string | null,
): string | null {
  if (amountCents === null) return null;
  const resolved = currency ?? "USD";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: resolved,
    }).format(amountCents / 100);
  } catch {
    return `${(amountCents / 100).toFixed(2)} ${resolved}`;
  }
}
