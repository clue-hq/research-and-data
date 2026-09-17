import type {
  InvitationSignUpInput,
  OnboardingAuthResult,
} from "../model/onboarding";

export const CLERK_CALL_TIMEOUT_MS = 15_000;

type ClerkErrorLike = {
  message: string;
  longMessage?: string | undefined;
};

type ClerkCallResult = { error: ClerkErrorLike | null };

export interface ClerkSignInDriver {
  readonly status: string | null;
  readonly identifier: string | null;
  readonly supportedSecondFactors: readonly { strategy: string }[];
  password(params: {
    identifier: string;
    password: string;
  }): Promise<ClerkCallResult>;
  finalize(): Promise<ClerkCallResult>;
  mfa: {
    sendEmailCode(): Promise<ClerkCallResult>;
    verifyEmailCode(params: { code: string }): Promise<ClerkCallResult>;
  };
}

export interface ClerkSignUpDriver {
  readonly status: string | null;
  readonly emailAddress: string | null;
  password(params: {
    emailAddress: string;
    password: string;
  }): Promise<ClerkCallResult>;
  finalize(): Promise<ClerkCallResult>;
  verifications: {
    sendEmailCode(): Promise<ClerkCallResult>;
    verifyEmailCode(params: { code: string }): Promise<ClerkCallResult>;
  };
}

export interface ClerkTicketDriver {
  readonly status: string | null;
  readonly missingFields: readonly string[];
  readonly unverifiedFields: readonly string[];
  create(params: InvitationSignUpInput & {
    strategy: "ticket";
  }): Promise<ClerkCallResult>;
  finalize(): Promise<ClerkCallResult>;
}

export async function acceptInvitationTicket(
  signUp: ClerkTicketDriver,
  params: InvitationSignUpInput,
  timeoutMs = CLERK_CALL_TIMEOUT_MS,
): Promise<OnboardingAuthResult> {
  if (signUp.status === "complete") return finalize(signUp, "sign-up");
  if (!params.password) {
    return {
      status: "error",
      message: "Set a password to finish creating your account.",
    };
  }
  // Clerk v7's ticket() helper does not accept a password. The underlying create()
  // ticket strategy accepts all required fields together and verifies the invited email.
  const attempted = await runClerkStep(
    () => signUp.create({ ...params, strategy: "ticket" }),
    timeoutMs,
  );
  if (!attempted.ok) return attempted.result;
  if (signUp.status === "complete") return finalize(signUp, "sign-up");
  if (signUp.missingFields.includes("password")) {
    return {
      status: "error",
      message: "Set a password to finish creating your account.",
    };
  }
  if (signUp.missingFields.length || signUp.unverifiedFields.length) {
    return {
      status: "error",
      message:
        "Your account has additional sign-up requirements that this invitation form does not support. Contact your workspace administrator.",
    };
  }
  return {
    status: "error",
    message:
      "Your account sign-up did not complete. Reopen the invitation from your email and try again.",
  };
}

type ClerkStepResult =
  | { ok: true }
  | { ok: false; result: OnboardingAuthResult };

const TIMEOUT_RESULT: OnboardingAuthResult = {
  status: "error",
  message:
    "The authentication service didn't respond. Check your connection and try again.",
};

const UNEXPECTED_RESULT: OnboardingAuthResult = {
  status: "error",
  message: "We couldn't complete authentication. Please try again.",
};

const INCOMPLETE_RESULT: OnboardingAuthResult = {
  status: "error",
  message: "Your sign-in needs another verification step. Please try again.",
};

const UNSUPPORTED_FACTOR_RESULT: OnboardingAuthResult = {
  status: "error",
  message:
    "This account requires a verification method that isn't available on this screen. Use another sign-in method or contact support.",
};

function errorResult(error: ClerkErrorLike): OnboardingAuthResult {
  return { status: "error", message: error.longMessage ?? error.message };
}

function thrownErrorResult(error: unknown): OnboardingAuthResult {
  if (error && typeof error === "object") {
    const candidate = error as { message?: unknown; longMessage?: unknown };
    if (typeof candidate.longMessage === "string" && candidate.longMessage) {
      return { status: "error", message: candidate.longMessage };
    }
    if (typeof candidate.message === "string" && candidate.message) {
      return { status: "error", message: candidate.message };
    }
  }
  return UNEXPECTED_RESULT;
}

/**
 * Bound one Clerk driver call without chaining session-changing work behind the timeout.
 *
 * Clerk's operations are not abortable. If a timed-out call eventually resolves it may update
 * Clerk's in-memory attempt, but no caller continuation runs and, critically, no late
 * `finalize()` activates a session behind an error screen.
 */
export async function runClerkStep(
  action: () => Promise<ClerkCallResult>,
  timeoutMs: number | null = CLERK_CALL_TIMEOUT_MS,
): Promise<ClerkStepResult> {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    const call = action();
    const settled =
      timeoutMs === null
        ? await call
        : await Promise.race([
            call,
            new Promise<"timeout">((resolve) => {
              timeout = setTimeout(() => resolve("timeout"), timeoutMs);
            }),
          ]);
    if (settled === "timeout") return { ok: false, result: TIMEOUT_RESULT };
    if (settled.error) return { ok: false, result: errorResult(settled.error) };
    return { ok: true };
  } catch (error) {
    return { ok: false, result: thrownErrorResult(error) };
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}

