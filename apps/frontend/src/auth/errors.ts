/** Stable frontend representation of an authentication-service refusal. */
export class ClueAuthenticationError extends Error {
  readonly code: string;
  readonly requestId: string | null;
  readonly status: number;

  constructor(
    message: string,
    options: { code: string; requestId?: string | null; status: number },
  ) {
    super(message);
    this.name = "ClueAuthenticationError";
    this.code = options.code;
    this.requestId = options.requestId ?? null;
    this.status = options.status;
  }
}
