/**
 * Local preview data for the projects chat flow.
 *
 * Fixtures are wire-shaped: every object below is exactly what the backend
 * serves, so the fixture adapters validate through the same schemas the HTTP
 * adapters do. A fixture that skipped validation would let the two drift, which
 * is the failure the repository seam exists to prevent.
 *
 * The scripted stream mirrors the canonical charter §5 fixture — one project,
 * one thread, one confirmed directive, two accounts — and exercises every event
 * class the reducer must handle: rounds, a governed tool call, aggregated
 * activity, genuine text deltas split mid-word, a gate, and a research task.
 */

export const FIXTURE_PROJECT_ID = "10m-landing-page-campaign";
export const FIXTURE_THREAD_ID = "thread-primary";
const FIXTURE_SECOND_THREAD_ID = "thread-launch-review";
const FIXTURE_TURN_ID = "8c4a0b1e-0000-4000-8000-000000000001";
const FIXTURE_ATTEMPT_ID = "8c4a0b1e-0000-4000-8000-0000000000a1";
const FIXTURE_MESSAGE_ID = "8c4a0b1e-0000-4000-8000-0000000000b1";
export const FIXTURE_GATE_ID = "8c4a0b1e-0000-4000-8000-0000000000c1";
const FIXTURE_SHA =
  "3f2a91c0d4b57e68a1c93f0b2d7e845619fa03cd7b1e2964805af3c1d92b7e40";

export const fixtureThreads = [
  {
    id: FIXTURE_THREAD_ID,
    title: "Landing page concepts",
    href: `/projects/${FIXTURE_PROJECT_ID}?thread=${FIXTURE_THREAD_ID}`,
    status: "idle",
    pinned: true,
    project_id: FIXTURE_PROJECT_ID,
    created_at: "2026-08-05T09:12:00Z",
    updated_at: "2026-08-09T11:04:00Z",
  },
  {
    id: FIXTURE_SECOND_THREAD_ID,
    title: null,
    href: `/projects/${FIXTURE_PROJECT_ID}?thread=${FIXTURE_SECOND_THREAD_ID}`,
    status: "approval",
    pinned: false,
    project_id: FIXTURE_PROJECT_ID,
    created_at: "2026-08-08T15:40:00Z",
    updated_at: "2026-08-09T10:58:00Z",
  },
] as const;

export const fixtureMessages = [
  {
    id: "8c4a0b1e-0000-4000-8000-0000000000a0",
    turn_id: FIXTURE_TURN_ID,
    thread_id: FIXTURE_THREAD_ID,
    sequence: 1,
    role: "user",
    body_artifact_key: `ws-demo/${FIXTURE_SHA}`,
    body_sha256: FIXTURE_SHA,
    body: "Research OpenAI and Anthropic, then get the deep pass moving.",
    body_unavailable_reason: null,
    created_at: "2026-08-09T11:02:11Z",
    refs: [],
  },
  {
    id: FIXTURE_MESSAGE_ID,
    turn_id: FIXTURE_TURN_ID,
    thread_id: FIXTURE_THREAD_ID,
    sequence: 2,
    role: "assistant",
    body_artifact_key: `ws-demo/${FIXTURE_SHA}`,
    body_sha256: FIXTURE_SHA,
    body:
      "I drafted a **deep research directive** covering both accounts.\n\n" +
      "- OpenAI — buying committee plus operational pain\n" +
      "- Anthropic — buying committee plus operational pain\n\n" +
      "Approve the card below and I will launch it.",
    body_unavailable_reason: null,
    created_at: "2026-08-09T11:02:48Z",
    refs: [
      {
        flavor: "open_gate",
        workspace_id: "ws-demo",
        object_type: "agent_gate",
        object_id: FIXTURE_GATE_ID,
        version: null,
        ordinal: 0,
      },
    ],
  },
] as const;

export const fixtureTurns = [
  {
    turn_id: FIXTURE_TURN_ID,
    thread_id: FIXTURE_THREAD_ID,
    project_id: FIXTURE_PROJECT_ID,
    state: "awaiting_input",
    requested_at: "2026-08-09T11:02:11Z",
    last_event_id: 24,
    generation_attempts: 1,
  },
] as const;

