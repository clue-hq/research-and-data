import assert from "node:assert/strict";
import test from "node:test";
import {
  SseFrameReader,
  parseChatStreamEvent,
  type ChatStreamEvent,
} from "./chat-events";
import {
  applyChatStreamEvent,
  composeTranscript,
  emptyTranscriptState,
  mergeThreadMessages,
  seedDesignLeg,
  turnsAwaitingRehydration,
  type TranscriptMessage,
  type TranscriptState,
} from "./chat-transcript";
import type { ChatMessage } from "./chat-message";
import type { ChatTextPart } from "./chat-parts";
import {
  fixtureLaunchEvents,
  fixtureTurnEvents,
} from "../data/chat.fixture";

/**
 * The stream adapter, driven by synthetic SSE conforming to D3's event schema.
 *
 * These mirror the charter §5 streaming cases at the consumer end: reconnect
 * replay, duplicate delivery, `part.updated` replacement, `stream.reset`, and
 * attempt isolation. They are the frontend's half of "the stream has its own
 * contract suite and is never used to prove the domain outcome".
 */

const TURN = "turn-1";
const ATTEMPT_A = "attempt-a";
const ATTEMPT_B = "attempt-b";

let nextEventId = 0;

function frame(payload: Record<string, unknown>): ChatStreamEvent {
  nextEventId += 1;
  const parsed = parseChatStreamEvent({
    schema_version: "1",
    event_id: nextEventId,
    sequence: nextEventId,
    project_id: "p1",
    thread_id: "t1",
    turn_id: TURN,
    generation_attempt_id: ATTEMPT_A,
    ...payload,
  });
  assert.ok(parsed.ok, `frame did not parse: ${parsed.ok ? "" : parsed.reason}`);
  return parsed.event;
}

function apply(
  state: TranscriptState,
  events: readonly ChatStreamEvent[],
): TranscriptState {
  return events.reduce(applyChatStreamEvent, state);
}

function textOf(state: TranscriptState, turnId = TURN): string {
  const turn = state.turns.get(turnId);
  assert.ok(turn, "expected a projected turn");
  const part = turn.parts.find((entry) => entry.part.kind === "text");
  return part ? (part.part as ChatTextPart).text : "";
}

test("text deltas accumulate in index order across arbitrary splits", () => {
  const events = [
    frame({ type: "turn.started" }),
    frame({ type: "text.start", part_id: "text:a", part_kind: "text" }),
    frame({ type: "text.delta", part_id: "text:a", delta_index: 0, delta: "Loo" }),
    frame({ type: "text.delta", part_id: "text:a", delta_index: 1, delta: "king at **bo" }),
    frame({ type: "text.delta", part_id: "text:a", delta_index: 2, delta: "th** accounts" }),
    frame({ type: "text.end", part_id: "text:a" }),
  ];
  const state = apply(emptyTranscriptState(), events);
  assert.equal(textOf(state), "Looking at **both** accounts");
  const part = state.turns.get(TURN)?.parts.find((entry) => entry.part.kind === "text");
  assert.equal((part?.part as ChatTextPart).streaming, false);
});

test("an out-of-order delta still lands at its own index", () => {
  const events = [
    frame({ type: "text.start", part_id: "text:a", part_kind: "text" }),
    frame({ type: "text.delta", part_id: "text:a", delta_index: 1, delta: "second" }),
    frame({ type: "text.delta", part_id: "text:a", delta_index: 0, delta: "first " }),
  ];
  assert.equal(textOf(apply(emptyTranscriptState(), events)), "first second");
});

test("duplicate delivery of the same event is a no-op", () => {
  const start = frame({ type: "text.start", part_id: "text:a", part_kind: "text" });
  const delta = frame({
    type: "text.delta",
    part_id: "text:a",
    delta_index: 0,
    delta: "hello",
  });
  const once = apply(emptyTranscriptState(), [start, delta]);
  const twice = apply(once, [start, delta, delta]);
  assert.equal(textOf(twice), "hello");
  assert.equal(twice, once, "a duplicate must not even produce a new state object");
});

test("a reconnect replay of the whole backlog reproduces the same transcript", () => {
  const events = [
    frame({ type: "turn.accepted" }),
    frame({ type: "turn.started" }),
    frame({ type: "text.start", part_id: "text:a", part_kind: "text" }),
    frame({ type: "text.delta", part_id: "text:a", delta_index: 0, delta: "abc" }),
  ];
  const live = apply(emptyTranscriptState(), events);
  // The server replays `event_id > cursor`; a client that lost its socket after
  // the first two frames receives the last two again.
  const replayed = apply(apply(emptyTranscriptState(), events.slice(0, 2)), events);
  assert.equal(textOf(replayed), textOf(live));
  assert.equal(replayed.cursor, live.cursor);
});

test("part.updated replaces the prior snapshot and never appends a second card", () => {
  const snapshot = (revision: number, state: string) => ({
    part_id: "tool:x",
    kind: "tool",
    revision,
    state,
    tool_name: "draft_directive",
    tool_call_id: "c1",
    node_key: "x",
  });
  const state = apply(emptyTranscriptState(), [
    frame({ type: "part.created", part_id: "tool:x", part_kind: "tool", part: snapshot(1, "input-available") }),
    frame({ type: "part.updated", part_id: "tool:x", part_kind: "tool", part: snapshot(2, "output-available") }),
  ]);
  const parts = state.turns.get(TURN)?.parts ?? [];
  assert.equal(parts.length, 1);
  assert.equal(parts[0].part.kind === "tool" && parts[0].part.state, "output-available");
});

test("an older revision never overwrites a newer snapshot", () => {
  const snapshot = (revision: number, state: string) => ({
    part_id: "tool:x",
    kind: "tool",
    revision,
    state,
    tool_name: "t",
    tool_call_id: "c",
    node_key: "x",
  });
  const state = apply(emptyTranscriptState(), [
    frame({ type: "part.created", part_id: "tool:x", part_kind: "tool", part: snapshot(2, "output-available") }),
    frame({ type: "part.updated", part_id: "tool:x", part_kind: "tool", part: snapshot(1, "input-available") }),
  ]);
  const parts = state.turns.get(TURN)?.parts ?? [];
  assert.equal(parts[0].part.kind === "tool" && parts[0].part.state, "output-available");
});

