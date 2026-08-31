export class ClueApiError extends Error {
  /** Open backend code set: branch on known codes and retain the fallback. */
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;

  constructor(
    message: string,
    options: { code: string; requestId: string | null; status: number },
  ) {
    super(message);
    this.name = "ClueApiError";
    this.code = options.code;
    this.status = options.status;
    this.requestId = options.requestId;
  }
}
