import assert from "node:assert/strict";
import test from "node:test";
import { fixtureOnboardingRepository } from "./onboarding.repository";

test("fixture onboarding repository returns the approved auth and setup payload", async () => {
  const flow = await fixtureOnboardingRepository.getFlow();

  assert.equal(flow.auth.signIn.title, "Login to your account");
  assert.equal(flow.auth.signUp.submitLabel, "Sign up");
  assert.equal(flow.setup.items.length, 4);
  assert.equal(flow.setup.items[1]?.status, "running");
});
