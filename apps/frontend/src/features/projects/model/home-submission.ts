import {
  ProjectBootstrapRequestSchema,
  type ProjectBootstrapRequest,
} from "./project-workspace";

export interface HomeSubmissionAttempt {
  draftRevision: number;
  fingerprint: string;
  idempotencyKey: string;
  sequence: number;
}

/** Validate locally before an idempotency identity or an HTTP request exists. */
export function parseHomeBootstrapDraft(input: {
  brandId: string;
  message: string;
}):
  | { success: true; request: ProjectBootstrapRequest; fingerprint: string }
  | { success: false; message: string } {
  const parsed = ProjectBootstrapRequestSchema.safeParse(input);
  if (parsed.success) {
    return {
      success: true,
      request: parsed.data,
      fingerprint: JSON.stringify(parsed.data),
    };
  }
  if (!input.brandId.trim()) {
    return { success: false, message: "Select a brand before starting a project." };
  }
  if (!input.message.trim()) {
    return { success: false, message: "Enter a message to start a project." };
  }
  if (input.message.length > 32_000) {
    return {
      success: false,
      message: "Keep the message at 32,000 characters or fewer.",
    };
  }
  return { success: false, message: "The project request is not valid." };
}

/**
 * Own the Home act's idempotency lifecycle independently from React.
 *
 * One exact draft may have only one request in flight. A failed unchanged
 * draft retains its key; any edit invalidates that retry identity. Different
 * drafts may proceed independently, and only the latest accepted act owns the
 * navigation so network completion order cannot send the user backwards.
 */
export class HomeSubmissionCoordinator {
  private draftRevision = 0;
  private sequence = 0;
  private latestSequence = 0;
  private readonly inFlight = new Map<string, HomeSubmissionAttempt>();
  private retry: Pick<HomeSubmissionAttempt, "fingerprint" | "idempotencyKey"> | null = null;

  draftChanged(): void {
    this.draftRevision += 1;
    this.retry = null;
  }

  begin(
    fingerprint: string,
    createIdempotencyKey: () => string,
  ): HomeSubmissionAttempt | null {
    if (this.inFlight.has(fingerprint)) return null;
    const idempotencyKey =
      this.retry?.fingerprint === fingerprint
        ? this.retry.idempotencyKey
        : createIdempotencyKey();
    this.retry = null;
    this.sequence += 1;
    this.latestSequence = this.sequence;
    const attempt = {
      draftRevision: this.draftRevision,
      fingerprint,
      idempotencyKey,
      sequence: this.sequence,
    };
    this.inFlight.set(fingerprint, attempt);
    return attempt;
  }

  failed(attempt: HomeSubmissionAttempt): { display: boolean } {
    this.finish(attempt);
    if (
      attempt.draftRevision === this.draftRevision &&
      attempt.sequence === this.latestSequence
    ) {
      this.retry = {
        fingerprint: attempt.fingerprint,
        idempotencyKey: attempt.idempotencyKey,
      };
    }
    return { display: attempt.sequence === this.latestSequence };
  }

  succeeded(attempt: HomeSubmissionAttempt): { navigate: boolean } {
    this.finish(attempt);
    if (this.retry?.fingerprint === attempt.fingerprint) this.retry = null;
    return { navigate: attempt.sequence === this.latestSequence };
  }

  isInFlight(fingerprint: string | null): boolean {
    return fingerprint !== null && this.inFlight.has(fingerprint);
  }

  private finish(attempt: HomeSubmissionAttempt): void {
    const current = this.inFlight.get(attempt.fingerprint);
    if (current?.sequence === attempt.sequence) {
      this.inFlight.delete(attempt.fingerprint);
    }
  }
}
