import test from "node:test";
import assert from "node:assert/strict";
import { createWorkspaceFixture } from "./workspace.fixture";
import { createWorkspaceRepository } from "./workspace.repository";
import type { WorkspaceState } from "../model/workspace";

test("fresh reply guidance follows reassignment and stops requesting handled work", async () => {
  let state = createWorkspaceFixture();
  const repo = createWorkspaceRepository({ read: async () => structuredClone(state),
    transact: async <R,>(change: (s: WorkspaceState) => { state: WorkspaceState; result: R }) => { const next = change(structuredClone(state)); state = next.state; return next.result; },
  });
  const account = state.accounts.find((a) => a.id === "account-linden-technologies")!;
  await repo.updateAccountOwner(account.id, account.revision, "alex");
  let response = await repo.addChatMessage("Who needs a reply?");
  assert.match(response.messages.at(-1)!.text, /Alex Rivera/);
  assert.doesNotMatch(response.messages.at(-1)!.text, /Jamie/);
  const email = state.emails.find((e) => e.status === "reply")!;
  await repo.markReplyHandled(email.id, email.revision);
  response = await repo.addChatMessage("Who needs a reply?");
  assert.match(response.messages.at(-1)!.text, /no outstanding recipient replies/i);
  assert.doesNotMatch(response.messages.at(-1)!.text, /waiting for/);
});