test("stream.reset drops the projection and asks for the canonical message", () => {
  const state = apply(emptyTranscriptState(), [
    frame({ type: "text.start", part_id: "text:a", part_kind: "text" }),
    frame({ type: "text.delta", part_id: "text:a", delta_index: 0, delta: "partial" }),
    frame({ type: "stream.reset", reason: "delta_reconciliation_mismatch" }),
  ]);
  assert.deepEqual(state.turns.get(TURN)?.parts, []);
  assert.deepEqual(turnsAwaitingRehydration(state), [TURN]);
  // The cursor restarts with the backlog, or the repaired stream would resume
  // past the very events it was told to re-read.
  assert.equal(state.cursor, 0);
});

test("a retry's attempt is never spliced into the superseded one", () => {
  const first = apply(emptyTranscriptState(), [
    frame({ type: "text.start", part_id: "text:a1", part_kind: "text" }),
    frame({ type: "text.delta", part_id: "text:a1", delta_index: 0, delta: "half a sen" }),
  ]);
  const retried = apply(first, [
    frame({
      type: "part.reset",
      part_id: "text:a1",
      part_kind: "text",
      generation_attempt_id: ATTEMPT_A,
      reason: "generation_attempt_superseded",
    }),
    frame({ type: "turn.retrying", generation_attempt_id: ATTEMPT_B }),
    frame({ type: "text.start", part_id: "text:a2", part_kind: "text", generation_attempt_id: ATTEMPT_B }),
    frame({
      type: "text.delta",
      part_id: "text:a2",
      delta_index: 0,
      delta: "a whole sentence",
      generation_attempt_id: ATTEMPT_B,
    }),
  ]);
  assert.equal(textOf(retried), "a whole sentence");
  assert.equal(
    retried.turns.get(TURN)?.parts.filter((entry) => entry.part.kind === "text").length,
    1,
  );
});

test("a cancelled turn keeps its partial text, marked as stopped", () => {
  const state = apply(emptyTranscriptState(), [
    frame({ type: "text.start", part_id: "text:a", part_kind: "text" }),
    frame({ type: "text.delta", part_id: "text:a", delta_index: 0, delta: "half" }),
    frame({ type: "turn.cancelled", reason: "stop_requested" }),
  ]);
  const part = state.turns.get(TURN)?.parts[0]?.part as ChatTextPart;
  assert.equal(part.text, "half");
  assert.equal(part.failed, true);
  assert.equal(part.streaming, false, "a stopped attempt must not look like a live one");
});

test("a terminal turn cannot leave replayed reasoning or activity visibly active", () => {
  const state = apply(emptyTranscriptState(), [
    frame({ type: "turn.started" }),
    frame({
      type: "part.created",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      part: reasoningSnapshot(),
    }),
    frame({
      type: "part.created",
      part_id: "activity:a",
      part_kind: "agent_activity",
      part: {
        part_id: "activity:a",
        kind: "agent_activity",
        revision: 1,
        title: "Agent activity",
        steps: [
          {
            id: "round-1",
            kind: "model_round",
            status: "active",
            label: "Model round",
          },
        ],
      },
    }),
    frame({ type: "turn.cancelled", reason: "stop_requested" }),
  ]);

  const transcript = composeTranscript({ messages: [], turns: [], stream: state });
  const assistant = transcript.find((message) => message.role === "assistant");
  assert.ok(assistant);
  assert.equal(assistant.state, "cancelled");
  const reasoning = assistant.parts.find((part) => part.kind === "reasoning");
  const activity = assistant.parts.find((part) => part.kind === "agent_activity");
  assert.equal(reasoning?.kind === "reasoning" && reasoning.state, "error");
  assert.equal(
    activity?.kind === "agent_activity" && activity.steps[0]?.status,
    "error",
  );
});

test("a replayed terminal turn asks to be rehydrated rather than faking deltas", () => {
  const state = apply(emptyTranscriptState(), [
    frame({ type: "turn.completed", status: "completed", replayed: true }),
  ]);
  assert.deepEqual(turnsAwaitingRehydration(state), [TURN]);
});

test("an unknown schema version is fatal; an unreadable part is not", () => {
  const version = parseChatStreamEvent({
    schema_version: "9",
    turn_id: TURN,
    type: "turn.started",
  });
  assert.equal(version.ok, false);
  assert.equal(version.ok === false && version.fatal, true);

  const badPart = parseChatStreamEvent({
    schema_version: "1",
    project_id: "p1",
    thread_id: "t1",
    turn_id: TURN,
    type: "part.created",
    part_id: "tool:x",
    part_kind: "tool",
    part: { part_id: "tool:x", kind: "tool" },
  });
  assert.equal(badPart.ok, false);
  assert.equal(badPart.ok === false && badPart.fatal, false);
});

test("connect control frames carry common identity and remain cursorless", () => {
  for (const type of ["stream.hello", "stream.reset"] as const) {
    const parsed = parseChatStreamEvent(
      {
        schema_version: "1",
        project_id: "p1",
        thread_id: "t1",
        turn_id: TURN,
        type,
        ...(type === "stream.reset"
          ? { reason: "cursor_older_than_horizon", rehydrate: "transcript" }
          : {}),
      },
      type,
    );
    assert.ok(parsed.ok);
    assert.equal(parsed.event.eventId, null);
    assert.equal(parsed.event.sequence, null);
    assert.equal(parsed.event.projectId, "p1");
    assert.equal(parsed.event.threadId, "t1");
  }
});

test("an SSE event name that disagrees with data.type is fatal", () => {
  const parsed = parseChatStreamEvent(
    {
      schema_version: "1",
      project_id: "p1",
      thread_id: "t1",
      turn_id: TURN,
      type: "turn.completed",
    },
    "turn.started",
  );
  assert.equal(parsed.ok, false);
  assert.equal(parsed.ok === false && parsed.fatal, true);
});

