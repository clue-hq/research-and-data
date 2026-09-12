import assert from "node:assert/strict";
import test from "node:test";
import {
  SetupApiError,
  SetupStatusSchema,
  readSetupStatus,
  setupStatusFromOnboarding,
  startWorkspaceSetup,
  FAST_STEP_KINDS,
} from "./setup";

function step(kind: string, status: string, phase = "fast") {
  return {
    kind,
    subjectRef: null,
    phase,
    status,
    startedAt: null,
    finishedAt: null,
    costUsd: "0",
    failureCode: null,
  };
}

const running = {
  schema_version: "1",
  runId: "run-1",
  status: "running",
  costUsd: "0.10",
  steps: [] as unknown[],
};

test("no run yet is none; a queued run is starting", () => {
  assert.equal(
    setupStatusFromOnboarding({
      schema_version: "1",
      runId: null,
      status: "none",
      steps: [],
      costUsd: "0",
    }).status,
    "none",
  );
  assert.equal(setupStatusFromOnboarding({ ...running, status: "queued" }).status, "starting");
});

test("the run is complete for the screen when every fast step is terminal and none failed", () => {
  const steps = FAST_STEP_KINDS.map((kind) => step(kind, "completed"));
  assert.equal(setupStatusFromOnboarding({ ...running, steps }).status, "complete");
  // `empty` is a correct outcome, not a failure.
  steps[2] = step("reviews", "empty");
  assert.equal(setupStatusFromOnboarding({ ...running, steps }).status, "complete");
  // Background work still running does not hold the release.
  assert.equal(
    setupStatusFromOnboarding({
      ...running,
      steps: [...steps, step("persona", "running", "background")],
    }).status,
    "complete",
  );
});

test("a fast step still running keeps the screen running; a failed fast step fails it", () => {
  const steps = [
    step("overview", "completed"),
    step("lineup", "running"),
    step("reviews", "queued"),
    step("synthesis", "queued"),
  ];
  assert.equal(setupStatusFromOnboarding({ ...running, steps }).status, "running");
  steps[1] = step("lineup", "failed");
  assert.equal(setupStatusFromOnboarding({ ...running, steps }).status, "failed");
});

test("an unknown run status degrades to unavailable rather than breaking the poll", () => {
  assert.equal(setupStatusFromOnboarding({ ...running, status: "paused" }).status, "unavailable");
});

test("start posts the company domain to the new lane and read parses the new shape", async (t) => {
  const calls: { url: string; init?: RequestInit }[] = [];
  t.mock.method(globalThis, "fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.endsWith("/api/clue/onboarding"))
      return new Response(
        JSON.stringify({ schema_version: "1", run_id: "run-1", status: "queued" }),
        { status: 202 },
      );
    return new Response(JSON.stringify(running), { status: 200 });
  });
  await startWorkspaceSetup({ companyWebsite: "https://Insighthealth.ai/" });
  assert.equal(calls[0].url, "/api/clue/onboarding");
  assert.equal(calls[0].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
    company_domain: "insighthealth.ai",
    brand_id: null,
  });
  const status = await readSetupStatus();
  assert.equal(calls[1].url, "/api/clue/onboarding/current");
  assert.equal(status.status, "running");
  assert.equal(status.run_id, "run-1");
});

test("a 409 onboarding_in_progress on start is not a failure: the run is already running", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(JSON.stringify({ detail: { error: "onboarding_in_progress", reason: "run-0" } }), {
        status: 409,
      }),
  );
  await startWorkspaceSetup({ companyWebsite: "insighthealth.ai" }); // resolves, does not throw
});

test("a missing company website never posts: a live run means the start already happened", async (t) => {
  const calls: { url: string; init?: RequestInit }[] = [];
  t.mock.method(globalThis, "fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(running), { status: 200 });
  });
  await startWorkspaceSetup({ companyWebsite: "  " }); // resolves quietly
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/clue/onboarding/current");
  assert.equal(calls[0].init?.method, undefined);
});

test("a missing company website with no run is a typed refusal, not a blind 422 post", async (t) => {
  const calls: { url: string; init?: RequestInit }[] = [];
  t.mock.method(globalThis, "fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(
      JSON.stringify({ schema_version: "1", runId: null, status: "none", steps: [], costUsd: "0" }),
      { status: 200 },
    );
  });
  await assert.rejects(
    startWorkspaceSetup({ companyWebsite: "" }),
    (error: unknown) =>
      error instanceof SetupApiError &&
      error.status === 422 &&
      error.code === "company_domain_missing",
  );
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/clue/onboarding/current");
  assert.equal(calls[0].init?.method, undefined);
});

test("status reads surface BFF auth envelopes with their code", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        JSON.stringify({
          error: { code: "AUTHENTICATION_REQUIRED", message: "Sign in to continue" },
        }),
        { status: 401, headers: { "content-type": "application/json" } },
      ),
  );
  await assert.rejects(
    readSetupStatus(),
    (error: unknown) =>
      error instanceof SetupApiError &&
      error.status === 401 &&
      error.code === "AUTHENTICATION_REQUIRED",
  );
});

test("the parsed status validates through the schema", () => {
  assert.ok(SetupStatusSchema.safeParse(setupStatusFromOnboarding(running)).success);
});