export const fixtureGates = [
  {
    gate_id: FIXTURE_GATE_ID,
    workspace_id: "ws-demo",
    project_id: FIXTURE_PROJECT_ID,
    thread_id: FIXTURE_THREAD_ID,
    turn_id: FIXTURE_TURN_ID,
    kind: "directive_confirmation",
    subject_ref: "research_directive:2f7c",
    subject_revision: 2,
    expected_subject_sha256: FIXTURE_SHA,
    subject_snapshot: {
      research_directive_id: "2f7c9a10-0000-4000-8000-000000000010",
      account_count: 2,
      accounts: ["OpenAI", "Anthropic"],
    },
    permitted_decisions: ["approved", "rejected", "revised"],
    max_spend_cents: "24000.0000",
    currency: "USD",
    addressee_user_id: "usr_demo",
    created_at: "2026-08-09T11:02:48Z",
    answer: null,
    launches: [],
  },
] as const;

/**
 * One scripted turn, as §3.2 frames.
 *
 * The text deltas split mid-word and mid-Markdown on purpose: reconstructing
 * them is the whole point of the reducer, and a fixture that only split on word
 * boundaries would never catch it.
 */
export function fixtureTurnEvents(turnId: string): Record<string, unknown>[] {
  const base = {
    schema_version: "1",
    project_id: FIXTURE_PROJECT_ID,
    thread_id: FIXTURE_THREAD_ID,
    turn_id: turnId,
    generation_attempt_id: FIXTURE_ATTEMPT_ID,
  };
  const textPartId = `text:${FIXTURE_ATTEMPT_ID}:1:0`;
  const deltas = [
    "Looking at both accounts now. ",
    "I found **two",
    " strong signals** worth ",
    "chasing:\n\n- OpenAI is hiring platform ",
    "engineers\n- Anthropic shipped an enterprise tier\n\n",
    "Shall I take the deep pass?",
  ];
  let sequence = 0;
  let eventId = 100;
  const frame = (payload: Record<string, unknown>) => ({
    ...base,
    event_id: (eventId += 1),
    sequence: (sequence += 1),
    occurred_at: "2026-08-09T11:20:00Z",
    ...payload,
  });

  return [
    frame({ type: "turn.accepted", source: "route", kind: "message" }),
    frame({ type: "turn.started", attempt_ordinal: 1 }),
    frame({
      type: "part.created",
      part_id: `reasoning:${FIXTURE_ATTEMPT_ID}:1`,
      part_kind: "reasoning",
      message_id: FIXTURE_MESSAGE_ID,
      part: {
        part_id: `reasoning:${FIXTURE_ATTEMPT_ID}:1`,
        kind: "reasoning",
        revision: 1,
        state: "active",
        round_ordinal: 1,
        requested_tool_calls: 0,
        started_at: "2026-08-09T11:20:00Z",
      },
    }),
    frame({
      type: "part.created",
      part_id: `activity:${FIXTURE_ATTEMPT_ID}`,
      part_kind: "agent_activity",
      message_id: FIXTURE_MESSAGE_ID,
      part: {
        part_id: `activity:${FIXTURE_ATTEMPT_ID}`,
        kind: "agent_activity",
        revision: 1,
        title: "Agent activity",
        steps: [
          {
            id: "round:1",
            kind: "model_round",
            status: "active",
            label: "Model round 1",
            started_at: "2026-08-09T11:20:00Z",
          },
        ],
      },
    }),
    frame({
      type: "part.created",
      part_id: "tool:draft_directive",
      part_kind: "tool",
      message_id: FIXTURE_MESSAGE_ID,
      part: {
        part_id: "tool:draft_directive",
        kind: "tool",
        revision: 1,
        state: "input-available",
        tool_name: "draft_account_research_directive",
        tool_version: "2",
        tool_call_id: "call_01",
        node_key: "draft_directive",
        input: { account_count: 2 },
      },
    }),
    frame({
      type: "part.completed",
      part_id: "tool:draft_directive",
      part_kind: "tool",
      message_id: FIXTURE_MESSAGE_ID,
      part: {
        part_id: "tool:draft_directive",
        kind: "tool",
        revision: 2,
        state: "output-available",
        tool_name: "draft_account_research_directive",
        tool_version: "2",
        tool_call_id: "call_01",
        node_key: "draft_directive",
        input: { account_count: 2 },
        output: { research_directive_id: "2f7c9a10", accounts: 2 },
      },
    }),
    frame({
      type: "part.completed",
      part_id: `reasoning:${FIXTURE_ATTEMPT_ID}:1`,
      part_kind: "reasoning",
      message_id: FIXTURE_MESSAGE_ID,
      part: {
        part_id: `reasoning:${FIXTURE_ATTEMPT_ID}:1`,
        kind: "reasoning",
        revision: 2,
        state: "complete",
        round_ordinal: 1,
        requested_tool_calls: 1,
        started_at: "2026-08-09T11:20:00Z",
        completed_at: "2026-08-09T11:20:04Z",
      },
    }),
    frame({
      type: "part.updated",
      part_id: `activity:${FIXTURE_ATTEMPT_ID}`,
      part_kind: "agent_activity",
      message_id: FIXTURE_MESSAGE_ID,
      part: {
        part_id: `activity:${FIXTURE_ATTEMPT_ID}`,
        kind: "agent_activity",
        revision: 2,
        title: "Agent activity",
        steps: [
          {
            id: "round:1",
            kind: "model_round",
            status: "complete",
            label: "Model round 1",
            started_at: "2026-08-09T11:20:00Z",
            completed_at: "2026-08-09T11:20:04Z",
          },
          {
            id: "tool:draft_directive",
            kind: "tool_call",
            status: "complete",
            label: "draft_account_research_directive@2",
            completed_at: "2026-08-09T11:20:03Z",
          },
        ],
      },
    }),
    frame({
      type: "text.start",
      part_id: textPartId,
      part_kind: "text",
      message_id: FIXTURE_MESSAGE_ID,
      round_ordinal: 1,
    }),
    ...deltas.map((delta, index) =>
      frame({
        type: "text.delta",
        part_id: textPartId,
        part_kind: "text",
        message_id: FIXTURE_MESSAGE_ID,
        delta_index: index,
        delta,
      }),
    ),
    frame({
      type: "text.end",
      part_id: textPartId,
      part_kind: "text",
      message_id: FIXTURE_MESSAGE_ID,
      byte_count: deltas.join("").length,
      delta_count: deltas.length,
    }),
    frame({
      type: "part.created",
      part_id: `gate:agent_gate:${FIXTURE_GATE_ID}`,
      part_kind: "gate",
      message_id: FIXTURE_MESSAGE_ID,
      part: {
        part_id: `gate:agent_gate:${FIXTURE_GATE_ID}`,
        kind: "gate",
        revision: 1,
        gate_ref: {
          workspace_id: "ws-demo",
          object_type: "agent_gate",
          object_id: FIXTURE_GATE_ID,
        },
        gate_kind: "directive_confirmation",
        state: "requested",
      },
    }),
    frame({
      type: "part.completed",
      part_id: `sources:${FIXTURE_MESSAGE_ID}`,
      part_kind: "sources",
      message_id: FIXTURE_MESSAGE_ID,
      part: {
        part_id: `sources:${FIXTURE_MESSAGE_ID}`,
        kind: "sources",
        revision: 1,
        items: [
          {
            source_id: "openai-careers",
            title: "OpenAI careers",
            url: "https://openai.com/careers",
            source_kind: "official_site",
          },
          {
            source_id: "anthropic-enterprise",
            title: "Anthropic enterprise tier",
            url: "https://anthropic.com/enterprise",
            source_kind: "official_site",
          },
        ],
      },
    }),
    frame({ type: "turn.awaiting_input", status: "awaiting_input", replayed: false }),
  ];
}