test("a typed frame without common project/thread/turn identity is fatal", () => {
  const parsed = parseChatStreamEvent({
    schema_version: "1",
    turn_id: TURN,
    type: "turn.started",
  });
  assert.equal(parsed.ok, false);
  assert.equal(parsed.ok === false && parsed.fatal, true);
});

test("the SSE reader reassembles frames split across chunk boundaries", () => {
  const reader = new SseFrameReader();
  assert.deepEqual(reader.push("id: 4\nevent: text.delta\nda"), []);
  const frames = reader.push('ta: {"a":1}\n\nid: 5\nevent: turn.completed\ndata: {}\n\n');
  assert.equal(frames.length, 2);
  assert.equal(frames[0].id, "4");
  assert.equal(frames[0].event, "text.delta");
  assert.equal(frames[0].data, '{"a":1}');
  assert.equal(frames[1].event, "turn.completed");
});

test("the scripted fixture turn produces a gate card and a complete text part", () => {
  const state = fixtureTurnEvents("fixture-turn").reduce((current, payload) => {
    const parsed = parseChatStreamEvent(payload);
    assert.ok(parsed.ok);
    return applyChatStreamEvent(current, parsed.event);
  }, emptyTranscriptState());

  const turn = state.turns.get("fixture-turn");
  assert.ok(turn);
  assert.equal(turn.state, "awaiting_input");
  const kinds = turn.parts.map((entry) => entry.part.kind);
  assert.deepEqual(kinds, [
    "reasoning",
    "agent_activity",
    "tool",
    "text",
    "gate",
    "sources",
  ]);
  const text = turn.parts.find((entry) => entry.part.kind === "text")?.part as ChatTextPart;
  assert.match(text.text, /Shall I take the deep pass\?$/);
  assert.equal(text.streaming, false);
});

test("the launch script keeps one task card per run at every revision", () => {
  const state = fixtureLaunchEvents("launch-turn").reduce((current, payload) => {
    const parsed = parseChatStreamEvent(payload);
    assert.ok(parsed.ok);
    return applyChatStreamEvent(current, parsed.event);
  }, emptyTranscriptState());
  const parts = state.turns.get("launch-turn")?.parts ?? [];
  const tasks = parts.filter((entry) => entry.part.kind === "task");
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].part.kind === "task" && tasks[0].part.state, "partial");
});

test("the transcript prefers a streamed text part and falls back to the durable body", () => {
  const durable = {
    id: "m1",
    turnId: TURN,
    threadId: "t1",
    sequence: 2,
    role: "assistant" as const,
    bodyArtifactKey: "k",
    bodySha256: "s",
    body: "the canonical answer",
    bodyUnavailableReason: null,
    createdAt: "2026-08-09T00:00:00Z",
    refs: [],
  };
  const streamed = apply(emptyTranscriptState(), [
    frame({ type: "text.start", part_id: "text:a", part_kind: "text" }),
    frame({ type: "text.delta", part_id: "text:a", delta_index: 0, delta: "the canonical answer" }),
  ]);

  const live = composeTranscript({
    messages: [durable],
    turns: [],
    stream: streamed,
  });
  assert.equal(live[0].body, null, "a live text part owns the prose while it streams");
  assert.equal(live[0].parts.length, 1);

  const cold = composeTranscript({
    messages: [durable],
    turns: [],
    stream: emptyTranscriptState(),
  });
  assert.equal(cold[0].body, "the canonical answer");
  assert.equal(cold[0].parts.length, 0);
});

test("an optimistic user turn shows immediately and is retired by the durable read", () => {
  const optimistic = [
    { turnId: TURN, text: "do the thing", requestedAt: "2026-08-09T00:00:00Z" },
  ];
  const pending = composeTranscript({
    messages: [],
    turns: [],
    stream: emptyTranscriptState(),
    optimistic,
  });
  assert.equal(pending[0].role, "user");
  assert.equal(pending[0].optimistic, true);
  assert.equal(pending[0].body, "do the thing");

  const settled = composeTranscript({
    messages: [
      {
        id: "m0",
        turnId: TURN,
        threadId: "t1",
        sequence: 1,
        role: "user",
        bodyArtifactKey: "k",
        bodySha256: "s",
        body: "do the thing",
        bodyUnavailableReason: null,
        createdAt: "2026-08-09T00:00:01Z",
        refs: [],
      },
    ],
    turns: [],
    stream: emptyTranscriptState(),
    optimistic,
  });
  assert.equal(settled.filter((message) => message.role === "user").length, 1);
  assert.equal(settled[0].optimistic, false);
});

test("an accepted submission renders before the worker materializes thread history", () => {
  const acceptedMessage = {
    id: "accepted-user-message",
    turnId: TURN,
    threadId: "t1",
    sequence: 0,
    role: "user" as const,
    bodyArtifactKey: "accepted-key",
    bodySha256: "accepted-sha",
    body: "Home accepted this exact message",
    bodyUnavailableReason: null,
    createdAt: "2026-08-09T00:00:00Z",
    refs: [],
  };
  const turns = [
    {
      turnId: TURN,
      threadId: "t1",
      projectId: "p1",
      state: "queued",
      requestedAt: acceptedMessage.createdAt,
      lastEventId: null,
      generationAttempts: 0,
      submissionMessage: acceptedMessage,
      derivation: null,
    },
  ];
  const pending = composeTranscript({
    messages: [],
    turns,
    stream: apply(emptyTranscriptState(), [frame({ type: "turn.accepted" })]),
  });
  assert.equal(pending[0].role, "user");
  assert.equal(pending[0].body, acceptedMessage.body);
  assert.equal(pending[0].optimistic, false);

  const materialized = composeTranscript({
    messages: [{ ...acceptedMessage, sequence: 1 }],
    turns,
    stream: emptyTranscriptState(),
  });
  assert.equal(materialized.filter((message) => message.role === "user").length, 1);
  assert.equal(materialized[0].id, acceptedMessage.id);
});

