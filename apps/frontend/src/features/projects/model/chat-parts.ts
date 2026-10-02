import { z } from "zod";

/**
 * The typed message parts the Clue turn stream projects.
 *
 * This file is the frontend half of charter §3.1 (the Clue-part ↔ renderer map)
 * and §3.4 (the payload floors), mirroring
 * `platform/api/clue_api/chat/turn_parts.py`. Two rules from that module carry
 * over verbatim and are why this file exists at all:
 *
 * - **Replacement, not append.** Every snapshot is the full current state of
 *   its part and carries a `revision` that increases per emission. A consumer
 *   replaces by `partId`; it never merges two half-cards.
 * - **No display copy.** The backend sends semantic state; the adapters in
 *   `components/` choose the words, the icons, and the motion. Nothing here
 *   accepts a label like "Thought for 5 seconds".
 *
 * The wire is snake_case (the chat surface is a Python/pydantic surface, unlike
 * the camelCase `/frontend/v1` accounts surface), so every schema below parses
 * the wire shape and transforms it into the camelCase domain type the rest of
 * the feature speaks. That mapping is the only place the two spellings meet.
 */

/** §3.1's domain-part vocabulary — `PartKind` in `turn_parts.py`. */
export const ChatPartKindSchema = z.enum([
  "text",
  "reasoning",
  "agent_activity",
  "tool",
  "task",
  "plan",
  "gate",
  "sources",
  "action",
  "clarification",
]);

/** The AI Elements tool lifecycle, spelled exactly as §3.4 requires. */
export const ToolPartStateSchema = z.enum([
  "input-streaming",
  "input-available",
  "approval-requested",
  "approval-responded",
  "output-available",
  "output-denied",
  "output-error",
]);

/** §3.4's task vocabulary: one run stays one visible task at 1 account or 500. */
export const TaskStateSchema = z.enum([
  "queued",
  "scoping",
  "light_research",
  "checkpoint",
  "deep_research",
  "synthesizing",
  "needs_input",
  "partial",
  "completed",
  "failed",
  "suspended",
]);

export const ActivityStepStatusSchema = z.enum([
  "pending",
  "active",
  "complete",
  "error",
]);

export const ReasoningStateSchema = z.enum(["active", "complete", "error"]);

/** What a human may answer on a gate (`DECISIONS` in `agent_gate.py`). */
export const GateDecisionSchema = z.enum(["approved", "rejected", "revised"]);

/**
 * A workspace-scoped pointer at a durable object.
 *
 * Deliberately tolerant: `object_ref_wire` duck-types whatever ref shape the
 * emitter held, so a ref may carry a domain type/id, a content address, or
 * both. Every member is optional because an honest gap beats a fabricated id.
 */
const ObjectRefWireSchema = z.object({
  workspace_id: z.string().optional(),
  object_type: z.string().optional(),
  object_id: z.string().optional(),
  version: z.number().int().optional(),
  artifact_key: z.string().optional(),
  sha256: z.string().optional(),
});

export interface ChatObjectRef {
  workspaceId: string | null;
  objectType: string | null;
  objectId: string | null;
  version: number | null;
  artifactKey: string | null;
  sha256: string | null;
}

type ObjectRefWire = z.infer<typeof ObjectRefWireSchema>;

function toObjectRef(wire: ObjectRefWire): ChatObjectRef {
  return {
    workspaceId: wire.workspace_id ?? null,
    objectType: wire.object_type ?? null,
    objectId: wire.object_id ?? null,
    version: wire.version ?? null,
    artifactKey: wire.artifact_key ?? null,
    sha256: wire.sha256 ?? null,
  };
}

const partBase = {
  part_id: z.string().min(1),
  revision: z.number().int().min(1).default(1),
};

// --- tool ----------------------------------------------------------------

const ToolPartWireSchema = z.object({
  ...partBase,
  kind: z.literal("tool"),
  state: ToolPartStateSchema,
  tool_name: z.string().min(1),
  tool_version: z.string().nullable().optional(),
  tool_call_id: z.string(),
  node_key: z.string(),
  operation_id: z.string().nullable().optional(),
  // Structured JSON, never pre-rendered prose (§3.4). The adapter chooses the
  // disclosure copy; the backend states what happened.
  input: z.record(z.string(), z.unknown()).nullable().optional(),
  output: z.record(z.string(), z.unknown()).nullable().optional(),
  error_code: z.string().nullable().optional(),
  error_reasons: z.array(z.string()).default([]),
});

