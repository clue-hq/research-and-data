import { z } from "zod";
import {
  GateDecisionSchema,
  parseCentAmount,
  type ChatGatePart,
  type GateDecision,
} from "./chat-parts";
import type { GateResponse } from "./chat-turn";

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
  answer: GateAnswerWireSchema.nullable().default(null),
  launches: z.array(GateLaunchWireSchema).default([]),
});

export interface ChatGateAnswer {
  turnId: string;
  actionRef: string;
  decision: string;
  expectedSubjectSha256: string;
  decisionPayload: Record<string, unknown>;
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
  answer: ChatGateAnswer | null;
  launches: readonly ChatGateLaunch[];
}

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
    answer:
      wire.answer === null
        ? null
        : {
            turnId: wire.answer.turn_id,
            actionRef: wire.answer.action_ref,
            decision: wire.answer.decision,
            expectedSubjectSha256: wire.answer.expected_subject_sha256,
            decisionPayload: wire.answer.decision_payload,
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
  };
}

export const ChatGateSchema = GateWireSchema.transform(toGate);

export const ChatGateListResponseSchema = z
  .object({ data: z.array(GateWireSchema).default([]) })
  .transform((wire) => wire.data.map(toGate));

/** "Open" is the absence of an answer record (ratified §6-D3), never a column. */
export function isGateOpen(gate: ChatGate): boolean {
  return gate.answer === null;
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
export type GateCardState = "requested" | "responded" | "denied" | "unavailable";

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
  /** The research run an approved gate's authority actually launched. */
  launches: readonly ChatGateLaunch[];
}

function decisionOf(value: string | null): GateDecision | null {
  const parsed = GateDecisionSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

const GATE_TITLES: Record<string, string> = {
  directive_confirmation: "Confirm research launch",
  icp_confirmation: "Confirm ICP",
  plan_approval: "Approve plan",
  budget_approval: "Approve budget",
};

const SUPPORTED_GATE_KINDS: ReadonlySet<string> = new Set([
  "directive_confirmation",
  "icp_confirmation",
]);

const RETRY_GATE_READ: GateRecoveryAction = {
  kind: "retry_gate_read",
  label: "Retry gate verification",
};

const REQUEST_NEW_GATE: GateRecoveryAction = {
  kind: "request_new_gate",
  label: "Ask Stage 0 to regenerate",
};

export function gateTitle(kind: string): string {
  return GATE_TITLES[kind] ?? kind.replaceAll("_", " ");
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
    const label =
      typeof gate.subjectSnapshot.icp_key === "string"
        ? gate.subjectSnapshot.icp_key.replaceAll("_", " ")
        : gate.subjectRef;
    return `ICP proposal ${label} · revision ${gate.subjectRevision}`;
  }
  if (gate.kind === "directive_confirmation") {
    const accountCount = gate.subjectSnapshot.account_count;
    const scope =
      typeof accountCount === "number"
        ? `${accountCount} ${accountCount === 1 ? "account" : "accounts"}`
        : gate.subjectRef;
    return `Research directive for ${scope} · revision ${gate.subjectRevision}`;
  }
  return `${gate.subjectRef} · revision ${gate.subjectRevision}`;
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
    launches: [],
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
  gateReadReason = null,
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
  gateReadReason?: string | null;
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
        "This request is not backed by a durable agent gate. A model-only reference cannot authorize a human decision.",
      recovery: REQUEST_NEW_GATE,
    });
  }
  if (gate === null) {
    if (gateReadLoading) {
      return notice({
        gate: null,
        part,
        reason: "Verifying the durable gate before showing any decision controls.",
        recovery: null,
      });
    }
    return notice({
      gate: null,
      part,
      reason: gateReadAvailable
        ? "The referenced durable gate is missing from this conversation. It cannot be answered safely."
        : (gateReadReason ??
          "The durable gate could not be verified, so no decision controls are available."),
      recovery: gateReadAvailable ? REQUEST_NEW_GATE : RETRY_GATE_READ,
    });
  }
  if (gate.gateId !== referencedGateId) {
    return notice({
      gate,
      part,
      reason: "The rendered reference does not match the fetched durable gate.",
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
      reason: "The durable gate does not belong to the active workspace conversation.",
      recovery: RETRY_GATE_READ,
    });
  }
  if (!SUPPORTED_GATE_KINDS.has(gate.kind)) {
    return notice({
      gate,
      part,
      reason: `This client does not support decisions for ${gateTitle(gate.kind)} gates.`,
      recovery: REQUEST_NEW_GATE,
    });
  }
  if (gate.subjectRevision === null || gate.subjectRevision < 1) {
    return notice({
      gate,
      part,
      reason: "The durable gate does not identify an exact positive subject revision.",
      recovery: REQUEST_NEW_GATE,
    });
  }
  if (new Set(gate.permittedDecisions).size !== gate.permittedDecisions.length) {
    return notice({
      gate,
      part,
      reason: "The durable gate contains a duplicated human decision.",
      recovery: REQUEST_NEW_GATE,
    });
  }

  const decision = decisionOf(gate.answer?.decision ?? null);
  if (gate.answer !== null && decision === null) {
    return notice({
      gate,
      part,
      reason: "The durable answer receipt contains an unsupported decision.",
      recovery: null,
    });
  }
  if (decision !== null) {
    if (
      gate.answer?.expectedSubjectSha256 !== gate.expectedSubjectSha256 ||
      !gate.permittedDecisions.includes(decision) ||
      gate.answer.answeredByUserId !== gate.addresseeUserId
    ) {
      return notice({
        gate,
        part,
        reason:
          "The durable answer receipt does not match the gate authority it claims to answer.",
        recovery: null,
      });
    }
    const revisionRequest = gate.answer?.decisionPayload.revision_request;
    return {
      gateId: gate.gateId,
      state: decision === "approved" ? "responded" : "denied",
      kind: gate.kind,
      title: gateTitle(gate.kind),
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
      launches: gate.launches,
    };
  }
  if (authorityFailure !== null) {
    return notice({
      gate,
      part,
      reason: authorityFailure.reason,
      recovery: authorityFailure.recovery,
    });
  }
  if (currentUserId === null || gate.addresseeUserId !== currentUserId) {
    return notice({
      gate,
      part,
      reason:
        currentUserId === null
          ? "The current user identity could not be verified."
          : "This confirmation is addressed to another workspace member.",
      recovery: null,
    });
  }
  if (gate.permittedDecisions.length === 0) {
    return notice({
      gate,
      part,
      reason: "The durable gate offers no supported human decision.",
      recovery: REQUEST_NEW_GATE,
    });
  }

  return {
    gateId: gate.gateId,
    state: "requested",
    kind: gate.kind,
    title: gateTitle(gate.kind),
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
    launches: gate.launches,
  };
}