test("a derived turn renders its assistant answer and no user bubble", () => {
  // The server made this turn from the user's own bytes (a design-leg redelivery), so the
  // durable user row exists — role-scoped history keeps it — and is hidden by `derivation`,
  // never by absence.
  const acceptedMessage = {
    id: "derived-user-message",
    turnId: TURN,
    threadId: "t1",
    sequence: 0,
    role: "user" as const,
    bodyArtifactKey: "derived-key",
    bodySha256: "derived-sha",
    body: "Make the hero darker",
    bodyUnavailableReason: null,
    createdAt: "2026-09-20T00:00:00Z",
    refs: [],
  };
  const assistantMessage = {
    ...acceptedMessage,
    id: "derived-assistant-message",
    sequence: 2,
    role: "assistant" as const,
    bodyArtifactKey: "derived-assistant-key",
    bodySha256: "derived-assistant-sha",
    body: "Darkened the hero.",
  };
  const turns = [
    {
      turnId: TURN,
      threadId: "t1",
      projectId: "p1",
      state: "completed",
      requestedAt: acceptedMessage.createdAt,
      lastEventId: null,
      generationAttempts: 1,
      submissionMessage: acceptedMessage,
      derivation: "design_leg_redelivery",
    },
  ];

  const withDurableUserRow = composeTranscript({
    messages: [{ ...acceptedMessage, sequence: 1 }, assistantMessage],
    turns,
    stream: emptyTranscriptState(),
  });
  assert.equal(withDurableUserRow.filter((message) => message.role === "user").length, 0);
  const durableAssistant = withDurableUserRow.find((message) => message.role === "assistant");
  assert.ok(durableAssistant);
  assert.equal(durableAssistant.body, assistantMessage.body);

  // The same turn before the worker materialized any history: only the accepted submission.
  const submissionOnly = composeTranscript({
    messages: [],
    turns,
    stream: emptyTranscriptState(),
  });
  assert.equal(submissionOnly.filter((message) => message.role === "user").length, 0);
  assert.ok(submissionOnly.some((message) => message.role === "assistant"));

  // And a human turn with the same shape still shows the accepted user message.
  const human = composeTranscript({
    messages: [],
    turns: [{ ...turns[0], derivation: null }],
    stream: emptyTranscriptState(),
  });
  assert.equal(human.filter((message) => message.role === "user").length, 1);
  assert.equal(human[0].body, acceptedMessage.body);
});

test("a cold cancelled turn keeps a visible terminal assistant receipt", () => {
  const acceptedMessage = {
    id: "cancelled-user-message",
    turnId: TURN,
    threadId: "t1",
    sequence: 0,
    role: "user" as const,
    bodyArtifactKey: "cancelled-key",
    bodySha256: "cancelled-sha",
    body: "Stop this turn",
    bodyUnavailableReason: null,
    createdAt: "2026-08-09T00:00:00Z",
    refs: [],
  };
  const cold = composeTranscript({
    messages: [],
    turns: [
      {
        turnId: TURN,
        threadId: "t1",
        projectId: "p1",
        state: "cancelled",
        requestedAt: acceptedMessage.createdAt,
        lastEventId: null,
        generationAttempts: 1,
        submissionMessage: acceptedMessage,
        derivation: null,
      },
    ],
    stream: emptyTranscriptState(),
  });

  assert.equal(cold.length, 2);
  assert.equal(cold[1].role, "assistant");
  assert.equal(cold[1].state, "cancelled");
  assert.equal(cold[1].body, null);
  assert.deepEqual(cold[1].parts, []);
});

for (const durableState of ["cancelled", "running"] as const) {
  test(`a replayed crash reconciles with durable ${durableState} without losing partial text`, () => {
    // Older design Stop attempts emitted turn.failed before turn.cancelled. The
    // SSE reader closes on the first terminal, so only the durable turn read can
    // prove that the user cancelled after the generic crash unwinder ran.
    const stream = apply(emptyTranscriptState(), [
      frame({ type: "turn.started" }),
      frame({ type: "text.start", part_id: "text:partial", part_kind: "text" }),
      frame({ type: "text.delta", part_id: "text:partial", delta_index: 0, delta: "Draft started" }),
      frame({ type: "turn.failed", failure_code: "design_leg_turn_crashed" }),
    ]);
    const messages = composeTranscript({
      messages: [],
      turns: [{
        turnId: TURN,
        threadId: "t1",
        projectId: "p1",
        state: durableState,
        requestedAt: "2026-09-13T00:00:00Z",
        lastEventId: null,
        generationAttempts: 1,
        submissionMessage: null,
        derivation: null,
      }],
      stream,
    });
    const assistant = messages.find((message) => message.role === "assistant");
    assert.ok(assistant);
    assert.equal(assistant.state, durableState === "cancelled" ? "cancelled" : "failed");
    assert.equal(assistant.failureCode, durableState === "cancelled" ? null : "design_leg_turn_crashed");
    assert.equal(assistant.live, false);
    const partial = assistant.parts.find((part) => part.kind === "text");
    assert.ok(partial?.kind === "text");
    assert.equal(partial.text, "Draft started");
    assert.equal(partial.failed, true);
  });
}

test("a cancellation frame clears an earlier crash notice", () => {
  const stream = apply(emptyTranscriptState(), [
    frame({ type: "turn.failed", failure_code: "design_leg_turn_crashed" }),
    frame({ type: "turn.cancelled", reason: "stop_requested" }),
  ]);
  const [assistant] = composeTranscript({ messages: [], turns: [], stream });
  assert.equal(assistant.state, "cancelled");
  assert.equal(assistant.failureCode, null);
});

/**
 * Rule 6 — the dev-lens raw reasoning trace.
 *
 * The lens reuses `text.delta` targeting the *reasoning* part's id, so the
 * reducer's routing is the only thing standing between "a collapsible
 * diagnostic beside a model round" and "the model's private thoughts spliced
 * into the assistant's answer". These are that guard.
 */

function reasoningPart(state: TranscriptState, partId: string) {
  const turn = state.turns.get(TURN);
  assert.ok(turn, "expected a projected turn");
  const entry = turn.parts.find((item) => item.part.partId === partId);
  assert.ok(entry, `expected a part ${partId}`);
  assert.equal(entry.part.kind, "reasoning");
  return entry.part as Extract<(typeof entry)["part"], { kind: "reasoning" }>;
}