export interface ChatToolPart {
  kind: "tool";
  partId: string;
  revision: number;
  state: z.infer<typeof ToolPartStateSchema>;
  toolName: string;
  toolVersion: string | null;
  toolCallId: string;
  nodeKey: string;
  operationId: string | null;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  errorCode: string | null;
  errorReasons: readonly string[];
}

// --- reasoning -----------------------------------------------------------

/**
 * A model round's status card.
 *
 * `text` is absent in every production deployment: charter §3.3's ratified
 * contract is that what streams as reasoning is a safe activity summary and
 * never provider reasoning content, and the backend refuses to start with the
 * raw lens configured outside a developer's own deployment. It is optional here
 * for exactly that lens — `CLUE_CHAT_REASONING_TRACE_MODE=raw`, a prompt/skill
 * tuning affordance — and **payload presence alone decides whether it renders**.
 * No frontend flag: a client cannot know whether the server sent a trace by
 * reading its own environment, only by looking at what arrived.
 *
 * `text_ephemeral` is the backend saying the load-bearing thing about that
 * text: unlike assistant prose it has no durable counterpart, so it exists for
 * as long as the stream held it and cannot be re-fetched after a reload or a
 * `stream.reset`. The frontend groups supplied text into one plain-text
 * disclosure per response; its presentation does not change that retention.
 */
const ReasoningPartWireSchema = z.object({
  ...partBase,
  kind: z.literal("reasoning"),
  state: ReasoningStateSchema,
  round_ordinal: z.number().int().min(1),
  requested_tool_calls: z.number().int().min(0).default(0),
  started_at: z.string(),
  completed_at: z.string().nullable().optional(),
  text: z.string().nullable().optional(),
  text_ephemeral: z.boolean().nullable().optional(),
});

export interface ChatReasoningPart {
  kind: "reasoning";
  partId: string;
  revision: number;
  state: z.infer<typeof ReasoningStateSchema>;
  roundOrdinal: number;
  requestedToolCalls: number;
  startedAt: string;
  completedAt: string | null;
  /** The dev-lens raw trace, when one was streamed. `null` is the normal case. */
  text: string | null;
  /** True whenever `text` is set: this text is not part of the durable turn. */
  textEphemeral: boolean;
}

// --- agent activity ------------------------------------------------------

const ActivityStepWireSchema = z.object({
  id: z.string().min(1),
  kind: z.string(),
  status: ActivityStepStatusSchema,
  label: z.string(),
  description: z.string().nullable().optional(),
  object_refs: z.array(ObjectRefWireSchema).default([]),
  started_at: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
});

const AgentActivityPartWireSchema = z.object({
  ...partBase,
  kind: z.literal("agent_activity"),
  title: z.string(),
  steps: z.array(ActivityStepWireSchema).default([]),
});

export interface ChatActivityStep {
  id: string;
  kind: string;
  status: z.infer<typeof ActivityStepStatusSchema>;
  label: string;
  description: string | null;
  objectRefs: readonly ChatObjectRef[];
  startedAt: string | null;
  completedAt: string | null;
}

export interface ChatActivityPart {
  kind: "agent_activity";
  partId: string;
  revision: number;
  title: string;
  steps: readonly ChatActivityStep[];
}

// --- task ----------------------------------------------------------------

const TaskCountsWireSchema = z.object({
  total: z.number().int().min(0).default(0),
  queued: z.number().int().min(0).default(0),
  running: z.number().int().min(0).default(0),
  completed: z.number().int().min(0).default(0),
  partial: z.number().int().min(0).default(0),
  /** Defaulted like its siblings, so a snapshot persisted before the split still parses. */
  needs_review: z.number().int().min(0).default(0),
  blocked: z.number().int().min(0).default(0),
  failed: z.number().int().min(0).default(0),
});

const TaskPartWireSchema = z.object({
  ...partBase,
  kind: z.literal("task"),
  state: TaskStateSchema,
  title: z.string(),
  run_ref: ObjectRefWireSchema,
  counts: TaskCountsWireSchema.prefault({}),
  exception_refs: z.array(ObjectRefWireSchema).default([]),
});

