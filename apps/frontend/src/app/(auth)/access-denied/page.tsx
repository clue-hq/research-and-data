import Link from "next/link";

const MESSAGES: Record<string, string> = {
  IDENTITY_NOT_PROVISIONED:
    "Your signed-in account has not been provisioned in Clue yet.",
  USER_DISABLED: "Your Clue account is suspended or disabled.",
  WORKSPACE_FORBIDDEN:
    "You no longer have active access to the selected workspace.",
};

export default async function AccessDeniedPage({
  searchParams,
}: {
  searchParams: Promise<{ code?: string }>;
}) {
  const { code } = await searchParams;
  return (
    <main className="grid min-h-screen place-items-center p-6">
      <section className="max-w-md rounded-xl border border-[var(--clue-border-neutral)] bg-[var(--clue-background-page)] p-6 shadow-[var(--clue-shadow-low)]">
        <h1 className="text-xl font-medium">Clue access unavailable</h1>
        <p className="mt-2 text-[var(--clue-content-subtle)]">
          {(code && MESSAGES[code]) ??
            "We could not authorize this session for a Clue workspace."}
        </p>
        <Link className="mt-4 inline-block underline" href="/sign-out">
          Sign in with a different account
        </Link>
      </section>
    </main>
  );
}