function reasoningSnapshot(extra: Record<string, unknown> = {}) {
  return {
    part_id: "reasoning:a:1",
    kind: "reasoning",
    revision: 1,
    state: "active",
    round_ordinal: 1,
    requested_tool_calls: 0,
    started_at: "2026-08-09T00:00:00Z",
    ...extra,
  };
}

test("a reasoning delta accumulates on its round's card, never as assistant text", () => {
  const state = apply(emptyTranscriptState(), [
    frame({
      type: "part.created",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      part: reasoningSnapshot(),
    }),
    frame({ type: "text.start", part_id: "text:a", part_kind: "text" }),
    frame({ type: "text.delta", part_id: "text:a", delta_index: 0, delta: "Hello" }),
    frame({
      type: "text.delta",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      delta_index: 0,
      delta: "The user ",
    }),
    frame({
      type: "text.delta",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      delta_index: 1,
      delta: "is fishing.",
    }),
  ]);

  // The two streams stayed apart: the answer is untouched by the trace.
  assert.equal(textOf(state), "Hello");
  const reasoning = reasoningPart(state, "reasoning:a:1");
  assert.equal(reasoning.text, "The user is fishing.");
  assert.equal(reasoning.textEphemeral, true);
  // And the round is still one card, not a card plus a stray text part.
  const turn = state.turns.get(TURN);
  assert.ok(turn);
  assert.equal(turn.parts.filter((entry) => entry.part.kind === "text").length, 1);
  assert.equal(turn.parts.filter((entry) => entry.part.kind === "reasoning").length, 1);
});

test("a reasoning delta is idempotent and order-insensitive, like every other delta", () => {
  const state = apply(emptyTranscriptState(), [
    frame({
      type: "part.created",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      part: reasoningSnapshot(),
    }),
    frame({
      type: "text.delta",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      delta_index: 1,
      delta: "second",
    }),
    frame({
      type: "text.delta",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      delta_index: 0,
      delta: "first ",
    }),
    frame({
      type: "text.delta",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      delta_index: 0,
      delta: "first ",
    }),
  ]);
  assert.equal(reasoningPart(state, "reasoning:a:1").text, "first second");
});

test("the round's closing snapshot still replaces the locally accumulated trace", () => {
  // Regression guard for the reason `upsertReasoningText` does not bump
  // `revision`: if it did, rule 2 ("never backwards") would make the local copy
  // outrank the server's `part.completed` and the authoritative trace would be
  // silently dropped.
  const state = apply(emptyTranscriptState(), [
    frame({
      type: "part.created",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      part: reasoningSnapshot(),
    }),
    frame({
      type: "text.delta",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      delta_index: 0,
      delta: "partial",
    }),
    frame({
      type: "part.completed",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      part: reasoningSnapshot({
        revision: 2,
        state: "complete",
        requested_tool_calls: 1,
        completed_at: "2026-08-09T00:00:02Z",
        text: "partial trace, whole",
        text_ephemeral: true,
      }),
    }),
  ]);
  const reasoning = reasoningPart(state, "reasoning:a:1");
  assert.equal(reasoning.state, "complete");
  assert.equal(reasoning.text, "partial trace, whole");
  assert.equal(reasoning.textEphemeral, true);
});

test("a summary-mode reasoning card carries no text at all", () => {
  const state = apply(emptyTranscriptState(), [
    frame({
      type: "part.completed",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      part: reasoningSnapshot({ revision: 2, state: "complete" }),
    }),
  ]);
  const reasoning = reasoningPart(state, "reasoning:a:1");
  assert.equal(reasoning.text, null);
  assert.equal(reasoning.textEphemeral, false);
});

test("a reasoning delta with no card to belong to invents nothing", () => {
  // A frame out of order must not conjure a model round that never started.
  const state = apply(emptyTranscriptState(), [
    frame({
      type: "text.delta",
      part_id: "reasoning:a:1",
      part_kind: "reasoning",
      delta_index: 0,
      delta: "orphan",
    }),
  ]);
  const turn = state.turns.get(TURN);
  assert.ok(turn);
  assert.equal(turn.parts.length, 0);
});

// --- the design leg (genweb slice 3) --------------------------------------

function legFrame(
  payload: Record<string, unknown>,
  turnId: string = TURN,
): ChatStreamEvent {
  nextEventId += 1;
  const parsed = parseChatStreamEvent({
    schema_version: "1",
    event_id: nextEventId,
    sequence: nextEventId,
    project_id: "p1",
    thread_id: "t1",
    turn_id: turnId,
    ...payload,
  });
  assert.ok(parsed.ok, `leg frame did not parse: ${parsed.ok ? "" : parsed.reason}`);
  return parsed.event;
}

function assistantOf(
  state: TranscriptState,
  turnId: string,
): TranscriptMessage {
  const composed = composeTranscript({ messages: [], turns: [], stream: state });
  const message = composed.find(
    (item) => item.turnId === turnId && item.role === "assistant",
  );
  assert.ok(message, `no assistant message for ${turnId}`);
  return message;
}

test("the four leg frames parse and carry their leg id", () => {
  for (const type of [
    "leg.opened",
    "leg.awaiting_user",
    "leg.closed",
    "leg.reopened",
  ] as const) {
    const event = legFrame({ type, leg_id: "leg-9", reason: "locked" });
    assert.equal(event.type, type);
    assert.equal(event.legId, "leg-9");
  }
});

test("an unrecognized leg frame is dropped without killing the stream", () => {
  // Forward compatibility: a NEW backend frame must never crash an old build.
  const parsed = parseChatStreamEvent({
    schema_version: "1",
    project_id: "p1",
    thread_id: "t1",
    turn_id: TURN,
    type: "leg.something_new",
    leg_id: "leg-9",
  });
  assert.equal(parsed.ok, false);
  assert.equal(parsed.ok === false && parsed.fatal, false);
});