/** The launch narration a gate approval produces — one task per run, at any scale. */
export function fixtureLaunchEvents(turnId: string): Record<string, unknown>[] {
  const runId = "5b1d2c30-0000-4000-8000-000000000200";
  const messageId = "5b1d2c30-0000-4000-8000-0000000002b1";
  const attemptId = "5b1d2c30-0000-4000-8000-0000000002a1";
  let sequence = 0;
  let eventId = 200;
  const frame = (payload: Record<string, unknown>) => ({
    schema_version: "1",
    project_id: FIXTURE_PROJECT_ID,
    thread_id: FIXTURE_THREAD_ID,
    turn_id: turnId,
    generation_attempt_id: attemptId,
    event_id: (eventId += 1),
    sequence: (sequence += 1),
    occurred_at: "2026-08-09T11:24:00Z",
    ...payload,
  });
  const taskPart = (revision: number, state: string, counts: Record<string, number>) => ({
    part_id: `task:${runId}`,
    kind: "task",
    revision,
    state,
    title: "account research",
    run_ref: {
      workspace_id: "ws-demo",
      object_type: "entity_research_run",
      object_id: runId,
    },
    counts: { total: 2, queued: 0, running: 0, completed: 0, partial: 0, blocked: 0, failed: 0, ...counts },
  });

  return [
    frame({ type: "turn.accepted", source: "route", kind: "gate_response" }),
    frame({ type: "turn.started", attempt_ordinal: 1 }),
    frame({
      type: "part.created",
      part_id: `task:${runId}`,
      part_kind: "task",
      message_id: messageId,
      run_id: runId,
      part: taskPart(1, "queued", { queued: 2 }),
    }),
    frame({
      type: "part.updated",
      part_id: `task:${runId}`,
      part_kind: "task",
      message_id: messageId,
      run_id: runId,
      part: taskPart(2, "deep_research", { running: 2 }),
    }),
    frame({
      type: "part.updated",
      part_id: `task:${runId}`,
      part_kind: "task",
      message_id: messageId,
      run_id: runId,
      part: taskPart(3, "partial", { completed: 1, partial: 1 }),
    }),
    frame({ type: "turn.completed", status: "completed", replayed: false }),
  ];
}

