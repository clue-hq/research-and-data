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
  turnsAwaitingRehydration,
  type TranscriptState,
} from "./chat-transcript";
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
    turn_id: TURN,
    type: "part.created",
    part_id: "tool:x",
    part_kind: "tool",
    part: { part_id: "tool:x", kind: "tool" },
  });
  assert.equal(badPart.ok, false);
  assert.equal(badPart.ok === false && badPart.fatal, false);
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