test("leg lines land on the turn that performed the transition, in order", () => {
  const state = apply(emptyTranscriptState(), [
    legFrame({ type: "leg.opened", leg_id: "leg-9" }, "turn-open"),
    legFrame({ type: "leg.awaiting_user", leg_id: "leg-9" }, "turn-design"),
    legFrame(
      { type: "leg.closed", leg_id: "leg-9", reason: "locked" },
      "turn-design",
    ),
  ]);
  assert.deepEqual(assistantOf(state, "turn-open").legNotices, [
    "Design session opened — generating now.",
  ]);
  assert.deepEqual(assistantOf(state, "turn-design").legNotices, [
    "Design is ready for your next message.",
    "Design session closed — the page is locked in.",
  ]);
});

test("a replayed leg backlog re-lands the same lines, never a second copy", () => {
  const opened = legFrame({ type: "leg.opened", leg_id: "leg-9" }, "turn-open");
  const state = apply(emptyTranscriptState(), [opened, opened, opened]);
  assert.equal(assistantOf(state, "turn-open").legNotices.length, 1);
});

test("a leg frame changes no turn state and creates no part", () => {
  const state = apply(emptyTranscriptState(), [
    frame({ type: "turn.started" }),
    legFrame({ type: "leg.awaiting_user", leg_id: "leg-9" }),
  ]);
  const turn = state.turns.get(TURN);
  assert.ok(turn);
  assert.equal(turn.state, "running");
  assert.equal(turn.parts.length, 0);
});

test("a turn running inside an open leg is generating; the opener is not", () => {
  const state = apply(emptyTranscriptState(), [
    legFrame({ type: "leg.opened", leg_id: "leg-9" }, "turn-open"),
    legFrame({ type: "turn.started" }, "turn-open"),
    legFrame({ type: "turn.awaiting_input" }, "turn-open"),
    legFrame({ type: "turn.started" }, "turn-design"),
  ]);
  assert.equal(assistantOf(state, "turn-open").generatingDesign, false);
  assert.equal(assistantOf(state, "turn-design").generatingDesign, true);
});

test("nothing is generating once the leg has closed", () => {
  const state = apply(emptyTranscriptState(), [
    legFrame({ type: "leg.opened", leg_id: "leg-9" }, "turn-open"),
    legFrame({ type: "leg.closed", leg_id: "leg-9", reason: "locked" }, "turn-a"),
    legFrame({ type: "turn.started" }, "turn-b"),
  ]);
  assert.equal(state.designLeg.open, false);
  assert.equal(assistantOf(state, "turn-b").generatingDesign, false);
});

test("with no leg frame in the backlog nothing claims to be generating", () => {
  // The honest degradation: an opening frame older than the replayed backlog
  // means the surface says less, never something untrue.
  const state = apply(emptyTranscriptState(), [
    legFrame({ type: "turn.started" }, "turn-design"),
  ]);
  assert.equal(assistantOf(state, "turn-design").generatingDesign, false);
});

test("a reopen names its own delegating turn and reopens the leg", () => {
  const state = apply(emptyTranscriptState(), [
    legFrame({ type: "leg.opened", leg_id: "leg-9" }, "turn-open"),
    legFrame({ type: "leg.closed", leg_id: "leg-9", reason: "locked" }, "turn-a"),
    legFrame({ type: "leg.reopened", leg_id: "leg-9" }, "turn-reopen"),
  ]);
  assert.deepEqual(state.designLeg, {
    known: true,
    open: true,
    legId: "leg-9",
    openedByTurnId: "turn-reopen",
  });
  assert.deepEqual(assistantOf(state, "turn-reopen").legNotices, [
    "Design session reopened — generating now.",
  ]);
});

test("an awaiting frame keeps the leg open without stealing the opener", () => {
  const state = apply(emptyTranscriptState(), [
    legFrame({ type: "leg.opened", leg_id: "leg-9" }, "turn-open"),
    legFrame({ type: "leg.awaiting_user", leg_id: "leg-9" }, "turn-design"),
  ]);
  assert.deepEqual(state.designLeg, {
    known: true,
    open: true,
    legId: "leg-9",
    openedByTurnId: "turn-open",
  });
});

/* --------------------------------------------------------------------------
 * The durable seed (task 4 fix round 1, finding I1)
 *
 * The frame backlog reaches back only a few turns, so a leg opened before it
 * is invisible to the stream. The thread wire's speaker projection knows, and
 * seeding from it is what stops "no frame said so" reading as "there is no
 * leg".
 * ----------------------------------------------------------------------- */

test("the durable seed answers a leg no frame in the backlog mentions", () => {
  const state = seedDesignLeg(emptyTranscriptState(), {
    legId: "leg-9",
    open: true,
  });
  assert.deepEqual(state.designLeg, {
    known: true,
    open: true,
    legId: "leg-9",
    // No frame named the delegating turn, and the wire does not carry one.
    openedByTurnId: null,
  });
});

test("a seed that says there is no leg is still KNOWLEDGE", () => {
  const state = seedDesignLeg(emptyTranscriptState(), {
    legId: null,
    open: false,
  });
  assert.equal(state.designLeg.known, true);
  assert.equal(state.designLeg.open, false);
});

test("nothing observed and nothing seeded is UNKNOWN, not closed", () => {
  assert.equal(emptyTranscriptState().designLeg.known, false);
  assert.equal(emptyTranscriptState().designLeg.open, false);
});

test("a seed never overwrites what the stream has already observed", () => {
  // The wire is a snapshot taken when the thread list was read; the frames are
  // live. A leg the stream watched close must stay closed.
  const observed = apply(emptyTranscriptState(), [
    legFrame({ type: "leg.opened", leg_id: "leg-9" }, "turn-open"),
    legFrame({ type: "leg.closed", leg_id: "leg-9", reason: "locked" }, "turn-a"),
  ]);
  const seeded = seedDesignLeg(observed, { legId: "leg-9", open: true });
  assert.equal(seeded, observed);
  assert.equal(seeded.designLeg.open, false);
});

test("a frame still outranks a seed that landed first", () => {
  const seeded = seedDesignLeg(emptyTranscriptState(), {
    legId: "leg-9",
    open: true,
  });
  const state = apply(seeded, [
    legFrame({ type: "leg.closed", leg_id: "leg-9", reason: "locked" }, "turn-a"),
  ]);
  assert.equal(state.designLeg.open, false);
  assert.equal(state.designLeg.known, true);
});