export interface ChatTaskCounts {
  total: number;
  queued: number;
  running: number;
  completed: number;
  partial: number;
  /** Finished and routed to a human — a queue, not the shortfall `partial` names. */
  needsReview: number;
  blocked: number;
  failed: number;
}

export interface ChatTaskPart {
  kind: "task";
  partId: string;
  revision: number;
  state: z.infer<typeof TaskStateSchema>;
  title: string;
  runRef: ChatObjectRef;
  counts: ChatTaskCounts;
  exceptionRefs: readonly ChatObjectRef[];
}

function toTaskPart(wire: z.infer<typeof TaskPartWireSchema>): ChatTaskPart {
  return {
    kind: "task",
    partId: wire.part_id,
    revision: wire.revision,
    state: wire.state,
    title: wire.title,
    runRef: toObjectRef(wire.run_ref),
    counts: {
      total: wire.counts.total,
      queued: wire.counts.queued,
      running: wire.counts.running,
      completed: wire.counts.completed,
      partial: wire.counts.partial,
      needsReview: wire.counts.needs_review,
      blocked: wire.counts.blocked,
      failed: wire.counts.failed,
    },
    exceptionRefs: wire.exception_refs.map(toObjectRef),
  };
}

// --- plan ----------------------------------------------------------------

const PlanStepWireSchema = z.object({
  id: z.string().min(1),
  label: z.string(),
  status: ActivityStepStatusSchema.default("pending"),
});

const PlanPartWireSchema = z.object({
  ...partBase,
  kind: z.literal("plan"),
  plan_ref: ObjectRefWireSchema,
  revision_label: z.string().nullable().optional(),
  title: z.string(),
  summary: z.string().nullable().optional(),
  steps: z.array(PlanStepWireSchema).default([]),
  status: z.string().default("proposed"),
  subject_refs: z.array(ObjectRefWireSchema).default([]),
});

export interface ChatPlanStep {
  id: string;
  label: string;
  status: z.infer<typeof ActivityStepStatusSchema>;
}

export interface ChatPlanPart {
  kind: "plan";
  partId: string;
  revision: number;
  planRef: ChatObjectRef;
  revisionLabel: string | null;
  title: string;
  summary: string | null;
  steps: readonly ChatPlanStep[];
  status: string;
  subjectRefs: readonly ChatObjectRef[];
}

// --- gate ----------------------------------------------------------------

const GatePartWireSchema = z.object({
  ...partBase,
  kind: z.literal("gate"),
  gate_ref: ObjectRefWireSchema,
  gate_kind: z.string(),
  state: z.string(),
  title: z.string().nullable().optional(),
  summary: z.string().nullable().optional(),
  subject_refs: z.array(ObjectRefWireSchema).default([]),
  expected_subject_sha256: z.string().nullable().optional(),
  // D-5: money crosses the wire as a cent count plus its unit; the client
  // formats. `amount_cents` is `int | None` on the backend part, but the gate
  // projection stores `numeric(20,4)`, so a string spelling is accepted too.
  amount_cents: z.union([z.number(), z.string()]).nullable().optional(),
  currency: z.string().nullable().optional(),
  addressee_user_id: z.string().nullable().optional(),
  permitted_decisions: z.array(z.string()).default([]),
  decision: z.string().nullable().optional(),
  answered_by_user_id: z.string().nullable().optional(),
  answered_at: z.string().nullable().optional(),
});

export interface ChatGatePart {
  kind: "gate";
  partId: string;
  revision: number;
  gateRef: ChatObjectRef;
  gateKind: string;
  state: string;
  title: string | null;
  summary: string | null;
  subjectRefs: readonly ChatObjectRef[];
  expectedSubjectSha256: string | null;
  amountCents: number | null;
  currency: string | null;
  addresseeUserId: string | null;
  permittedDecisions: readonly string[];
  decision: string | null;
  answeredByUserId: string | null;
  answeredAt: string | null;
}

