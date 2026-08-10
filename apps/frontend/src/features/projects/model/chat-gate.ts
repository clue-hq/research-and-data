import { z } from "zod";
import {
  GateDecisionSchema,
  parseCentAmount,
  type ChatGatePart,
  type GateDecision,
} from "./chat-parts";

/**
 * The durable gate object the approval card renders (charter §3-P5(a), §3.4).
 *
 * **Why this is a repository read and not just the stream part.** A gate is
 * answered by echoing back exactly what was on the screen: `gate_response`
 * requires `expected_subject_sha256` and `expected_estimated_cost_cents`, and
 * the server refuses anything that does not match the immutable gate row. The
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
  gate_id: z.string().min(1),
  workspace_id: z.string(),
  project_id: z.string(),
  thread_id: z.string(),
  turn_id: z.string(),
  kind: z.string(),
  subject_ref: z.string(),
  subject_revision: z.number().int().nullable().default(null),
  expected_subject_sha256: z.string(),
  subject_snapshot: z.record(z.string(), z.unknown()).default({}),
  max_spend_cents: z.union([z.number(), z.string()]),
  currency: z.string(),
  addressee_user_id: z.string(),
  created_at: z.string(),
  answer: GateAnswerWireSchema.nullable().default(null),
  launches: z.array(GateLaunchWireSchema).default([]),
});

export interface ChatGateAnswer {
  turnId: string;
  actionRef: string;
  decision: string;
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
  currency: string;
  addresseeUserId: string;
  createdAt: string;
  answer: ChatGateAnswer | null;
  launches: readonly ChatGateLaunch[];
}

function toGate(wire: z.infer<typeof GateWireSchema>): ChatGate {
  return {
    gateId: wire.gate_id,
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
    addresseeUserId: wire.addressee_user_id,
    createdAt: wire.created_at,
    answer:
      wire.answer === null
        ? null
        : {
            turnId: wire.answer.turn_id,
            actionRef: wire.answer.action_ref,
            decision: wire.answer.decision,
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
 * read. The card then renders the request with its controls **disabled** and
 * says why, because an approve button that cannot send the required digest and
 * amount would refuse at the server anyway — and a card that guessed them would
 * be worse.
 */
export type GateCardState =
  | "requested"
  | "responded"
  | "denied"
  | "unavailable";

export interface GateCardModel {
  gateId: string;
  state: GateCardState;
  kind: string;
  title: string;
  summary: string | null;
  amountCents: number | null;
  currency: string | null;
  expectedSubjectSha256: string | null;
  permittedDecisions: readonly GateDecision[];
  decision: GateDecision | null;
  answeredAt: string | null;
  answeredByUserId: string | null;
  /** Non-null only in `unavailable`; the exact reason the card cannot act. */
  unavailableReason: string | null;
  /** The research run an approved gate's authority actually launched. */
  launches: readonly ChatGateLaunch[];
}

const ALL_DECISIONS: readonly GateDecision[] = [
  "approved",
  "rejected",
  "revised",
];

function decisionOf(value: string | null): GateDecision | null {
  const parsed = GateDecisionSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

const GATE_TITLES: Record<string, string> = {
  directive_confirmation: "Confirm research launch",
  plan_approval: "Approve plan",
  budget_approval: "Approve budget",
};

export function gateTitle(kind: string): string {
  return GATE_TITLES[kind] ?? kind.replaceAll("_", " ");
}

/**
 * Build the card model from whichever of the two sources exist.
 *
 * The durable gate wins wherever it is present; the stream part is the fallback
 * and the "a gate exists here" signal. A card with no durable gate and no
 * digest is `unavailable` — it cannot legally be answered, so it must not offer
 * to be.
 */
export function gateCardModel({
  gate,
  part,
  unavailableReason = null,
}: {
  gate: ChatGate | null;
  part: ChatGatePart | null;
  unavailableReason?: string | null;
}): GateCardModel | null {
  if (gate === null && part === null) return null;

  const gateId =
    gate?.gateId ?? part?.gateRef.objectId ?? part?.partId ?? "unknown-gate";
  const kind =
    gate?.kind ??
    (part && part.gateKind !== "agent_gate" ? part.gateKind : null) ??
    "directive_confirmation";
  const expectedSubjectSha256 =
    gate?.expectedSubjectSha256 ?? part?.expectedSubjectSha256 ?? null;
  const amountCents = gate?.maxSpendCents ?? part?.amountCents ?? null;
  const currency = gate?.currency ?? part?.currency ?? null;
  const decision =
    decisionOf(gate?.answer?.decision ?? null) ?? decisionOf(part?.decision ?? null);

  const answerable =
    expectedSubjectSha256 !== null && amountCents !== null && decision === null;

  let state: GateCardState;
  if (decision === "approved") state = "responded";
  else if (decision !== null) state = "denied";
  else if (answerable) state = "requested";
  else state = "unavailable";

  return {
    gateId,
    state,
    kind,
    title: part?.title ?? gateTitle(kind),
    summary: part?.summary ?? null,
    amountCents,
    currency,
    expectedSubjectSha256,
    permittedDecisions:
      part && part.permittedDecisions.length > 0
        ? part.permittedDecisions.filter((value): value is GateDecision =>
            ALL_DECISIONS.includes(value as GateDecision),
          )
        : ALL_DECISIONS,
    decision,
    answeredAt: gate?.answer?.answeredAt ?? part?.answeredAt ?? null,
    answeredByUserId:
      gate?.answer?.answeredByUserId ?? part?.answeredByUserId ?? null,
    unavailableReason:
      state === "unavailable"
        ? (unavailableReason ??
          "this deployment did not serve the gate's spend limit and subject digest")
        : null,
    launches: gate?.launches ?? [],
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
