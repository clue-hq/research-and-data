import assert from "node:assert/strict";
import test from "node:test";
import { ChatPartSnapshotSchema } from "./chat-parts";
import {
  ChatMessageListResponseSchema,
  openGateIds,
} from "./chat-message";
import {
  ChatThreadListResponseSchema,
  ChatThreadResponseSchema,
  THREAD_STATUS_PRECEDENCE,
  deriveThreadStatus,
  mostUrgentThreadStatus,
  threadLabel,
} from "./chat-thread";
import {
  AcceptedTurnResponseSchema,
  ChatTurnListResponseSchema,
  turnStateForStreamEvent,
  turnRequestBody,
} from "./chat-turn";
import { ChatGateListResponseSchema, formatCents, isGateOpen } from "./chat-gate";
import {
  fixtureGates,
  fixtureMessages,
  fixtureThreads,
  fixtureTurns,
} from "../data/chat.fixture";

/** Schema round-trips for every amended model, against wire-shaped fixtures. */

test("the thread list parses the as-built wire and its nullable title", () => {
  const page = ChatThreadListResponseSchema.parse({
    data: fixtureThreads,
    meta: { next_cursor: "cursor-2" },
  });
  assert.equal(page.nextCursor, "cursor-2");
  assert.equal(page.threads[0].projectId, "10m-landing-page-campaign");
  assert.equal(page.threads[1].title, null);
  assert.equal(threadLabel(page.threads[1]), "New chat");
});

test("create returns the ratified 201 superset", () => {
  const thread = ChatThreadResponseSchema.parse({ data: fixtureThreads[0] });
  assert.equal(thread.pinned, true);
  assert.equal(thread.status, "idle");
  assert.ok(thread.createdAt);
});

test("the status vocabulary is the pinned precedence, and archived outranks all", () => {
  assert.deepEqual(THREAD_STATUS_PRECEDENCE, [
    "archived",
    "approval",
    "needs-input",
    "running",
    "idle",
  ]);
  assert.equal(
    deriveThreadStatus({
      archived: true,
      openGateKinds: ["directive_confirmation"],
      running: true,
    }),
    "archived",
  );
  // An open gate outranks running: the conversation is blocked on the user.
  assert.equal(
    deriveThreadStatus({
      archived: false,
      openGateKinds: ["directive_confirmation"],
      running: true,
    }),
    "approval",
  );
  assert.equal(
    deriveThreadStatus({ archived: false, openGateKinds: ["budget_approval"] }),
    "needs-input",
  );
  assert.equal(deriveThreadStatus({ archived: false, running: true }), "running");
  assert.equal(deriveThreadStatus({ archived: false }), "idle");
  assert.equal(mostUrgentThreadStatus("running", "approval"), "approval");
});

test("message reads are body-free by default and carry the typed refs", () => {
  const page = ChatMessageListResponseSchema.parse({
    data: fixtureMessages.map((message) => ({
      ...message,
      body: null,
      body_unavailable_reason: null,
    })),
    meta: {},
  });
  assert.equal(page.messages[0].body, null);
  assert.equal(page.messages[1].refs[0].flavor, "open_gate");
  assert.deepEqual(openGateIds(page.messages[1]), [fixtureGates[0].gate_id]);
});

test("an unservable body is reported with its reason, never as empty text", () => {
  const page = ChatMessageListResponseSchema.parse({
    data: [{ ...fixtureMessages[0], body: null, body_unavailable_reason: "erased" }],
    meta: {},
  });
  assert.equal(page.messages[0].body, null);
  assert.equal(page.messages[0].bodyUnavailableReason, "erased");
});

test("the submissions-union keeps queued turns and their attach cursor", () => {
  const page = ChatTurnListResponseSchema.parse({
    data: [
      ...fixtureTurns,
      {
        turn_id: "queued-1",
        thread_id: "thread-primary",
        project_id: "10m-landing-page-campaign",
        state: "queued",
        requested_at: "2026-08-09T11:30:00Z",
        last_event_id: null,
        generation_attempts: 0,
      },
    ],
    meta: { thread_status: "running" },
  });
  assert.equal(page.threadRunning, true);
  assert.equal(page.turns[0].lastEventId, 24);
  assert.equal(page.turns[1].state, "queued");
});

