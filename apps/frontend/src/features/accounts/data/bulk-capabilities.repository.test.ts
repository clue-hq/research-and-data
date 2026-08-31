import assert from "node:assert/strict";
import test from "node:test";
import { z } from "zod";
import {
  DISABLED_ACCOUNT_BULK_CAPABILITIES,
  DISABLED_CONTACT_BULK_CAPABILITIES,
  readAccountBulkCapabilities,
  readContactBulkCapabilities,
} from "./bulk-capabilities.repository";
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

test("invalid Contact capability payloads fail closed", async () => {
  const schemaError = (() => {
    try {
      z.object({ allowed: z.boolean() }).parse({ allowed: "yes" });
    } catch (error) {
      return error;
    }
    throw new Error("schema fixture should fail");
  })();

  const result = await readContactBulkCapabilities("account-1", async () => {
    throw schemaError;
  });

  assert.deepEqual(result, DISABLED_CONTACT_BULK_CAPABILITIES);
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
