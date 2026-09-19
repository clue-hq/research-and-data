import assert from "node:assert/strict";
import test from "node:test";
import {
  OnboardingProvisionError,
  fixtureOnboardingRepository,
  provisionWorkspace,
  provisionWorkspaceFixture,
} from "./onboarding.repository";

const PROVISION_INPUT = {
  first_name: "Aakash",
  last_name: "Shrivastava",
  job_role: "Founder",
  company_name: "Insight Health",
  company_website: "https://insight.health",
};

function stubFetch(response: Response): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = async () => response;
  return () => {
    globalThis.fetch = original;
  };
}

test("fixture onboarding repository returns the approved auth and setup payload", async () => {
  const flow = await fixtureOnboardingRepository.getFlow();

  assert.equal(flow.auth.signIn.title, "Login to your account");
  assert.equal(flow.auth.signUp.submitLabel, "Sign up");
  assert.equal(flow.auth.verifyEmail.submitLabel, "Verify");
  // The four checklist groups plus the brand-kit row (the row the lane does not own).
  assert.deepEqual(
    flow.setup.items.map((item) => item.id),
    ["company", "products", "proof", "audience", "brand-kit"],
  );
  assert.equal(flow.setup.items[1]?.status, "running");
});

test("provision maps the backend error envelope to a typed error", async () => {
  const restore = stubFetch(
    new Response(
      JSON.stringify({
        error: { code: "PROVISIONING_CONFLICT", message: "already provisioned" },
      }),
      { status: 409, headers: { "content-type": "application/json" } },
    ),
  );
  try {
    await assert.rejects(
      provisionWorkspace(PROVISION_INPUT),
      (error: unknown) =>
        error instanceof OnboardingProvisionError &&
        error.code === "PROVISIONING_CONFLICT" &&
        error.status === 409,
    );
  } finally {
    restore();
  }
});

test("provision turns an envelope-less 422 into friendly copy, not a status string", async () => {
  const restore = stubFetch(
    new Response(JSON.stringify({ detail: [{ msg: "value_error" }] }), {
      status: 422,
      headers: { "content-type": "application/json" },
    }),
  );
  try {
    await assert.rejects(
      provisionWorkspace(PROVISION_INPUT),
      (error: unknown) =>
        error instanceof OnboardingProvisionError &&
        error.message === "Please check your details and try again.",
    );
  } finally {
    restore();
  }
});

test("provision tolerates additive response fields and defaults the divergence flag", async () => {
  const restore = stubFetch(
    new Response(
      JSON.stringify({
        user_id: "usr_1",
        workspace_id: "ws_1",
        brand_id: "brd_1",
        membership_id: "wsm_1",
        role_key: "owner",
        company_name: "Insight Health",
        company_website: "https://insight.health",
        first_name: "Aakash",
        last_name: "Shrivastava",
        job_role: "Founder",
        created: false,
        company_name_ignored: true,
        future_field: 1,
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );
  try {
    const provisioned = await provisionWorkspace(PROVISION_INPUT);
    assert.equal(provisioned.created, false);
    assert.equal(provisioned.company_name_ignored, true);
  } finally {
    restore();
  }
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