test("durable stream events immediately refine queued/running/terminal turn state", () => {
  assert.equal(turnStateForStreamEvent("turn.accepted"), "queued");
  assert.equal(turnStateForStreamEvent("turn.started"), "running");
  assert.equal(turnStateForStreamEvent("turn.completed"), "completed");
  assert.equal(turnStateForStreamEvent("turn.awaiting_input"), "awaiting_input");
  assert.equal(turnStateForStreamEvent("text.delta"), null);
});

test("a 202 reports whether it replayed an already-accepted identity", () => {
  const accepted = AcceptedTurnResponseSchema.parse({
    data: {
      turn_id: "t1",
      thread_id: "th1",
      requested_at: "2026-08-09T11:30:00Z",
      replayed: true,
    },
  });
  assert.equal(accepted.replayed, true);
});

test("a turn body is exactly one of a message or a gate response", () => {
  assert.deepEqual(turnRequestBody({ kind: "message", message: "hi" }), {
    message: "hi",
  });
  assert.deepEqual(
    turnRequestBody({
      kind: "gate_response",
      response: {
        gateId: "g1",
        decision: "approved",
        expectedSubjectSha256: "a".repeat(64),
        expectedEstimatedCostCents: 24000,
      },
    }),
    {
      gate_response: {
        gate_id: "g1",
        decision: "approved",
        expected_subject_sha256: "a".repeat(64),
        expected_estimated_cost_cents: 24000,
      },
    },
  );
});

test("a gate parses its decimal spend and derives open from the missing answer", () => {
  const gates = ChatGateListResponseSchema.parse({ data: fixtureGates });
  assert.equal(gates[0].maxSpendCents, 24000);
  assert.equal(gates[0].currency, "USD");
  assert.equal(isGateOpen(gates[0]), true);
  assert.equal(formatCents(24000, "USD"), "$240.00");
});

test("every part kind round-trips from its wire snapshot", () => {
  const tool = ChatPartSnapshotSchema.parse({
    part_id: "tool:x",
    kind: "tool",
    revision: 3,
    state: "output-error",
    tool_name: "launch_account_research",
    tool_version: "1",
    tool_call_id: "c1",
    node_key: "x",
    error_code: "launch_action_ref_missing",
    error_reasons: ["no human receipt"],
  });
  assert.equal(tool.kind === "tool" && tool.errorCode, "launch_action_ref_missing");

  const task = ChatPartSnapshotSchema.parse({
    part_id: "task:r",
    kind: "task",
    revision: 1,
    state: "needs_input",
    title: "account research",
    run_ref: { object_type: "entity_research_run", object_id: "r" },
  });
  assert.equal(task.kind === "task" && task.counts.total, 0);

  const gate = ChatPartSnapshotSchema.parse({
    part_id: "gate:g",
    kind: "gate",
    revision: 1,
    gate_ref: { object_type: "agent_gate", object_id: "g" },
    gate_kind: "directive_confirmation",
    state: "requested",
    amount_cents: 24000,
    currency: "USD",
    permitted_decisions: ["approved", "rejected"],
  });
  assert.equal(gate.kind === "gate" && gate.amountCents, 24000);

  const sources = ChatPartSnapshotSchema.parse({
    part_id: "sources:m",
    kind: "sources",
    revision: 1,
    items: [{ source_id: "s1", title: "OpenAI", url: "https://openai.com" }],
  });
  assert.equal(sources.kind === "sources" && sources.items[0].sourceKind, null);

  const activity = ChatPartSnapshotSchema.parse({
    part_id: "activity:a",
    kind: "agent_activity",
    revision: 2,
    title: "Agent activity",
    steps: [{ id: "round:1", kind: "model_round", status: "active", label: "Model round 1" }],
  });
  assert.equal(activity.kind === "agent_activity" && activity.steps[0].description, null);
});

test("a streaming-start text part is representable — empty text, empty parts", () => {
  // The old contract's `text.min(1)` / `parts.min(1)` made this unrepresentable
  // (charter §2's D-4 hazard list). The domain type simply allows it.
  const empty = { kind: "text" as const, partId: "text:a", revision: 1, text: "", streaming: true, failed: false, failureReason: null };
  assert.equal(empty.text, "");
});
