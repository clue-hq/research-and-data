import { z } from "zod";

/**
 * The turn-context inspector's wire shapes — the dev-lens drawer's four tabs.
 *
 * The backend half is `platform/api/clue_api/chat/inspector.py`, and its two
 * governing properties are mirrored here rather than restated:
 *
 * - **Zero new storage.** Every field is a C6 receipt the turn already wrote. A
 *   fact the platform did not make durable is absent, with the reason it is
 *   absent, and this file has nowhere to put a fabricated one.
 * - **Truncation is loud.** A body is either whole or replaced by its content
 *   address plus an `omittedReason`. There is no shortened-text case, because a
 *   half-rendered prompt would be worse than an absent one: a developer would
 *   tune against text the model never saw.
 *
 * The routes exist only in a development deployment — the backend refuses to
 * start with the flag set in production, and with it unset never registers
 * them — so the frontend discovers them by asking (`ChatInspectorCapability`),
 * never by reading its own environment.
 */

// --- shared ---------------------------------------------------------------

const BodyWireSchema = z.object({
  artifact_key: z.string(),
  sha256: z.string(),
  text: z.string().nullable().optional(),
  omitted_reason: z.string().nullable().optional(),
});

export interface ChatInspectorBody {
  artifactKey: string;
  sha256: string;
  text: string | null;
  /** `budget` | `unavailable` | `digest_mismatch` | `not_text`, or `null`. */
  omittedReason: string | null;
}

type BodyWire = z.infer<typeof BodyWireSchema>;

function toBody(wire: BodyWire): ChatInspectorBody {
  return {
    artifactKey: wire.artifact_key,
    sha256: wire.sha256,
    text: wire.text ?? null,
    omittedReason: wire.omitted_reason ?? null,
  };
}

// --- capability probe -----------------------------------------------------

export const ChatInspectorCapabilitySchema = z
  .object({
    data: z.object({
      enabled: z.boolean(),
      tabs: z.array(z.string()).default([]),
      budget_bytes: z.number().int().min(0),
      bodies_available: z.boolean(),
    }),
  })
  .transform((wire) => ({
    enabled: wire.data.enabled,
    tabs: wire.data.tabs,
    budgetBytes: wire.data.budget_bytes,
    bodiesAvailable: wire.data.bodies_available,
  }));

export type ChatInspectorCapability = z.infer<
  typeof ChatInspectorCapabilitySchema
>;

// --- tab 1: context -------------------------------------------------------

const ContextRefWireSchema = z.object({
  disposition: z.string(),
  ordinal: z.number().int(),
  ref_kind: z.string(),
  artifact_key: z.string().nullable().optional(),
  artifact_sha256: z.string().nullable().optional(),
  object_type: z.string().nullable().optional(),
  object_id: z.string().nullable().optional(),
  object_version: z.number().int().nullable().optional(),
  content_sha256: z.string().nullable().optional(),
  materialized_path: z.string().nullable().optional(),
  token_count: z.number().int().nullable().optional(),
  exclusion_reason_code: z.string().nullable().optional(),
  body: BodyWireSchema.nullable().optional(),
});

const ContextLayerWireSchema = z.object({
  ordinal: z.number().int(),
  layer: z.string(),
  token_budget: z.number().int(),
  token_count: z.number().int(),
  included_count: z.number().int(),
  excluded_count: z.number().int(),
  refs: z.array(ContextRefWireSchema).default([]),
});

export interface ChatInspectorContextRef {
  disposition: string;
  ordinal: number;
  refKind: string;
  artifactKey: string | null;
  objectType: string | null;
  objectId: string | null;
  objectVersion: number | null;
  contentSha256: string | null;
  materializedPath: string | null;
  tokenCount: number | null;
  exclusionReasonCode: string | null;
  body: ChatInspectorBody | null;
}

