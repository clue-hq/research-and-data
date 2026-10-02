import assert from "node:assert/strict";
import test from "node:test";
import {
  DISABLED_ACCOUNT_BULK_CAPABILITIES,
  readAccountBulkCapabilities,
} from "./bulk-capabilities.repository";
import { z } from "zod";
import { ClueApiError } from "./frontend-api";

test("expected Account capability failures hide optional bulk controls", async () => {
  const result = await readAccountBulkCapabilities(async () => {
    throw new ClueApiError("private upstream message", {
      code: "SERVICE_UNAVAILABLE",
      requestId: "request-capability",
      status: 503,
    });
  });

  assert.deepEqual(result, DISABLED_ACCOUNT_BULK_CAPABILITIES);
});

test("an invalid capability payload fails closed", async () => {
  const schemaError = (() => {
    try {
      z.object({ allowed: z.boolean() }).parse({ allowed: "yes" });
    } catch (error) {
      return error;
    }
    throw new Error("schema fixture should fail");
  })();

  const result = await readAccountBulkCapabilities(async () => {
    throw schemaError;
  });

  assert.deepEqual(result, DISABLED_ACCOUNT_BULK_CAPABILITIES);
});

test("unexpected capability programming errors remain observable", async () => {
  const bug = new RangeError("unexpected implementation bug");

  await assert.rejects(
    readAccountBulkCapabilities(async () => {
      throw bug;
    }),
    (error: unknown) => error === bug,
  );
});

test("fixture mode closes the bulk actions without asking a backend", async () => {
  process.env.CLUE_ACCOUNTS_FIXTURE_MODE = "true";
  try {
    const result = await readAccountBulkCapabilities(async () => {
      throw new Error("fixture mode must not read the backend");
    });
    assert.deepEqual(result, DISABLED_ACCOUNT_BULK_CAPABILITIES);
  } finally {
    delete process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
  }
});
