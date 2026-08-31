import assert from "node:assert/strict";
import test from "node:test";
import { ClueConfigurationError } from "@/auth/config";
import { ClueAuthenticationError } from "@/auth/errors";
import { protectedSessionRecoveryFor } from "./session-recovery";

test("a provider outage is the only retryable protected-session state", () => {
  assert.deepEqual(
    protectedSessionRecoveryFor(
      new ClueAuthenticationError("identity provider unavailable", {
        code: "AUTHENTICATION_UNAVAILABLE",
        requestId: "req-auth-outage",
        status: 503,
      }),
    ),
    {
      kind: "service_unavailable",
      requestId: "req-auth-outage",
      retryable: true,
    },
  );

  assert.deepEqual(
    protectedSessionRecoveryFor(
      new ClueAuthenticationError("unexpected auth contract", {
        code: "NOT_FOUND",
        requestId: "req-auth-contract",
        status: 404,
      }),
    ),
    {
      kind: "contract_error",
      requestId: "req-auth-contract",
      retryable: false,
    },
  );
});

test("configuration and unexpected programmer failures do not become retry loops", () => {
  assert.deepEqual(
    protectedSessionRecoveryFor(
      new ClueConfigurationError("private configuration detail"),
    ),
    { kind: "contract_error", requestId: null, retryable: false },
  );
  assert.equal(
    protectedSessionRecoveryFor(new RangeError("implementation bug")),
    null,
  );
});
