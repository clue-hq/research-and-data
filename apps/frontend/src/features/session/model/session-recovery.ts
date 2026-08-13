import { z } from "zod";
import { ClueConfigurationError } from "@/auth/config";
import { ClueAuthenticationError } from "@/auth/errors";

export type ProtectedSessionRecovery = Readonly<{
  kind: "service_unavailable" | "contract_error";
  requestId: string | null;
  retryable: boolean;
}>;

export type ProtectedSessionResult<Session> =
  | Readonly<{ status: "ready"; session: Session }>
  | Readonly<{
      status: "recovery";
      recovery: ProtectedSessionRecovery;
    }>;

export function protectedSessionRecoveryFor(
  error: unknown,
): ProtectedSessionRecovery | null {
  if (error instanceof ClueAuthenticationError) {
    const unavailable =
      error.code === "AUTHENTICATION_UNAVAILABLE" ||
      error.status === 408 ||
      error.status === 429 ||
      error.status >= 500;
    return {
      kind: unavailable ? "service_unavailable" : "contract_error",
      requestId: error.requestId,
      retryable: unavailable,
    };
  }
  if (
    error instanceof ClueConfigurationError ||
    error instanceof z.ZodError ||
    error instanceof SyntaxError
  ) {
    return { kind: "contract_error", requestId: null, retryable: false };
  }
  if (error instanceof TypeError) {
    return { kind: "service_unavailable", requestId: null, retryable: true };
  }
  return null;
}
