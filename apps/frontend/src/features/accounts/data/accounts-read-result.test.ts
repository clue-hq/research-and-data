import assert from "node:assert/strict";
import test from "node:test";
import { ClueConfigurationError } from "@/auth/config";
import { ClueAuthenticationError } from "@/auth/errors";
import type { AccountsResponse } from "../model/account";
import { AccountsResponseSchema } from "../model/account";
import { ClueApiError } from "./frontend-api";
import {
  accountRecoveryFor,
  readAccountsResult,
} from "./accounts-read-result";

const EMPTY_RESPONSE: AccountsResponse = {
  data: [],
  meta: {
    nextCursor: null,
    total: 0,
  },
};

test("an honest empty Account response remains a ready result", async () => {
  const result = await readAccountsResult(undefined, async () => EMPTY_RESPONSE);

  assert.deepEqual(result, { status: "ready", response: EMPTY_RESPONSE });
});

test("expected Account failures map to the five closed recovery kinds", () => {
  const cases = [
    {
      error: new ClueAuthenticationError("provider token expired", {
        code: "SESSION_INVALID",
        requestId: "req-session",
        status: 401,
      }),
      kind: "session_expired",
      requestId: "req-session",
      retryable: false,
    },
    {
      error: new ClueAuthenticationError("explicit selection required", {
        code: "WORKSPACE_SELECTION_REQUIRED",
        requestId: "req-select-typed",
        status: 403,
      }),
      kind: "workspace_selection",
      requestId: "req-select-typed",
      retryable: false,
    },
    {
      error: new ClueApiError("a workspace selection is required", {
        code: "WORKSPACE_FORBIDDEN",
        requestId: "req-select",
        status: 403,
      }),
      kind: "workspace_selection",
      requestId: "req-select",
      retryable: false,
    },
    {
      error: new ClueApiError("membership does not authorize this workspace", {
        code: "WORKSPACE_FORBIDDEN",
        requestId: "req-forbidden",
        status: 403,
      }),
      kind: "forbidden",
      requestId: "req-forbidden",
      retryable: false,
    },
    {
      error: new ClueApiError("upstream unavailable", {
        code: "AUTHENTICATION_UNAVAILABLE",
        requestId: "req-unavailable",
        status: 503,
      }),
      kind: "service_unavailable",
      requestId: "req-unavailable",
      retryable: true,
    },
    {
      error: new ClueApiError("wrong mount", {
        code: "NOT_FOUND",
        requestId: "req-contract",
        status: 404,
      }),
      kind: "contract_error",
      requestId: "req-contract",
      retryable: false,
    },
  ] as const;

  for (const expected of cases) {
    assert.deepEqual(accountRecoveryFor(expected.error), {
      kind: expected.kind,
      requestId: expected.requestId,
      retryable: expected.retryable,
    });
  }
});

test("network, schema, JSON, and deployment failures remain distinct", () => {
  const schemaFailure = (() => {
    try {
      AccountsResponseSchema.parse({ data: "not-an-array", meta: {} });
    } catch (error) {
      return error;
    }
    throw new Error("schema fixture should fail");
  })();

  assert.deepEqual(accountRecoveryFor(new TypeError("fetch failed: ECONNREFUSED")), {
    kind: "service_unavailable",
    requestId: null,
    retryable: true,
  });
  for (const error of [
    schemaFailure,
    new SyntaxError("Unexpected token < in JSON"),
    new ClueConfigurationError("secret deployment detail"),
  ]) {
    assert.deepEqual(accountRecoveryFor(error), {
      kind: "contract_error",
      requestId: null,
      retryable: false,
    });
  }
});

test("typed results discard internal messages before reaching the page", async () => {
  const marker = "INTERNAL stack /srv/private/module.ts:42";
  const result = await readAccountsResult(undefined, async () => {
    throw new ClueApiError(marker, {
      code: "NOT_FOUND",
      requestId: "req-safe-reference",
      status: 404,
    });
  });

  assert.equal(JSON.stringify(result).includes(marker), false);
  assert.deepEqual(result, {
    status: "recovery",
    recovery: {
      kind: "contract_error",
      requestId: "req-safe-reference",
      retryable: false,
    },
  });
});

test("unexpected programming errors are rethrown", async () => {
  const bug = new RangeError("unexpected implementation bug");

  await assert.rejects(
    readAccountsResult(undefined, async () => {
      throw bug;
    }),
    (error: unknown) => error === bug,
  );
});
