import assert from "node:assert/strict";
import test from "node:test";
import type { ProtectedSession } from "@/features/session/model/session";
import { getWorkspaceProfile } from "./workspace-profile.repository";
import { workspaceProfileFixture } from "./workspace-profile.fixture";

const session = {
  userId: "priya@clue.example",
  memberships: [],
  principal: {},
} as unknown as ProtectedSession;

function withFixtureMode<T>(enabled: boolean, body: () => T): T {
  const previous = process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
  process.env.CLUE_ACCOUNTS_FIXTURE_MODE = enabled ? "true" : "false";
  try {
    return body();
  } finally {
    if (previous === undefined) delete process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
    else process.env.CLUE_ACCOUNTS_FIXTURE_MODE = previous;
  }
}

test("a sessionless live request gets a neutral profile, never the fixture person", () => {
  const profile = withFixtureMode(false, () => getWorkspaceProfile(null));
  assert.deepEqual(profile, {
    fullName: "Workspace",
    displayName: "Workspace",
    initials: "W",
    avatarColor: workspaceProfileFixture.avatarColor,
  });
  assert.notEqual(profile.fullName, workspaceProfileFixture.fullName);
});

test("a sessionless request in fixture mode is the design build's own person", () => {
  assert.deepEqual(
    withFixtureMode(true, () => getWorkspaceProfile(null)),
    workspaceProfileFixture,
  );
});

test("a session names the session user in either mode", () => {
  for (const fixtureMode of [true, false]) {
    const profile = withFixtureMode(fixtureMode, () =>
      getWorkspaceProfile(session),
    );
    assert.equal(profile.id, "priya@clue.example");
    assert.equal(profile.fullName, "priya");
    assert.equal(profile.initials, "P");
  }
});