// --- the dev-lens turn-context inspector -----------------------------------
//
// Wire-shaped like everything else here, so the fixture adapter parses through
// the same schemas the HTTP adapter does. The values are deliberately *typical*
// rather than tidy: one included body and one budget-dropped body, one dropped
// context ref, a plan whose proposal has a step its validated form does not, and
// a turn ledger carrying a `plan_rejected` refusal that no per-operation row can
// express. A fixture that showed only the happy shape would let the drawer be
// built without ever rendering the cases it exists to surface.

const FIXTURE_INSPECTOR_BUDGET = 512_000;

export function fixtureInspectorContext(turnId: string) {
  return {
    data: {
      turn_id: turnId,
      context_bundle_id: "8c4a0b1e-0000-4000-8000-0000000000d1",
      schema_version: "1",
      policy_version: "conversation-v3",
      token_counter_version: "tc-2026-07",
      aggregate_sha256: FIXTURE_SHA,
      assembled_at: "2026-08-09T09:59:58Z",
      budget_bytes: FIXTURE_INSPECTOR_BUDGET,
      truncated: true,
      layers: [
        {
          ordinal: 1,
          layer: "l1_identity",
          token_budget: 2000,
          token_count: 384,
          included_count: 1,
          excluded_count: 0,
          refs: [
            {
              disposition: "included",
              ordinal: 0,
              ref_kind: "artifact",
              artifact_key: `ws-fixture/${FIXTURE_SHA}`,
              artifact_sha256: FIXTURE_SHA,
              content_sha256: FIXTURE_SHA,
              materialized_path: "identity/system.md",
              token_count: 384,
              body: {
                artifact_key: `ws-fixture/${FIXTURE_SHA}`,
                sha256: FIXTURE_SHA,
                text:
                  "You are the Head of ABM for this workspace. You never fetch " +
                  "external sources on this surface.",
              },
            },
          ],
        },
        {
          ordinal: 4,
          layer: "l4_memory",
          token_budget: 3000,
          token_count: 2960,
          included_count: 1,
          excluded_count: 0,
          refs: [
            {
              disposition: "included",
              ordinal: 0,
              ref_kind: "artifact",
              artifact_key: "ws-fixture/" + "a".repeat(64),
              artifact_sha256: "a".repeat(64),
              content_sha256: "a".repeat(64),
              token_count: 2960,
              body: {
                artifact_key: "ws-fixture/" + "a".repeat(64),
                sha256: "a".repeat(64),
                text: null,
                omitted_reason: "budget",
              },
            },
          ],
        },
        {
          ordinal: 6,
          layer: "l6_conversation",
          token_budget: 8000,
          token_count: 7940,
          included_count: 0,
          excluded_count: 1,
          refs: [
            {
              disposition: "excluded",
              ordinal: 0,
              ref_kind: "domain",
              object_type: "agent_thread_message",
              object_id: "8c4a0b1e-0000-4000-8000-00000000000f",
              object_version: 1,
              exclusion_reason_code: "layer_budget_exhausted",
            },
          ],
        },
      ],
    },
  };
}

export function fixtureInspectorRounds() {
  return {
    data: [
      {
        model_call_id: "8c4a0b1e-0000-4000-8000-0000000000e1",
        sequence: 1,
        requested_model: "openai/gpt-5.6-terra",
        answering_model: "openai/gpt-5.6-terra",
        status: "completed",
        input_tokens: 11_482,
        output_tokens: 612,
        cost_millicredits: 143,
        latency_ms: 2841.5,
        started_at: "2026-08-09T10:00:00Z",
        completed_at: "2026-08-09T10:00:03Z",
      },
      {
        model_call_id: "8c4a0b1e-0000-4000-8000-0000000000e2",
        sequence: 2,
        requested_model: "openai/gpt-5.6-terra",
        answering_model: "anthropic/claude-sonnet-4",
        status: "completed",
        input_tokens: 12_004,
        output_tokens: 288,
        cost_millicredits: 97,
        latency_ms: 1920.25,
        started_at: "2026-08-09T10:00:04Z",
        completed_at: "2026-08-09T10:00:06Z",
      },
    ],
  };
}