export function gateAuthorityFailure(
  code: string,
  message: string,
): GateAuthorityFailure {
  switch (code) {
    case "GATE_SUBJECT_STALE":
    case "GATE_NOT_FOUND":
    case "GATE_KIND_UNSUPPORTED":
    case "GATE_DECISION_UNSUPPORTED":
      return {
        reason: `${message} The current card cannot be used safely.`,
        recovery: REQUEST_NEW_GATE,
      };
    case "GATE_ALREADY_ANSWERED":
    case "GATE_AMOUNT_STALE":
      return {
        reason: `${message} Refresh the durable gate before taking another action.`,
        recovery: RETRY_GATE_READ,
      };
    case "GATE_FORBIDDEN":
      return { reason: message, recovery: null };
    default:
      return {
        reason: `${message} The durable gate must be verified again before retrying.`,
        recovery: RETRY_GATE_READ,
      };
  }
}

export function gateAnswerResponse(
  card: GateCardModel,
  decision: GateDecision,
  revisionRequest?: string,
): GateResponse {
  if (card.state !== "requested" || card.expectedSubjectSha256 === null) {
    throw new Error("only a verified, unanswered durable gate may be answered");
  }
  if (!card.permittedDecisions.includes(decision)) {
    throw new Error("this decision was not offered by the durable gate");
  }
  const trimmedRevision = revisionRequest?.trim();
  if (trimmedRevision && trimmedRevision.length > 4_000) {
    throw new Error("an ICP revision request must be at most 4000 characters");
  }
  if (card.kind === "icp_confirmation" && decision === "revised") {
    if (!trimmedRevision) {
      throw new Error("describe the ICP changes you want before requesting a revision");
    }
  } else if (trimmedRevision) {
    throw new Error("revision text is valid only when revising an ICP");
  }
  return {
    gateId: card.gateId,
    decision,
    expectedSubjectSha256: card.expectedSubjectSha256,
    expectedEstimatedCostCents:
      card.kind === "directive_confirmation" ? card.amountCents : null,
    ...(trimmedRevision ? { revisionRequest: trimmedRevision } : {}),
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
