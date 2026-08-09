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
