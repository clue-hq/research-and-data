import assert from "node:assert/strict";
import test from "node:test";
import {
  fixtureOnboardingRepository,
  provisionWorkspaceFixture,
} from "./onboarding.repository";

test("fixture onboarding repository returns the approved auth and setup payload", async () => {
  const flow = await fixtureOnboardingRepository.getFlow();

  assert.equal(flow.auth.signIn.title, "Login to your account");
  assert.equal(flow.auth.signUp.submitLabel, "Sign up");
  assert.equal(flow.auth.verifyEmail.submitLabel, "Verify");
  assert.equal(flow.setup.items.length, 4);
  assert.equal(flow.setup.items[1]?.status, "running");
});

test("fixture provisioning echoes the submitted profile with deterministic ids", async () => {
  const provisioned = await provisionWorkspaceFixture({
    first_name: "Aakash",
    last_name: "Shrivastava",
    job_role: "Founder",
    company_name: "Insight Health",
    company_website: "https://insight.health",
  });

  assert.equal(provisioned.workspace_id, "ws_fixture");
  assert.equal(provisioned.role_key, "owner");
  assert.equal(provisioned.company_name, "Insight Health");
  assert.equal(provisioned.created, true);
});
