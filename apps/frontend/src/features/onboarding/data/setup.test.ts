import assert from "node:assert/strict";
import test from "node:test";
import {
  SetupApiError,
  SetupStatusSchema,
  companyDomainOf,
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
  // R6: one failure does not end the screen while its neighbours are still working.
  assert.equal(setupStatusFromOnboarding({ ...running, steps }).status, "running");
});

test("the failed verdict waits for every fast step to settle (ruling R6)", () => {
  // A provider error is a STEP outcome; the run carries on. Declaring the screen failed here
  // would stop the poll on a run that was about to release the user.
  const inFlight = [
    step("overview", "failed"),
    step("lineup", "running"),
    step("reviews", "completed"),
    step("synthesis", "queued"),
  ];
  assert.equal(setupStatusFromOnboarding({ ...running, steps: inFlight }).status, "running");

  const settled = [
    step("overview", "failed"),
    step("lineup", "completed"),
    step("reviews", "empty"),
    step("synthesis", "completed"),
  ];
  assert.equal(setupStatusFromOnboarding({ ...running, steps: settled }).status, "failed");
});

test("a fast kind moved to the background phase never gates the release", () => {
  // `CLUE_ONBOARDING_REVIEWS_PHASE=background` moves `reviews` off the fast lane; the step
  // keeps its kind, and background work must never hold the release.
  const steps = [
    step("overview", "completed"),
    step("lineup", "completed"),
    step("reviews", "running", "background"),
    step("synthesis", "completed"),
  ];
  assert.equal(setupStatusFromOnboarding({ ...running, steps }).status, "complete");
  // Nor does its failure fail the screen.
  steps[2] = step("reviews", "failed", "background");
  assert.equal(setupStatusFromOnboarding({ ...running, steps }).status, "complete");
});

test("every run status the backend can emit maps to a named screen status", () => {
  // The run vocabulary is the migration's CHECK (0aa95f87eb49 — `queued | running |
  // completed | completed_with_gaps | failed`), plus the route's synthetic `none`. A raw wire
  // body per case, so this table exercises the real parse.
  const done = FAST_STEP_KINDS.map((kind) => step(kind, "completed"));
  const cases: [string, unknown[], string][] = [
    ["none", [], "none"],
    ["queued", [], "starting"],
    ["running", [], "running"],
    ["running", done, "complete"],
    ["completed", [], "complete"],
    // The lane's ORDINARY terminal: any `empty` or `failed` step settles the run here, and
    // `empty` is a correct outcome. It is a release, not "setup isn't available".
    ["completed_with_gaps", [], "complete"],
    ["failed", [], "failed"],
    ["paused", [], "unavailable"],
  ];
  for (const [wireStatus, steps, expected] of cases) {
    assert.equal(
      setupStatusFromOnboarding({
        schema_version: "1",
        runId: wireStatus === "none" ? null : "run-1",
        status: wireStatus,
        steps,
        costUsd: "0",
      }).status,
      expected,
      `run status ${wireStatus} with ${steps.length} steps`,
    );
  }
});

test("the brand-kit ingestion job is carried through from the wire, or honest null", () => {
  assert.deepEqual(
    setupStatusFromOnboarding({
      ...running,
      brandKitIngestion: { jobId: "job-1", status: "succeeded" },
    }).brand_kit_ingestion,
    { job_id: "job-1", status: "succeeded" },
  );
  // A future job status degrades to in-flight, never to a kit that exists (FE-N2).
  assert.equal(
    setupStatusFromOnboarding({
      ...running,
      brandKitIngestion: { jobId: "job-1", status: "who-knows" },
    }).brand_kit_ingestion?.status,
    "running",
  );
  // Absent (a backend that does not serve it) and explicit null are both "no job".
  assert.equal(setupStatusFromOnboarding(running).brand_kit_ingestion, null);
  assert.equal(
    setupStatusFromOnboarding({ ...running, brandKitIngestion: null }).brand_kit_ingestion,
    null,
  );
});

test("companyDomainOf folds everything after the host away", () => {
  assert.equal(
    companyDomainOf("  HTTPS://www.Insighthealth.ai:8443/pricing?ref=x#plans  "),
    "insighthealth.ai",
  );
  assert.equal(companyDomainOf("insighthealth.ai"), "insighthealth.ai");
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
