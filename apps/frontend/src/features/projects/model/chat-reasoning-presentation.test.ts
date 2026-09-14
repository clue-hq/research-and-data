import assert from "node:assert/strict";
import test from "node:test";
import type { ChatPart, ChatReasoningPart } from "./chat-parts";
import { presentChatReasoning } from "./chat-reasoning-presentation";

function round(overrides: Partial<ChatReasoningPart> = {}): ChatReasoningPart {
  return {
    kind: "reasoning", partId: "round-1", revision: 1, state: "active",
    roundOrdinal: 1, requestedToolCalls: 0, startedAt: "2026-09-12T00:00:00Z",
    completedAt: null, text: null, textEphemeral: false, ...overrides,
  };
}

test("multiple rounds preserve literal text in one trace without activity labels", () => {
  const literal = "  `" + "a".repeat(2000) + "`\n```json\n{\"content\":\"**sample**\"}\n```\n";
  const parts: ChatPart[] = [
    round({ text: literal, textEphemeral: true, state: "complete" }),
    { kind: "agent_activity", partId: "activity", revision: 1, title: "Agent activity", steps: [] },
    round({ partId: "round-2", roundOrdinal: 2, text: "Second round" }),
  ];
  assert.deepEqual(presentChatReasoning(parts, "running"), {
    active: true, running: true, text: literal + "\n\nSecond round", ephemeral: true,
  });
  assert.equal(parts.length, 3);
});

test("no supplied text gives no invented completed trace", () => {
  assert.equal(presentChatReasoning([round({ text: "\n  " })], "completed").text, "");
  assert.equal(presentChatReasoning([round()], "running").active, true);
  assert.equal(presentChatReasoning([], "running").active, false);
});

test("terminal turns stop shimmering even if the last round still says active", () => {
  for (const state of ["awaiting_input", "completed", "cancelled", "failed"] as const) {
    const trace = presentChatReasoning([round({ text: "Existing trace" })], state);
    assert.equal(trace.active, false);
    assert.equal(trace.running, false);
    assert.equal(trace.text, "Existing trace");
  }
});

test("between model rounds the disclosure stays in the running turn", () => {
  const trace = presentChatReasoning([round({ state: "complete", text: "First round" })], "running");
  assert.equal(trace.active, false);
  assert.equal(trace.running, true);
});
