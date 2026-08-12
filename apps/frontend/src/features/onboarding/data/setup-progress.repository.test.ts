import assert from "node:assert/strict";
import test from "node:test";
import { SETUP_GROUPS } from "./setup-groups";
import {
  SetupApiError,
  SetupStatusSchema,
  readSetupStatus,
  startWorkspaceSetup,
  type SetupStatus,
} from "./setup";
import {
  FIXTURE_SETUP_PROGRESS_SCRIPT,
  FIXTURE_SETUP_BASELINE_FIELDS,
} from "./setup-progress.fixture";
import {
  createFixtureSetupProgressSource,
  httpSetupProgressSource,
} from "./setup-progress.repository";
import { deriveSetupItems } from "../model/setup-items";
import type { OnboardingFlow, SetupItem } from "../model/onboarding";

/** The stub-fetch pattern from `setup.test.ts`, extended to record what was requested — the
 * delegation evidence is the call the source makes, not a mock of the function it calls. */
function stubFetch(response: Response): {
  calls: { url: string; method: string }[];
  restore: () => void;
} {
  const original = globalThis.fetch;
  const calls: { url: string; method: string }[] = [];
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), method: init?.method ?? "GET" });
    return response;
  };
  return {
    calls,
    restore: () => {
      globalThis.fetch = original;
    },
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const STATUS_RANK: Record<SetupItem["status"], number> = {
  queued: 0,
  running: 1,
  complete: 2,
};

const FIXTURE_SETUP: OnboardingFlow["setup"] = {
  title: "Setting up",
  finalizingDetail: "Finalizing",
  // No brand-kit row: this test is about the durable groups, not the ratified dummy.
  items: [{ id: "unused", label: "unused", detail: "unused", status: "queued" }],
};

test("the http source delegates to the existing transport functions, unmoved", () => {
  assert.equal(httpSetupProgressSource.start, startWorkspaceSetup);
  assert.equal(httpSetupProgressSource.read, readSetupStatus);
});

test("the http source's start posts to the setup endpoint and surfaces its refusals", async () => {
  const ok = stubFetch(new Response(null, { status: 202 }));
  try {
    await httpSetupProgressSource.start();
    assert.equal(ok.calls.length, 1);
    assert.equal(ok.calls[0]?.url, "/api/clue/stage0/setup");
    assert.equal(ok.calls[0]?.method, "POST");
  } finally {
    ok.restore();
  }

  const refused = stubFetch(
    jsonResponse({ detail: { error: "setup_unavailable", reason: "no record" } }, 409),
  );
  try {
    await assert.rejects(
      httpSetupProgressSource.start(),
      (error: unknown) => error instanceof SetupApiError && error.status === 409,
    );
  } finally {
    refused.restore();
  }
});

test("the http source's read parses the status endpoint through the schema", async () => {
  const stub = stubFetch(
    jsonResponse({
      status: "running",
      fast_status: "running",
      fields: [{ field_key: "client.value_prop", lane: "fast", status: "started" }],
    }),
  );
  try {
    const status = await httpSetupProgressSource.read();
    assert.equal(stub.calls[0]?.url, "/api/clue/stage0/setup/current");
    assert.equal(status.status, "running");
    assert.equal(status.fields[0]?.field_key, "client.value_prop");
    // Schema defaults applied — the fixture path and the http path return the same shape.
    assert.equal(status.background_budget_exhausted, null);
  } finally {
    stub.restore();
  }
});

test("the fixture source replays its script frame per read and sticks at the last frame", async () => {
  const script: SetupStatus[] = [
    SetupStatusSchema.parse({ status: "starting" }),
    SetupStatusSchema.parse({ status: "running", fast_status: "running" }),
    SetupStatusSchema.parse({ status: "complete", fast_status: "completed" }),
  ];
  const source = createFixtureSetupProgressSource(script);

  assert.equal((await source.read()).status, "starting");
  assert.equal((await source.read()).status, "running");
  assert.equal((await source.read()).status, "complete");
  // Sticks: the stream has no further state, and time alone never invents one.
  assert.equal((await source.read()).status, "complete");
  assert.equal((await source.read()).status, "complete");
});

test("the fixture source's start is not a read: it consumes no frame", async () => {
  const source = createFixtureSetupProgressSource([
    SetupStatusSchema.parse({ status: "starting" }),
    SetupStatusSchema.parse({ status: "running" }),
  ]);
  await source.start();
  await source.start();
  assert.equal((await source.read()).status, "starting");
});

test("the fixture source validates every frame through the same schema the http path uses", async () => {
  const wireFrame = {
    status: "some-future-status",
    fields: [{ field_key: "client.product", lane: "fast", status: "who-knows" }],
  } as unknown as SetupStatus;
  const source = createFixtureSetupProgressSource([wireFrame]);
  const frame = await source.read();
  // Exactly the http path's degradations (review FE-N2), because it is the same parse.
  assert.equal(frame.status, "unavailable");
  assert.equal(frame.fields[0]?.status, "started");
  assert.equal(frame.recon_run_id, null);
});

test("an empty fixture script fails loudly rather than serving nothing", () => {
  assert.throws(() => createFixtureSetupProgressSource([]), /at least one frame/);
});

test("every default-script frame parses through SetupStatusSchema unchanged", () => {
  assert.ok(FIXTURE_SETUP_PROGRESS_SCRIPT.length > 1);
  for (const frame of FIXTURE_SETUP_PROGRESS_SCRIPT) {
    const parsed = SetupStatusSchema.parse(frame);
    // Wire-shaped: parsing is a no-op, so the fixture cannot drift from the wire contract.
    assert.deepEqual(parsed, frame);
  }
});

test("the default script opens on starting with no field events yet", () => {
  const first = FIXTURE_SETUP_PROGRESS_SCRIPT[0];
  assert.equal(first?.status, "starting");
  assert.deepEqual(first?.fields, []);
  assert.equal(first?.recon_run_id, null);
});

test("the default script's final frame is complete with all eleven field terminals", () => {
  const last = FIXTURE_SETUP_PROGRESS_SCRIPT[FIXTURE_SETUP_PROGRESS_SCRIPT.length - 1];
  assert.equal(last?.status, "complete");
  assert.equal(last?.fast_status, "completed");
  assert.notEqual(last?.fact_count, null);
  assert.equal(last?.fields.length, 11);
  assert.equal(FIXTURE_SETUP_BASELINE_FIELDS.length, 11);
  assert.deepEqual(
    last?.fields.map((field) => field.field_key),
    [...FIXTURE_SETUP_BASELINE_FIELDS],
  );
  for (const field of last?.fields ?? []) {
    assert.notEqual(field.status, "started");
  }
  // The two tier-3-only fields are re-derived by the background lane (the fast lane's
  // max_source_tier=2 walk left them empty at zero spend).
  const background = (last?.fields ?? []).filter((field) => field.lane === "background");
  assert.deepEqual(
    background.map((field) => field.field_key),
    ["client.competitor", "client.buyer_profile"],
  );
  assert.ok(background.every((field) => field.status === "empty"));
});

test("the default script covers every checklist group's fields exactly once", () => {
  const grouped = SETUP_GROUPS.flatMap((group) => group.fieldKeys);
  assert.deepEqual([...grouped].sort(), [...FIXTURE_SETUP_BASELINE_FIELDS].sort());
});

test("the default script moves: each frame differs from the one before it", () => {
  for (let index = 1; index < FIXTURE_SETUP_PROGRESS_SCRIPT.length; index += 1) {
    assert.notDeepEqual(
      FIXTURE_SETUP_PROGRESS_SCRIPT[index],
      FIXTURE_SETUP_PROGRESS_SCRIPT[index - 1],
      `frame ${index} repeats its predecessor — the poll tick would render no motion`,
    );
  }
});

test("the default script announces a field start before its terminal, in baseline order", () => {
  const started: string[] = [];
  const terminated = new Set<string>();
  for (const frame of FIXTURE_SETUP_PROGRESS_SCRIPT) {
    for (const field of frame.fields) {
      if (field.status === "started" && !started.includes(field.field_key)) {
        assert.ok(
          !terminated.has(field.field_key) || field.lane === "background",
          `${field.field_key} restarted in its own lane`,
        );
        started.push(field.field_key);
      }
      if (field.status !== "started") terminated.add(field.field_key);
    }
    // The backend serves the reduced field list in baseline order; a frame must not pretend
    // otherwise (the client never re-sorts).
    const keys = frame.fields.map((field) => field.field_key);
    assert.deepEqual(
      keys,
      FIXTURE_SETUP_BASELINE_FIELDS.filter((key) => keys.includes(key)),
    );
  }
  assert.deepEqual(started, [...FIXTURE_SETUP_BASELINE_FIELDS]);
});

test("the derived checklist advances monotonically across the whole default script", async () => {
  const source = createFixtureSetupProgressSource();
  const seen: Record<string, number> = {};
  let sawRunning = false;
  for (let index = 0; index < FIXTURE_SETUP_PROGRESS_SCRIPT.length; index += 1) {
    const items = deriveSetupItems(FIXTURE_SETUP, await source.read());
    assert.equal(items.length, SETUP_GROUPS.length);
    for (const item of items) {
      const rank = STATUS_RANK[item.status];
      if (item.status === "running") sawRunning = true;
      assert.ok(
        rank >= (seen[item.id] ?? 0),
        `${item.id} regressed to ${item.status} at frame ${index}`,
      );
      seen[item.id] = rank;
    }
  }
  assert.ok(sawRunning, "the script never rendered a running row");
  assert.ok(
    SETUP_GROUPS.every((group) => seen[group.id] === STATUS_RANK.complete),
    "the script ended with an unfinished checklist row",
  );
});