test("seeding twice is idempotent and allocates nothing", () => {
  const once = seedDesignLeg(emptyTranscriptState(), {
    legId: "leg-9",
    open: true,
  });
  assert.equal(seedDesignLeg(once, { legId: "leg-9", open: true }), once);
});

test("stream.reset drops parts but keeps the leg lines it cannot re-read", () => {
  const state = apply(emptyTranscriptState(), [
    legFrame({ type: "leg.awaiting_user", leg_id: "leg-9" }),
    frame({ type: "text.start", part_id: "text:a", part_kind: "text" }),
    frame({ type: "stream.reset", reason: "reconciliation_mismatch" }),
  ]);
  const turn = state.turns.get(TURN);
  assert.ok(turn);
  assert.equal(turn.parts.length, 0);
  assert.equal(turn.legNotices.size, 1);
});

// --- mid-run checkpoints (scene live-streaming rung A) --------------------

test("a design checkpoint parses the mark the design run committed", () => {
  const event = legFrame({
    type: "design.checkpoint",
    document_id: "doc-7",
    version: 12,
    operations: 43,
    preflight_clean: true,
  });
  assert.equal(event.type, "design.checkpoint");
  assert.deepEqual(event.checkpoint, {
    documentId: "doc-7",
    version: 12,
    operations: 43,
    preflightClean: true,
  });
});

test("a checkpoint whose payload is missing or wrong-typed still reloads", () => {
  // The forwarder copies across only the keys the design event actually
  // carried, so a partial payload is a normal frame, not a broken one — and
  // the reload decision needs nothing but the type. Refusing the frame would
  // trade a whole missing feature for an unreadable field.
  for (const payload of [
    {},
    { document_id: 4, version: "twelve", operations: null, preflight_clean: "no" },
  ]) {
    const parsed = parseChatStreamEvent({
      schema_version: "1",
      event_id: 9001,
      project_id: "p1",
      thread_id: "t1",
      turn_id: TURN,
      type: "design.checkpoint",
      ...payload,
    });
    assert.ok(parsed.ok, "a malformed checkpoint payload must not drop the frame");
    assert.deepEqual(parsed.event.checkpoint, {
      documentId: null,
      version: null,
      operations: null,
      preflightClean: null,
    });
  }
});

test("only a checkpoint frame carries a checkpoint", () => {
  assert.equal(legFrame({ type: "leg.awaiting_user", leg_id: "leg-9" }).checkpoint, null);
  assert.equal(frame({ type: "turn.started" }).checkpoint, null);
});

test("a checkpoint writes no transcript line and moves no turn state", () => {
  const state = apply(emptyTranscriptState(), [
    frame({ type: "turn.started" }),
    legFrame({ type: "design.checkpoint", document_id: "doc-7", version: 3 }),
  ]);
  const turn = state.turns.get(TURN);
  assert.ok(turn);
  assert.equal(turn.state, "running");
  assert.equal(turn.parts.length, 0);
  assert.equal(turn.legNotices.size, 0);
  assert.equal(state.designLeg.open, false);
});

// --- streamed op batches (scene live-streaming rung B) --------------------

test("an op batch parses the operations, the ledger position, and the iteration", () => {
  const event = legFrame({
    type: "design.op_batch",
    document_id: "doc-7",
    operations: [{ kind: "remove_node", node_id: "n1" }],
    operations_total: 44,
    iteration: 3,
  });
  assert.equal(event.type, "design.op_batch");
  assert.deepEqual(event.opBatch, {
    documentId: "doc-7",
    operations: [{ kind: "remove_node", node_id: "n1" }],
    operationsTotal: 44,
    iteration: 3,
  });
});

test("a POSITION-ONLY op batch parses with its operations absent", () => {
  // The forwarder drops an oversize `operations` and keeps the position, on
  // purpose: half a batch applied to a canvas is a corrupted document, a bare
  // position is honest. The reader must carry that shape through, not refuse it.
  const event = legFrame({
    type: "design.op_batch",
    document_id: "doc-7",
    operations_total: 44,
    iteration: 3,
  });
  assert.deepEqual(event.opBatch, {
    documentId: "doc-7",
    operations: null,
    operationsTotal: 44,
    iteration: 3,
  });
});

test("an op batch with an unreadable payload is read as absent, never dropped", () => {
  // Same discipline as the checkpoint above: a malformed member must not break
  // the stream. It reads as no operations, which the cursor turns into a wait
  // for the next checkpoint — never into a guess at what was meant.
  for (const operations of [
    "not-a-list",
    7,
    {},
    [],
    [null],
    [{ node_id: "n1" }],
    [{ kind: "remove_node" }, "second"],
  ]) {
    const parsed = parseChatStreamEvent({
      schema_version: "1",
      event_id: 9101,
      project_id: "p1",
      thread_id: "t1",
      turn_id: TURN,
      type: "design.op_batch",
      document_id: "doc-7",
      operations,
      operations_total: 44,
    });
    assert.ok(parsed.ok, "a malformed op batch must not drop the frame");
    assert.deepEqual(parsed.event.opBatch, {
      documentId: "doc-7",
      operations: null,
      operationsTotal: 44,
      iteration: null,
    });
  }
});

test("only an op-batch frame carries an op batch", () => {
  assert.equal(legFrame({ type: "design.checkpoint", document_id: "d" }).opBatch, null);
  assert.equal(frame({ type: "turn.started" }).opBatch, null);
});

test("an op batch writes no transcript line and moves no turn state", () => {
  const state = apply(emptyTranscriptState(), [
    frame({ type: "turn.started" }),
    legFrame({
      type: "design.op_batch",
      document_id: "doc-7",
      operations: [{ kind: "remove_node", node_id: "n1" }],
      operations_total: 1,
    }),
  ]);
  const turn = state.turns.get(TURN);
  assert.ok(turn);
  assert.equal(turn.state, "running");
  assert.equal(turn.parts.length, 0);
  assert.equal(turn.legNotices.size, 0);
  assert.equal(state.designLeg.open, false);
});

