import type { AgentRunEvent } from "./agentRunner";

/**
 * Derives the Moda-style plan checklist from the raw run-event stream. Pure
 * (no state, no policy) so the chat panel stays a renderer: the hook owns the
 * event list, this maps it to display rows. The loop emits granular,
 * per-iteration events (see apps/agent_runtime tools.record); we fold them
 * into a small ordered set of stages that only ever tick forward — a repair
 * iteration that re-authors never un-ticks an earlier stage.
 */

export interface AgentChecklistStep {
  key: string;
  label: string;
  status: "active" | "done";
}

const STAGE_ORDER = ["plan", "author", "apply", "preflight", "review", "finalize"] as const;
type Stage = (typeof STAGE_ORDER)[number];

const STAGE_LABEL: Record<Stage, string> = {
  plan: "Planning the design",
  author: "Drafting the design",
  apply: "Applying edits",
  preflight: "Checking layout & brand",
  review: "Reviewing the design",
  finalize: "Finalizing"
};

const EVENT_STAGE: Record<string, Stage> = {
  run_started: "plan",
  knowledge_loaded: "plan",
  director_decision: "plan",
  seeded_mode_coerced: "plan",
  edit_surface_recommended: "plan",
  dsl_block_requested: "author",
  dsl_block_produced: "author",
  fresh_rewrite_scene_started: "author",
  dsl_compiled: "apply",
  operations_applied: "apply",
  structured_edit_applied: "apply",
  asset_placed: "apply",
  image_generated: "apply",
  qr_generated: "apply",
  binding_set_validated: "apply",
  preflight_completed: "preflight",
  critic_preview_loaded: "review",
  critique_result: "review",
  edit_scoped_acceptance: "review",
  run_finalized: "finalize"
};

export function agentChecklist(
  events: AgentRunEvent[],
  isRunning: boolean
): AgentChecklistStep[] {
  let maxStage = -1;
  for (const event of events) {
    const stage = EVENT_STAGE[event.type];
    if (stage) {
      maxStage = Math.max(maxStage, STAGE_ORDER.indexOf(stage));
    }
  }
  if (maxStage < 0) {
    // Nothing mapped yet — while a turn is live, show the first stage warming
    // up so the checklist never flashes empty between "sent" and first event.
    return isRunning ? [{ key: "plan", label: STAGE_LABEL.plan, status: "active" }] : [];
  }
  return STAGE_ORDER.slice(0, maxStage + 1).map((stage, index) => ({
    key: stage,
    label: STAGE_LABEL[stage],
    status: index < maxStage ? "done" : isRunning ? "active" : "done"
  }));
}

const EVENT_LABEL: Record<string, string> = {
  run_started: "Started the design run",
  knowledge_loaded: "Loaded design knowledge",
  director_decision: "Chose an approach",
  seeded_mode_coerced: "Read the current design",
  edit_surface_recommended: "Scoped the edit",
  dsl_block_requested: "Requested a design block",
  dsl_block_produced: "Authored a design block",
  fresh_rewrite_scene_started: "Started a fresh rewrite",
  dsl_compiled: "Compiled the design",
  dsl_compile_failed: "Compile failed — repairing",
  dsl_compile_rejected: "Compile rejected — repairing",
  operations_applied: "Applied edits",
  operations_failed: "Edits rejected — repairing",
  structured_edit_applied: "Applied a structured edit",
  asset_placed: "Placed an asset",
  image_generated: "Generated imagery",
  qr_generated: "Generated a QR code",
  binding_set_validated: "Validated content bindings",
  preflight_completed: "Checked layout & brand",
  preflight_failed: "Preflight found issues — repairing",
  critic_preview_loaded: "Loaded the preview for review",
  critique_result: "Reviewed the design",
  critique_failed: "Review incomplete — retrying",
  edit_scoped_acceptance: "Accepted the scoped edit",
  repair_requested: "Requested a repair",
  run_finalized: "Finalized the run"
};

/** Friendly one-line label for a raw event (used in the "Show work" list). */
export function agentEventLabel(event: AgentRunEvent): string {
  const base = EVENT_LABEL[event.type] ?? event.type.replace(/_/g, " ");
  const iteration = event.data.iteration;
  return typeof iteration === "number" && iteration > 0
    ? `${base} · pass ${iteration}`
    : base;
}
