import assert from "node:assert/strict";
import test from "node:test";
import type { IngestionJob } from "../model/brand-kit-actions";
import {
  createBrandKitActions,
  httpBrandKitActionsSource,
  type BrandKitActionsSource,
} from "./brand-kit-actions";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolveFn, rejectFn) => {
    resolve = resolveFn;
    reject = rejectFn;
  });
  return { promise, reject, resolve };
}

function recordingSource(overrides: Partial<BrandKitActionsSource> = {}) {
  const calls: string[] = [];
  const source: BrandKitActionsSource = {
    async enqueueWebsiteIngestion(request) {
      calls.push(`ingest:${JSON.stringify(request)}`);
    },
    async listIngestionJobs() {
      calls.push("list");
      return [];
    },
    ...overrides,
  };
  return { calls, source };
}

// --- the in-flight guard -----------------------------------------------------------



test("a second re-extract while the first is in flight fires no second request", async () => {
  const gate = deferred<void>();
  const { calls, source } = recordingSource({
    async enqueueWebsiteIngestion(request) {
      calls.push(`ingest:${JSON.stringify(request)}`);
      await gate.promise;
    },
  });
  const actions = createBrandKitActions(source);

  const first = actions.reExtract({ brand_kit_id: "kit_1", url: "https://stripe.com" });
  const second = actions.reExtract({ brand_kit_id: "kit_1", url: "https://stripe.com" });
  assert.equal(calls.length, 1);

  gate.resolve();
  await Promise.all([first, second]);
  assert.deepEqual(calls, ['ingest:{"brand_kit_id":"kit_1","url":"https://stripe.com"}']);
});

test("a failed action releases its guard so the client can retry", async () => {
  let attempts = 0;
  const { source } = recordingSource({
    async enqueueWebsiteIngestion() {
      attempts += 1;
      throw new Error("design API refused");
    },
  });
  const actions = createBrandKitActions(source);

  await assert.rejects(actions.reExtract({url: "https://stripe.com"}));
  await assert.rejects(actions.reExtract({url: "https://stripe.com"}));
  assert.equal(attempts, 2);
});



// --- the BFF transport -------------------------------------------------------------

function stubFetch(
  handler: (url: string, init?: RequestInit) => Response,
): { calls: { init?: RequestInit; url: string }[]; restore(): void } {
  const calls: { init?: RequestInit; url: string }[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ init, url });
    return handler(url, init);
  }) as typeof fetch;
  return { calls, restore: () => (globalThis.fetch = original) };
}



test("re-extract posts the ingestion request to the BFF", async () => {
  const stub = stubFetch(() => new Response(JSON.stringify({ job: {} }), { status: 200 }));
  try {
    await httpBrandKitActionsSource.enqueueWebsiteIngestion({
      brand_kit_id: "brand_kit_ing_1",
      url: "https://stripe.com",
    });
  } finally {
    stub.restore();
  }

  assert.equal(stub.calls[0].url, "/api/clue/design/brand-kits/ingest/website");
  assert.equal(stub.calls[0].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(stub.calls[0].init?.body)), {
    brand_kit_id: "brand_kit_ing_1",
    url: "https://stripe.com",
  });
});

test("a refused mutation raises rather than pretending it landed", async () => {
  const stub = stubFetch(() => new Response("nope", { status: 503 }));
  try {
    await assert.rejects(httpBrandKitActionsSource.enqueueWebsiteIngestion({url: "https://stripe.com"}));
  } finally {
    stub.restore();
  }
});

test("the job list is read through the BFF and parsed", async () => {
  const stub = stubFetch(
    () =>
      new Response(
        JSON.stringify({
          jobs: [
            {
              brand_kit_id: null,
              job_id: "ingest_2",
              kind: "website",
              status: "running",
              website_url: "https://stripe.com",
            },
            { job_id: "ingest_1", kind: "pdf", status: "succeeded", website_url: null },
          ],
          schema_version: 1,
        }),
        { status: 200 },
      ),
  );
  let jobs: IngestionJob[] | null;
  try {
    jobs = await httpBrandKitActionsSource.listIngestionJobs();
  } finally {
    stub.restore();
  }

  assert.equal(stub.calls[0].url, "/api/clue/design/brand-kits/ingest");
  assert.ok(jobs);
  assert.deepEqual(jobs.map((entry) => entry.job_id), ["ingest_2", "ingest_1"]);
  assert.equal(jobs[0].website_url, "https://stripe.com");
});

test("an unreadable job list is unknown state, never permission to duplicate a run", async () => {
  const stub = stubFetch(() => new Response("gateway down", { status: 502 }));
  try {
    assert.equal(await httpBrandKitActionsSource.listIngestionJobs(), null);
  } finally {
    stub.restore();
  }
});
