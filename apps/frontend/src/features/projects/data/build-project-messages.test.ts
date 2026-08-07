import assert from "node:assert/strict";
import test from "node:test";
import { ProjectMessageSchema } from "../model/project-workspace";
import { projectWorkspaceFixture } from "./project-workspace.fixture";
import { buildProjectMessages } from "./build-project-messages";

test("project phases produce ordered, contract-safe message parts", () => {
  const messages = buildProjectMessages({
    generationProgress: 100,
    phase: "complete",
    workspace: projectWorkspaceFixture,
  });

  messages.forEach((message) => ProjectMessageSchema.parse(message));
  assert.equal(messages[0].role, "user");
  assert.deepEqual(
    messages.at(-1)?.parts.map((part) => part.type),
    ["text", "task", "sources"],
  );
  assert.ok(messages.some((message) => message.parts.some((part) => part.type === "tool")));
  assert.ok(messages.some((message) => message.parts.some((part) => part.type === "plan")));
});

test("streaming reasoning is the only assistant part during the initial phase", () => {
  const messages = buildProjectMessages({
    generationProgress: 0,
    phase: "conversation",
    workspace: projectWorkspaceFixture,
  });

  assert.equal(messages.length, 2);
  assert.equal(messages[1].parts[0].type, "reasoning");
  assert.equal(
    messages[1].parts[0].type === "reasoning" && messages[1].parts[0].streaming,
    true,
  );
});