/** Parse a cent amount that may arrive as a JSON number or a decimal string. */
export function parseCentAmount(
  value: number | string | null | undefined,
): number | null {
  if (value === null || value === undefined) return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

// --- clarification -------------------------------------------------------

const ClarificationQuestionWireSchema = z.object({
  id: z.string().min(1),
  question: z.string(),
  why_it_matters: z.string().default(""),
  options: z.array(z.string()).default([]),
  default: z.string(),
  allow_freeform: z.boolean().default(true),
});

/**
 * Spec 2026-09-20 (clarification cards) §2.1: a design document's opening-move
 * questions, one part per document whose run stopped to ask.
 *
 * `account_name` is `.nullable().optional()` because the backend's `_Part.wire()`
 * drops `None` fields — an untagged document sends no `account_name` key at all,
 * and both spellings mean the same thing here: no account, render no suffix.
 */
const ClarificationPartWireSchema = z.object({
  ...partBase,
  kind: z.literal("clarification"),
  document_id: z.string().min(1),
  document_title: z.string(),
  doc_kind: z.string(),
  account_name: z.string().nullable().optional(),
  run_id: z.string().min(1),
  // No default: a clarification part without its questions is not a card with
  // nothing in it, it is an unreadable snapshot — the stream drops it rather
  // than rendering an empty card.
  questions: z.array(ClarificationQuestionWireSchema),
});

export interface ChatClarificationQuestion {
  id: string;
  question: string;
  whyItMatters: string;
  options: readonly string[];
  /** What the runtime uses when the question is skipped. */
  default: string;
  allowFreeform: boolean;
}

export interface ChatClarificationPart {
  kind: "clarification";
  partId: string;
  revision: number;
  documentId: string;
  documentTitle: string;
  docKind: string;
  accountName: string | null;
  runId: string;
  questions: readonly ChatClarificationQuestion[];
}

// --- sources -------------------------------------------------------------

const SourceItemWireSchema = z.object({
  source_id: z.string().min(1),
  title: z.string().nullable().optional(),
  url: z.string().nullable().optional(),
  source_kind: z.string().nullable().optional(),
  evidence_ref: ObjectRefWireSchema.nullable().optional(),
});

const SourcesPartWireSchema = z.object({
  ...partBase,
  kind: z.literal("sources"),
  items: z.array(SourceItemWireSchema).default([]),
});

export interface ChatSourceItem {
  sourceId: string;
  title: string | null;
  url: string | null;
  sourceKind: string | null;
  evidenceRef: ChatObjectRef | null;
}

export interface ChatSourcesPart {
  kind: "sources";
  partId: string;
  revision: number;
  items: readonly ChatSourceItem[];
}

// --- text ----------------------------------------------------------------

/**
 * Assistant prose.
 *
 * It has no wire snapshot: text arrives as `text.start` / `text.delta` /
 * `text.end`, and the transcript reducer accumulates it. `text` is allowed to
 * be empty — that is the streaming-start shape the old `z.string().min(1)`
 * made unrepresentable (charter §2's D-4 hazard list).
 */
export interface ChatTextPart {
  kind: "text";
  partId: string;
  revision: number;
  text: string;
  /** True between `text.start` and `text.end` — drives Shimmer, never a wire value. */
  streaming: boolean;
  /** A stopped or failed attempt keeps its partial text visible for audit (§3.3(8)). */
  failed: boolean;
  failureReason: string | null;
}

// --- the union -----------------------------------------------------------

export type ChatPart =
  | ChatTextPart
  | ChatReasoningPart
  | ChatActivityPart
  | ChatToolPart
  | ChatTaskPart
  | ChatPlanPart
  | ChatGatePart
  | ChatSourcesPart
  | ChatClarificationPart;

/**
 * One part snapshot, exactly as `part.created|updated|completed|failed` carries it.
 *
 * `text` and `action` are absent on purpose: text never arrives as a snapshot,
 * and `PartKind.ACTION` exists in the backend enum with no model and no
 * emitter, so accepting one here would mean inventing its payload.
 */
export const ChatPartSnapshotSchema = z
  .discriminatedUnion("kind", [
    ToolPartWireSchema,
    ReasoningPartWireSchema,
    AgentActivityPartWireSchema,
    TaskPartWireSchema,
    PlanPartWireSchema,
    GatePartWireSchema,
    SourcesPartWireSchema,
    ClarificationPartWireSchema,
  ])
  .transform((wire): ChatPart => {
    switch (wire.kind) {
      case "tool":
        return {
          kind: "tool",
          partId: wire.part_id,
          revision: wire.revision,
          state: wire.state,
          toolName: wire.tool_name,
          toolVersion: wire.tool_version ?? null,
          toolCallId: wire.tool_call_id,
          nodeKey: wire.node_key,
          operationId: wire.operation_id ?? null,
          input: wire.input ?? null,
          output: wire.output ?? null,
          errorCode: wire.error_code ?? null,
          errorReasons: wire.error_reasons,
        };
      case "reasoning":
        return {
          kind: "reasoning",
          partId: wire.part_id,
          revision: wire.revision,
          state: wire.state,
          roundOrdinal: wire.round_ordinal,
          requestedToolCalls: wire.requested_tool_calls,
          startedAt: wire.started_at,
          completedAt: wire.completed_at ?? null,
          text: wire.text ?? null,
          textEphemeral: wire.text_ephemeral ?? false,
        };
      case "agent_activity":
        return {
          kind: "agent_activity",
          partId: wire.part_id,
          revision: wire.revision,
          title: wire.title,
          steps: wire.steps.map((step) => ({
            id: step.id,
            kind: step.kind,
            status: step.status,
            label: step.label,
            description: step.description ?? null,
            objectRefs: step.object_refs.map(toObjectRef),
            startedAt: step.started_at ?? null,
            completedAt: step.completed_at ?? null,
          })),
        };
      case "task":
        return toTaskPart(wire);
      case "plan":
        return {
          kind: "plan",
          partId: wire.part_id,
          revision: wire.revision,
          planRef: toObjectRef(wire.plan_ref),
          revisionLabel: wire.revision_label ?? null,
          title: wire.title,
          summary: wire.summary ?? null,
          steps: wire.steps,
          status: wire.status,
          subjectRefs: wire.subject_refs.map(toObjectRef),
        };
      case "gate":
        return {
          kind: "gate",
          partId: wire.part_id,
          revision: wire.revision,
          gateRef: toObjectRef(wire.gate_ref),
          gateKind: wire.gate_kind,
          state: wire.state,
          title: wire.title ?? null,
          summary: wire.summary ?? null,
          subjectRefs: wire.subject_refs.map(toObjectRef),
          expectedSubjectSha256: wire.expected_subject_sha256 ?? null,
          amountCents: parseCentAmount(wire.amount_cents),
          currency: wire.currency ?? null,
          addresseeUserId: wire.addressee_user_id ?? null,
          permittedDecisions: wire.permitted_decisions,
          decision: wire.decision ?? null,
          answeredByUserId: wire.answered_by_user_id ?? null,
          answeredAt: wire.answered_at ?? null,
        };
      case "clarification":
        return {
          kind: "clarification",
          partId: wire.part_id,
          revision: wire.revision,
          documentId: wire.document_id,
          documentTitle: wire.document_title,
          docKind: wire.doc_kind,
          accountName: wire.account_name ?? null,
          runId: wire.run_id,
          questions: wire.questions.map((question) => ({
            id: question.id,
            question: question.question,
            whyItMatters: question.why_it_matters,
            options: question.options,
            default: question.default,
            allowFreeform: question.allow_freeform,
          })),
        };
      case "sources":
        return {
          kind: "sources",
          partId: wire.part_id,
          revision: wire.revision,
          items: wire.items.map((item) => ({
            sourceId: item.source_id,
            title: item.title ?? null,
            url: item.url ?? null,
            sourceKind: item.source_kind ?? null,
            evidenceRef:
              item.evidence_ref === null || item.evidence_ref === undefined
                ? null
                : toObjectRef(item.evidence_ref),
          })),
        };
    }
  });

export type ChatPartKind = z.infer<typeof ChatPartKindSchema>;
export type ToolPartState = z.infer<typeof ToolPartStateSchema>;
export type TaskState = z.infer<typeof TaskStateSchema>;
export type ActivityStepStatus = z.infer<typeof ActivityStepStatusSchema>;
export type ReasoningState = z.infer<typeof ReasoningStateSchema>;
export type GateDecision = z.infer<typeof GateDecisionSchema>;
