import Link from "next/link";
import { ApplicationShell } from "@/components/shell/application-shell";
import {
  ACCOUNT_RECOVERY_COPY,
  type AccountRecovery,
} from "../model/account-recovery";

const actionClassName =
  "inline-flex h-8 items-center justify-center rounded-lg bg-[var(--primary)] px-3 text-sm font-medium text-white outline-none hover:opacity-80 focus-visible:ring-3 focus-visible:ring-[var(--ring)]/50";

function RecoveryAction({
  recovery,
  retryHref,
}: {
  recovery: AccountRecovery;
  retryHref: string;
}) {
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
        <a className={actionClassName} href="/select-workspace">
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
        <form action={retryHref} method="get">
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
  section = "Accounts",
  retryHref = "/accounts",
  standalone = false,
  embedded = false,
}: {
  recovery: AccountRecovery;
  section?: string;
  retryHref?: string;
  standalone?: boolean;
  embedded?: boolean;
}) {
  const copy = ACCOUNT_RECOVERY_COPY[recovery.kind];
  const Container = embedded ? "div" : "main";
  const Title = embedded ? "h2" : "h1";

  const content = (
    <>
      <Container className="grid h-full min-h-0 place-items-center overflow-auto px-6 py-12">
        <section
          aria-labelledby="accounts-recovery-title"
          className="w-full max-w-lg rounded-xl border border-[var(--clue-border-neutral)] bg-[var(--clue-background-page)] p-6 shadow-[var(--clue-shadow-low)]"
        >
          <p className="text-sm font-medium text-[var(--clue-content-subtle)]">
            {section}
          </p>
          <Title
            className="mt-1 text-xl font-medium"
            id="accounts-recovery-title"
          >
            {copy.title.replaceAll("Accounts", section)}
          </Title>
          <p className="mt-2 max-w-prose text-[var(--clue-content-subtle)]">
            {copy.body
              .replaceAll("Accounts", section)
              .replaceAll("Account service", `${section} service`)}
          </p>
          {recovery.kind === "workspace_selection" ? (
            <p className="mt-2 text-sm text-[var(--clue-content-subtle)]">
              Choose an active workspace to continue.
            </p>
          ) : null}
          {recovery.kind === "contract_error" ? (
            <p className="mt-3 text-sm text-[var(--clue-content-subtle)]">
              Contact your Clue administrator or support team
              {recovery.requestId ? (
                <>
                  {" "}
                  and include reference{" "}
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
            <RecoveryAction recovery={recovery} retryHref={retryHref} />
          </div>
        </section>
      </Container>
    </>
  );
  return standalone ? (
    content
  ) : (
    <ApplicationShell activeHref="/accounts">{content}</ApplicationShell>
  );
}