function signInVerificationPurpose(
  status: string | null,
): "device-trust" | "second-factor" | null {
  if (status === "needs_client_trust") return "device-trust";
  if (status === "needs_second_factor") return "second-factor";
  return null;
}

function supportsEmailCode(signIn: ClerkSignInDriver): boolean {
  return signIn.supportedSecondFactors.some(
    (factor) => factor.strategy === "email_code",
  );
}

async function finalize(
  resource: { finalize(): Promise<ClerkCallResult> },
  flow: "sign-in" | "sign-up",
): Promise<OnboardingAuthResult> {
  // A successful preceding Clerk call proves clerk-js loaded. Do not put an unabortable session
  // activation behind the CDN-load timeout; catch and surface its own failure instead.
  const finalized = await runClerkStep(() => resource.finalize(), null);
  return finalized.ok ? { status: "complete", flow } : finalized.result;
}

export async function startPasswordSignIn(
  signIn: ClerkSignInDriver,
  identifier: string,
  password: string,
  timeoutMs = CLERK_CALL_TIMEOUT_MS,
): Promise<OnboardingAuthResult> {
  const attempted = await runClerkStep(
    () => signIn.password({ identifier, password }),
    timeoutMs,
  );
  if (!attempted.ok) return attempted.result;

  if (signIn.status === "complete") return finalize(signIn, "sign-in");

  const purpose = signInVerificationPurpose(signIn.status);
  if (purpose) {
    if (!supportsEmailCode(signIn)) return UNSUPPORTED_FACTOR_RESULT;
    const sent = await runClerkStep(
      () => signIn.mfa.sendEmailCode(),
      timeoutMs,
    );
    if (!sent.ok) return sent.result;
    return { status: "needs-verification", purpose };
  }

  return INCOMPLETE_RESULT;
}

export async function startPasswordSignUp(
  signUp: ClerkSignUpDriver,
  emailAddress: string,
  password: string,
  timeoutMs = CLERK_CALL_TIMEOUT_MS,
): Promise<OnboardingAuthResult> {
  const attempted = await runClerkStep(
    () => signUp.password({ emailAddress, password }),
    timeoutMs,
  );
  if (!attempted.ok) return attempted.result;
  if (signUp.status === "complete") return finalize(signUp, "sign-up");

  const sent = await runClerkStep(
    () => signUp.verifications.sendEmailCode(),
    timeoutMs,
  );
  if (!sent.ok) return sent.result;
  return { status: "needs-verification", purpose: "sign-up" };
}

export async function verifyPendingEmailCode(
  signIn: ClerkSignInDriver,
  signUp: ClerkSignUpDriver,
  code: string,
  timeoutMs = CLERK_CALL_TIMEOUT_MS,
): Promise<OnboardingAuthResult> {
  const signInPurpose = signInVerificationPurpose(signIn.status);
  if (signInPurpose) {
    const verified = await runClerkStep(
      () => signIn.mfa.verifyEmailCode({ code }),
      timeoutMs,
    );
    if (!verified.ok) return verified.result;
    return signIn.status === "complete"
      ? finalize(signIn, "sign-in")
      : INCOMPLETE_RESULT;
  }
  if (signIn.status === "complete") return finalize(signIn, "sign-in");

  if (!signUp.status) {
    return {
      status: "error",
      message:
        "We couldn't find a verification in progress. Please start again from the sign-up or sign-in screen.",
    };
  }
  if (signUp.status === "complete") return finalize(signUp, "sign-up");

  const verified = await runClerkStep(
    () => signUp.verifications.verifyEmailCode({ code }),
    timeoutMs,
  );
  if (!verified.ok) return verified.result;
  return signUp.status === "complete"
    ? finalize(signUp, "sign-up")
    : INCOMPLETE_RESULT;
}

export async function resendPendingEmailCode(
  signIn: ClerkSignInDriver,
  signUp: ClerkSignUpDriver,
  timeoutMs = CLERK_CALL_TIMEOUT_MS,
): Promise<OnboardingAuthResult> {
  const signInPurpose = signInVerificationPurpose(signIn.status);
  if (signInPurpose) {
    if (!supportsEmailCode(signIn)) return UNSUPPORTED_FACTOR_RESULT;
    const sent = await runClerkStep(
      () => signIn.mfa.sendEmailCode(),
      timeoutMs,
    );
    return sent.ok
      ? { status: "needs-verification", purpose: signInPurpose }
      : sent.result;
  }

  if (!signUp.status || signUp.status === "complete") {
    return {
      status: "error",
      message:
        "We couldn't find a verification in progress. Please start again from the sign-up or sign-in screen.",
    };
  }
  const sent = await runClerkStep(
    () => signUp.verifications.sendEmailCode(),
    timeoutMs,
  );
  return sent.ok
    ? { status: "needs-verification", purpose: "sign-up" }
    : sent.result;
}

export function pendingVerificationEmail(
  signIn: Pick<ClerkSignInDriver, "status" | "identifier">,
  signUp: Pick<ClerkSignUpDriver, "emailAddress">,
): string | null {
  return signInVerificationPurpose(signIn.status)
    ? signIn.identifier
    : signUp.emailAddress;
}