export interface ChatInspectorContextLayer {
  ordinal: number;
  layer: string;
  tokenBudget: number;
  tokenCount: number;
  includedCount: number;
  excludedCount: number;
  refs: readonly ChatInspectorContextRef[];
}

export interface ChatInspectorContext {
  turnId: string;
  contextBundleId: string;
  policyVersion: string;
  tokenCounterVersion: string;
  aggregateSha256: string;
  assembledAt: string;
  layers: readonly ChatInspectorContextLayer[];
  budgetBytes: number;
  truncated: boolean;
}

/** `null` for a turn that never assembled a bundle — an honest gap, not an empty skeleton. */
export const ChatInspectorContextResponseSchema = z
  .object({
    data: z
      .object({
        turn_id: z.string(),
        context_bundle_id: z.string(),
        schema_version: z.string(),
        policy_version: z.string(),
        token_counter_version: z.string(),
        aggregate_sha256: z.string(),
        assembled_at: z.string(),
        layers: z.array(ContextLayerWireSchema).default([]),
        budget_bytes: z.number().int(),
        truncated: z.boolean(),
      })
      .nullable(),
  })
  .transform((wire): ChatInspectorContext | null =>
    wire.data === null
      ? null
      : {
          turnId: wire.data.turn_id,
          contextBundleId: wire.data.context_bundle_id,
          policyVersion: wire.data.policy_version,
          tokenCounterVersion: wire.data.token_counter_version,
          aggregateSha256: wire.data.aggregate_sha256,
          assembledAt: wire.data.assembled_at,
          budgetBytes: wire.data.budget_bytes,
          truncated: wire.data.truncated,
          layers: wire.data.layers.map((layer) => ({
            ordinal: layer.ordinal,
            layer: layer.layer,
            tokenBudget: layer.token_budget,
            tokenCount: layer.token_count,
            includedCount: layer.included_count,
            excludedCount: layer.excluded_count,
            refs: layer.refs.map((ref) => ({
              disposition: ref.disposition,
              ordinal: ref.ordinal,
              refKind: ref.ref_kind,
              artifactKey: ref.artifact_key ?? null,
              objectType: ref.object_type ?? null,
              objectId: ref.object_id ?? null,
              objectVersion: ref.object_version ?? null,
              contentSha256: ref.content_sha256 ?? null,
              materializedPath: ref.materialized_path ?? null,
              tokenCount: ref.token_count ?? null,
              exclusionReasonCode: ref.exclusion_reason_code ?? null,
              body: ref.body ? toBody(ref.body) : null,
            })),
          })),
        },
  );

// --- tab 2: rounds --------------------------------------------------------

export interface ChatInspectorRound {
  modelCallId: string;
  sequence: number;
  requestedModel: string;
  /** The id that actually replied. Differs from `requestedModel` on a fallback. */
  answeringModel: string | null;
  status: string;
  inputTokens: number;
  outputTokens: number;
  costMillicredits: number;
  latencyMs: number;
  errorCode: string | null;
  startedAt: string;
  completedAt: string | null;
}

export const ChatInspectorRoundsResponseSchema = z
  .object({
    data: z
      .array(
        z.object({
          model_call_id: z.string(),
          sequence: z.number().int(),
          requested_model: z.string(),
          answering_model: z.string().nullable().optional(),
          status: z.string(),
          input_tokens: z.number().int(),
          output_tokens: z.number().int(),
          cost_millicredits: z.number().int(),
          latency_ms: z.number(),
          error_code: z.string().nullable().optional(),
          started_at: z.string(),
          completed_at: z.string().nullable().optional(),
        }),
      )
      .default([]),
  })
  .transform((wire): ChatInspectorRound[] =>
    wire.data.map((item) => ({
      modelCallId: item.model_call_id,
      sequence: item.sequence,
      requestedModel: item.requested_model,
      answeringModel: item.answering_model ?? null,
      status: item.status,
      inputTokens: item.input_tokens,
      outputTokens: item.output_tokens,
      costMillicredits: item.cost_millicredits,
      latencyMs: item.latency_ms,
      errorCode: item.error_code ?? null,
      startedAt: item.started_at,
      completedAt: item.completed_at ?? null,
    })),
  );

