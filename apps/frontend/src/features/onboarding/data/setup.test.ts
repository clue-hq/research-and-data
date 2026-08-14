import assert from "node:assert/strict";
import test from "node:test";
import {
  SetupApiError,
  SetupStatusSchema,
  readSetupStatus,
  startWorkspaceSetup,
} from "./setup";
import { FIXTURE_OFFICIAL_SITE_PROGRESS } from "./setup-progress.fixture";

function stubFetch(response: Response): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = async () => response;
  return () => {
    globalThis.fetch = original;
  };
}

test("a minimal status payload parses with null defaults", () => {
  const parsed = SetupStatusSchema.parse({ status: "none" });
  assert.equal(parsed.recon_run_id, null);
  assert.equal(parsed.fast_status, null);
  assert.equal(parsed.fact_count, null);
});

test("a pre-slice-3 payload still parses: no fields, no fabricated budget verdict", () => {
  const parsed = SetupStatusSchema.parse({ status: "running", fast_status: "running" });
  assert.deepEqual(parsed.fields, []);
  // null = "we do not know yet" — never a fabricated false (backend BE contract).
  assert.equal(parsed.fast_budget_exhausted, null);
  assert.equal(parsed.background_budget_exhausted, null);
  assert.equal(parsed.official_site, null);
});

test("the C8 official-site fixture and live wire parse through the same additive schema", () => {
  const parsed = SetupStatusSchema.parse({
    status: "complete",
    future_top_level_field: true,
    official_site: {
      ...FIXTURE_OFFICIAL_SITE_PROGRESS,
      future_crawl_field: "ignored",
    },
  });
  assert.equal(parsed.official_site?.run_status, "background_active");
  assert.equal(parsed.official_site?.fetch_spend_unknown, 1);
  assert.equal(parsed.official_site?.partial, true);
  assert.equal(parsed.official_site?.last_event_seq, 42);
});

test("an unknown per-field status degrades to started rather than failing the parse", () => {
  const parsed = SetupStatusSchema.parse({
    status: "running",
    fields: [
      { field_key: "client.product", lane: "fast", status: "resolved" },
      { field_key: "client.value_prop", lane: "background", status: "some-future-status" },
    ],
  });
  assert.equal(parsed.fields.length, 2);
  assert.equal(parsed.fields[0]?.status, "resolved");
  // An additive backend status must never kill the poll loop (review FE-N2, per-field).
  assert.equal(parsed.fields[1]?.status, "started");
  assert.equal(parsed.fields[1]?.lane, "background");
});

test("additive fields are tolerated; an unknown status degrades loudly, not silently", () => {
  const parsed = SetupStatusSchema.parse({
    status: "some-future-status",
    fast_status: "completed",
    future_field: 1,
  });
  // The catch pins the decided behaviour (review FE-N2): unknown → surfaced terminal.
  assert.equal(parsed.status, "unavailable");
  assert.equal(parsed.fast_status, "completed");
});

test("start maps the backend 409 detail envelope onto a typed error", async () => {
  const restore = stubFetch(
    new Response(
      JSON.stringify({ detail: { error: "setup_unavailable", reason: "no record" } }),
      { status: 409, headers: { "content-type": "application/json" } },
    ),
  );
  try {
    await assert.rejects(
      startWorkspaceSetup(),
      (error: unknown) =>
        error instanceof SetupApiError &&
        error.status === 409 &&
        error.code === "setup_unavailable" &&
        error.message === "no record",
    );
  } finally {
    restore();
  }
});

test("status reads surface BFF auth envelopes with their code", async () => {
  const restore = stubFetch(
    new Response(
      JSON.stringify({
        error: { code: "AUTHENTICATION_REQUIRED", message: "Sign in to continue" },
      }),
      { status: 401, headers: { "content-type": "application/json" } },
    ),
  );
  try {
    await assert.rejects(
      readSetupStatus(),
      (error: unknown) =>
        error instanceof SetupApiError &&
        error.status === 401 &&
        error.code === "AUTHENTICATION_REQUIRED",
    );
  } finally {
    restore();
  }
});

test("a healthy status read parses end to end", async () => {
  const restore = stubFetch(
    new Response(
      JSON.stringify({
        status: "complete",
        recon_run_id: "run-1",
        fast_status: "completed",
        background_status: "running",
        fast_client_kb_version: 1,
        fact_count: 0,
        fields: [{ field_key: "client.product", lane: "fast", status: "resolved" }],
        fast_budget_exhausted: false,
        official_site: FIXTURE_OFFICIAL_SITE_PROGRESS,
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );
  try {
    const status = await readSetupStatus();
    assert.equal(status.status, "complete");
    assert.equal(status.fact_count, 0);
    assert.equal(status.fields[0]?.field_key, "client.product");
    assert.equal(status.fast_budget_exhausted, false);
    assert.equal(status.background_budget_exhausted, null);
    assert.equal(status.official_site?.states.includes("persisted"), true);
  } finally {
    restore();
  }
});
