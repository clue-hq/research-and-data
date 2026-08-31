import Link from "next/link";
import { ApplicationShell } from "@/components/shell/application-shell";
import {
  ACCOUNT_RECOVERY_COPY,
  type AccountRecovery,
} from "../model/account-recovery";

const actionClassName =
  "inline-flex h-8 items-center justify-center rounded-lg bg-[var(--primary)] px-3 text-sm font-medium text-white outline-none hover:opacity-80 focus-visible:ring-3 focus-visible:ring-[var(--ring)]/50";

function RecoveryAction({ recovery }: { recovery: AccountRecovery }) {
  switch (recovery.kind) {
    case "session_expired":
      return (
        <Link
          className={actionClassName}
          href="/sign-in?reason=session_expired"
        >
          Sign in
        </Link>
      );
    case "workspace_selection":
      return (
        <a className={actionClassName} href="#clue-workspace-selector">
          Choose workspace
        </a>
      );
    case "forbidden":
      return (
        <Link
          className={actionClassName}
          href="/access-denied?code=WORKSPACE_FORBIDDEN"
        >
          View access options
        </Link>
      );
    case "service_unavailable":
      return (
        <form action="/accounts" method="get">
          <button className={actionClassName} type="submit">
            Try again
          </button>
        </form>
      );
    case "contract_error":
      return null;
  }
}

export function AccountsRecoveryScreen({
  recovery,
}: {
  recovery: AccountRecovery;
}) {
  const copy = ACCOUNT_RECOVERY_COPY[recovery.kind];

  return (
    <ApplicationShell activeHref="/accounts">
      <main className="grid h-full min-h-0 place-items-center overflow-auto px-6 py-12">
        <section
          aria-labelledby="accounts-recovery-title"
          className="w-full max-w-lg rounded-xl border border-[var(--clue-border-neutral)] bg-[var(--clue-background-page)] p-6 shadow-[var(--clue-shadow-low)]"
        >
          <p className="text-sm font-medium text-[var(--clue-content-subtle)]">
            Accounts
          </p>
          <h1
            className="mt-1 text-xl font-medium"
            id="accounts-recovery-title"
          >
            {copy.title}
          </h1>
          <p className="mt-2 max-w-prose text-[var(--clue-content-subtle)]">
            {copy.body}
          </p>
          {recovery.kind === "workspace_selection" ? (
            <p className="mt-2 text-sm text-[var(--clue-content-subtle)]">
              Use the workspace menu at the top of this page.
            </p>
          ) : null}
          {recovery.kind === "contract_error" ? (
            <p className="mt-3 text-sm text-[var(--clue-content-subtle)]">
              Contact your Clue administrator or support team
              {recovery.requestId ? (
                <>
                  {" "}and include reference{" "}
                  <code className="rounded bg-[var(--clue-background-neutral)] px-1.5 py-0.5 text-[var(--clue-content-neutral)]">
                    {recovery.requestId}
                  </code>
                </>
              ) : (
                "."
              )}
            </p>
          ) : null}
          <div className="mt-5">
            <RecoveryAction recovery={recovery} />
          </div>
        </section>
      </main>
    </ApplicationShell>
  );
}
