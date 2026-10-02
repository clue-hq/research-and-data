import assert from "node:assert/strict";
import { test } from "node:test";
import {
  discoveryLaunchToOpen,
  type LaunchSignalMessage,
} from "./discovery-launch-signal";

function message(parts: LaunchSignalMessage["parts"]): LaunchSignalMessage {
  return { parts };
}

const done = {
  kind: "tool" as const,
  toolName: "launch_arv2_discovery",
  toolCallId: "c1",
  state: "output-available" as const,
};

test("a completed discovery launch that was not seen before opens the surface", () => {
  assert.equal(
    discoveryLaunchToOpen({
      transcript: [message([done])],
      knownToolCallIds: new Set(),
    }),
    "c1",
  );
});

test("a launch already banked, a launch still running, and another tool all stay quiet", () => {
  assert.equal(
    discoveryLaunchToOpen({
      transcript: [message([done])],
      knownToolCallIds: new Set(["c1"]),
    }),
    null,
  );
  assert.equal(
    discoveryLaunchToOpen({
      transcript: [message([{ ...done, state: "input-available" }])],
      knownToolCallIds: new Set(),
    }),
    null,
  );
  assert.equal(
    discoveryLaunchToOpen({
      transcript: [message([{ ...done, toolName: "launch_account_research" }])],
      knownToolCallIds: new Set(),
    }),
    null,
  );
});

test("a refused launch never opens anything", () => {
  assert.equal(
    discoveryLaunchToOpen({
      transcript: [message([{ ...done, state: "output-error" }])],
      knownToolCallIds: new Set(),
    }),
    null,
  );
});
