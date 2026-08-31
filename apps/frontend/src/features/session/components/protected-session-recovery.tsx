"use client";

import type { ProtectedSessionRecovery } from "../model/session-recovery";

const actionClassName =
  "mt-5 inline-flex h-8 items-center justify-center rounded-lg bg-[var(--primary)] px-3 text-sm font-medium text-white outline-none hover:opacity-80 focus-visible:ring-3 focus-visible:ring-[var(--ring)]/50";

export function ProtectedSessionRecoveryScreen({
  recovery,
}: {
  recovery: ProtectedSessionRecovery;
}) {
  const unavailable = recovery.kind === "service_unavailable";

  return (
    <main className="grid min-h-screen place-items-center bg-[var(--clue-background-neutral)] p-6">
      <section
        aria-labelledby="protected-session-recovery-title"
        className="w-full max-w-lg rounded-xl border border-[var(--clue-border-neutral)] bg-[var(--clue-background-page)] p-6 shadow-[var(--clue-shadow-low)]"
      >
        <p className="text-sm font-medium text-[var(--clue-content-subtle)]">
          Clue
        </p>
        <h1
          className="mt-1 text-xl font-medium"
          id="protected-session-recovery-title"
        >
          {unavailable
            ? "Your workspace is temporarily unavailable"
            : "Your workspace needs support"}
        </h1>
        <p className="mt-2 text-[var(--clue-content-subtle)]">
          {unavailable
            ? "Clue could not verify your workspace session. No workspace data has been changed."
            : "Clue could not safely use the authentication service response. Contact your administrator or support team."}
        </p>
        {!unavailable && recovery.requestId ? (
          <p className="mt-3 text-sm text-[var(--clue-content-subtle)]">
            Include reference{" "}
            <code className="rounded bg-[var(--clue-background-neutral)] px-1.5 py-0.5 text-[var(--clue-content-neutral)]">
              {recovery.requestId}
            </code>
            .
          </p>
        ) : null}
        {unavailable ? (
          <button
            className={actionClassName}
            onClick={() => window.location.reload()}
            type="button"
          >
            Try again
          </button>
        ) : null}
      </section>
    </main>
  );
}