// --- tab 3: plan ----------------------------------------------------------

const PlanEventWireSchema = z.object({
  status: z.string(),
  reason_code: z.string().nullable().optional(),
  created_at: z.string(),
});

export interface ChatInspectorLedgerEntry {
  status: string;
  reasonCode: string | null;
  createdAt: string;
}

export interface ChatInspectorPlanOperation {
  nodeKey: string;
  ordinal: number;
  operationId: string;
  kind: string;
  address: string;
  estimatedCostMillicents: number;
  authoritySha256: string;
  validation: string;
}

export interface ChatInspectorPlan {
  planId: string;
  role: string;
  resourceManifestSha256: string;
  maxParallelism: number;
  estimatedCostMillicents: number;
  budgetLimitMillicents: number;
  validatedAt: string;
  /** What the model authored. */
  proposal: ChatInspectorBody;
  /** What validation admitted. The difference is the answer to "what was dropped?". */
  validated: ChatInspectorBody;
  operations: readonly ChatInspectorPlanOperation[];
  events: readonly ChatInspectorLedgerEntry[];
}

export interface ChatInspectorPlanView {
  turnId: string;
  plans: readonly ChatInspectorPlan[];
  /**
   * The turn's own status ledger. A plan the validator *rejects* is never
   * journaled, so it has no per-operation verdict; its refusal is here.
   */
  turnEvents: readonly ChatInspectorLedgerEntry[];
  budgetBytes: number;
  truncated: boolean;
}

export const ChatInspectorPlanResponseSchema = z
  .object({
    data: z.object({
      turn_id: z.string(),
      plans: z
        .array(
          z.object({
            plan_id: z.string(),
            role: z.string(),
            resource_manifest_sha256: z.string(),
            max_parallelism: z.number().int(),
            estimated_cost_millicents: z.number().int(),
            budget_limit_millicents: z.number().int(),
            validated_at: z.string(),
            proposal: BodyWireSchema,
            validated: BodyWireSchema,
            operations: z
              .array(
                z.object({
                  node_key: z.string(),
                  ordinal: z.number().int(),
                  operation_id: z.string(),
                  kind: z.string(),
                  address: z.string(),
                  estimated_cost_millicents: z.number().int(),
                  authority_sha256: z.string(),
                  validation: z.string().default("admitted"),
                }),
              )
              .default([]),
            events: z.array(PlanEventWireSchema).default([]),
          }),
        )
        .default([]),
      turn_events: z.array(PlanEventWireSchema).default([]),
      budget_bytes: z.number().int(),
      truncated: z.boolean(),
    }),
  })
  .transform((wire): ChatInspectorPlanView => {
    const ledger = (entry: z.infer<typeof PlanEventWireSchema>) => ({
      status: entry.status,
      reasonCode: entry.reason_code ?? null,
      createdAt: entry.created_at,
    });
    return {
      turnId: wire.data.turn_id,
      budgetBytes: wire.data.budget_bytes,
      truncated: wire.data.truncated,
      turnEvents: wire.data.turn_events.map(ledger),
      plans: wire.data.plans.map((plan) => ({
        planId: plan.plan_id,
        role: plan.role,
        resourceManifestSha256: plan.resource_manifest_sha256,
        maxParallelism: plan.max_parallelism,
        estimatedCostMillicents: plan.estimated_cost_millicents,
        budgetLimitMillicents: plan.budget_limit_millicents,
        validatedAt: plan.validated_at,
        proposal: toBody(plan.proposal),
        validated: toBody(plan.validated),
        events: plan.events.map(ledger),
        operations: plan.operations.map((operation) => ({
          nodeKey: operation.node_key,
          ordinal: operation.ordinal,
          operationId: operation.operation_id,
          kind: operation.kind,
          address: operation.address,
          estimatedCostMillicents: operation.estimated_cost_millicents,
          authoritySha256: operation.authority_sha256,
          validation: operation.validation,
        })),
      })),
    };
  });