export function fixtureInspectorPlan(turnId: string) {
  return {
    data: {
      turn_id: turnId,
      budget_bytes: FIXTURE_INSPECTOR_BUDGET,
      truncated: false,
      plans: [
        {
          plan_id: "8c4a0b1e-0000-4000-8000-0000000000f1",
          role: "head_of_abm",
          resource_manifest_sha256: FIXTURE_SHA,
          max_parallelism: 4,
          estimated_cost_millicents: 120,
          budget_limit_millicents: 5000,
          validated_at: "2026-08-09T10:00:03Z",
          proposal: {
            artifact_key: `ws-fixture/${FIXTURE_SHA}`,
            sha256: FIXTURE_SHA,
            text: JSON.stringify(
              {
                steps: [
                  { node_key: "agent_draft_directive_01", tool: "draft_account_research_directive@2" },
                  { node_key: "agent_fetch_page_02", tool: "fetch_page@1" },
                ],
              },
              null,
              2,
            ),
          },
          validated: {
            artifact_key: "ws-fixture/" + "b".repeat(64),
            sha256: "b".repeat(64),
            text: JSON.stringify(
              {
                steps: [
                  { node_key: "agent_draft_directive_01", tool: "draft_account_research_directive@2" },
                ],
              },
              null,
              2,
            ),
          },
          operations: [
            {
              node_key: "agent_draft_directive_01",
              ordinal: 0,
              operation_id: "8c4a0b1e-0000-4000-8000-000000000101",
              kind: "tool",
              address: "draft_account_research_directive@2",
              estimated_cost_millicents: 120,
              authority_sha256: "c".repeat(64),
              validation: "admitted",
            },
          ],
          events: [{ status: "validated", created_at: "2026-08-09T10:00:03Z" }],
        },
      ],
      turn_events: [
        { status: "requested", created_at: "2026-08-09T09:59:57Z" },
        { status: "context_ready", created_at: "2026-08-09T09:59:58Z" },
        {
          status: "failed",
          reason_code: "plan_rejected",
          created_at: "2026-08-09T10:00:02Z",
        },
        { status: "completed", created_at: "2026-08-09T10:00:07Z" },
      ],
    },
  };
}

export function fixtureInspectorTools(turnId: string) {
  return {
    data: {
      turn_id: turnId,
      budget_bytes: FIXTURE_INSPECTOR_BUDGET,
      truncated: false,
      calls: [
        {
          plan_id: "8c4a0b1e-0000-4000-8000-0000000000f1",
          node_key: "agent_draft_directive_01",
          operation_id: "8c4a0b1e-0000-4000-8000-000000000101",
          kind: "tool",
          address: "draft_account_research_directive@2",
          estimated_cost_millicents: 120,
          arguments: {
            artifact_key: "ws-fixture/" + "d".repeat(64),
            sha256: "d".repeat(64),
            text: JSON.stringify({ project_id: FIXTURE_PROJECT_ID, account_count: 2 }, null, 2),
          },
          result: {
            artifact_key: "ws-fixture/" + "e".repeat(64),
            sha256: "e".repeat(64),
            text: JSON.stringify({ references: { research_directive_id: "rd-1" } }, null, 2),
          },
          replayed: false,
          reference_count: 1,
          completed_at: "2026-08-09T10:00:05Z",
        },
        {
          plan_id: "8c4a0b1e-0000-4000-8000-0000000000f1",
          node_key: "agent_resolve_committee_02",
          operation_id: "8c4a0b1e-0000-4000-8000-000000000102",
          kind: "tool",
          address: "resolve_committee@1",
          estimated_cost_millicents: 60,
          arguments: {
            artifact_key: "ws-fixture/" + "f".repeat(64),
            sha256: "f".repeat(64),
            text: JSON.stringify({ account_id: "acc-1" }, null, 2),
          },
          // Admitted and never completed: the honest shape for a governed call
          // that failed after validation, and precisely the row a developer
          // opens this tab to find.
          result: null,
          replayed: null,
          reference_count: null,
          completed_at: null,
        },
      ],
    },
  };
}
