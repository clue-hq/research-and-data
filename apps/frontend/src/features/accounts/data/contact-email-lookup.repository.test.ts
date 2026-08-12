import assert from "node:assert/strict";
import test from "node:test";
import { ClueApiError } from "./clue-api-error";
import {
  pollContactEmailLookup,
  startContactEmailLookup,
} from "./contact-email-lookup.repository";

const available = {
  lookupId: "lookup-1",
  state: "available",
  resolution: "single_source",
  emails: [
    {
      value: "dana@example.com",
      sources: [{ key: "exa_websets", label: "Exa" }],
    },
  ],
  retryable: false,
};

test("contact email mutations use the same-origin BFF and encode every identifier", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ input: string; init: RequestInit | undefined }> = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return Response.json(available);
  };
  try {
    const started = await startContactEmailLookup("account/1", "contact/1");
    const polled = await pollContactEmailLookup(
      "account/1",
      "contact/1",
      "lookup/1",
    );

    assert.equal(started.emails[0]?.value, "dana@example.com");
    assert.deepEqual(polled, started);
    assert.deepEqual(
      calls.map((call) => call.input),
      [
        "/api/clue/frontend/v1/accounts/account%2F1/contacts/contact%2F1/email-lookup",
        "/api/clue/frontend/v1/accounts/account%2F1/contacts/contact%2F1/email-lookup/lookup%2F1/poll",
      ],
    );
    assert.ok(calls.every((call) => call.init?.method === "POST"));
    assert.ok(
      calls.every(
        (call) => new Headers(call.init?.headers).get("content-type") === "application/json",
      ),
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("contact email mutations retain typed backend failure metadata", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    Response.json(
      {
        error: {
          code: "EMAIL_LOOKUP_UNAVAILABLE",
          message: "Email enrichment is not configured",
          requestId: "request-10",
        },
      },
      { status: 503 },
    );
  try {
    await assert.rejects(
      startContactEmailLookup("account-1", "contact-1"),
      (error: unknown) =>
        error instanceof ClueApiError &&
        error.status === 503 &&
        error.code === "EMAIL_LOOKUP_UNAVAILABLE" &&
        error.requestId === "request-10",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
