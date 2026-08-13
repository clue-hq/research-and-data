import { z } from "zod";
import { ClueConfigurationError } from "@/auth/config";
import { ClueAuthenticationError } from "@/auth/errors";
import type { AccountsResponse } from "../model/account";
import type {
  AccountRecovery,
  AccountRecoveryKind,
} from "../model/account-recovery";
import {
  getAccounts,
  type AccountsQuery,
} from "./accounts.repository";
import { ClueApiError } from "./frontend-api";

const SESSION_CODES = new Set([
  "AUTHENTICATION_REQUIRED",
  "SESSION_INVALID",
  "UNAUTHORIZED",
]);

const WORKSPACE_SELECTION_CODES = new Set([
  "WORKSPACE_SELECTION_REQUIRED",
]);

const FORBIDDEN_CODES = new Set([
  "IDENTITY_NOT_PROVISIONED",
  "MEMBERSHIP_STATE_CHANGED",
  "PERMISSION_DENIED",
  "USER_DISABLED",
  "WORKSPACE_FORBIDDEN",
]);

const UNAVAILABLE_CODES = new Set([
  "AUTHENTICATION_UNAVAILABLE",
  "RATE_LIMITED",
  "SERVICE_UNAVAILABLE",
]);

function recovery(
  kind: AccountRecoveryKind,
  requestId: string | null = null,
): AccountRecovery {
  return {
    kind,
    requestId,
    retryable: kind === "service_unavailable",
  };
}

function isLegacyWorkspaceSelectionFailure(error: Error & { code: string }) {
  // Lane B's current auth vocabulary overloads WORKSPACE_FORBIDDEN for a
  // missing selector. Keep this exact compatibility rule here, never in UI
  // copy, until the backend emits WORKSPACE_SELECTION_REQUIRED itself.
  return (
    error.code === "WORKSPACE_FORBIDDEN" &&
    error.message.trim().toLocaleLowerCase() ===
      "a workspace selection is required"
  );
}

function recoveryForTransportError(
  error: ClueApiError | ClueAuthenticationError,
): AccountRecovery {
  if (SESSION_CODES.has(error.code) || error.status === 401) {
    return recovery("session_expired", error.requestId);
  }
  if (
    WORKSPACE_SELECTION_CODES.has(error.code) ||
    isLegacyWorkspaceSelectionFailure(error)
  ) {
    return recovery("workspace_selection", error.requestId);
  }
  if (FORBIDDEN_CODES.has(error.code) || error.status === 403) {
    return recovery("forbidden", error.requestId);
  }
  if (
    UNAVAILABLE_CODES.has(error.code) ||
    error.status === 408 ||
    error.status === 429 ||
    error.status >= 500
  ) {
    return recovery("service_unavailable", error.requestId);
  }
  return recovery("contract_error", error.requestId);
}

/**
 * Convert a normal Account read failure into a closed, safe page state.
 *
 * Returning `null` is deliberate: an unexpected programming exception stays
 * exceptional and reaches observability instead of being mislabeled as an
 * outage. No returned value contains the original exception message.
 */
export function accountRecoveryFor(
  error: unknown,
): AccountRecovery | null {
  if (
    error instanceof ClueApiError ||
    error instanceof ClueAuthenticationError
  ) {
    return recoveryForTransportError(error);
  }
  if (
    error instanceof ClueConfigurationError ||
    error instanceof z.ZodError ||
    error instanceof SyntaxError
  ) {
    return recovery("contract_error");
  }
  if (error instanceof TypeError) {
    // Node's fetch rejects network failures as TypeError. This catch is scoped
    // to the repository call by the caller; unrelated TypeErrors still throw.
    return recovery("service_unavailable");
  }
  return null;
}

export type AccountsReadResult =
  | Readonly<{ status: "ready"; response: AccountsResponse }>
  | Readonly<{ status: "recovery"; recovery: AccountRecovery }>;

/** Expected failures are data; unexpected programming errors remain errors. */
export async function readAccountsResult(
  query?: AccountsQuery,
  read: (query?: AccountsQuery) => Promise<AccountsResponse> = getAccounts,
): Promise<AccountsReadResult> {
  try {
    return { status: "ready", response: await read(query) };
  } catch (error) {
    const recovery = accountRecoveryFor(error);
    if (recovery) return { status: "recovery", recovery };
    throw error;
  }
}