// --- C5: newest-first pages merging backward ------------------------------------------------

function durablePageMessage(
  sequence: number,
  role: "user" | "assistant",
  turnId: string,
): ChatMessage {
  return {
    id: `m${sequence}`,
    turnId,
    threadId: "t1",
    sequence,
    role,
    bodyArtifactKey: `k${sequence}`,
    bodySha256: `s${sequence}`,
    body: `message ${sequence}`,
    bodyUnavailableReason: null,
    createdAt: "2026-08-09T00:00:00Z",
    refs: [],
  };
}

test("the newest page hydrates the transcript with the latest user message", () => {
  // The audited defect: a >50-message thread reloaded to its OLDEST page, so the
  // user's latest prompts were durably stored yet invisible. The newest-first
  // page is what initial load merges now.
  const newestPage = [
    durablePageMessage(119, "user", "turn-119"),
    durablePageMessage(120, "assistant", "turn-119"),
  ];
  const merged = mergeThreadMessages([], newestPage);
  const transcript = composeTranscript({
    messages: merged,
    turns: [],
    stream: emptyTranscriptState(),
  });
  const users = transcript.filter((message) => message.role === "user");
  assert.equal(users.length, 1);
  assert.equal(users[0].body, "message 119");
});

test("prepending an older page keeps ascending order and never reorders what is loaded", () => {
  const newest = [
    durablePageMessage(3, "user", "turn-3"),
    durablePageMessage(4, "assistant", "turn-3"),
  ];
  const older = [
    durablePageMessage(1, "user", "turn-1"),
    durablePageMessage(2, "assistant", "turn-1"),
  ];
  const merged = mergeThreadMessages(newest, older);
  assert.deepEqual(
    merged.map((message) => message.sequence),
    [1, 2, 3, 4],
  );
  // The already-loaded entries survive by identity — a prepend is not a rebuild.
  assert.equal(merged[2], newest[0]);
  assert.equal(merged[3], newest[1]);
});

test("an overlapping refetch never duplicates a message", () => {
  const loaded = [
    durablePageMessage(2, "user", "turn-2"),
    durablePageMessage(3, "assistant", "turn-2"),
  ];
  const overlapping = [
    durablePageMessage(1, "assistant", "turn-1"),
    durablePageMessage(2, "user", "turn-2"),
  ];
  const merged = mergeThreadMessages(loaded, overlapping);
  assert.deepEqual(
    merged.map((message) => message.id),
    ["m1", "m2", "m3"],
  );
});

test("a prepended older page retires its own optimistic and streamed stand-ins", () => {
  // The reducer's identity guards are the merge seam: a durable user message
  // retires the optimistic stand-in for its turn, and a durable assistant
  // message for a projected turn composes as one entry, not two.
  const streamed = apply(emptyTranscriptState(), [
    frame({ type: "turn.started", attempt_ordinal: 1 }),
    frame({ type: "text.start", part_id: "text:a", part_kind: "text" }),
    frame({ type: "text.delta", part_id: "text:a", delta_index: 0, delta: "message 2" }),
  ]);
  const olderPage = [
    durablePageMessage(1, "user", TURN),
    durablePageMessage(2, "assistant", TURN),
  ];
  const transcript = composeTranscript({
    messages: mergeThreadMessages([], olderPage),
    turns: [],
    stream: streamed,
    optimistic: [{ turnId: TURN, text: "message 1", requestedAt: "2026-08-09T00:00:00Z" }],
  });
  assert.equal(transcript.filter((message) => message.role === "user").length, 1);
  assert.equal(transcript.filter((message) => message.role === "assistant").length, 1);
  assert.equal(transcript[0].optimistic, false, "the durable user message won");
});

test("a clarification snapshot parses into the card's camelCase shape", () => {
  const state = apply(emptyTranscriptState(), [
    frame({
      type: "part.created",
      part_id: "clarification:doc-1",
      part_kind: "clarification",
      part: {
        part_id: "clarification:doc-1",
        kind: "clarification",
        revision: 1,
        document_id: "doc-1",
        document_title: "Acme retargeting ad",
        doc_kind: "scene",
        account_name: "Acme",
        run_id: "run-1",
        questions: [
          {
            id: "q1",
            question: "Which offer should lead?",
            why_it_matters: "It sets the headline.",
            options: ["Free trial", "Demo"],
            default: "Free trial",
            allow_freeform: false,
          },
          // The runtime may ask an open question: no options, no rationale, and
          // the emitter's own defaults fill what the wire leaves out.
          { id: "q2", question: "Anything else?", default: "No" },
        ],
      },
    }),
  ]);

  const part = state.turns.get(TURN)?.parts[0]?.part;
  assert.equal(part?.kind, "clarification");
  assert.deepEqual(part, {
    kind: "clarification",
    partId: "clarification:doc-1",
    revision: 1,
    documentId: "doc-1",
    documentTitle: "Acme retargeting ad",
    docKind: "scene",
    accountName: "Acme",
    runId: "run-1",
    questions: [
      {
        id: "q1",
        question: "Which offer should lead?",
        whyItMatters: "It sets the headline.",
        options: ["Free trial", "Demo"],
        default: "Free trial",
        allowFreeform: false,
      },
      {
        id: "q2",
        question: "Anything else?",
        whyItMatters: "",
        options: [],
        default: "No",
        allowFreeform: true,
      },
    ],
  });
});

test("an untagged document sends no account_name key at all, and reads as null", () => {
  const state = apply(emptyTranscriptState(), [
    frame({
      type: "part.created",
      part_id: "clarification:doc-2",
      part_kind: "clarification",
      part: {
        part_id: "clarification:doc-2",
        kind: "clarification",
        revision: 1,
        document_id: "doc-2",
        document_title: "Untitled ad",
        doc_kind: "scene",
        run_id: "run-2",
        questions: [{ id: "q1", question: "Which tone?", default: "Bold" }],
      },
    }),
  ]);

  const part = state.turns.get(TURN)?.parts[0]?.part;
  assert.equal(part?.kind === "clarification" && part.accountName, null);
});