// --- tab 4: tools ---------------------------------------------------------

export interface ChatInspectorToolCall {
  planId: string;
  nodeKey: string;
  operationId: string;
  kind: string;
  address: string;
  estimatedCostMillicents: number;
  arguments: ChatInspectorBody;
  /** `null` means admitted and not completed — never "no receipt, so no card". */
  result: ChatInspectorBody | null;
  replayed: boolean | null;
  referenceCount: number | null;
  completedAt: string | null;
}

export interface ChatInspectorToolsView {
  turnId: string;
  calls: readonly ChatInspectorToolCall[];
  budgetBytes: number;
  truncated: boolean;
}

export const ChatInspectorToolsResponseSchema = z
  .object({
    data: z.object({
      turn_id: z.string(),
      calls: z
        .array(
          z.object({
            plan_id: z.string(),
            node_key: z.string(),
            operation_id: z.string(),
            kind: z.string(),
            address: z.string(),
            estimated_cost_millicents: z.number().int(),
            arguments: BodyWireSchema,
            result: BodyWireSchema.nullable().optional(),
            replayed: z.boolean().nullable().optional(),
            reference_count: z.number().int().nullable().optional(),
            completed_at: z.string().nullable().optional(),
          }),
        )
        .default([]),
      budget_bytes: z.number().int(),
      truncated: z.boolean(),
    }),
  })
  .transform((wire): ChatInspectorToolsView => ({
    turnId: wire.data.turn_id,
    budgetBytes: wire.data.budget_bytes,
    truncated: wire.data.truncated,
    calls: wire.data.calls.map((call) => ({
      planId: call.plan_id,
      nodeKey: call.node_key,
      operationId: call.operation_id,
      kind: call.kind,
      address: call.address,
      estimatedCostMillicents: call.estimated_cost_millicents,
      arguments: toBody(call.arguments),
      result: call.result ? toBody(call.result) : null,
      replayed: call.replayed ?? null,
      referenceCount: call.reference_count ?? null,
      completedAt: call.completed_at ?? null,
    })),
  }));

// --- presentation helpers (pure) ------------------------------------------

/** The seven layers' human names. Unknown ordinals fall back to the wire name. */
const LAYER_NAMES: Record<string, string> = {
  l1_identity: "L1 · Identity",
  l2_workspace_product: "L2 · Workspace & product",
  l3_project: "L3 · Project",
  l4_memory: "L4 · Memory",
  l5_focus: "L5 · Focus",
  l6_conversation: "L6 · Conversation",
  l7_turn: "L7 · Turn",
};

export function layerLabel(layer: string): string {
  return LAYER_NAMES[layer] ?? layer;
}

/**
 * A layer's share of its own budget, clamped to `[0, 1]`.
 *
 * A zero budget reports `0` rather than dividing: a layer that was allotted
 * nothing did not "fill 100% of nothing", and a meter that read full would say
 * the opposite of what happened.
 */
export function budgetRatio(tokenCount: number, tokenBudget: number): number {
  if (tokenBudget <= 0) return 0;
  return Math.max(0, Math.min(1, tokenCount / tokenBudget));
}

/** What to show where a body is not. Never an empty string masquerading as one. */
export function bodyPlaceholder(body: ChatInspectorBody): string | null {
  if (body.text !== null) return null;
  switch (body.omittedReason) {
    case "budget":
      return "Too large for this response's byte budget — not truncated, withheld.";
    case "digest_mismatch":
      return "The stored bytes no longer match the digest this receipt committed to.";
    case "not_text":
      return "Not a text artifact.";
    case "unavailable":
      return "Erased, purged, or not served by this deployment.";
    default:
      return "Unavailable.";
  }
}
